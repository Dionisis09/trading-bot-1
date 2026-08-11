#!/usr/bin/env python3
"""Build and audit the locked ProDayTraderV2 canonical OHLCV snapshot.

This program is deliberately independent from strategy/model/PnL code.  Its only
market-data inputs are the three locked Binance futures 5m Feather files.  The
5m files are copied byte-for-byte and every informative timeframe is generated
from complete, epoch-aligned UTC bins.  A failed check never publishes a partial
canonical directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0"
CYCLE_ID = "pro_day_v2_cycle1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "user_data" / "data" / "binance" / "futures"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "user_data" / "data" / "binance" / "pro_day_v2_canonical"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "user_data" / "reports" / CYCLE_ID
REPORT_NAME = "canonical_data_audit.json"
REPORT_CHECKSUM_NAME = "canonical_data_audit.sha256"

PAIRS: tuple[str, ...] = (
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "BNB/USDT:USDT",
)
PAIR_STEMS: Mapping[str, str] = {
    "BTC/USDT:USDT": "BTC_USDT_USDT",
    "ETH/USDT:USDT": "ETH_USDT_USDT",
    "BNB/USDT:USDT": "BNB_USDT_USDT",
}
TIMEFRAME_SPECS: Mapping[str, tuple[str, int]] = {
    "5m": ("5min", 1),
    "15m": ("15min", 3),
    "1h": ("1h", 12),
    "4h": ("4h", 48),
}
INFORMATIVE_TIMEFRAMES: tuple[str, ...] = ("15m", "1h", "4h")
AUXILIARY_SPECS: Mapping[str, str] = {
    "funding_rate": "8h",
    "mark": "1h",
}
REQUIRED_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class PipelineError(RuntimeError):
    """An invalid invocation or an immutable-artifact conflict."""


def utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


@dataclass(frozen=True)
class CanonicalPolicy:
    """Half-open UTC source window and its exact expected 5m row count."""

    start: pd.Timestamp
    end: pd.Timestamp
    source_rows: int

    def __post_init__(self) -> None:
        start = utc_timestamp(self.start)
        end = utc_timestamp(self.end)
        if start >= end:
            raise ValueError("start must be before end")
        if self.source_rows <= 0:
            raise ValueError("source_rows must be positive")
        expected = len(pd.date_range(start, end, freq="5min", inclusive="left"))
        if expected != self.source_rows:
            raise ValueError(
                f"source_rows={self.source_rows} does not match the UTC window ({expected})"
            )
        for timeframe, (_, factor) in TIMEFRAME_SPECS.items():
            if self.source_rows % factor:
                raise ValueError(f"source row count does not form complete {timeframe} bins")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def rows(self, timeframe: str) -> int:
        return self.source_rows // TIMEFRAME_SPECS[timeframe][1]


DEFAULT_POLICY = CanonicalPolicy(
    start=utc_timestamp("2020-12-01T00:00:00Z"),
    end=utc_timestamp("2026-08-02T00:00:00Z"),
    source_rows=596_160,
)


def iso_utc(value: pd.Timestamp) -> str:
    return utc_timestamp(value).isoformat().replace("+00:00", "Z")


def portable_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")


def data_filename(pair: str, timeframe: str) -> str:
    return f"{PAIR_STEMS[pair]}-{timeframe}-futures.feather"


def auxiliary_filename(pair: str, kind: str) -> str:
    return f"{PAIR_STEMS[pair]}-1h-{kind}.feather"


def expected_index(policy: CanonicalPolicy, timeframe: str) -> pd.DatetimeIndex:
    frequency = TIMEFRAME_SPECS[timeframe][0]
    return pd.date_range(policy.start, policy.end, freq=frequency, inclusive="left")


def _failure(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _read_frame(path: Path) -> tuple[pd.DataFrame | None, str | None]:
    try:
        return pd.read_feather(path), None
    except Exception as exc:  # pyarrow exceptions differ by version
        return None, f"{type(exc).__name__}: {exc}"


def _audit_frame(
    raw: pd.DataFrame,
    *,
    pair: str,
    timeframe: str,
    path: Path,
    project_root: Path,
    policy: CanonicalPolicy,
    file_sha256: str,
) -> tuple[pd.DataFrame | None, dict[str, Any], list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    actual_columns = tuple(str(column) for column in raw.columns)
    schema_exact = actual_columns == REQUIRED_COLUMNS
    if not schema_exact:
        failures.append(
            _failure(
                "INVALID_SCHEMA",
                pair=pair,
                timeframe=timeframe,
                expected_columns=list(REQUIRED_COLUMNS),
                actual_columns=list(actual_columns),
            )
        )
        record = {
            "pair": pair,
            "timeframe": timeframe,
            "path": portable_path(path, project_root),
            "sha256": file_sha256,
            "row_count": int(len(raw)),
            "expected_row_count": policy.rows(timeframe),
            "schema_exact": False,
            "status": "FAIL",
        }
        return None, record, failures

    date_dtype = raw["date"].dtype
    utc_dtype = isinstance(date_dtype, pd.DatetimeTZDtype) and str(date_dtype.tz) == "UTC"
    frame = raw.loc[:, REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    timestamps = frame["date"]
    valid_timestamps = timestamps.dropna()
    expected = expected_index(policy, timeframe)
    observed_unique = pd.DatetimeIndex(valid_timestamps.unique())
    missing = expected.difference(observed_unique)
    unexpected = observed_unique.difference(expected)
    duplicate_rows = int(valid_timestamps.duplicated(keep=False).sum())
    out_of_order_rows = int(valid_timestamps.diff().le(pd.Timedelta(0)).sum())
    interval_ns = int(pd.Timedelta(TIMEFRAME_SPECS[timeframe][0]).value)
    timestamp_ns = valid_timestamps.astype("datetime64[ns, UTC]").astype("int64")
    misaligned = int((timestamp_ns % interval_ns != 0).sum())

    numeric = frame.loc[:, OHLCV_COLUMNS]
    numeric_values = numeric.to_numpy(dtype=float, copy=False)
    finite_rows = np.isfinite(numeric_values).all(axis=1)
    finite_frame = frame.loc[finite_rows]
    invalid_ohlc = (
        finite_frame["high"]
        < finite_frame[["open", "close", "low"]].max(axis=1)
    ) | (
        finite_frame["low"]
        > finite_frame[["open", "close", "high"]].min(axis=1)
    )

    first = valid_timestamps.iloc[0] if not valid_timestamps.empty else None
    last = valid_timestamps.iloc[-1] if not valid_timestamps.empty else None
    expected_last = expected[-1]
    counts: dict[str, int] = {
        "row_count_delta": abs(int(len(frame)) - policy.rows(timeframe)),
        "null_timestamps": int(timestamps.isna().sum()),
        "duplicate_timestamp_rows": duplicate_rows,
        "out_of_order_rows": out_of_order_rows,
        "missing_expected_timestamps": int(len(missing)),
        "unexpected_timestamps": int(len(unexpected)),
        "misaligned_timestamps": misaligned,
        "null_ohlcv_cells": int(numeric.isna().sum().sum()),
        "nonfinite_ohlcv_cells": int(np.isinf(numeric_values).sum()),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "nonpositive_low_rows": int((finite_frame["low"] <= 0).sum()),
        "negative_volume_rows": int((finite_frame["volume"] < 0).sum()),
        "coverage_boundary_failures": int(first != policy.start) + int(last != expected_last),
        "utc_dtype_failures": int(not utc_dtype),
    }
    bad_fields = [key for key, value in counts.items() if value]
    if bad_fields:
        failures.append(
            _failure(
                "DATA_QUALITY_FAILURE",
                pair=pair,
                timeframe=timeframe,
                failed_checks=bad_fields,
            )
        )

    record = {
        "pair": pair,
        "timeframe": timeframe,
        "path": portable_path(path, project_root),
        "sha256": file_sha256,
        "row_count": int(len(frame)),
        "expected_row_count": policy.rows(timeframe),
        "first_timestamp_utc": iso_utc(first) if first is not None else None,
        "last_timestamp_utc": iso_utc(last) if last is not None else None,
        "expected_first_timestamp_utc": iso_utc(policy.start),
        "expected_last_timestamp_utc": iso_utc(expected_last),
        "schema_exact": schema_exact,
        "utc_datetime_dtype": utc_dtype,
        **counts,
        "status": "PASS" if not bad_fields else "FAIL",
    }
    return frame if not bad_fields else None, record, failures


def _aggregate_complete(
    source: pd.DataFrame, timeframe: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    frequency, factor = TIMEFRAME_SPECS[timeframe]
    indexed = source.set_index("date")
    resampler = indexed.resample(
        frequency,
        label="left",
        closed="left",
        origin="epoch",
    )
    sizes = resampler.size()
    aggregate = resampler.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).reset_index()
    counts = {
        "bins": int(len(sizes)),
        "minimum_constituent_rows": int(sizes.min()) if len(sizes) else 0,
        "maximum_constituent_rows": int(sizes.max()) if len(sizes) else 0,
        "expected_constituent_rows": factor,
        "partial_bins": int((sizes != factor).sum()),
    }
    return aggregate.loc[:, REQUIRED_COLUMNS], counts


def _audit_auxiliary(
    raw: pd.DataFrame,
    *,
    pair: str,
    kind: str,
    path: Path,
    project_root: Path,
    policy: CanonicalPolicy,
    file_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit funding/mark inputs without treating funding as OHLCV price data."""

    failures: list[dict[str, Any]] = []
    actual_columns = tuple(str(column) for column in raw.columns)
    if actual_columns != REQUIRED_COLUMNS:
        failures.append(
            _failure(
                "INVALID_AUXILIARY_SCHEMA",
                pair=pair,
                kind=kind,
                expected_columns=list(REQUIRED_COLUMNS),
                actual_columns=list(actual_columns),
            )
        )
        return (
            {
                "pair": pair,
                "kind": kind,
                "path": portable_path(path, project_root),
                "sha256": file_sha256,
                "status": "FAIL",
            },
            failures,
        )

    date_dtype = raw["date"].dtype
    utc_dtype = isinstance(date_dtype, pd.DatetimeTZDtype) and str(date_dtype.tz) == "UTC"
    frame = raw.loc[:, REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    timestamps = frame["date"]
    valid_timestamps = timestamps.dropna()
    numeric = frame.loc[:, OHLCV_COLUMNS]
    numeric_values = numeric.to_numpy(dtype=float, copy=False)
    frequency = AUXILIARY_SPECS[kind]
    interval_ns = int(pd.Timedelta(frequency).value)
    expected = pd.date_range(policy.start, policy.end, freq=frequency, inclusive="left")
    in_window = frame.loc[(timestamps >= policy.start) & (timestamps < policy.end)]
    window_dates = pd.DatetimeIndex(in_window["date"].dropna().unique())

    counts: dict[str, int] = {
        "null_timestamps": int(timestamps.isna().sum()),
        "duplicate_timestamp_rows": int(valid_timestamps.duplicated(keep=False).sum()),
        "out_of_order_rows": int(valid_timestamps.diff().le(pd.Timedelta(0)).sum()),
        "misaligned_timestamps": int(
            (
                valid_timestamps.astype("datetime64[ns, UTC]").astype("int64")
                % interval_ns
                != 0
            ).sum()
        ),
        "null_numeric_cells": int(numeric.isna().sum().sum()),
        "nonfinite_numeric_cells": int(np.isinf(numeric_values).sum()),
        "locked_window_row_count_delta": abs(int(len(in_window)) - int(len(expected))),
        "locked_window_missing_timestamps": int(len(expected.difference(window_dates))),
        "locked_window_unexpected_timestamps": int(len(window_dates.difference(expected))),
        "utc_dtype_failures": int(not utc_dtype),
    }
    if kind == "mark":
        finite_rows = np.isfinite(numeric_values).all(axis=1)
        finite_frame = frame.loc[finite_rows]
        invalid_ohlc = (
            finite_frame["high"]
            < finite_frame[["open", "close", "low"]].max(axis=1)
        ) | (
            finite_frame["low"]
            > finite_frame[["open", "close", "high"]].min(axis=1)
        )
        counts.update(
            {
                "invalid_mark_ohlc_rows": int(invalid_ohlc.sum()),
                "nonpositive_mark_low_rows": int((finite_frame["low"] <= 0).sum()),
                "negative_mark_volume_rows": int((finite_frame["volume"] < 0).sum()),
            }
        )
    bad_fields = [key for key, value in counts.items() if value]
    if bad_fields:
        failures.append(
            _failure(
                "AUXILIARY_DATA_QUALITY_FAILURE",
                pair=pair,
                kind=kind,
                failed_checks=bad_fields,
            )
        )
    record = {
        "pair": pair,
        "kind": kind,
        "path": portable_path(path, project_root),
        "sha256": file_sha256,
        "full_row_count": int(len(frame)),
        "full_first_timestamp_utc": (
            iso_utc(valid_timestamps.iloc[0]) if not valid_timestamps.empty else None
        ),
        "full_last_timestamp_utc": (
            iso_utc(valid_timestamps.iloc[-1]) if not valid_timestamps.empty else None
        ),
        "locked_window_frequency": frequency,
        "locked_window_row_count": int(len(in_window)),
        "locked_window_expected_row_count": int(len(expected)),
        "locked_window_first_expected_utc": iso_utc(expected[0]),
        "locked_window_last_expected_utc": iso_utc(expected[-1]),
        "schema_exact": True,
        "utc_datetime_dtype": utc_dtype,
        **counts,
        "status": "PASS" if not bad_fields else "FAIL",
    }
    return record, failures


def _exact_reconstruction(
    expected: pd.DataFrame,
    observed: pd.DataFrame,
    *,
    pair: str,
    timeframe: str,
    bin_counts: Mapping[str, int],
) -> dict[str, Any]:
    mismatches: dict[str, int] = {}
    if len(expected) != len(observed):
        mismatches["row_count"] = abs(len(expected) - len(observed))
    compared = min(len(expected), len(observed))
    if compared:
        expected_dates = (
            pd.to_datetime(expected["date"], utc=True)
            .astype("datetime64[ns, UTC]")
            .astype("int64")
            .to_numpy()
        )
        observed_dates = (
            pd.to_datetime(observed["date"], utc=True)
            .astype("datetime64[ns, UTC]")
            .astype("int64")
            .to_numpy()
        )
        mismatches["date"] = int(
            np.not_equal(expected_dates[:compared], observed_dates[:compared]).sum()
        )
        for column in OHLCV_COLUMNS:
            left = expected[column].to_numpy(dtype=np.float64)[:compared]
            right = observed[column].to_numpy(dtype=np.float64)[:compared]
            mismatches[column] = int(np.not_equal(left, right).sum())
    mismatches = {key: value for key, value in mismatches.items() if value}
    partial_bins = int(bin_counts["partial_bins"])
    return {
        "pair": pair,
        "timeframe": timeframe,
        **dict(bin_counts),
        "mismatch_counts": mismatches,
        "exact_all_rows": not mismatches and partial_bins == 0,
        "status": "PASS" if not mismatches and partial_bins == 0 else "FAIL",
    }


def _expected_ohlcv_names() -> set[str]:
    return {
        data_filename(pair, timeframe)
        for pair in PAIRS
        for timeframe in TIMEFRAME_SPECS
    }


def _expected_auxiliary_names() -> set[str]:
    return {
        auxiliary_filename(pair, kind)
        for pair in PAIRS
        for kind in AUXILIARY_SPECS
    }


def _expected_output_names() -> set[str]:
    return _expected_ohlcv_names() | _expected_auxiliary_names()


def _inventory(directory: Path) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    unsafe: list[str] = []
    if not directory.is_dir() or directory.is_symlink():
        return names, ["directory_missing_or_symlink"]
    for item in directory.iterdir():
        names.add(item.name)
        if not item.is_file() or item.is_symlink():
            unsafe.append(item.name)
    return names, sorted(unsafe)


def _same_snapshot(left: Path, right: Path) -> tuple[bool, list[str]]:
    expected_names = _expected_output_names()
    left_names, left_unsafe = _inventory(left)
    right_names, right_unsafe = _inventory(right)
    problems = left_unsafe + right_unsafe
    if left_names != expected_names:
        problems.append("existing_inventory_not_exact")
    if right_names != expected_names:
        problems.append("staged_inventory_not_exact")
    if problems:
        return False, sorted(problems)
    for name in sorted(expected_names):
        if sha256_file(left / name) != sha256_file(right / name):
            problems.append(f"hash_mismatch:{name}")
    return not problems, problems


def _safe_remove_stage(stage: Path, parent: Path, prefix: str) -> None:
    resolved = stage.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(prefix):
        raise PipelineError(f"refusing to remove unexpected staging path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _publish_snapshot(stage: Path, output_dir: Path) -> str:
    prefix = f".{output_dir.name}.stage-"
    if output_dir.exists():
        same, problems = _same_snapshot(output_dir, stage)
        if not same:
            raise PipelineError(
                "immutable canonical output conflict: " + ", ".join(problems)
            )
        _safe_remove_stage(stage, output_dir.parent, prefix)
        return "VERIFIED_EXISTING"
    try:
        os.replace(stage, output_dir)
        return "CREATED"
    except OSError:
        if output_dir.exists():
            same, problems = _same_snapshot(output_dir, stage)
            if same:
                _safe_remove_stage(stage, output_dir.parent, prefix)
                return "VERIFIED_EXISTING_AFTER_RACE"
            raise PipelineError(
                "canonical output appeared concurrently with different content: "
                + ", ".join(problems)
            )
        raise


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_hash = hashlib.sha256(payload).hexdigest()
    if path.exists():
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_hash:
            raise PipelineError(f"immutable artifact conflict: {path}")
        return expected_hash
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return expected_hash


def write_report_bundle(report: Mapping[str, Any], report_dir: Path) -> str:
    report_bytes = canonical_json_bytes(report)
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    report_path = report_dir / REPORT_NAME
    checksum_path = report_dir / REPORT_CHECKSUM_NAME
    _write_immutable(report_path, report_bytes)
    checksum = f"{report_hash}  {REPORT_NAME}\n".encode("ascii")
    _write_immutable(checksum_path, checksum)
    return report_hash


def _with_payload_integrity(report: dict[str, Any]) -> dict[str, Any]:
    payload_hash = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
    result = dict(report)
    result["report_integrity"] = {
        "algorithm": "sha256",
        "canonical_payload_sha256": payload_hash,
        "canonical_payload_scope": "entire report before report_integrity field",
        "file_sha256_record": REPORT_CHECKSUM_NAME,
    }
    return result


def _base_report(
    *,
    project_root: Path,
    source_dir: Path,
    output_dir: Path,
    report_dir: Path,
    policy: CanonicalPolicy,
    code_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": CYCLE_ID,
        "gate": "CANONICAL_5M_DATA_PRE_PNL",
        "pnl_evaluated": False,
        "policy": {
            "window_semantics": "half_open_utc",
            "start_utc": iso_utc(policy.start),
            "end_exclusive_utc": iso_utc(policy.end),
            "last_5m_timestamp_utc": iso_utc(policy.end - pd.Timedelta(minutes=5)),
            "pairs": list(PAIRS),
            "row_counts_per_pair": {
                timeframe: policy.rows(timeframe) for timeframe in TIMEFRAME_SPECS
            },
            "required_columns": list(REQUIRED_COLUMNS),
            "aggregation": {
                "alignment": "UTC epoch",
                "closed": "left",
                "label": "left",
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            },
        },
        "paths": {
            "source_dir": portable_path(source_dir, project_root),
            "canonical_dir": portable_path(output_dir, project_root),
            "report": portable_path(report_dir / REPORT_NAME, project_root),
            "report_checksum": portable_path(
                report_dir / REPORT_CHECKSUM_NAME, project_root
            ),
        },
        "code_hashes": {
            "generator_source": {
                "path": portable_path(Path(__file__), project_root),
                "sha256": code_hash,
            },
            "audit_source": {
                "path": portable_path(Path(__file__), project_root),
                "sha256": code_hash,
            },
        },
        "native_timeframe_exclusion": {
            "status": "PASS",
            "only_permitted_ohlcv_inputs": [
                portable_path(source_dir / data_filename(pair, "5m"), project_root)
                for pair in PAIRS
            ],
            "permitted_cost_accounting_auxiliary_inputs": [
                portable_path(source_dir / auxiliary_filename(pair, kind), project_root)
                for pair in PAIRS
                for kind in AUXILIARY_SPECS
            ],
            "native_ohlcv_15m_1h_4h_files_read": [],
            "native_timeframes_are_reconciliation_targets": False,
            "auxiliary_files_are_entry_or_ml_features": False,
            "auxiliary_purpose": "recorded funding and futures backtest compatibility only",
            "shadow_inputs_excluded": [
                "order_flow",
                "open_interest",
                "taker_ratio",
                "news_sentiment",
            ],
        },
        "publication": {
            "atomic_directory_snapshot": True,
            "existing_different_snapshot_policy": "DATA_BLOCKED_NO_OVERWRITE",
            "report_is_deterministic": True,
        },
    }


def run_pipeline(
    *,
    project_root: Path = PROJECT_ROOT,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_dir: Path = DEFAULT_REPORT_DIR,
    policy: CanonicalPolicy = DEFAULT_POLICY,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Build, independently reread, and audit one immutable canonical snapshot."""

    project_root = Path(project_root).resolve()
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    report_dir = Path(report_dir).resolve()
    if source_dir == output_dir or source_dir in output_dir.parents or output_dir in source_dir.parents:
        raise PipelineError("source and canonical directories must be separate siblings")

    code_hash = sha256_file(Path(__file__))
    report = _base_report(
        project_root=project_root,
        source_dir=source_dir,
        output_dir=output_dir,
        report_dir=report_dir,
        policy=policy,
        code_hash=code_hash,
    )
    failures: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    auxiliary_source_records: list[dict[str, Any]] = []
    source_frames: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    auxiliary_hashes: dict[tuple[str, str], str] = {}

    for pair in PAIRS:
        path = source_dir / data_filename(pair, "5m")
        if not path.is_file() or path.is_symlink():
            failures.append(
                _failure(
                    "MISSING_OR_UNSAFE_SOURCE_5M",
                    pair=pair,
                    path=portable_path(path, project_root),
                )
            )
            source_records.append(
                {
                    "pair": pair,
                    "timeframe": "5m",
                    "path": portable_path(path, project_root),
                    "status": "FAIL",
                }
            )
            continue
        file_hash = sha256_file(path)
        source_hashes[pair] = file_hash
        raw, read_error = _read_frame(path)
        if read_error or raw is None:
            failures.append(
                _failure("UNREADABLE_SOURCE_5M", pair=pair, error=read_error)
            )
            source_records.append(
                {
                    "pair": pair,
                    "timeframe": "5m",
                    "path": portable_path(path, project_root),
                    "sha256": file_hash,
                    "status": "FAIL",
                }
            )
            continue
        frame, record, frame_failures = _audit_frame(
            raw,
            pair=pair,
            timeframe="5m",
            path=path,
            project_root=project_root,
            policy=policy,
            file_sha256=file_hash,
        )
        source_records.append(record)
        failures.extend(frame_failures)
        if frame is not None:
            source_frames[pair] = frame

    for pair in PAIRS:
        for kind in AUXILIARY_SPECS:
            path = source_dir / auxiliary_filename(pair, kind)
            if not path.is_file() or path.is_symlink():
                failures.append(
                    _failure(
                        "MISSING_OR_UNSAFE_AUXILIARY_FILE",
                        pair=pair,
                        kind=kind,
                        path=portable_path(path, project_root),
                    )
                )
                auxiliary_source_records.append(
                    {
                        "pair": pair,
                        "kind": kind,
                        "path": portable_path(path, project_root),
                        "status": "FAIL",
                    }
                )
                continue
            file_hash = sha256_file(path)
            auxiliary_hashes[(pair, kind)] = file_hash
            raw, read_error = _read_frame(path)
            if read_error or raw is None:
                failures.append(
                    _failure(
                        "UNREADABLE_AUXILIARY_FILE",
                        pair=pair,
                        kind=kind,
                        error=read_error,
                    )
                )
                auxiliary_source_records.append(
                    {
                        "pair": pair,
                        "kind": kind,
                        "path": portable_path(path, project_root),
                        "sha256": file_hash,
                        "status": "FAIL",
                    }
                )
                continue
            record, auxiliary_failures = _audit_auxiliary(
                raw,
                pair=pair,
                kind=kind,
                path=path,
                project_root=project_root,
                policy=policy,
                file_sha256=file_hash,
            )
            auxiliary_source_records.append(record)
            failures.extend(auxiliary_failures)

    report["source_files"] = source_records
    report["auxiliary_source_files"] = auxiliary_source_records
    if failures:
        report.update(
            {
                "canonical_files": [],
                "auxiliary_canonical_files": [],
                "lineage": [],
                "auxiliary_lineage": [],
                "roundtrip_reconstruction": [],
                "failures": failures,
                "summary": {
                    "source_files_passed": sum(
                        row.get("status") == "PASS" for row in source_records
                    ),
                    "source_files_required": len(PAIRS),
                    "auxiliary_source_files_passed": sum(
                        row.get("status") == "PASS"
                        for row in auxiliary_source_records
                    ),
                    "auxiliary_source_files_required": len(_expected_auxiliary_names()),
                    "canonical_files_passed": 0,
                    "canonical_files_required": len(_expected_ohlcv_names()),
                    "auxiliary_files_passed": 0,
                    "auxiliary_files_required": len(_expected_auxiliary_names()),
                    "roundtrip_checks_passed": 0,
                    "roundtrip_checks_required": len(PAIRS) * len(INFORMATIVE_TIMEFRAMES),
                },
                "status": "DATA_BLOCKED",
                "decision": "DATA_BLOCKED",
            }
        )
        final = _with_payload_integrity(report)
        if write_outputs:
            write_report_bundle(final, report_dir)
        return final

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_prefix = f".{output_dir.name}.stage-"
    stage = Path(tempfile.mkdtemp(dir=output_dir.parent, prefix=stage_prefix))
    canonical_records: list[dict[str, Any]] = []
    auxiliary_canonical_records: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    auxiliary_lineage: list[dict[str, Any]] = []
    reconstruction: list[dict[str, Any]] = []
    try:
        expected_aggregates: dict[tuple[str, str], tuple[pd.DataFrame, dict[str, int]]] = {}
        for pair in PAIRS:
            source_path = source_dir / data_filename(pair, "5m")
            copied_path = stage / data_filename(pair, "5m")
            shutil.copyfile(source_path, copied_path)
            copied_hash = sha256_file(copied_path)
            canonical_records.append(
                {
                    "pair": pair,
                    "timeframe": "5m",
                    "path": portable_path(output_dir / copied_path.name, project_root),
                    "sha256": copied_hash,
                    "source_5m_sha256": source_hashes[pair],
                    "transformation": "byte_exact_copy",
                    "byte_exact_source_copy": copied_hash == source_hashes[pair],
                    "status": "PASS" if copied_hash == source_hashes[pair] else "FAIL",
                }
            )
            if copied_hash != source_hashes[pair]:
                failures.append(_failure("FIVE_MINUTE_COPY_HASH_MISMATCH", pair=pair))

            for timeframe in INFORMATIVE_TIMEFRAMES:
                aggregate, bin_counts = _aggregate_complete(source_frames[pair], timeframe)
                expected_aggregates[(pair, timeframe)] = (aggregate, bin_counts)
                derived_path = stage / data_filename(pair, timeframe)
                aggregate.reset_index(drop=True).to_feather(derived_path, compression="lz4")

            for kind in AUXILIARY_SPECS:
                source_auxiliary = source_dir / auxiliary_filename(pair, kind)
                copied_auxiliary = stage / auxiliary_filename(pair, kind)
                shutil.copyfile(source_auxiliary, copied_auxiliary)
                copied_hash = sha256_file(copied_auxiliary)
                source_hash = auxiliary_hashes[(pair, kind)]
                copy_exact = copied_hash == source_hash
                auxiliary_canonical_records.append(
                    {
                        "pair": pair,
                        "kind": kind,
                        "path": portable_path(
                            output_dir / copied_auxiliary.name, project_root
                        ),
                        "sha256": copied_hash,
                        "source_sha256": source_hash,
                        "transformation": "byte_exact_copy",
                        "byte_exact_source_copy": copy_exact,
                        "entry_or_ml_feature": False,
                        "purpose": "recorded funding cost"
                        if kind == "funding_rate"
                        else "futures mark-price compatibility",
                        "status": "PASS" if copy_exact else "FAIL",
                    }
                )
                auxiliary_lineage.append(
                    {
                        "pair": pair,
                        "kind": kind,
                        "canonical_path": portable_path(
                            output_dir / copied_auxiliary.name, project_root
                        ),
                        "canonical_sha256": copied_hash,
                        "source_path": portable_path(source_auxiliary, project_root),
                        "source_sha256": source_hash,
                        "transformation": "byte_exact_copy",
                    }
                )
                if not copy_exact:
                    failures.append(
                        _failure("AUXILIARY_COPY_HASH_MISMATCH", pair=pair, kind=kind)
                    )

        staged_names, unsafe_entries = _inventory(stage)
        expected_names = _expected_output_names()
        unexpected_entries = sorted(staged_names - expected_names)
        missing_entries = sorted(expected_names - staged_names)
        if unsafe_entries or unexpected_entries or missing_entries:
            failures.append(
                _failure(
                    "CANONICAL_INVENTORY_NOT_EXACT",
                    unsafe_entries=unsafe_entries,
                    unexpected_entries=unexpected_entries,
                    missing_entries=missing_entries,
                )
            )

        for pair in PAIRS:
            for timeframe in INFORMATIVE_TIMEFRAMES:
                staged_path = stage / data_filename(pair, timeframe)
                derived_hash = sha256_file(staged_path)
                raw, read_error = _read_frame(staged_path)
                logical_path = output_dir / staged_path.name
                if read_error or raw is None:
                    failures.append(
                        _failure(
                            "UNREADABLE_DERIVED_FILE",
                            pair=pair,
                            timeframe=timeframe,
                            error=read_error,
                        )
                    )
                    continue
                observed, quality, quality_failures = _audit_frame(
                    raw,
                    pair=pair,
                    timeframe=timeframe,
                    path=logical_path,
                    project_root=project_root,
                    policy=policy,
                    file_sha256=derived_hash,
                )
                canonical_records.append(
                    {
                        **quality,
                        "source_5m_sha256": source_hashes[pair],
                        "transformation": "complete_utc_5m_bin_aggregation",
                    }
                )
                failures.extend(quality_failures)
                expected, bin_counts = expected_aggregates[(pair, timeframe)]
                if observed is None:
                    reconstruction_row = {
                        "pair": pair,
                        "timeframe": timeframe,
                        **bin_counts,
                        "mismatch_counts": {"quality_gate": 1},
                        "exact_all_rows": False,
                        "status": "FAIL",
                    }
                else:
                    reconstruction_row = _exact_reconstruction(
                        expected,
                        observed,
                        pair=pair,
                        timeframe=timeframe,
                        bin_counts=bin_counts,
                    )
                reconstruction.append(reconstruction_row)
                if reconstruction_row["status"] != "PASS":
                    failures.append(
                        _failure(
                            "AGGREGATE_RECONSTRUCTION_FAILURE",
                            pair=pair,
                            timeframe=timeframe,
                            mismatch_counts=reconstruction_row["mismatch_counts"],
                            partial_bins=reconstruction_row["partial_bins"],
                        )
                    )
                lineage.append(
                    {
                        "pair": pair,
                        "timeframe": timeframe,
                        "derived_path": portable_path(logical_path, project_root),
                        "derived_sha256": derived_hash,
                        "source_5m_path": portable_path(
                            source_dir / data_filename(pair, "5m"), project_root
                        ),
                        "source_5m_sha256": source_hashes[pair],
                        "transformation": "complete_utc_5m_bin_aggregation",
                        "constituent_rows_per_bin": TIMEFRAME_SPECS[timeframe][1],
                    }
                )

        # Close the read/copy race: the locked inputs must not change mid-build.
        for pair in PAIRS:
            source_path = source_dir / data_filename(pair, "5m")
            final_hash = sha256_file(source_path)
            if final_hash != source_hashes[pair]:
                failures.append(
                    _failure(
                        "SOURCE_CHANGED_DURING_BUILD",
                        pair=pair,
                        initial_sha256=source_hashes[pair],
                        final_sha256=final_hash,
                    )
                )
            for kind in AUXILIARY_SPECS:
                source_auxiliary = source_dir / auxiliary_filename(pair, kind)
                final_hash = sha256_file(source_auxiliary)
                initial_hash = auxiliary_hashes[(pair, kind)]
                if final_hash != initial_hash:
                    failures.append(
                        _failure(
                            "AUXILIARY_SOURCE_CHANGED_DURING_BUILD",
                            pair=pair,
                            kind=kind,
                            initial_sha256=initial_hash,
                            final_sha256=final_hash,
                        )
                    )

        if failures:
            _safe_remove_stage(stage, output_dir.parent, stage_prefix)
        elif write_outputs:
            _publish_snapshot(stage, output_dir)
        else:
            _safe_remove_stage(stage, output_dir.parent, stage_prefix)
    except Exception:
        if stage.exists():
            _safe_remove_stage(stage, output_dir.parent, stage_prefix)
        raise

    canonical_records.sort(key=lambda row: (PAIRS.index(row["pair"]), list(TIMEFRAME_SPECS).index(row["timeframe"])))
    report["canonical_files"] = canonical_records
    report["auxiliary_canonical_files"] = auxiliary_canonical_records
    report["lineage"] = lineage
    report["auxiliary_lineage"] = auxiliary_lineage
    report["roundtrip_reconstruction"] = reconstruction
    report["native_timeframe_exclusion"].update(
        {
            "canonical_inventory_expected": sorted(_expected_output_names()),
            "canonical_inventory_exact": not any(
                failure["code"] == "CANONICAL_INVENTORY_NOT_EXACT"
                for failure in failures
            ),
        }
    )
    if not report["native_timeframe_exclusion"]["canonical_inventory_exact"]:
        report["native_timeframe_exclusion"]["status"] = "FAIL"
    report["failures"] = failures
    report["summary"] = {
        "source_files_passed": sum(row.get("status") == "PASS" for row in source_records),
        "source_files_required": len(PAIRS),
        "auxiliary_source_files_passed": sum(
            row.get("status") == "PASS" for row in auxiliary_source_records
        ),
        "auxiliary_source_files_required": len(_expected_auxiliary_names()),
        "canonical_files_passed": sum(
            row.get("status") == "PASS" for row in canonical_records
        ),
        "canonical_files_required": len(_expected_ohlcv_names()),
        "auxiliary_files_passed": sum(
            row.get("status") == "PASS" for row in auxiliary_canonical_records
        ),
        "auxiliary_files_required": len(_expected_auxiliary_names()),
        "roundtrip_checks_passed": sum(
            row.get("status") == "PASS" for row in reconstruction
        ),
        "roundtrip_checks_required": len(PAIRS) * len(INFORMATIVE_TIMEFRAMES),
        "partial_aggregate_bins": sum(int(row["partial_bins"]) for row in reconstruction),
    }
    report["status"] = "PASS" if not failures else "DATA_BLOCKED"
    report["decision"] = (
        "READY_FOR_PRE_PNL_TECHNICAL_GATES" if not failures else "DATA_BLOCKED"
    )
    final = _with_payload_integrity(report)
    if write_outputs:
        write_report_bundle(final, report_dir)
    return final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_pipeline(
            project_root=args.project_root,
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            write_outputs=True,
        )
    except (OSError, PipelineError, ValueError) as exc:
        print(f"TECHNICAL_BLOCKED: {exc}", file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "status": result["status"],
                "decision": result["decision"],
                "pnl_evaluated": result["pnl_evaluated"],
                "summary": result["summary"],
                "report": result["paths"]["report"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
