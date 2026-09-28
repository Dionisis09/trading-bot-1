#!/usr/bin/env python3
"""Post-failure TRAIN-only ranking diagnostic; never a qualification result."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_intraday_ml_cycle1"
PREDICTIONS = REPORT / "models/profit-max-intraday-ml-cycle1-20260816/backtesting_predictions"
BASE_ARCHIVE = ROOT / "user_data/reports/profit_max_intraday_cycle2/train.zip"
OUTPUT = REPORT / "ranking_diagnostic.json"
PREDICTION = "&-short_net_log_return_4h"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def metrics(frame: pd.DataFrame) -> dict:
    gains = frame.loc[frame["profit_abs"] > 0.0, "profit_abs"].sum()
    losses = -frame.loc[frame["profit_abs"] < 0.0, "profit_abs"].sum()
    return {
        "trades": len(frame),
        "trades_per_day": len(frame) / 730.0,
        "subset_profit_abs_usdt": float(frame["profit_abs"].sum()),
        "subset_profit_factor": float(gains / losses) if losses else None,
        "positive_pairs": int((frame.groupby("pair")["profit_abs"].sum() > 0.0).sum()),
        "minimum_prediction": float(frame[PREDICTION].min()),
    }


def main() -> int:
    frames = []
    for path in sorted(PREDICTIONS.glob("*.feather")):
        symbol = path.name.split("_")[1].upper()
        frame = pd.read_feather(path, columns=["date", PREDICTION, "do_predict"])
        frame["pair"] = f"{symbol}/USDT:USDT"
        frames.append(frame)
    predictions = pd.concat(frames, ignore_index=True).drop_duplicates(["pair", "date"])
    predictions["date"] = pd.to_datetime(predictions["date"], utc=True)
    with zipfile.ZipFile(BASE_ARCHIVE) as archive:
        result_name = next(name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json"))
        trades = pd.DataFrame(json.loads(archive.read(result_name))["strategy"]["ProfitMaxIntradayShortBase15m"]["trades"])
    trades["signal_date"] = pd.to_datetime(trades["open_date"], utc=True) - pd.Timedelta(minutes=15)
    merged = trades.merge(predictions, left_on=["pair", "signal_date"], right_on=["pair", "date"], how="left", validate="one_to_one")
    if merged[PREDICTION].isna().any() or not (merged["do_predict"] == 1).all():
        raise RuntimeError("prediction mapping is incomplete")
    ranked = merged.sort_values(PREDICTION, ascending=False)
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_intraday_ml_cycle1",
        "status": "POST_FAILURE_DIAGNOSTIC_ONLY",
        "qualification_evidence": False,
        "validation_revealed": False,
        "caveat": "Filtered subsets ignore changed concurrency and newly eligible signals; they are not backtests and cannot authorize threshold selection.",
        "mapped_base_trades": len(merged),
        "top_rank_subsets": {str(count): metrics(ranked.head(count)) for count in (219, 365, 500, 600, 730, 800, 904)},
        "interpretation": "At the required 730-trade boundary, the diagnostic subset remains negative with PF below 1.0; no post-hoc threshold is authorized.",
        "inputs": {
            "base_archive_sha256": digest(BASE_ARCHIVE),
            "ml_decision_sha256": digest(REPORT / "train_decision.json"),
            "model_inventory_sha256": json.loads((REPORT / "train_decision.json").read_text(encoding="utf-8"))["model_inventory"]["inventory_sha256"],
        },
    }
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"status": payload["status"], "mapped": len(merged), "sha256": digest(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
