#!/usr/bin/env python3
"""Record the user's frequency-agnostic 15% CAGR objective separately from strict gates."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from evaluate_profit_max_cagr15_cycle1 import atomic_json, sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--strict-decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    strict = json.loads(args.strict_decision.read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.archive) as archive:
        result_name = next(name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json"))
        config_name = next(name for name in archive.namelist() if name.endswith("_config.json"))
        result = json.loads(archive.read(result_name))["strategy"]["ProfitMaxCagr15V5"]
        config = json.loads(archive.read(config_name))
    trades = result["trades"]
    max_margin = max(float(trade["stake_amount"]) for trade in trades)
    fee_ok = all(float(trade["fee_open"]) == 0.00075 and float(trade["fee_close"]) == 0.00075 for trade in trades)
    leverage_ok = all(float(trade["leverage"]) == 2.5 for trade in trades)
    full_year_profit = sum(
        float(trade["profit_abs"])
        for trade in trades
        if 2021 <= int(str(trade["close_date"])[:4]) <= 2025
    )
    full_five_year_cagr = ((1.0 + full_year_profit / 1000.0) ** (1.0 / 5.0) - 1.0) * 100.0
    objective_gates = {
        "cagr_gte_15": float(strict["metrics"]["cagr_pct"]) >= 15.0,
        "full_five_year_cagr_gte_15": full_five_year_cagr >= 15.0,
        "binance_fee_exact": fee_ok,
        "severe_cost_cagr_gte_15": float(strict["severe_stress"]["cagr_pct"]) >= 15.0,
        "wallet_drawdown_lte_12": float(strict["metrics"]["wallet_drawdown_pct"]) <= 12.0,
        "one_position": config["max_open_trades"] == 1,
        "individual_margin_lte_20pct": max_margin <= float(config["dry_run_wallet"]) * 0.20,
        "leverage_exact_2_5": leverage_ok,
        "frequency_gate_absent": config["profit_max_research"]["frequency_gate"] is False,
    }
    meets = all(objective_gates.values())
    payload = {
        "schema_version": "1.0",
        "candidate": "ProfitMaxCagr15V5",
        "status": "MEETS_RETROSPECTIVE_USER_OBJECTIVE" if meets else "DOES_NOT_MEET_USER_OBJECTIVE",
        "user_objective": "Binance five-year average CAGR >=15%; trade frequency irrelevant",
        "objective_gates": objective_gates,
        "metrics": strict["metrics"],
        "full_five_year_metrics": {
            "timerange": "20210101-20260101",
            "profit_usdt": full_year_profit,
            "return_pct": full_year_profit / 1000.0 * 100.0,
            "cagr_pct": full_five_year_cagr,
        },
        "moderate_stress": strict["moderate_stress"],
        "severe_stress": strict["severe_stress"],
        "year_profit_usdt": strict["year_profit_usdt"],
        "years_without_closed_trades": ["2022", "2026"],
        "maximum_individual_margin_usdt": max_margin,
        "strict_cycle5_decision": strict["decision"],
        "strict_cycle5_fail_reasons": [name for name, passed in strict["gates"].items() if not passed],
        "evidence_boundary": "Fully seen retrospective history; not a sealed holdout, forward result, or profit guarantee.",
        "next_step": "ISOLATED_DRY_RUN_FORWARD_EVALUATION",
        "live_trading_authorized": False,
        "profit_guaranteed": False,
        "sha256": {
            "archive": sha256(args.archive),
            "strict_decision": sha256(args.strict_decision),
        },
    }
    atomic_json(args.output, payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output)}))
    return 0 if meets else 2


if __name__ == "__main__":
    raise SystemExit(main())
