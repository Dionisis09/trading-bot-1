#!/usr/bin/env python3
"""Fail-closed evaluator for the locked ProfitMax CAGR15 Cycle 1 archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


CANDIDATE = "ProfitMaxCagr15V1"
TIMERANGE = "20210101-20260801"
BASE_FEE = 0.00075
EXPECTED_DAYS = 2038
YEAR_DAYS = 365.2425


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} is not finite")
    return number


def _load_archive(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("archive integrity failure")
        result_members = [
            name for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        config_members = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(result_members) != 1 or len(config_members) != 1:
            raise ValueError("archive must contain exactly one result and one config JSON")
        result = json.loads(archive.read(result_members[0]))
        config = json.loads(archive.read(config_members[0]))
    if CANDIDATE not in result.get("strategy", {}):
        raise ValueError(f"missing strategy {CANDIDATE}")
    return result["strategy"][CANDIDATE], config


def _cagr(profit_abs: float, wallet: float, days: int) -> float:
    ending_multiple = 1.0 + profit_abs / wallet
    if ending_multiple <= 0:
        return -100.0
    return (ending_multiple ** (YEAR_DAYS / days) - 1.0) * 100.0


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return math.inf if wins > 0 else 0.0
    return wins / losses


def _realized_drawdown_pct(trades: list[dict[str, Any]], profits: list[float], wallet: float) -> float:
    ordered = sorted(zip(trades, profits), key=lambda item: (item[0]["close_timestamp"], item[0]["open_timestamp"]))
    equity = peak = wallet
    maximum = 0.0
    for _, profit in ordered:
        equity += profit
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / wallet * 100.0)
    return maximum


def _stress(trades: list[dict[str, Any]], wallet: float, days: int, extra_per_side: float) -> dict[str, float]:
    stressed: list[float] = []
    for trade in trades:
        amount = _finite(trade["amount"], "amount")
        open_notional = amount * _finite(trade["open_rate"], "open_rate")
        close_notional = amount * _finite(trade["close_rate"], "close_rate")
        stressed.append(
            _finite(trade["profit_abs"], "profit_abs")
            - extra_per_side * (open_notional + close_notional)
        )
    profit_abs = sum(stressed)
    return {
        "extra_cost_per_side": extra_per_side,
        "profit_usdt": profit_abs,
        "cagr_pct": _cagr(profit_abs, wallet, days),
        "profit_factor": _profit_factor(stressed),
        "realized_drawdown_pct": _realized_drawdown_pct(trades, stressed, wallet),
    }


def _peak_concurrent_stake(trades: list[dict[str, Any]]) -> float:
    events: list[tuple[int, int, float]] = []
    for trade in trades:
        stake = _finite(trade["stake_amount"], "stake_amount")
        # Opens sort before closes at the same timestamp for a conservative bound.
        events.append((int(trade["open_timestamp"]), 0, stake))
        events.append((int(trade["close_timestamp"]), 1, -stake))
    running = peak = 0.0
    for _, _, change in sorted(events):
        running += change
        peak = max(peak, running)
    return peak


def evaluate(archive_path: Path, plan_path: Path, strategy_path: Path, config_path: Path) -> dict[str, Any]:
    strategy, embedded_config = _load_archive(archive_path)
    trades = strategy.get("trades")
    if not isinstance(trades, list) or not trades:
        raise ValueError("non-empty trade list required")
    wallet = _finite(embedded_config.get("dry_run_wallet"), "dry_run_wallet")
    if wallet != 1000.0 or embedded_config.get("stake_amount") != 350:
        raise ValueError("embedded wallet/stake mismatch")
    if embedded_config.get("max_open_trades") != 2 or embedded_config.get("fee") != BASE_FEE:
        raise ValueError("embedded max_open_trades/fee mismatch")
    if strategy.get("timerange") != TIMERANGE or int(strategy.get("backtest_days")) != EXPECTED_DAYS:
        raise ValueError("timerange/day mismatch")
    if any(
        _finite(trade.get(field), field) != BASE_FEE
        for trade in trades for field in ("fee_open", "fee_close")
    ):
        raise ValueError("trade fee mismatch")

    profit_abs = _finite(strategy["profit_total_abs"], "profit_total_abs")
    recomputed_profit = sum(_finite(trade["profit_abs"], "profit_abs") for trade in trades)
    if abs(profit_abs - recomputed_profit) > 1e-6:
        raise ValueError("profit reconciliation mismatch")
    years: dict[str, float] = defaultdict(float)
    for trade in trades:
        years[str(trade["close_date"])[:4]] += _finite(trade["profit_abs"], "profit_abs")

    return_pct = profit_abs / wallet * 100.0
    drawdown_pct = _finite(strategy["max_drawdown_account"], "max_drawdown_account") * 100.0
    cagr_pct = _cagr(profit_abs, wallet, EXPECTED_DAYS)
    peak_stake = _peak_concurrent_stake(trades)
    moderate = _stress(trades, wallet, EXPECTED_DAYS, 0.0005)
    severe = _stress(trades, wallet, EXPECTED_DAYS, 0.0010)
    gates = {
        "cagr_gte_15": cagr_pct >= 15.0,
        "profit_factor_gte_2": _finite(strategy["profit_factor"], "profit_factor") >= 2.0,
        "drawdown_lte_12": drawdown_pct <= 12.0,
        "return_to_drawdown_gte_10": drawdown_pct > 0 and return_pct / drawdown_pct >= 10.0,
        "all_full_years_positive": all(years.get(str(year), 0.0) > 0 for year in range(2021, 2026)),
        "partial_2026_gt_minus_2pct": years.get("2026", 0.0) / wallet * 100.0 > -2.0,
        "both_sides": any(not trade["is_short"] for trade in trades) and any(trade["is_short"] for trade in trades),
        "peak_concurrent_stake_lte_50pct": peak_stake <= wallet * 0.50,
        "moderate_stress": moderate["cagr_pct"] >= 13.0 and moderate["profit_factor"] >= 1.70 and moderate["realized_drawdown_pct"] <= 15.0,
        "severe_stress": severe["cagr_pct"] >= 10.0 and severe["profit_factor"] >= 1.40 and severe["realized_drawdown_pct"] <= 18.0,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    return {
        "schema_version": "1.0",
        "cycle": "profit_max_cagr15_cycle1",
        "candidate": CANDIDATE,
        "status": status,
        "decision": "APPROVE_ISOLATED_DRY_RUN_ONLY" if status == "PASS" else "KEEP_OFFLINE_RESEARCH",
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
        "live_trading_authorized": False,
        "profit_guaranteed": False,
        "metrics": {
            "days": EXPECTED_DAYS,
            "trades": len(trades),
            "profit_usdt": profit_abs,
            "return_pct": return_pct,
            "cagr_pct": cagr_pct,
            "profit_factor": _finite(strategy["profit_factor"], "profit_factor"),
            "wallet_drawdown_pct": drawdown_pct,
            "return_to_drawdown": return_pct / drawdown_pct if drawdown_pct else None,
            "long_trades": sum(not trade["is_short"] for trade in trades),
            "short_trades": sum(trade["is_short"] for trade in trades),
            "peak_concurrent_stake_usdt": peak_stake,
        },
        "year_profit_usdt": dict(sorted(years.items())),
        "moderate_stress": moderate,
        "severe_stress": severe,
        "gates": gates,
        "sha256": {
            "locked_plan": sha256(plan_path),
            "strategy": sha256(strategy_path),
            "config": sha256(config_path),
            "archive": sha256(archive_path),
        },
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=Path("docs/profit_max_cagr15_cycle1_locked_plan.md"))
    parser.add_argument("--strategy", type=Path, default=Path("user_data/strategies/ProfitMaxCagr15V1.py"))
    parser.add_argument("--config", type=Path, default=Path("user_data/config-profit-max-cagr15-cycle1.json"))
    args = parser.parse_args()
    try:
        payload = evaluate(args.archive, args.plan, args.strategy, args.config)
        atomic_json(args.output, payload)
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "output": str(args.output)}))
        return 0 if payload["status"] == "PASS" else 2
    except Exception as exc:  # fail closed at the CLI boundary
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_cagr15_cycle1",
            "status": "TECHNICAL_FAILURE",
            "decision": "REJECT_CAGR15_CYCLE1",
            "error": str(exc),
            "live_trading_authorized": False,
            "profit_guaranteed": False,
        }
        atomic_json(args.output, payload)
        print(json.dumps(payload))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
