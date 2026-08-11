#!/usr/bin/env python3
"""Fail-closed data-quality audit for the locked ProDayTraderV1 research cycle.

The audit is intentionally independent from Freqtrade backtesting.  It reads the
exact twelve native Binance futures candle files, validates their declared UTC
research windows, reconciles complete 5m aggregates with the native informative
timeframes, and writes inspectable JSON/CSV evidence before any PnL is allowed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "user_data" / "data" / "binance" / "futures"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "user_data" / "reports" / "pro_day"

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
TIMEFRAME_SECONDS: Mapping[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}
INFORMATIVE_TIMEFRAMES: tuple[str, ...] = ("15m", "1h", "4h")
REQUIRED_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


@dataclass(frozen=True)
class AuditPolicy:
    """Locked thresholds and half-open UTC windows used by the audit."""

    download_start: pd.Timestamp
    download_end: pd.Timestamp
    splits: tuple[tuple[str, pd.Timestamp, pd.Timestamp], ...]
    minimum_coverage_pct: float = 99.95
    maximum_undocumented_gap_candles: int = 3
    maximum_mismatch_days_pct: float = 0.20
    reconciliation_relative_tolerance: float = 1e-9
    reconciliation_absolute_tolerance: float = 1e-8

    def __post_init__(self) -> None:
        start = utc_timestamp(self.download_start)
        end = utc_timestamp(self.download_end)
        normalized_splits = tuple(
            (name, utc_timestamp(split_start), utc_timestamp(split_end))
            for name, split_start, split_end in self.splits
        )
        if start >= end:
            raise ValueError("download_start must be before download_end")
        if not normalized_splits:
            raise ValueError("at least one split is required")
        for name, split_start, split_end in normalized_splits:
            if not name or split_start >= split_end:
                raise ValueError(f"invalid split: {name!r}")
            if split_start < start or split_end > end:
                raise ValueError(f"split {name!r} is outside the download window")
        object.__setattr__(self, "download_start", start)
        object.__setattr__(self, "download_end", end)
        object.__setattr__(self, "splits", normalized_splits)


DEFAULT_POLICY = AuditPolicy(
    download_start=utc_timestamp("2020-12-01T00:00:00Z"),
    download_end=utc_timestamp("2026-08-02T00:00:00Z"),
    splits=(
        ("TRAIN", utc_timestamp("2021-01-01T00:00:00Z"), utc_timestamp("2024-01-01T00:00:00Z")),
        (
            "VALIDATION",
            utc_timestamp("2024-01-01T00:00:00Z"),
            utc_timestamp("2026-01-01T00:00:00Z"),
        ),
        (
            "CURRENT_PARTIAL",
            utc_timestamp("2026-01-01T00:00:00Z"),
            utc_timestamp("2026-08-01T00:00:00Z"),
        ),
    ),
)


class AuditError(RuntimeError):
    """Raised for an invalid audit invocation rather than a data-quality failure."""


def iso_utc(value: pd.Timestamp | datetime) -> str:
    timestamp = utc_timestamp(pd.Timestamp(value))
    return timestamp.isoformat().replace("+00:00", "Z")


def generated_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def portable_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(project_root.resolve())
        return relative.as_posix()
    except ValueError:
        return resolved.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_path(data_dir: Path, pair: str, timeframe: str) -> Path:
    return data_dir / f"{PAIR_STEMS[pair]}-{timeframe}-futures.feather"


def expected_index(start: pd.Timestamp, end: pd.Timestamp, seconds: int) -> pd.DatetimeIndex:
    # ``inclusive='left'`` makes every locked period explicitly half-open.
    return pd.date_range(start=start, end=end, freq=pd.Timedelta(seconds=seconds), inclusive="left")


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.loc[:, REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _quality_counts(frame: pd.DataFrame, timeframe_seconds: int) -> dict[str, int]:
    timestamps = frame["date"]
    numeric = frame.loc[:, OHLCV_COLUMNS]
    finite_values = numeric.to_numpy(dtype=float, copy=False)
    valid_numeric_rows = np.isfinite(finite_values).all(axis=1)
    valid = frame.loc[valid_numeric_rows]

    invalid_ohlc = (
        (valid["high"] < valid[["open", "close"]].max(axis=1))
        | (valid["low"] > valid[["open", "close"]].min(axis=1))
    )
    invalid_low = valid["low"] <= 0
    invalid_volume = valid["volume"] < 0

    valid_timestamps = timestamps.dropna()
    interval = pd.Timedelta(seconds=timeframe_seconds)
    misaligned = (
        int((valid_timestamps != valid_timestamps.dt.floor(interval)).sum())
        if not valid_timestamps.empty
        else 0
    )

    return {
        "null_timestamps": int(timestamps.isna().sum()),
        "duplicate_timestamps": int(valid_timestamps.duplicated(keep=False).sum()),
        "null_ohlcv_cells": int(numeric.isna().sum().sum()),
        "nonfinite_ohlcv_cells": int(np.isinf(finite_values).sum()),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "nonpositive_low_rows": int(invalid_low.sum()),
        "negative_volume_rows": int(invalid_volume.sum()),
        "misaligned_timestamps": misaligned,
    }


def _quality_failure_count(counts: Mapping[str, int]) -> int:
    return sum(int(value) for value in counts.values())


def _missing_runs(
    expected: pd.DatetimeIndex, observed: pd.DatetimeIndex, seconds: int
) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    missing = expected.difference(observed)
    if missing.empty:
        return []
    interval = pd.Timedelta(seconds=seconds)
    runs: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    run_start = missing[0]
    previous = missing[0]
    count = 1
    for timestamp in missing[1:]:
        if timestamp - previous == interval:
            count += 1
        else:
            runs.append((run_start, previous + interval, count))
            run_start = timestamp
            count = 1
        previous = timestamp
    runs.append((run_start, previous + interval, count))
    return runs


def load_documented_gaps(path: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if path is None:
        return [], None
    if not path.is_file():
        raise AuditError(f"Documented-gap file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"Invalid documented-gap JSON: {path}: {exc}") from exc
    records = payload.get("gaps") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise AuditError("Documented-gap JSON must contain a 'gaps' list")
    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise AuditError(f"Documented gap #{index + 1} is not an object")
        pair = record.get("pair")
        timeframe = record.get("timeframe")
        reason = record.get("reason")
        if pair not in PAIRS or timeframe not in TIMEFRAME_SECONDS:
            raise AuditError(f"Documented gap #{index + 1} has an invalid pair/timeframe")
        if not isinstance(reason, str) or not reason.strip():
            raise AuditError(f"Documented gap #{index + 1} requires a non-empty reason")
        try:
            start = utc_timestamp(record["start_utc"])
            end = utc_timestamp(record["end_utc"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError(f"Documented gap #{index + 1} has invalid UTC bounds") from exc
        if start >= end:
            raise AuditError(f"Documented gap #{index + 1} has an empty/reversed range")
        normalized.append(
            {
                "pair": pair,
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "reason": reason.strip(),
            }
        )
    descriptor = {
        "path": path.resolve().as_posix(),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    return normalized, descriptor


def _gap_documentation(
    pair: str,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    records: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    matches = [
        record
        for record in records
        if record["pair"] == pair
        and record["timeframe"] == timeframe
        and start >= record["start"]
        and end <= record["end"]
    ]
    if len(matches) != 1:
        return False, ""
    return True, str(matches[0]["reason"])


def _aggregate_complete_bins(
    base: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    target_seconds: int,
) -> pd.DataFrame:
    selected = base[
        base["date"].notna() & (base["date"] >= start) & (base["date"] < end)
    ].copy()
    if selected.empty:
        return pd.DataFrame(columns=("date", *OHLCV_COLUMNS))
    selected = selected.sort_values("date")
    selected["bin"] = selected["date"].dt.floor(pd.Timedelta(seconds=target_seconds))
    grouped = selected.groupby("bin", sort=True, observed=True)
    expected_count = target_seconds // TIMEFRAME_SECONDS["5m"]
    counts = grouped["date"].agg(rows="size", unique_timestamps="nunique")
    aggregate = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    complete_index = counts.index[
        (counts["rows"] == expected_count) & (counts["unique_timestamps"] == expected_count)
    ]
    aggregate = aggregate.loc[aggregate.index.intersection(complete_index)].reset_index()
    aggregate = aggregate.rename(columns={"bin": "date"})
    return aggregate.loc[:, ("date", *OHLCV_COLUMNS)]


def _reconcile_split(
    *,
    pair: str,
    timeframe: str,
    base: pd.DataFrame,
    native: pd.DataFrame,
    split: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    policy: AuditPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target_seconds = TIMEFRAME_SECONDS[timeframe]
    aggregate = _aggregate_complete_bins(base, start, end, target_seconds)
    native_selected = native[
        native["date"].notna() & (native["date"] >= start) & (native["date"] < end)
    ].copy()
    duplicate_dates = set(
        native_selected.loc[
            native_selected["date"].duplicated(keep=False), "date"
        ].tolist()
    )
    native_unique = native_selected.drop_duplicates("date", keep=False).set_index("date")

    bin_rows: list[dict[str, Any]] = []
    for record in aggregate.itertuples(index=False):
        timestamp = record.date
        mismatch_fields: list[str] = []
        missing_native = timestamp not in native_unique.index
        duplicate_native = timestamp in duplicate_dates
        if missing_native or duplicate_native:
            mismatch_fields.append("native_timestamp")
        else:
            stored = native_unique.loc[timestamp]
            for column in OHLCV_COLUMNS:
                actual = float(getattr(record, column))
                expected_value = float(stored[column])
                if not (
                    math.isfinite(actual)
                    and math.isfinite(expected_value)
                    and math.isclose(
                        actual,
                        expected_value,
                        rel_tol=policy.reconciliation_relative_tolerance,
                        abs_tol=policy.reconciliation_absolute_tolerance,
                    )
                ):
                    mismatch_fields.append(column)
        bin_rows.append(
            {
                "date_utc": timestamp.floor("D"),
                "missing_native": int(missing_native),
                "duplicate_native": int(duplicate_native),
                "mismatch": int(bool(mismatch_fields)),
                "mismatch_fields": ";".join(mismatch_fields),
            }
        )

    daily_rows: list[dict[str, Any]] = []
    if bin_rows:
        bins = pd.DataFrame(bin_rows)
        for date_value, day in bins.groupby("date_utc", sort=True):
            fields = sorted(
                {
                    field
                    for value in day["mismatch_fields"]
                    for field in str(value).split(";")
                    if field
                }
            )
            daily_rows.append(
                {
                    "split": split,
                    "pair": pair,
                    "timeframe": timeframe,
                    "date_utc": iso_utc(date_value),
                    "complete_5m_bins": int(len(day)),
                    "missing_native_bins": int(day["missing_native"].sum()),
                    "duplicate_native_bins": int(day["duplicate_native"].sum()),
                    "mismatched_bins": int(day["mismatch"].sum()),
                    "mismatch_fields": ";".join(fields),
                    "status": "FAIL" if int(day["mismatch"].sum()) else "PASS",
                }
            )

    compared_days = len(daily_rows)
    mismatch_days = sum(row["status"] == "FAIL" for row in daily_rows)
    mismatch_days_pct = 100.0 * mismatch_days / compared_days if compared_days else 100.0
    summary = {
        "split": split,
        "pair": pair,
        "timeframe": timeframe,
        "complete_5m_bins": int(len(aggregate)),
        "compared_days": int(compared_days),
        "mismatch_days": int(mismatch_days),
        "mismatch_days_pct": float(mismatch_days_pct),
        "maximum_mismatch_days_pct": policy.maximum_mismatch_days_pct,
        "status": (
            "PASS"
            if compared_days > 0 and mismatch_days_pct <= policy.maximum_mismatch_days_pct
            else "FAIL"
        ),
    }
    return summary, daily_rows


def _csv_safe_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in row.items()} for row in rows]


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_csv_atomic(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(_csv_safe_rows(rows))
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_reports(report_dir: Path, report: Mapping[str, Any]) -> dict[str, str]:
    paths = {
        "json": report_dir / "data_quality.json",
        "files_csv": report_dir / "data_quality_files.csv",
        "splits_csv": report_dir / "data_quality_splits.csv",
        "gaps_csv": report_dir / "data_quality_gaps.csv",
        "reconciliation_csv": report_dir / "data_quality_reconciliation.csv",
        "reconciliation_daily_csv": report_dir / "data_quality_reconciliation_daily.csv",
    }
    _write_json_atomic(paths["json"], report)
    _write_csv_atomic(
        paths["files_csv"],
        report["data_files"],
        (
            "pair",
            "timeframe",
            "path",
            "filename",
            "exists",
            "bytes",
            "sha256",
            "rows",
            "first_utc",
            "last_utc",
            "download_window_expected_candles",
            "download_window_observed_candles",
            "download_window_coverage_pct",
            "null_timestamps",
            "duplicate_timestamps",
            "null_ohlcv_cells",
            "nonfinite_ohlcv_cells",
            "invalid_ohlc_rows",
            "nonpositive_low_rows",
            "negative_volume_rows",
            "misaligned_timestamps",
            "status",
            "error",
        ),
    )
    _write_csv_atomic(
        paths["splits_csv"],
        report["split_checks"],
        (
            "split",
            "pair",
            "timeframe",
            "start_utc",
            "end_utc",
            "expected_candles",
            "observed_candles",
            "missing_candles",
            "coverage_pct",
            "minimum_coverage_pct",
            "duplicate_timestamps",
            "null_ohlcv_cells",
            "nonfinite_ohlcv_cells",
            "invalid_ohlc_rows",
            "nonpositive_low_rows",
            "negative_volume_rows",
            "misaligned_timestamps",
            "undocumented_gaps_over_limit",
            "largest_undocumented_gap_candles",
            "status",
        ),
    )
    _write_csv_atomic(
        paths["gaps_csv"],
        report["gaps"],
        (
            "split",
            "pair",
            "timeframe",
            "gap_start_utc",
            "gap_end_utc",
            "missing_candles",
            "documented",
            "documentation_reason",
            "over_limit",
            "status",
        ),
    )
    _write_csv_atomic(
        paths["reconciliation_csv"],
        report["reconciliation_checks"],
        (
            "split",
            "pair",
            "timeframe",
            "complete_5m_bins",
            "compared_days",
            "mismatch_days",
            "mismatch_days_pct",
            "maximum_mismatch_days_pct",
            "status",
        ),
    )
    _write_csv_atomic(
        paths["reconciliation_daily_csv"],
        report["reconciliation_daily"],
        (
            "split",
            "pair",
            "timeframe",
            "date_utc",
            "complete_5m_bins",
            "missing_native_bins",
            "duplicate_native_bins",
            "mismatched_bins",
            "mismatch_fields",
            "status",
        ),
    )
    return {key: value.resolve().as_posix() for key, value in paths.items()}


def run_audit(
    *,
    project_root: Path = PROJECT_ROOT,
    data_dir: Path | None = None,
    report_dir: Path | None = None,
    policy: AuditPolicy = DEFAULT_POLICY,
    pairs: Sequence[str] = PAIRS,
    timeframes: Sequence[str] = tuple(TIMEFRAME_SECONDS),
    documented_gaps_path: Path | None = None,
    write_output: bool = True,
) -> dict[str, Any]:
    """Run the audit and return its JSON-serializable evidence payload.

    Pair/timeframe overrides exist for compact unit tests.  The CLI deliberately
    exposes no such override and therefore always enforces the locked 3 x 4 set.
    """

    root = project_root.resolve()
    selected_data_dir = (data_dir or (root / "user_data" / "data" / "binance" / "futures")).resolve()
    selected_report_dir = (report_dir or (root / "user_data" / "reports" / "pro_day")).resolve()
    invalid_pairs = sorted(set(pairs) - set(PAIR_STEMS))
    invalid_timeframes = sorted(set(timeframes) - set(TIMEFRAME_SECONDS))
    if invalid_pairs or invalid_timeframes or "5m" not in timeframes:
        raise AuditError(
            f"Invalid audit universe; pairs={invalid_pairs}, timeframes={invalid_timeframes}, 5m required"
        )

    documented_gaps, documented_gap_descriptor = load_documented_gaps(documented_gaps_path)
    data_files: list[dict[str, Any]] = []
    split_checks: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    reconciliation_checks: list[dict[str, Any]] = []
    reconciliation_daily: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    loaded: dict[tuple[str, str], pd.DataFrame] = {}

    for pair in pairs:
        for timeframe in timeframes:
            path = data_path(selected_data_dir, pair, timeframe)
            base_descriptor: dict[str, Any] = {
                "pair": pair,
                "timeframe": timeframe,
                "path": portable_path(path, root),
                "filename": path.name,
                "exists": path.is_file(),
                "bytes": None,
                "sha256": None,
                "rows": 0,
                "first_utc": None,
                "last_utc": None,
                "download_window_expected_candles": len(
                    expected_index(policy.download_start, policy.download_end, TIMEFRAME_SECONDS[timeframe])
                ),
                "download_window_observed_candles": 0,
                "download_window_coverage_pct": 0.0,
                **{key: 0 for key in _quality_counts(_empty_frame(), TIMEFRAME_SECONDS[timeframe])},
                "status": "FAIL",
                "error": "",
            }
            if not path.is_file():
                base_descriptor["error"] = "MISSING_REQUIRED_DATA_FILE"
                data_files.append(base_descriptor)
                failures.append(
                    {
                        "severity": "CRITICAL",
                        "code": "MISSING_REQUIRED_DATA_FILE",
                        "pair": pair,
                        "timeframe": timeframe,
                        "detail": base_descriptor["path"],
                    }
                )
                continue
            try:
                stat_before = path.stat()
                raw = pd.read_feather(path)
                missing_columns = sorted(set(REQUIRED_COLUMNS) - set(raw.columns))
                if missing_columns:
                    raise AuditError(f"missing columns: {', '.join(missing_columns)}")
                frame = _normalize_frame(raw)
                digest = sha256_file(path)
                stat_after = path.stat()
                if (stat_before.st_size, stat_before.st_mtime_ns) != (
                    stat_after.st_size,
                    stat_after.st_mtime_ns,
                ):
                    raise AuditError("file changed while it was being audited")
            except Exception as exc:  # malformed input is a reportable fail-closed result
                base_descriptor["error"] = f"UNREADABLE_DATA_FILE: {type(exc).__name__}: {exc}"
                data_files.append(base_descriptor)
                failures.append(
                    {
                        "severity": "CRITICAL",
                        "code": "UNREADABLE_DATA_FILE",
                        "pair": pair,
                        "timeframe": timeframe,
                        "detail": str(exc),
                    }
                )
                continue

            counts = _quality_counts(frame, TIMEFRAME_SECONDS[timeframe])
            valid_dates = frame["date"].dropna().sort_values()
            expected_download = expected_index(
                policy.download_start, policy.download_end, TIMEFRAME_SECONDS[timeframe]
            )
            observed_download = pd.DatetimeIndex(valid_dates.drop_duplicates()).intersection(
                expected_download
            )
            coverage = 100.0 * len(observed_download) / len(expected_download)
            base_descriptor.update(
                {
                    "bytes": stat_after.st_size,
                    "sha256": digest,
                    "rows": int(len(frame)),
                    "first_utc": iso_utc(valid_dates.iloc[0]) if not valid_dates.empty else None,
                    "last_utc": iso_utc(valid_dates.iloc[-1]) if not valid_dates.empty else None,
                    "download_window_observed_candles": int(len(observed_download)),
                    "download_window_coverage_pct": float(coverage),
                    **counts,
                }
            )
            file_ok = _quality_failure_count(counts) == 0 and coverage >= policy.minimum_coverage_pct
            base_descriptor["status"] = "PASS" if file_ok else "FAIL"
            if not file_ok:
                failures.append(
                    {
                        "severity": "CRITICAL",
                        "code": "FILE_QUALITY_OR_DOWNLOAD_COVERAGE_FAILED",
                        "pair": pair,
                        "timeframe": timeframe,
                        "detail": (
                            f"quality_failures={_quality_failure_count(counts)}, "
                            f"download_coverage_pct={coverage:.8f}"
                        ),
                    }
                )
            data_files.append(base_descriptor)
            loaded[(pair, timeframe)] = frame

    for pair in pairs:
        for timeframe in timeframes:
            frame = loaded.get((pair, timeframe))
            if frame is None:
                continue
            seconds = TIMEFRAME_SECONDS[timeframe]
            for split, start, end in policy.splits:
                selected = frame[
                    frame["date"].notna() & (frame["date"] >= start) & (frame["date"] < end)
                ].copy()
                expected = expected_index(start, end, seconds)
                observed = pd.DatetimeIndex(selected["date"].drop_duplicates()).intersection(expected)
                missing = expected.difference(observed)
                coverage = 100.0 * len(observed) / len(expected)
                counts = _quality_counts(selected, seconds)
                undocumented_over_limit = 0
                largest_undocumented = 0
                for gap_start, gap_end, missing_candles in _missing_runs(expected, observed, seconds):
                    documented, reason = _gap_documentation(
                        pair, timeframe, gap_start, gap_end, documented_gaps
                    )
                    over_limit = (
                        not documented
                        and missing_candles > policy.maximum_undocumented_gap_candles
                    )
                    if over_limit:
                        undocumented_over_limit += 1
                        largest_undocumented = max(largest_undocumented, missing_candles)
                    gap_rows.append(
                        {
                            "split": split,
                            "pair": pair,
                            "timeframe": timeframe,
                            "gap_start_utc": iso_utc(gap_start),
                            "gap_end_utc": iso_utc(gap_end),
                            "missing_candles": int(missing_candles),
                            "documented": bool(documented),
                            "documentation_reason": reason,
                            "over_limit": bool(over_limit),
                            "status": "FAIL" if over_limit else "PASS",
                        }
                    )
                split_ok = (
                    coverage >= policy.minimum_coverage_pct
                    and _quality_failure_count(counts) == 0
                    and undocumented_over_limit == 0
                )
                row = {
                    "split": split,
                    "pair": pair,
                    "timeframe": timeframe,
                    "start_utc": iso_utc(start),
                    "end_utc": iso_utc(end),
                    "expected_candles": int(len(expected)),
                    "observed_candles": int(len(observed)),
                    "missing_candles": int(len(missing)),
                    "coverage_pct": float(coverage),
                    "minimum_coverage_pct": policy.minimum_coverage_pct,
                    **counts,
                    "undocumented_gaps_over_limit": int(undocumented_over_limit),
                    "largest_undocumented_gap_candles": int(largest_undocumented),
                    "status": "PASS" if split_ok else "FAIL",
                }
                split_checks.append(row)
                if not split_ok:
                    failures.append(
                        {
                            "severity": "CRITICAL",
                            "code": "SPLIT_DATA_QUALITY_FAILED",
                            "split": split,
                            "pair": pair,
                            "timeframe": timeframe,
                            "detail": (
                                f"coverage_pct={coverage:.8f}, "
                                f"quality_failures={_quality_failure_count(counts)}, "
                                f"undocumented_large_gaps={undocumented_over_limit}"
                            ),
                        }
                    )

    for pair in pairs:
        base = loaded.get((pair, "5m"))
        if base is None:
            continue
        for timeframe in INFORMATIVE_TIMEFRAMES:
            if timeframe not in timeframes:
                continue
            native = loaded.get((pair, timeframe))
            if native is None:
                continue
            for split, start, end in policy.splits:
                summary, daily = _reconcile_split(
                    pair=pair,
                    timeframe=timeframe,
                    base=base,
                    native=native,
                    split=split,
                    start=start,
                    end=end,
                    policy=policy,
                )
                reconciliation_checks.append(summary)
                reconciliation_daily.extend(daily)
                if summary["status"] != "PASS":
                    failures.append(
                        {
                            "severity": "CRITICAL",
                            "code": "TIMEFRAME_RECONCILIATION_FAILED",
                            "split": split,
                            "pair": pair,
                            "timeframe": timeframe,
                            "detail": (
                                f"mismatch_days_pct={summary['mismatch_days_pct']:.8f}, "
                                f"compared_days={summary['compared_days']}"
                            ),
                        }
                    )

    expected_file_count = len(pairs) * len(timeframes)
    all_required_loaded = len(loaded) == expected_file_count
    all_files_pass = len(data_files) == expected_file_count and all(
        row["status"] == "PASS" for row in data_files
    )
    all_splits_present = len(split_checks) == expected_file_count * len(policy.splits)
    all_splits_pass = all_splits_present and all(row["status"] == "PASS" for row in split_checks)
    expected_reconciliation_count = (
        len(pairs) * len([tf for tf in INFORMATIVE_TIMEFRAMES if tf in timeframes]) * len(policy.splits)
    )
    all_reconciliations_pass = (
        len(reconciliation_checks) == expected_reconciliation_count
        and all(row["status"] == "PASS" for row in reconciliation_checks)
    )
    passed = bool(
        all_required_loaded
        and all_files_pass
        and all_splits_pass
        and all_reconciliations_pass
        and not failures
    )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc(),
        "status": "PASS" if passed else "DATA_BLOCKED",
        "decision": "READY_FOR_RESEARCH_FREEZE" if passed else "DATA_BLOCKED",
        "candidate": "ProDayTraderV1",
        "intended_grain": "one native UTC candle per pair, timeframe, and candle-open timestamp",
        "expected_pairs": list(pairs),
        "expected_timeframes": list(timeframes),
        "required_file_count": expected_file_count,
        "thresholds": {
            "minimum_coverage_pct": policy.minimum_coverage_pct,
            "maximum_undocumented_gap_candles": policy.maximum_undocumented_gap_candles,
            "maximum_mismatch_days_pct": policy.maximum_mismatch_days_pct,
            "reconciliation_relative_tolerance": policy.reconciliation_relative_tolerance,
            "reconciliation_absolute_tolerance": policy.reconciliation_absolute_tolerance,
        },
        "windows": {
            "download": {
                "start_utc": iso_utc(policy.download_start),
                "end_utc": iso_utc(policy.download_end),
            },
            "splits": [
                {"name": name, "start_utc": iso_utc(start), "end_utc": iso_utc(end)}
                for name, start, end in policy.splits
            ],
        },
        "documented_gaps_source": documented_gap_descriptor,
        "summary": {
            "files_passed": sum(row["status"] == "PASS" for row in data_files),
            "files_total": expected_file_count,
            "split_checks_passed": sum(row["status"] == "PASS" for row in split_checks),
            "split_checks_total": expected_file_count * len(policy.splits),
            "reconciliation_checks_passed": sum(
                row["status"] == "PASS" for row in reconciliation_checks
            ),
            "reconciliation_checks_total": expected_reconciliation_count,
            "failure_count": len(failures),
        },
        "data_files": data_files,
        "split_checks": split_checks,
        "gaps": gap_rows,
        "reconciliation_checks": reconciliation_checks,
        "reconciliation_daily": reconciliation_daily,
        "failures": failures,
        "pnl_evaluated": False,
        "live_trading_authorized": False,
        "evidence_boundary": (
            "Data suitability only. No PnL was parsed; PASS is not a profit guarantee, "
            "forward evidence, or live-trading authorization."
        ),
    }
    if write_output:
        report["report_paths"] = write_reports(selected_report_dir, report)
        # Rewrite once so the canonical JSON records the complete explicit report paths.
        _write_json_atomic(selected_report_dir / "data_quality.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--documented-gaps", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_audit(
            project_root=args.project_root,
            data_dir=args.data_dir,
            report_dir=args.report_dir,
            documented_gaps_path=args.documented_gaps,
        )
    except (AuditError, OSError, ValueError) as exc:
        print(json.dumps({"status": "DATA_BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "failure_count": report["summary"]["failure_count"],
                "report": report.get("report_paths", {}).get("json"),
                "pnl_evaluated": False,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
