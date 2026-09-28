#!/usr/bin/env python3
"""Audit all Liquid50 1h Cycle 1 market inputs before PnL."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_one_hour_cycle1_source/futures"
UNIVERSE = ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json"
CONFIG = ROOT / "user_data/config-profit-max-liquid50-one-hour-cycle1.json"
REPORT = ROOT / "user_data/reports/profit_max_liquid50_one_hour_cycle1/data_quality.json"
COLUMNS = ("date", "open", "high", "low", "close", "volume")
NUMERIC = ("open", "high", "low", "close", "volume")
START = pd.Timestamp("2021-01-01T00:00:00Z")
END = pd.Timestamp("2026-08-02T00:00:00Z")


class DataBlocked(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path, label: str, *, ohlc: bool) -> pd.DataFrame:
    if not path.is_file() or path.is_symlink():
        raise DataBlocked(f"missing or unsafe {label}: {path}")
    frame = pd.read_feather(path)
    if tuple(frame.columns) != COLUMNS:
        raise DataBlocked(f"{label}: invalid schema")
    frame = frame.loc[:, COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any() or not np.isfinite(frame.loc[:, NUMERIC].to_numpy(float)).all():
        raise DataBlocked(f"{label}: null or non-finite values")
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise DataBlocked(f"{label}: duplicate or unordered timestamps")
    if ohlc:
        invalid = (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (
            frame["low"] > frame[["open", "close", "high"]].min(axis=1)
        )
        if invalid.any() or (frame["low"] <= 0).any() or (frame["volume"] < 0).any():
            raise DataBlocked(f"{label}: invalid OHLCV")
    return frame


def continuity(frame: pd.DataFrame, maximum: pd.Timedelta, label: str, *, exact: bool) -> None:
    differences = frame["date"].diff().dropna()
    invalid = not differences.eq(maximum).all() if exact else (differences <= pd.Timedelta(0)).any() or (differences > maximum).any()
    if invalid:
        raise DataBlocked(f"{label}: invalid timestamp continuity")
    if frame["date"].iloc[0] > START or frame["date"].iloc[-1] < END - maximum:
        raise DataBlocked(f"{label}: insufficient locked-period coverage")


def main() -> int:
    if REPORT.exists():
        print(f"DATA_BLOCKED: immutable report exists: {REPORT}", file=sys.stderr)
        return 2
    try:
        universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        pairs = [row["freqtrade_pair"] for row in universe["selected"]]
        if universe.get("status") != "FROZEN_BEFORE_DATA_AND_PNL" or len(pairs) != 50:
            raise DataBlocked("universe contract mismatch")
        if config["exchange"]["pair_whitelist"] != pairs or config.get("fee") != 0.00075 or config.get("timeframe") != "1h":
            raise DataBlocked("config universe, fee, or timeframe mismatch")

        files = []
        reconciliation = []
        for pair in pairs:
            symbol = pair.split("/")[0]
            paths = {
                "1h_futures": DATA / f"{symbol}_USDT_USDT-1h-futures.feather",
                "1d_futures": DATA / f"{symbol}_USDT_USDT-1d-futures.feather",
                "1h_mark": DATA / f"{symbol}_USDT_USDT-1h-mark.feather",
                "1h_funding_rate": DATA / f"{symbol}_USDT_USDT-1h-funding_rate.feather",
            }
            frames = {
                kind: load(path, f"{symbol}:{kind}", ohlc=kind != "1h_funding_rate")
                for kind, path in paths.items()
            }
            continuity(frames["1h_futures"], pd.Timedelta(hours=1), f"{symbol}:1h_futures", exact=True)
            continuity(frames["1d_futures"], pd.Timedelta(days=1), f"{symbol}:1d_futures", exact=True)
            continuity(frames["1h_mark"], pd.Timedelta(hours=1), f"{symbol}:1h_mark", exact=True)
            continuity(frames["1h_funding_rate"], pd.Timedelta(hours=8), f"{symbol}:funding", exact=False)
            for kind, frame in frames.items():
                path = paths[kind]
                files.append({
                    "pair": pair, "kind": kind, "path": path.relative_to(ROOT).as_posix(),
                    "rows": len(frame), "first_utc": frame["date"].iloc[0].isoformat(),
                    "last_utc": frame["date"].iloc[-1].isoformat(), "bytes": path.stat().st_size,
                    "sha256": digest(path), "status": "PASS",
                })

            hourly = frames["1h_futures"].loc[frames["1h_futures"]["date"] < END]
            derived = hourly.set_index("date").resample("1D", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna().reset_index()
            native = frames["1d_futures"].loc[frames["1d_futures"]["date"] < END]
            joined = derived.merge(native, on="date", suffixes=("_derived", "_native"), validate="one_to_one")
            mismatch = pd.Series(False, index=joined.index)
            for column in ("open", "high", "low", "close"):
                mismatch |= ~np.isclose(joined[f"{column}_derived"], joined[f"{column}_native"], rtol=1e-10, atol=1e-12)
            reconciliation.append({"pair": pair, "overlap_days": len(joined), "mismatch_days": int(mismatch.sum())})

        expected = {path.relative_to(ROOT).as_posix() for path in DATA.glob("*.feather")}
        audited = {row["path"] for row in files}
        if len(files) != 200 or audited != expected:
            raise DataBlocked(f"expected exact 200-file inventory; audited={len(files)} disk={len(expected)}")
        total_mismatch = sum(row["mismatch_days"] for row in reconciliation)
        total_overlap = sum(row["overlap_days"] for row in reconciliation)
        if total_mismatch > 20 or total_mismatch / total_overlap > 0.0002:
            raise DataBlocked("native 1d versus complete 1h reconciliation exceeded tolerance")

        payload = {
            "schema_version": "1.0", "cycle": "profit_max_liquid50_one_hour_cycle1",
            "status": "PASS", "decision": "READY_FOR_PRE_PNL_FREEZE", "pnl_evaluated": False,
            "locked_timerange": "20210101-20260801",
            "policy": {"main_timeframe": "1h", "informative_timeframe": "1d", "fee_per_side": 0.00075, "files_expected": 200},
            "files": sorted(files, key=lambda row: row["path"]),
            "daily_reconciliation": {"rows": reconciliation, "total_overlap_days": total_overlap,
                                     "total_mismatch_days": total_mismatch, "maximum_fraction": 0.0002, "status": "PASS"},
            "summary": {"pairs": 50, "files_passed": 200, "files_failed": 0},
            "universe_sha256": digest(UNIVERSE), "config_sha256": digest(CONFIG), "code_sha256": digest(Path(__file__).resolve()),
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        temporary = REPORT.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, REPORT)
        print(json.dumps({"status": "PASS", "summary": payload["summary"], "daily_mismatch_days": total_mismatch, "sha256": digest(REPORT)}))
        return 0
    except (DataBlocked, FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"DATA_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
