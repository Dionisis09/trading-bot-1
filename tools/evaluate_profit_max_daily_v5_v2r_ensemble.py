#!/usr/bin/env python3
"""Evaluate the locked three-sleeve retrospective ensemble."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from evaluate_profit_max_daily_v5_ensemble_train import ROOT, WALLET, digest, maximum_exposure, profit_factor, summary, wallet_drawdown_pct
from evaluate_profit_max_daily_v5_weighted_continuous import load


DAYS = 2038


def stressed(trades: list[dict], extra_per_side: float) -> dict:
    adjusted = []
    for trade in trades:
        current = dict(trade)
        current["profit_abs"] = float(trade["profit_abs"]) - float(trade["stake_amount"]) * extra_per_side * 2
        adjusted.append(current)
    return {
        "extra_cost_per_side": extra_per_side,
        "profit_usdt": sum(float(trade["profit_abs"]) for trade in adjusted),
        "profit_factor": profit_factor(adjusted),
        "wallet_drawdown_pct": wallet_drawdown_pct(adjusted),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--v5", type=Path, required=True)
    parser.add_argument("--v2r", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: (ROOT / getattr(args, name)).resolve() for name in ("daily", "v5", "v2r")}
    output = (ROOT / args.output).resolve()
    if output.exists():
        print("EVALUATION_BLOCKED: output exists", file=sys.stderr)
        return 3
    try:
        values = {
            "daily": load(paths["daily"], "ProfitMaxDailyCrossStop20AuditV2", 50, 20),
            "v5": load(paths["v5"], "ProfitMaxV5Asymmetric50", 6, 50),
            "v2r": load(paths["v2r"], "DualTrendFuturesV2R", 6, 25),
        }
        trades = [dict(trade, portfolio_component=name) for name, value in values.items() for trade in value["trades"]]
        profit = sum(float(trade["profit_abs"]) for trade in trades)
        return_pct = profit / WALLET * 100
        pf = profit_factor(trades)
        dd = wallet_drawdown_pct(trades)
        positions, stake = maximum_exposure(trades)
        components = {name: summary(value["trades"]) for name, value in values.items()}
        years = {str(year): summary([trade for trade in trades if str(trade["close_date"]).startswith(str(year))]) for year in range(2021, 2027)}
        moderate = stressed(trades, 0.0005)
        severe = stressed(trades, 0.0010)
        metrics = {
            "trades": len(trades),
            "trades_per_day": len(trades) / DAYS,
            "profit_usdt": profit,
            "return_pct": return_pct,
            "profit_factor": pf,
            "wallet_drawdown_pct": dd,
            "return_to_drawdown": return_pct / dd if dd else None,
            "maximum_concurrent_positions": positions,
            "maximum_concurrent_stake_usdt": stake,
        }
        gates = {
            "frequency_1_to_2": 1 <= metrics["trades_per_day"] <= 2,
            "return_gte_15": return_pct >= 15,
            "pf_gte_1_40": pf is not None and pf >= 1.40,
            "dd_lte_10": dd <= 10,
            "return_dd_gte_3": (metrics["return_to_drawdown"] or 0) >= 3,
            "all_years_positive_pf_gte_1_05": all(years[str(year)]["profit_usdt"] > 0 and (years[str(year)]["profit_factor"] or 0) >= 1.05 for year in range(2021, 2027)),
            "daily_nonnegative_pf_gte_1": components["daily"]["profit_usdt"] >= 0 and (components["daily"]["profit_factor"] or 0) >= 1,
            "v5_positive_pf_gte_1_50": components["v5"]["profit_usdt"] > 0 and (components["v5"]["profit_factor"] or 0) >= 1.50,
            "v2r_positive_pf_gte_1_50": components["v2r"]["profit_usdt"] > 0 and (components["v2r"]["profit_factor"] or 0) >= 1.50,
            "exposure": positions <= 6 and stake <= WALLET * 0.20 + 1e-9,
            "moderate_stress": moderate["profit_usdt"] > 0 and (moderate["profit_factor"] or 0) >= 1.25,
            "severe_stress": severe["profit_usdt"] > 0 and (severe["profit_factor"] or 0) >= 1.10,
        }
        passed = all(gates.values())
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_daily_v5_v2r_ensemble_cycle1",
            "status": "PASS" if passed else "FAIL",
            "decision": "PROPOSE_ISOLATED_DRY_RUN" if passed else "KEEP_OFFLINE_RESEARCH",
            "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
            "live_trading_authorized": False,
            "metrics": metrics,
            "components": components,
            "years": years,
            "moderate_stress": moderate,
            "severe_stress": severe,
            "gates": gates,
            "artifacts": {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for name, path in paths.items()},
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0 if passed else 2
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"EVALUATION_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
