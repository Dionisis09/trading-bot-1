#!/usr/bin/env python3
"""Build the immutable six-pair 15m-source canonical dataset before PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "user_data/data/binance/profit_max_intraday_cycle1_source/futures"
AUXILIARY = ROOT / "user_data/data/binance/futures"
OUTPUT_ROOT = ROOT / "user_data/data/binance/profit_max_intraday_cycle1_canonical"
REPORT = ROOT / "user_data/reports/profit_max_intraday_cycle1/canonical_data_audit.json"
START = pd.Timestamp("2021-12-01T00:00:00Z")
END = pd.Timestamp("2026-08-02T00:00:00Z")
PAIRS = ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE")
COLUMNS = ("date", "open", "high", "low", "close", "volume")
NUMERIC = ("open", "high", "low", "close", "volume")
EXPECTED_15M_ROWS = 163_680


class DataBlocked(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def normalize(raw: pd.DataFrame, *, label: str) -> pd.DataFrame:
    if tuple(raw.columns) != COLUMNS:
        raise DataBlocked(f"{label}: schema {tuple(raw.columns)!r} != {COLUMNS!r}")
    frame = raw.loc[:, COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any():
        raise DataBlocked(f"{label}: null values")
    values = frame.loc[:, NUMERIC].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DataBlocked(f"{label}: non-finite numeric values")
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise DataBlocked(f"{label}: duplicate or unordered timestamps")
    invalid = (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (
        frame["low"] > frame[["open", "close", "high"]].min(axis=1)
    )
    if invalid.any() or (frame["low"] <= 0).any() or (frame["volume"] < 0).any():
        raise DataBlocked(f"{label}: invalid OHLCV")
    return frame


def audit_source(frame: pd.DataFrame, *, pair: str) -> dict:
    expected = pd.date_range(START, END, freq="15min", inclusive="left")
    observed = pd.DatetimeIndex(frame["date"])
    if len(frame) != EXPECTED_15M_ROWS or not observed.equals(expected):
        raise DataBlocked(f"{pair}: incomplete exact 15m UTC coverage")
    return {
        "pair": pair,
        "rows": len(frame),
        "first_utc": frame["date"].iloc[0].isoformat(),
        "last_utc": frame["date"].iloc[-1].isoformat(),
        "duplicates": 0,
        "nulls": 0,
        "nonfinite": 0,
        "invalid_ohlcv": 0,
        "status": "PASS",
    }


def aggregate(frame: pd.DataFrame, *, timeframe: str, factor: int) -> pd.DataFrame:
    grouped = frame.set_index("date").resample(timeframe, label="left", closed="left", origin="epoch")
    sizes = grouped.size()
    if len(sizes) == 0 or not sizes.eq(factor).all():
        raise DataBlocked(f"{timeframe}: partial aggregate bins")
    result = grouped.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).reset_index()
    expected = pd.date_range(START, END, freq=timeframe, inclusive="left")
    if not pd.DatetimeIndex(result["date"]).equals(expected):
        raise DataBlocked(f"{timeframe}: aggregate timestamp mismatch")
    return result.loc[:, COLUMNS]


def audit_auxiliary(path: Path, *, pair: str, kind: str) -> dict:
    raw = pd.read_feather(path)
    if tuple(raw.columns) != COLUMNS:
        raise DataBlocked(f"{pair}:{kind}: invalid schema")
    frame = raw.loc[:, COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any() or not np.isfinite(frame.loc[:, NUMERIC].to_numpy(dtype=float)).all():
        raise DataBlocked(f"{pair}:{kind}: null or non-finite values")
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise DataBlocked(f"{pair}:{kind}: duplicate or unordered timestamps")
    if kind == "mark":
        invalid = (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (
            frame["low"] > frame[["open", "close", "high"]].min(axis=1)
        )
        if invalid.any() or (frame["low"] <= 0).any():
            raise DataBlocked(f"{pair}:{kind}: invalid mark OHLC")
    if frame["date"].iloc[0] > START or frame["date"].iloc[-1] < END:
        raise DataBlocked(f"{pair}:{kind}: does not cover locked period")
    return {
        "pair": pair,
        "kind": kind,
        "rows": len(frame),
        "first_utc": frame["date"].iloc[0].isoformat(),
        "last_utc": frame["date"].iloc[-1].isoformat(),
        "sha256": sha256_file(path),
        "decision_feature": False,
        "status": "PASS",
    }


def safe_remove_stage(stage: Path, parent: Path) -> None:
    resolved = stage.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(".profit-max-intraday-stage-"):
        raise DataBlocked(f"unsafe stage cleanup path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def build(source: Path, auxiliary: Path, output_root: Path, report_path: Path) -> dict:
    source = source.resolve()
    auxiliary = auxiliary.resolve()
    output_root = output_root.resolve()
    report_path = report_path.resolve()
    if output_root.exists():
        raise DataBlocked(f"immutable output already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".profit-max-intraday-stage-", dir=output_root.parent))
    futures = stage / "futures"
    futures.mkdir()
    sources: list[dict] = []
    canonical: list[dict] = []
    auxiliary_rows: list[dict] = []
    try:
        for pair in PAIRS:
            source_path = source / f"{pair}_USDT_USDT-15m-futures.feather"
            if not source_path.is_file() or source_path.is_symlink():
                raise DataBlocked(f"missing source: {source_path}")
            source_hash = sha256_file(source_path)
            frame = normalize(pd.read_feather(source_path), label=f"{pair}:15m")
            source_row = audit_source(frame, pair=pair)
            source_row["sha256"] = source_hash
            sources.append(source_row)
            outputs = {
                "15m": frame,
                "1h": aggregate(frame, timeframe="1h", factor=4),
                "4h": aggregate(frame, timeframe="4h", factor=16),
            }
            for timeframe, output in outputs.items():
                destination = futures / f"{pair}_USDT_USDT-{timeframe}-futures.feather"
                if timeframe == "15m":
                    shutil.copyfile(source_path, destination)
                    transformation = "byte_exact_copy"
                else:
                    output.reset_index(drop=True).to_feather(destination, compression="lz4")
                    transformation = "complete_utc_15m_aggregation"
                reread = normalize(pd.read_feather(destination), label=f"{pair}:{timeframe}:roundtrip")
                if len(reread) != len(output) or not pd.DatetimeIndex(reread["date"]).equals(
                    pd.DatetimeIndex(output["date"])
                ):
                    raise DataBlocked(f"{pair}:{timeframe}: roundtrip mismatch")
                canonical.append(
                    {
                        "pair": pair,
                        "timeframe": timeframe,
                        "rows": len(reread),
                        "sha256": sha256_file(destination),
                        "source_15m_sha256": source_hash,
                        "transformation": transformation,
                        "status": "PASS",
                    }
                )
            for kind in ("funding_rate", "mark"):
                aux_path = auxiliary / f"{pair}_USDT_USDT-1h-{kind}.feather"
                if not aux_path.is_file() or aux_path.is_symlink():
                    raise DataBlocked(f"missing auxiliary: {aux_path}")
                row = audit_auxiliary(aux_path, pair=pair, kind=kind)
                destination = futures / aux_path.name
                shutil.copyfile(aux_path, destination)
                if sha256_file(destination) != row["sha256"]:
                    raise DataBlocked(f"{pair}:{kind}: copy hash mismatch")
                auxiliary_rows.append(row)
        if any(sha256_file(source / f"{pair}_USDT_USDT-15m-futures.feather") != row["sha256"] for pair, row in zip(PAIRS, sources)):
            raise DataBlocked("source changed during build")
        os.replace(stage, output_root)
    except Exception:
        safe_remove_stage(stage, output_root.parent)
        raise
    report = {
        "schema_version": "1.0",
        "cycle": "profit_max_intraday_cycle1",
        "status": "PASS",
        "decision": "READY_FOR_FREEZE_AND_TRAIN",
        "pnl_evaluated": False,
        "policy": {
            "source_timeframe": "15m",
            "start_utc": START.isoformat(),
            "end_utc_exclusive": END.isoformat(),
            "pairs": list(PAIRS),
            "expected_15m_rows_per_pair": EXPECTED_15M_ROWS,
        },
        "source_files": sources,
        "canonical_files": canonical,
        "auxiliary_files": auxiliary_rows,
        "summary": {
            "source_passed": len(sources),
            "source_required": 6,
            "canonical_passed": len(canonical),
            "canonical_required": 18,
            "auxiliary_passed": len(auxiliary_rows),
            "auxiliary_required": 12,
        },
        "code_sha256": sha256_file(Path(__file__)),
    }
    payload = canonical_bytes(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--auxiliary", type=Path, default=AUXILIARY)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    try:
        report = build(args.source, args.auxiliary, args.output_root, args.report)
    except (DataBlocked, OSError, ValueError) as exc:
        print(f"DATA_BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "summary": report["summary"], "pnl_evaluated": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
