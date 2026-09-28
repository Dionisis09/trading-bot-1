#!/usr/bin/env python3
"""Deterministic evaluator for the locked ProfitMax CAGR15 Cycle 5 run."""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import defaultdict
from pathlib import Path

from evaluate_profit_max_cagr15_cycle1 import (
    _cagr,
    _finite,
    _stress,
    atomic_json,
    sha256,
)


CANDIDATE = "ProfitMaxCagr15V5"
FEE = 0.00075
DAYS = 2038


def load(path: Path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("archive integrity failure")
        results = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        configs = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(results) != 1 or len(configs) != 1:
            raise ValueError("exactly one result/config JSON required")
        payload = json.loads(archive.read(results[0]))
        config = json.loads(archive.read(configs[0]))
    if CANDIDATE not in payload.get("strategy", {}):
        raise ValueError("candidate missing")
    return payload["strategy"][CANDIDATE], config


def evaluate(archive: Path) -> dict:
    result, config = load(archive)
    trades = result.get("trades")
    if not isinstance(trades, list) or len(trades) < 80:
        raise ValueError("at least 80 trades required")
    if result.get("timerange") != "20210101-20260801" or result.get("backtest_days") != DAYS:
        raise ValueError("timerange mismatch")
    if config.get("dry_run_wallet") != 1000 or config.get("stake_amount") != 300:
        raise ValueError("wallet/stake mismatch")
    if config.get("max_open_trades") != 1 or config.get("fee") != FEE:
        raise ValueError("max-open/fee mismatch")
    if any(_finite(t[field], field) != FEE for t in trades for field in ("fee_open", "fee_close")):
        raise ValueError("trade fee mismatch")
    if any(t.get("is_short") is not False for t in trades):
        raise ValueError("short trade present")
    if any(_finite(t.get("leverage"), "leverage") != 2.5 for t in trades):
        raise ValueError("leverage mismatch")

    wallet = 1000.0
    profit = _finite(result["profit_total_abs"], "profit_total_abs")
    if abs(profit - sum(_finite(t["profit_abs"], "profit_abs") for t in trades)) > 1e-6:
        raise ValueError("profit reconciliation mismatch")
    years = defaultdict(float)
    for trade in trades:
        years[str(trade["close_date"])[:4]] += _finite(trade["profit_abs"], "profit_abs")
    return_pct = profit / wallet * 100
    cagr = _cagr(profit, wallet, DAYS)
    dd = _finite(result["max_drawdown_account"], "max_drawdown_account") * 100
    pf = _finite(result["profit_factor"], "profit_factor")
    # max_open_trades=1 is validated above. A close and the replacement entry may
    # share one candle timestamp, but they are not simultaneously open positions.
    peak_margin = max(_finite(trade["stake_amount"], "stake_amount") for trade in trades)
    moderate = _stress(trades, wallet, DAYS, 0.0005)
    severe = _stress(trades, wallet, DAYS, 0.0010)
    gates = {
        "cagr_gte_15": cagr >= 15,
        "profit_factor_gte_2": pf >= 2,
        "wallet_drawdown_lte_12": dd <= 12,
        "return_to_drawdown_gte_10": dd > 0 and return_pct / dd >= 10,
        "full_years_positive": all(years.get(str(year), 0) > 0 for year in range(2021, 2026)),
        "partial_2026_gt_minus_2pct": years.get("2026", 0) / wallet * 100 > -2,
        "trades_gte_80": len(trades) >= 80,
        "long_only": all(not t["is_short"] for t in trades),
        "leverage_exact_2_5": all(float(t["leverage"]) == 2.5 for t in trades),
        "peak_margin_lte_20pct": peak_margin <= wallet * 0.20,
        "moderate_stress": moderate["cagr_pct"] >= 13 and moderate["profit_factor"] >= 1.70 and moderate["realized_drawdown_pct"] <= 15,
        "severe_stress": severe["cagr_pct"] >= 10 and severe["profit_factor"] >= 1.40 and severe["realized_drawdown_pct"] <= 18,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    return {
        "schema_version": "1.0",
        "cycle": "profit_max_cagr15_cycle5",
        "candidate": CANDIDATE,
        "status": status,
        "decision": "APPROVE_ISOLATED_DRY_RUN_ONLY" if status == "PASS" else "KEEP_OFFLINE_RESEARCH",
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
        "live_trading_authorized": False,
        "profit_guaranteed": False,
        "metrics": {
            "days": DAYS,
            "trades": len(trades),
            "profit_usdt": profit,
            "return_pct": return_pct,
            "cagr_pct": cagr,
            "profit_factor": pf,
            "wallet_drawdown_pct": dd,
            "return_to_drawdown": return_pct / dd if dd else None,
            "peak_concurrent_margin_usdt": peak_margin,
            "leverage": 2.5,
        },
        "year_profit_usdt": dict(sorted(years.items())),
        "moderate_stress": moderate,
        "severe_stress": severe,
        "gates": gates,
        "sha256": {
            "plan": sha256(Path("docs/profit_max_cagr15_cycle5_locked_plan.md")),
            "strategy": sha256(Path("user_data/strategies/ProfitMaxCagr15V5.py")),
            "config": sha256(Path("user_data/config-profit-max-cagr15-cycle5.json")),
            "risk_policy": sha256(Path("user_data/risk_policy_profit_max_cagr15_cycle5.json")),
            "archive": sha256(archive),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = evaluate(args.archive)
    except Exception as exc:
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_cagr15_cycle5",
            "status": "TECHNICAL_FAILURE",
            "decision": "REJECT_CAGR15_CYCLE5",
            "error": str(exc),
            "live_trading_authorized": False,
            "profit_guaranteed": False,
        }
    atomic_json(args.output, payload)
    print(json.dumps({"status": payload["status"], "decision": payload["decision"]}))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
