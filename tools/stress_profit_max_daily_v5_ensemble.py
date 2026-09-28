#!/usr/bin/env python3
"""Apply locked additive per-side slippage to the frozen ensemble trades."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate_profit_max_daily_v5_ensemble_cycle2_train import load
from evaluate_profit_max_daily_v5_ensemble_train import ROOT, WALLET, profit_factor, wallet_drawdown_pct


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--v5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    daily = load((ROOT / args.daily).resolve(), "ProfitMaxDailyCrossStop20", 50)
    v5 = load((ROOT / args.v5).resolve(), "ProfitMaxV5Asymmetric50", 6)
    raw = [dict(trade) for trade in daily["trades"] + v5["trades"]]
    scenarios = {}
    for name, bps_per_side in (("moderate", 5.0), ("severe", 15.0)):
        adjusted = []
        for trade in raw:
            current = dict(trade)
            current["profit_abs"] = float(trade["profit_abs"]) - float(trade["stake_amount"]) * (2 * bps_per_side / 10000.0)
            adjusted.append(current)
        profit = sum(trade["profit_abs"] for trade in adjusted)
        pf = profit_factor(adjusted)
        dd = wallet_drawdown_pct(adjusted)
        years = {}
        for year in ("2021", "2022", "2023"):
            annual = [trade for trade in adjusted if str(trade["close_date"]).startswith(year)]
            years[year] = {"profit_usdt": sum(trade["profit_abs"] for trade in annual), "profit_factor": profit_factor(annual)}
        scenarios[name] = {
            "added_slippage_bps_per_side": bps_per_side,
            "profit_usdt": profit,
            "return_pct": profit / WALLET * 100.0,
            "profit_factor": pf,
            "wallet_drawdown_pct": dd,
            "years": years,
            "pass": profit > 0 and pf is not None and pf >= (1.20 if name == "moderate" else 1.05),
        }
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_cycle2",
        "trade_count": len(raw), "scenarios": scenarios,
        "validation_revealed": False, "live_trading_authorized": False,
        "pass": all(row["pass"] for row in scenarios.values()),
    }
    output = (ROOT / args.output).resolve()
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0 if payload["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
