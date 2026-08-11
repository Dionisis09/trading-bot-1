#!/usr/bin/env python3
"""Bounded, no-PnL compatibility check for Freqtrade 2026.7 orderflow.

The checker reads a Freqtrade trade Feather, retains only the latest twelve
UTC 5-minute buckets (or fewer when less data exists), builds a candle frame
containing only ``date``, and calls Freqtrade's official
``populate_dataframe_with_trades`` implementation.  It intentionally performs
no strategy evaluation, backtest, exchange request, or PnL calculation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pa_compute
import pyarrow.ipc as pa_ipc
from freqtrade.constants import DEFAULT_TRADES_COLUMNS
from freqtrade.data.converter.orderflow import populate_dataframe_with_trades


SCHEMA_VERSION = "1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT / "user_data" / "data" / "binance" / "futures"
    / "BTC_USDT_USDT-trades.feather"
)
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "user_data" / "config-pro-day-orderflow-local.json"
DEFAULT_REPORT_PATH = (
    PROJECT_ROOT / "user_data" / "reports" / "pro_day"
    / "orderflow_compatibility.json"
)
MAX_ALLOWED_BUCKETS = 12
TIMEFRAME = "5m"
BUCKET_FREQUENCY = "5min"
FLOAT_REL_TOLERANCE = 1e-9
FLOAT_ABS_TOLERANCE = 1e-12


class CompatibilityError(RuntimeError):
    """Raised when input/configuration is unsafe for the bounded check."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_iso(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write canonical JSON through a same-directory temporary file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def process_peak_rss_bytes() -> int:
    """Return this process's operating-system peak resident-set size."""

    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB; macOS reports bytes.
        return peak if sys.platform == "darwin" else peak * 1024
    except (ImportError, OSError, ValueError):
        try:
            import psutil

            memory = psutil.Process().memory_info()
            return int(getattr(memory, "peak_wset", memory.rss))
        except (ImportError, OSError, ValueError) as exc:
            raise CompatibilityError("process peak RSS is unavailable") from exc


def _plain_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise CompatibilityError(f"{field} must be a positive integer")
    result = int(value)
    if result <= 0:
        raise CompatibilityError(f"{field} must be a positive integer")
    return result


def _positive_finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise CompatibilityError(f"{field} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise CompatibilityError(f"{field} must be a positive finite number")
    return result


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CompatibilityError(f"config is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("config JSON cannot be read") from exc
    if not isinstance(payload, dict):
        raise CompatibilityError("config JSON root must be an object")
    if payload.get("timeframe") != TIMEFRAME:
        raise CompatibilityError("config timeframe must be exactly 5m")
    orderflow = payload.get("orderflow")
    if not isinstance(orderflow, dict):
        raise CompatibilityError("config orderflow must be an object")

    _plain_positive_int(orderflow.get("max_candles"), "orderflow.max_candles")
    _plain_positive_int(orderflow.get("cache_size"), "orderflow.cache_size")
    _plain_positive_int(
        orderflow.get("stacked_imbalance_range"),
        "orderflow.stacked_imbalance_range",
    )
    _positive_finite_number(orderflow.get("scale"), "orderflow.scale")
    _positive_finite_number(
        orderflow.get("imbalance_volume"), "orderflow.imbalance_volume"
    )
    _positive_finite_number(
        orderflow.get("imbalance_ratio"), "orderflow.imbalance_ratio"
    )
    return payload


def validate_trade_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize trades already materialized from Arrow."""

    expected_columns = list(DEFAULT_TRADES_COLUMNS)
    if list(frame.columns) != expected_columns:
        raise CompatibilityError(
            "trade Feather columns do not match Freqtrade DEFAULT_TRADES_COLUMNS"
        )
    if frame.empty:
        raise CompatibilityError("trade Feather contains no trades")
    if not pd.api.types.is_integer_dtype(frame["timestamp"]):
        raise CompatibilityError("trade timestamps must use an integer dtype")
    if frame["timestamp"].isna().any() or (frame["timestamp"] <= 0).any():
        raise CompatibilityError("trade timestamps must be positive and non-null")
    if frame["id"].isna().any() or frame.duplicated(["timestamp", "id"]).any():
        raise CompatibilityError("trade timestamp/id keys must be non-null and unique")
    if frame["side"].isna().any() or not frame["side"].isin(["buy", "sell"]).all():
        raise CompatibilityError("trade side must be exactly buy or sell")

    for column in ("price", "amount", "cost"):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype=float)).all() or (numeric <= 0).any():
            raise CompatibilityError(f"trade {column} must be positive and finite")
        frame[column] = numeric.astype(float)

    expected_cost = frame["price"] * frame["amount"]
    if not np.allclose(
        frame["cost"].to_numpy(dtype=float),
        expected_cost.to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-9,
    ):
        raise CompatibilityError("trade cost is inconsistent with price times amount")

    frame = frame.sort_values(["timestamp", "id"], kind="mergesort").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True, errors="coerce")
    if frame["date"].isna().any():
        raise CompatibilityError("trade timestamps cannot be converted to UTC dates")
    return frame


def load_trade_feather(path: Path) -> pd.DataFrame:
    """Compatibility helper for callers that explicitly need the entire file."""

    if not path.is_file():
        raise CompatibilityError(f"trade Feather is not a regular file: {path}")
    try:
        frame = pd.read_feather(path)
    except (OSError, ValueError, TypeError) as exc:
        raise CompatibilityError("trade Feather cannot be read") from exc
    return validate_trade_frame(frame)


def load_latest_trade_buckets(
    path: Path,
    *,
    maximum_buckets: int = MAX_ALLOWED_BUCKETS,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Materialize only Arrow tail batches needed for the latest UTC buckets.

    A forward pass validates timestamp ordering and counts rows while retaining
    no record batch.  The reverse pass converts only the minimal tail batches
    to pandas.  Continuing one batch beyond the cutoff when necessary ensures
    that a bucket split across Arrow record-batch boundaries remains complete.
    """

    bucket_limit = _plain_positive_int(maximum_buckets, "maximum_buckets")
    if bucket_limit > MAX_ALLOWED_BUCKETS:
        raise CompatibilityError(f"maximum_buckets cannot exceed {MAX_ALLOWED_BUCKETS}")
    if not path.is_file():
        raise CompatibilityError(f"trade Feather is not a regular file: {path}")

    try:
        with pa.memory_map(str(path), "r") as source:
            reader = pa_ipc.open_file(source)
            if list(reader.schema.names) != list(DEFAULT_TRADES_COLUMNS):
                raise CompatibilityError(
                    "trade Feather columns do not match Freqtrade DEFAULT_TRADES_COLUMNS"
                )
            total_batches = int(reader.num_record_batches)
            if total_batches <= 0:
                raise CompatibilityError("trade Feather contains no record batches")

            timestamp_index = reader.schema.get_field_index("timestamp")
            total_rows = 0
            previous_last_timestamp: int | None = None
            # Inspect one timestamp vector at a time.  No full pandas frame or
            # prior Arrow batch is retained during this ordering pass.
            for index in range(total_batches):
                batch = reader.get_batch(index)
                total_rows += int(batch.num_rows)
                if batch.num_rows == 0:
                    del batch
                    continue
                timestamps = batch.column(timestamp_index).to_numpy(zero_copy_only=False)
                if not np.issubdtype(timestamps.dtype, np.integer):
                    raise CompatibilityError("trade timestamps must use an integer Arrow type")
                if (timestamps <= 0).any() or (np.diff(timestamps) < 0).any():
                    raise CompatibilityError("trade timestamps are not positive and monotonic")
                first_timestamp = int(timestamps[0])
                if (
                    previous_last_timestamp is not None
                    and first_timestamp < previous_last_timestamp
                ):
                    raise CompatibilityError("trade timestamps reverse across Arrow batches")
                previous_last_timestamp = int(timestamps[-1])
                del timestamps
                del batch
            if total_rows <= 0:
                raise CompatibilityError("trade Feather contains no trades")

            tail_batches: list[pa.RecordBatch] = []
            observed_buckets: set[pd.Timestamp] = set()
            batches_scanned = 0
            for index in range(total_batches - 1, -1, -1):
                batch = reader.get_batch(index)
                if batch.num_rows == 0:
                    del batch
                    continue
                dates = pd.to_datetime(
                    batch.column(timestamp_index).to_numpy(zero_copy_only=False),
                    unit="ms",
                    utc=True,
                    errors="coerce",
                )
                if dates.isna().any():
                    raise CompatibilityError("trade timestamps cannot be converted to UTC dates")
                frame_buckets = dates.floor(BUCKET_FREQUENCY)
                observed_buckets.update(pd.Timestamp(value) for value in frame_buckets.unique())
                tail_batches.append(batch)
                batches_scanned += 1

                if len(observed_buckets) >= bucket_limit:
                    cutoff = sorted(observed_buckets)[-bucket_limit]
                    # If the current batch begins inside the cutoff bucket, a
                    # preceding batch can still contain earlier trades from it.
                    if index == 0 or frame_buckets.min() < cutoff:
                        break

            if not tail_batches:
                raise CompatibilityError("trade Feather tail contains no trades")

            cutoff = sorted(observed_buckets)[-min(bucket_limit, len(observed_buckets))]
            cutoff_ms = int(cutoff.timestamp() * 1000)
            tail_frames: list[pd.DataFrame] = []
            tail_rows_materialized = 0
            # Apply the timestamp filter in Arrow before pandas conversion, so
            # even a large final record batch only materializes the bounded
            # UTC window as a pandas DataFrame.
            for batch in reversed(tail_batches):
                mask = pa_compute.greater_equal(
                    batch.column(timestamp_index),
                    pa.scalar(cutoff_ms, type=batch.column(timestamp_index).type),
                )
                filtered = batch.filter(mask)
                if filtered.num_rows:
                    tail_rows_materialized += int(filtered.num_rows)
                    tail_frames.append(filtered.to_pandas())
            del tail_batches
    except CompatibilityError:
        raise
    except (OSError, ValueError, TypeError, pa.ArrowException) as exc:
        raise CompatibilityError("trade Feather cannot be read as Arrow IPC") from exc

    tail = pd.concat(list(reversed(tail_frames)), ignore_index=True)
    validated_tail = validate_trade_frame(tail)
    selected, candles = select_latest_buckets(
        validated_tail,
        maximum_buckets=bucket_limit,
    )
    return selected, candles, {
        "input_rows": total_rows,
        "total_record_batches": total_batches,
        "tail_record_batches_scanned": batches_scanned,
        "tail_rows_materialized": tail_rows_materialized,
    }


def select_latest_buckets(
    trades: pd.DataFrame,
    *,
    maximum_buckets: int = MAX_ALLOWED_BUCKETS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return only trades in the latest bounded UTC 5-minute buckets."""

    bucket_limit = _plain_positive_int(maximum_buckets, "maximum_buckets")
    if bucket_limit > MAX_ALLOWED_BUCKETS:
        raise CompatibilityError(f"maximum_buckets cannot exceed {MAX_ALLOWED_BUCKETS}")
    if trades.empty or "date" not in trades.columns:
        raise CompatibilityError("validated trades with date are required")

    working = trades.copy()
    dates = pd.to_datetime(working["date"], utc=True, errors="coerce")
    if dates.isna().any():
        raise CompatibilityError("trade dates contain invalid UTC values")
    working["date"] = dates
    working["_bucket"] = dates.dt.floor(BUCKET_FREQUENCY)
    buckets = working["_bucket"].drop_duplicates().sort_values().tail(bucket_limit)
    if buckets.empty:
        raise CompatibilityError("no UTC 5m trade buckets are available")

    selected = working.loc[working["_bucket"].isin(buckets)].copy()
    selected = selected.sort_values(["timestamp", "id"], kind="mergesort").reset_index(drop=True)
    selected.drop(columns=["_bucket"], inplace=True)
    candle_frame = pd.DataFrame({"date": pd.DatetimeIndex(buckets).sort_values()})
    candle_frame.reset_index(drop=True, inplace=True)
    if list(candle_frame.columns) != ["date"]:
        raise CompatibilityError("minimal candle frame construction failed")
    return selected, candle_frame


def _isclose(actual: float, expected: float) -> bool:
    return math.isclose(
        actual,
        expected,
        rel_tol=FLOAT_REL_TOLERANCE,
        abs_tol=FLOAT_ABS_TOLERANCE,
    )


def _check_output(
    selected: pd.DataFrame,
    candles: pd.DataFrame,
    populated: pd.DataFrame,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    required_columns = {
        "date",
        "trades",
        "orderflow",
        "bid",
        "ask",
        "delta",
        "total_trades",
    }
    columns_present = required_columns.issubset(populated.columns)
    checks: dict[str, dict[str, Any]] = {
        "official_columns_present": {
            "pass": columns_present,
            "required": sorted(required_columns),
        },
        "output_candle_count": {
            "pass": len(populated) == len(candles),
            "actual": int(len(populated)),
            "expected": int(len(candles)),
        },
    }
    if not columns_present or len(populated) != len(candles):
        checks["populated_candles"] = {"pass": False, "actual": 0, "expected": int(len(candles))}
        checks["total_trades"] = {"pass": False, "actual": 0, "expected": int(len(selected))}
        checks["finite_bid_ask_delta"] = {"pass": False}
        checks["orderflow_objects"] = {"pass": False}
        checks["side_consistency"] = {"pass": False}
        return checks, {"populated_candles": 0, "total_trades": 0}

    output = populated.copy()
    output["date"] = pd.to_datetime(output["date"], utc=True, errors="coerce")
    selected_buckets = selected["date"].dt.floor(BUCKET_FREQUENCY)

    populated_mask = output["total_trades"].fillna(0).astype(float) > 0
    populated_count = int(populated_mask.sum())
    total_trades_value = pd.to_numeric(output["total_trades"], errors="coerce")
    finite_values = output[["bid", "ask", "delta"]].apply(pd.to_numeric, errors="coerce")
    finite_mask = np.isfinite(finite_values.to_numpy(dtype=float)).all(axis=1)
    nonnegative_mask = (
        (finite_values["bid"] >= 0) & (finite_values["ask"] >= 0)
    ).to_numpy(dtype=bool)
    finite_ok = bool(finite_mask.all() and nonnegative_mask.all())

    orderflow_ok = True
    side_ok = True
    detail: list[dict[str, Any]] = []
    for row in output.itertuples(index=False):
        bucket = pd.Timestamp(row.date)
        expected_rows = selected.loc[selected_buckets == bucket]
        expected_bid = float(expected_rows.loc[expected_rows["side"] == "sell", "amount"].sum())
        expected_ask = float(expected_rows.loc[expected_rows["side"] == "buy", "amount"].sum())
        expected_delta = expected_ask - expected_bid
        expected_count = int(len(expected_rows))

        try:
            actual_bid = float(row.bid)
            actual_ask = float(row.ask)
            actual_delta = float(row.delta)
            actual_count_float = float(row.total_trades)
            actual_count = int(actual_count_float)
        except (TypeError, ValueError, OverflowError):
            actual_bid = actual_ask = actual_delta = math.nan
            actual_count_float = math.nan
            actual_count = -1

        trade_records = row.trades
        trade_object_ok = isinstance(trade_records, list) and len(trade_records) == expected_count
        if trade_object_ok:
            trade_object_ok = all(
                isinstance(item, dict) and item.get("side") in {"buy", "sell"}
                for item in trade_records
            )

        profile = row.orderflow
        profile_ok = isinstance(profile, dict) and bool(profile)
        profile_bid = 0.0
        profile_ask = 0.0
        if profile_ok:
            for level in profile.values():
                if not isinstance(level, dict):
                    profile_ok = False
                    break
                try:
                    bid_amount = float(level["bid_amount"])
                    ask_amount = float(level["ask_amount"])
                    level_delta = float(level["delta"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    profile_ok = False
                    break
                if not all(math.isfinite(value) for value in (bid_amount, ask_amount, level_delta)):
                    profile_ok = False
                    break
                if bid_amount < 0 or ask_amount < 0 or not _isclose(
                    level_delta, ask_amount - bid_amount
                ):
                    profile_ok = False
                    break
                profile_bid += bid_amount
                profile_ask += ask_amount

        profile_ok = bool(
            profile_ok
            and _isclose(profile_bid, expected_bid)
            and _isclose(profile_ask, expected_ask)
        )
        row_side_ok = bool(
            trade_object_ok
            and math.isfinite(actual_count_float)
            and actual_count_float.is_integer()
            and actual_count == expected_count
            and _isclose(actual_bid, expected_bid)
            and _isclose(actual_ask, expected_ask)
            and _isclose(actual_delta, expected_delta)
            and _isclose(actual_delta, actual_ask - actual_bid)
        )
        orderflow_ok = orderflow_ok and profile_ok
        side_ok = side_ok and row_side_ok
        detail.append(
            {
                "bucket_utc": utc_iso(bucket),
                "trades": expected_count,
                "buy_amount": expected_ask,
                "sell_amount": expected_bid,
                "delta": expected_delta,
                "orderflow_object_valid": profile_ok,
                "side_consistent": row_side_ok,
            }
        )

    total_actual = int(total_trades_value.fillna(0).sum()) if np.isfinite(
        total_trades_value.fillna(0).to_numpy(dtype=float)
    ).all() else -1
    checks["populated_candles"] = {
        "pass": populated_count == len(candles),
        "actual": populated_count,
        "expected": int(len(candles)),
    }
    checks["total_trades"] = {
        "pass": total_actual == len(selected),
        "actual": total_actual,
        "expected": int(len(selected)),
    }
    checks["finite_bid_ask_delta"] = {
        "pass": finite_ok,
        "nonnegative_bid_ask": bool(nonnegative_mask.all()),
    }
    checks["orderflow_objects"] = {
        "pass": bool(orderflow_ok),
        "validated_candles": int(len(detail)),
    }
    checks["side_consistency"] = {
        "pass": bool(side_ok),
        "validated_candles": int(len(detail)),
    }
    return checks, {
        "populated_candles": populated_count,
        "total_trades": total_actual,
        "candles": detail,
    }


def run_compatibility_check(
    *,
    input_path: Path = DEFAULT_INPUT_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    maximum_buckets: int = MAX_ALLOWED_BUCKETS,
    write_output: bool = True,
    populate_function: Callable[
        [pd.DataFrame | None, dict[str, Any], pd.DataFrame, pd.DataFrame],
        tuple[pd.DataFrame, pd.DataFrame],
    ] = populate_dataframe_with_trades,
    peak_rss_function: Callable[[], int] = process_peak_rss_bytes,
) -> dict[str, Any]:
    """Execute the bounded compatibility check without calculating PnL."""

    total_started = time.perf_counter()
    rss_before = int(peak_rss_function())
    input_path = input_path.resolve()
    config_path = config_path.resolve()
    report_path = report_path.resolve()
    if report_path in {input_path, config_path}:
        raise CompatibilityError("report path cannot overwrite an input")

    config = load_config(config_path)
    declared_max = _plain_positive_int(
        config["orderflow"]["max_candles"], "orderflow.max_candles"
    )
    requested_max = _plain_positive_int(maximum_buckets, "maximum_buckets")
    if requested_max > MAX_ALLOWED_BUCKETS:
        raise CompatibilityError(f"maximum_buckets cannot exceed {MAX_ALLOWED_BUCKETS}")
    effective_max = min(MAX_ALLOWED_BUCKETS, declared_max, requested_max)
    selected, candles, load_metrics = load_latest_trade_buckets(
        input_path,
        maximum_buckets=effective_max,
    )

    bounded_config = copy.deepcopy(config)
    bounded_config["orderflow"]["max_candles"] = int(len(candles))
    bounded_config["orderflow"]["cache_size"] = min(
        _plain_positive_int(config["orderflow"]["cache_size"], "orderflow.cache_size"),
        int(len(candles)),
    )
    minimal_candles = candles[["date"]].copy()
    populate_started = time.perf_counter()
    populated, cache = populate_function(
        None,
        bounded_config,
        minimal_candles,
        selected.copy(),
    )
    populate_elapsed = time.perf_counter() - populate_started
    if not isinstance(populated, pd.DataFrame):
        raise CompatibilityError("official orderflow function did not return a DataFrame")
    if cache is not None and not isinstance(cache, pd.DataFrame):
        raise CompatibilityError("official orderflow cache is not a DataFrame")

    checks, results = _check_output(selected, candles, populated)
    all_passed = all(bool(item.get("pass")) for item in checks.values())
    rss_after = int(peak_rss_function())
    total_elapsed = time.perf_counter() - total_started
    try:
        freqtrade_version = version("freqtrade")
    except PackageNotFoundError:
        freqtrade_version = "unknown"

    bucket_start = candles["date"].iloc[0]
    bucket_end = candles["date"].iloc[-1]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if all_passed else "FAIL",
        "scope": "NO_PNL_LOCAL_ORDERFLOW_COMPATIBILITY",
        "pnl_computed": False,
        "network_used": False,
        "backtest_run": False,
        "generated_at_utc": utc_now_iso(),
        "freqtrade": {
            "version": freqtrade_version,
            "api": "freqtrade.data.converter.orderflow.populate_dataframe_with_trades",
        },
        "inputs": {
            "trade_feather": str(input_path),
            "trade_feather_sha256": sha256_file(input_path),
            "config": str(config_path),
            "config_sha256": sha256_file(config_path),
            "input_rows": load_metrics["input_rows"],
            "selected_rows": int(len(selected)),
            "input_columns": list(DEFAULT_TRADES_COLUMNS),
            "declared_max_candles": declared_max,
            "effective_max_buckets": effective_max,
            "selected_bucket_count": int(len(candles)),
            "selected_start_utc": utc_iso(bucket_start),
            "selected_end_exclusive_utc": utc_iso(bucket_end + pd.Timedelta(minutes=5)),
            "total_record_batches": load_metrics["total_record_batches"],
            "tail_record_batches_scanned": load_metrics["tail_record_batches_scanned"],
            "tail_rows_materialized": load_metrics["tail_rows_materialized"],
        },
        "measurements": {
            "populate_elapsed_seconds": round(populate_elapsed, 6),
            "total_elapsed_seconds": round(total_elapsed, 6),
            "process_peak_rss_bytes": rss_after,
            "peak_rss_growth_bytes": max(0, rss_after - rss_before),
            "cache_rows": 0 if cache is None else int(len(cache)),
        },
        "checks": checks,
        "results": results,
    }
    if write_output:
        atomic_write_json(report_path, payload)
    return payload


def failure_payload(
    *,
    input_path: Path,
    config_path: Path,
    error: BaseException,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "scope": "NO_PNL_LOCAL_ORDERFLOW_COMPATIBILITY",
        "pnl_computed": False,
        "network_used": False,
        "backtest_run": False,
        "generated_at_utc": utc_now_iso(),
        "inputs": {
            "trade_feather": str(input_path.resolve()),
            "config": str(config_path.resolve()),
        },
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded no-PnL Freqtrade orderflow compatibility check."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--max-buckets", type=int, default=MAX_ALLOWED_BUCKETS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_compatibility_check(
            input_path=args.input,
            config_path=args.config,
            report_path=args.report,
            maximum_buckets=args.max_buckets,
            write_output=True,
        )
    except Exception as exc:
        result = failure_payload(
            input_path=args.input,
            config_path=args.config,
            error=exc,
        )
        try:
            atomic_write_json(args.report.resolve(), result)
        except Exception as report_error:
            print(f"FAIL: {exc}; report write failed: {report_error}", file=sys.stderr)
            return 2
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": result["status"],
                "selected_buckets": result["inputs"]["selected_bucket_count"],
                "selected_trades": result["inputs"]["selected_rows"],
                "report": str(args.report.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
