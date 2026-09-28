#!/usr/bin/env python3
"""Finalize all frozen Cycle 2 TRAIN candidates from an explicit archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_cross_cycle2"
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
        if digest(ROOT / item["path"]) != item["sha256"]:
            raise SystemExit(f"frozen hash mismatch: {item['path']}")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise SystemExit("archive integrity failure")
        names = [name for name in bundle.namelist() if name.endswith(".json") and "_config" not in name and "market_change" not in name]
        if len(names) != 1:
            raise SystemExit("expected one result JSON")
        strategies = json.loads(bundle.read(names[0]))["strategy"]
    results = []
    for name in manifest["candidates"]:
        value = strategies[name]
        trades = value["trades"]
        years = {}
        for year in (2021, 2022, 2023):
            current = [trade for trade in trades if str(trade["open_date"]).startswith(str(year))]
            wins = sum(float(trade["profit_abs"]) for trade in current if float(trade["profit_abs"]) > 0)
            losses = -sum(float(trade["profit_abs"]) for trade in current if float(trade["profit_abs"]) < 0)
            years[str(year)] = {"trades": len(current), "profit_abs": sum(float(trade["profit_abs"]) for trade in current), "profit_factor": wins / losses if losses else None}
        pair_profit = {}
        for trade in trades:
            pair_profit[trade["pair"]] = pair_profit.get(trade["pair"], 0.0) + float(trade["profit_abs"])
        positives = [profit for profit in pair_profit.values() if profit > 0]
        return_pct = float(value["profit_total"]) * 100.0
        drawdown_pct = float(value["max_drawdown_account"]) * 100.0
        metrics = {
            "trades": int(value["total_trades"]), "trades_per_day": float(value["trades_per_day"]),
            "profit_abs": float(value["profit_total_abs"]), "return_pct": return_pct,
            "profit_factor": float(value["profit_factor"]), "wallet_drawdown_pct": drawdown_pct,
            "return_to_drawdown": return_pct / drawdown_pct if drawdown_pct else None,
            "traded_pairs": len(pair_profit), "positive_pairs": len(positives),
            "worst_pair_profit_pct_of_wallet": min(pair_profit.values()) / float(value["starting_balance"]) * 100.0,
            "largest_positive_pair_share": max(positives) / sum(positives) if positives else None,
            "years": years,
        }
        gates = {
            "count": 1095 <= metrics["trades"] <= 2190,
            "frequency": 1.0 <= metrics["trades_per_day"] <= 2.0,
            "return": return_pct > 0,
            "pf": metrics["profit_factor"] >= 1.15,
            "dd": drawdown_pct <= 12.0,
            "return_dd": (metrics["return_to_drawdown"] or 0) >= 1.0,
            "years": all(years[str(year)]["profit_abs"] > 0 and (years[str(year)]["profit_factor"] or 0) >= 1.02 for year in (2021, 2022, 2023)),
            "breadth": len(pair_profit) >= 35 and len(positives) >= 20 and metrics["worst_pair_profit_pct_of_wallet"] > -3 and (metrics["largest_positive_pair_share"] or 1) <= 0.25,
        }
        results.append({"strategy": name, "metrics": metrics, "gates": gates, "pass": all(gates.values())})
    passers = [row for row in results if row["pass"]]
    passers.sort(key=lambda row: (row["metrics"]["return_to_drawdown"], row["metrics"]["profit_factor"], -abs(float(strategies[row["strategy"]]["stoploss"]))), reverse=True)
    payload = {
        "schema_version": "1.0", "cycle": manifest["cycle"],
        "decision": "UNLOCK_TECHNICAL_GATES" if passers else "KEEP_OFFLINE_RESEARCH",
        "selected": passers[0]["strategy"] if passers else None,
        "validation_revealed": False, "live_trading_authorized": False,
        "archive": {"path": archive.relative_to(ROOT).as_posix(), "sha256": digest(archive)},
        "results": results,
    }
    (REPORT / "train_decision.json").write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0 if passers else 2


if __name__ == "__main__":
    raise SystemExit(main())
