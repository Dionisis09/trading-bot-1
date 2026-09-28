#!/usr/bin/env python3
"""Finalize the frozen daily-cross TRAIN result from an explicit archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_cross_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["files"].values():
        path = ROOT / item["path"]
        if digest(path) != item["sha256"]:
            raise SystemExit(f"source hash mismatch: {path}")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise SystemExit("archive integrity failure")
        result_names = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and "_config" not in name and "market_change" not in name
        ]
        if len(result_names) != 1:
            raise SystemExit("expected exactly one result JSON")
        strategy = json.loads(bundle.read(result_names[0]))["strategy"]["ProfitMaxDailyCrossSectional"]
    trades = strategy["trades"]
    years = {}
    for year in (2021, 2022, 2023):
        current = [trade for trade in trades if str(trade["open_date"]).startswith(str(year))]
        wins = sum(float(trade["profit_abs"]) for trade in current if float(trade["profit_abs"]) > 0)
        losses = -sum(float(trade["profit_abs"]) for trade in current if float(trade["profit_abs"]) < 0)
        years[str(year)] = {
            "trades": len(current),
            "profit_abs": sum(float(trade["profit_abs"]) for trade in current),
            "profit_factor": wins / losses if losses else None,
        }
    pair_profit = {}
    for trade in trades:
        pair_profit[trade["pair"]] = pair_profit.get(trade["pair"], 0.0) + float(trade["profit_abs"])
    positives = [value for value in pair_profit.values() if value > 0]
    largest_share = max(positives) / sum(positives) if positives else None
    return_pct = float(strategy["profit_total"]) * 100.0
    drawdown_pct = float(strategy["max_drawdown_account"]) * 100.0
    metrics = {
        "trades": int(strategy["total_trades"]),
        "trades_per_day": float(strategy["trades_per_day"]),
        "profit_abs": float(strategy["profit_total_abs"]),
        "return_pct": return_pct,
        "profit_factor": float(strategy["profit_factor"]),
        "wallet_drawdown_pct": drawdown_pct,
        "return_to_drawdown": return_pct / drawdown_pct if drawdown_pct > 0 else None,
        "traded_pairs": len(pair_profit),
        "positive_pairs": len(positives),
        "worst_pair_profit_pct_of_wallet": min(pair_profit.values()) / float(strategy["starting_balance"]) * 100.0,
        "largest_positive_pair_share": largest_share,
        "years": years,
    }
    gates = {
        "trade_count_1095_to_2190": 1095 <= metrics["trades"] <= 2190,
        "frequency_1_to_2": 1.0 <= metrics["trades_per_day"] <= 2.0,
        "return_positive": return_pct > 0,
        "profit_factor_1_15": metrics["profit_factor"] >= 1.15,
        "drawdown_at_most_12": drawdown_pct <= 12.0,
        "return_to_drawdown_1": (metrics["return_to_drawdown"] or 0) >= 1.0,
        "every_year_positive_pf_1_02": all(
            years[str(year)]["profit_abs"] > 0 and (years[str(year)]["profit_factor"] or 0) >= 1.02
            for year in (2021, 2022, 2023)
        ),
        "breadth": (
            metrics["traded_pairs"] >= 35
            and metrics["positive_pairs"] >= 20
            and metrics["worst_pair_profit_pct_of_wallet"] > -3.0
            and (largest_share or 1.0) <= 0.25
        ),
    }
    passed = all(gates.values())
    payload = {
        "schema_version": "1.0",
        "cycle": manifest["cycle"],
        "decision": "UNLOCK_TECHNICAL_GATES" if passed else "KEEP_OFFLINE_RESEARCH",
        "train_pass": passed,
        "validation_revealed": False,
        "live_trading_authorized": False,
        "archive": {"path": archive.relative_to(ROOT).as_posix(), "sha256": digest(archive)},
        "metrics": metrics,
        "gates": gates,
    }
    target_archive = REPORT / "train.zip"
    shutil.copyfile(archive, target_archive)
    (REPORT / "train_decision.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
