#!/usr/bin/env python3
"""Build the isolated ML cycle dataset from exact UTC 15m Binance futures candles."""

from __future__ import annotations

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
SOURCE = ROOT / "user_data/data/binance/profit_max_intraday_ml_cycle1_source/futures"
AUXILIARY = ROOT / "user_data/data/binance/profit_max_intraday_cycle1_canonical/futures"
OUTPUT = ROOT / "user_data/data/binance/profit_max_intraday_ml_cycle1_canonical"
REPORT = ROOT / "user_data/reports/profit_max_intraday_ml_cycle1/canonical_data_audit.json"
START = pd.Timestamp("2020-12-01T00:00:00Z")
END = pd.Timestamp("2026-08-02T00:00:00Z")
PAIRS = ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE")
COLUMNS = ("date", "open", "high", "low", "close", "volume")
NUMERIC = ("open", "high", "low", "close", "volume")
EXPECTED_ROWS = 198_720


class DataBlocked(RuntimeError):
    pass


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def normalize(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    if tuple(raw.columns) != COLUMNS:
        raise DataBlocked(f"{label}: invalid schema")
    frame = raw.loc[:, COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any() or not np.isfinite(frame.loc[:, NUMERIC].to_numpy(float)).all():
        raise DataBlocked(f"{label}: null or non-finite values")
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise DataBlocked(f"{label}: duplicate or unordered timestamps")
    invalid = (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (
        frame["low"] > frame[["open", "close", "high"]].min(axis=1)
    )
    if invalid.any() or (frame["low"] <= 0).any() or (frame["volume"] < 0).any():
        raise DataBlocked(f"{label}: invalid OHLCV")
    return frame


def exact_window(frame: pd.DataFrame, pair: str) -> pd.DataFrame:
    clipped = frame.loc[(frame["date"] >= START) & (frame["date"] < END)].reset_index(drop=True)
    expected = pd.date_range(START, END, freq="15min", inclusive="left")
    if len(clipped) != EXPECTED_ROWS or not pd.DatetimeIndex(clipped["date"]).equals(expected):
        raise DataBlocked(f"{pair}: incomplete exact 15m coverage")
    return clipped


def aggregate(frame: pd.DataFrame, rule: str, factor: int) -> pd.DataFrame:
    grouped = frame.set_index("date").resample(rule, label="left", closed="left", origin="epoch")
    if not grouped.size().eq(factor).all():
        raise DataBlocked(f"{rule}: partial aggregate bin")
    result = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).reset_index()
    expected = pd.date_range(START, END, freq=rule, inclusive="left")
    if not pd.DatetimeIndex(result["date"]).equals(expected):
        raise DataBlocked(f"{rule}: aggregate timestamp mismatch")
    return result.loc[:, COLUMNS]


def main() -> int:
    if OUTPUT.exists() or REPORT.exists():
        print("DATA_BLOCKED: immutable output or report already exists", file=sys.stderr)
        return 2
    stage = Path(tempfile.mkdtemp(prefix=".profit-max-ml-stage-", dir=OUTPUT.parent))
    futures = stage / "futures"
    futures.mkdir()
    source_rows = []
    canonical_rows = []
    auxiliary_rows = []
    try:
        for pair in PAIRS:
            source = SOURCE / f"{pair}_USDT_USDT-15m-futures.feather"
            if not source.is_file() or source.is_symlink():
                raise DataBlocked(f"missing source: {source}")
            source_hash = sha256(source)
            raw = normalize(pd.read_feather(source), f"{pair}:source")
            frame = exact_window(raw, pair)
            source_rows.append({
                "pair": pair,
                "raw_rows": len(raw),
                "canonical_rows": len(frame),
                "raw_first_utc": raw["date"].iloc[0].isoformat(),
                "raw_last_utc": raw["date"].iloc[-1].isoformat(),
                "sha256": source_hash,
                "status": "PASS",
            })
            outputs = {"15m": frame, "1h": aggregate(frame, "1h", 4), "4h": aggregate(frame, "4h", 16)}
            for timeframe, output in outputs.items():
                destination = futures / f"{pair}_USDT_USDT-{timeframe}-futures.feather"
                output.to_feather(destination, compression="lz4")
                reread = normalize(pd.read_feather(destination), f"{pair}:{timeframe}:roundtrip")
                if len(reread) != len(output) or not pd.DatetimeIndex(reread["date"]).equals(pd.DatetimeIndex(output["date"])):
                    raise DataBlocked(f"{pair}:{timeframe}: roundtrip mismatch")
                canonical_rows.append({
                    "pair": pair,
                    "timeframe": timeframe,
                    "rows": len(reread),
                    "sha256": sha256(destination),
                    "transformation": "exact_utc_clip" if timeframe == "15m" else "complete_utc_15m_aggregation",
                    "status": "PASS",
                })
            for kind in ("funding_rate", "mark"):
                source_aux = AUXILIARY / f"{pair}_USDT_USDT-1h-{kind}.feather"
                if not source_aux.is_file() or source_aux.is_symlink():
                    raise DataBlocked(f"missing auxiliary: {source_aux}")
                raw_aux = pd.read_feather(source_aux)
                if tuple(raw_aux.columns) != COLUMNS:
                    raise DataBlocked(f"{pair}:{kind}: invalid schema")
                aux = raw_aux.loc[:, COLUMNS].copy()
                aux["date"] = pd.to_datetime(aux["date"], utc=True, errors="coerce")
                for column in NUMERIC:
                    aux[column] = pd.to_numeric(aux[column], errors="coerce")
                if aux.isna().any().any() or not np.isfinite(aux.loc[:, NUMERIC].to_numpy(float)).all():
                    raise DataBlocked(f"{pair}:{kind}: null or non-finite values")
                if aux["date"].duplicated().any() or not aux["date"].is_monotonic_increasing:
                    raise DataBlocked(f"{pair}:{kind}: duplicate or unordered timestamps")
                if kind == "mark":
                    invalid = (aux["high"] < aux[["open", "close", "low"]].max(axis=1)) | (
                        aux["low"] > aux[["open", "close", "high"]].min(axis=1)
                    )
                    if invalid.any() or (aux["low"] <= 0).any():
                        raise DataBlocked(f"{pair}:{kind}: invalid mark OHLC")
                if aux["date"].iloc[0] > START or aux["date"].iloc[-1] < END:
                    raise DataBlocked(f"{pair}:{kind}: insufficient coverage")
                destination = futures / source_aux.name
                shutil.copyfile(source_aux, destination)
                if sha256(source_aux) != sha256(destination):
                    raise DataBlocked(f"{pair}:{kind}: copy mismatch")
                auxiliary_rows.append({"pair": pair, "kind": kind, "rows": len(aux), "sha256": sha256(destination), "model_feature": False, "status": "PASS"})
        for row in source_rows:
            if sha256(SOURCE / f"{row['pair']}_USDT_USDT-15m-futures.feather") != row["sha256"]:
                raise DataBlocked("source changed during build")
        os.replace(stage, OUTPUT)
        report = {
            "schema_version": "1.0",
            "cycle": "profit_max_intraday_ml_cycle1",
            "status": "PASS",
            "decision": "READY_FOR_PRE_PNL_FREEZE",
            "pnl_evaluated": False,
            "policy": {"source_timeframe": "15m", "start_utc": START.isoformat(), "end_utc_exclusive": END.isoformat(), "expected_rows_per_pair": EXPECTED_ROWS, "pairs": list(PAIRS)},
            "source_files": source_rows,
            "canonical_files": canonical_rows,
            "auxiliary_files": auxiliary_rows,
            "summary": {"sources": len(source_rows), "canonical": len(canonical_rows), "auxiliary": len(auxiliary_rows), "failures": 0},
            "code_sha256": sha256(Path(__file__)),
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        temporary = REPORT.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, REPORT)
        print(json.dumps({"status": "PASS", "summary": report["summary"], "pnl_evaluated": False}))
        return 0
    except (DataBlocked, OSError, ValueError) as exc:
        if stage.exists() and stage.parent.resolve() == OUTPUT.parent.resolve() and stage.name.startswith(".profit-max-ml-stage-"):
            shutil.rmtree(stage)
        print(f"DATA_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
