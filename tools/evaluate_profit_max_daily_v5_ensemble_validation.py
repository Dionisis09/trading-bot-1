#!/usr/bin/env python3
"""Evaluate the once-revealed 2024-2025 daily-cross + V5 portfolio."""

from __future__ import annotations

import argparse
import json
import math
import sys
import zipfile
from pathlib import Path

from evaluate_profit_max_daily_v5_ensemble_train import ROOT, WALLET, digest, maximum_exposure, profit_factor, summary, wallet_drawdown_pct


FEE = 0.00075
DAYS = 731
TIMERANGE = "20240101-20260101"


def load(path: Path, strategy_name: str, pair_count: int) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("archive integrity failure")
        results = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        configs = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(results) != 1 or len(configs) != 1:
            raise ValueError("archive inventory failure")
        value = json.loads(archive.read(results[0])).get("strategy", {}).get(strategy_name)
        config = json.loads(archive.read(configs[0]))
    exchange = config.get("exchange") or {}
    markers = {"", "REDACTED"}
    if not isinstance(value, dict) or not (
        value.get("timerange") == TIMERANGE and value.get("backtest_days") == DAYS
        and config.get("dry_run_wallet") == WALLET and config.get("fee") == FEE
        and config.get("stake_amount") == 50 and config.get("max_open_trades") == 2
        and config.get("trading_mode") == "futures" and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "4h" and len(exchange.get("pair_whitelist") or []) == pair_count
        and str(exchange.get("key") or "").strip() in markers
        and str(exchange.get("secret") or "").strip() in markers
    ):
        raise ValueError(f"validation contract mismatch: {strategy_name}")
    trades = value.get("trades") or []
    if len(trades) != value.get("total_trades"):
        raise ValueError("trade reconciliation failure")
    for trade in trades:
        stake = trade.get("stake_amount")
        if trade.get("fee_open") != FEE or trade.get("fee_close") != FEE or trade.get("leverage", 1.0) != 1.0:
            raise ValueError("fee/leverage mismatch")
        if isinstance(stake, bool) or not isinstance(stake, (int, float)) or not math.isfinite(stake) or not 0 < stake <= 50:
            raise ValueError("stake mismatch")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--v5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    daily_path, v5_path = (ROOT / args.daily).resolve(), (ROOT / args.v5).resolve()
    output = (ROOT / args.output).resolve()
    if output.exists():
        print("EVALUATION_BLOCKED: output exists", file=sys.stderr)
        return 3
    try:
        daily = load(daily_path, "ProfitMaxDailyCrossStop20AuditV2", 50)
        v5 = load(v5_path, "ProfitMaxV5Asymmetric50", 6)
        daily_trades = [dict(trade, portfolio_component="daily_cross") for trade in daily["trades"]]
        v5_trades = [dict(trade, portfolio_component="v5") for trade in v5["trades"]]
        if {(trade["pair"], trade["open_timestamp"]) for trade in daily_trades} & {(trade["pair"], trade["open_timestamp"]) for trade in v5_trades}:
            raise ValueError("exact component overlap")
        trades = daily_trades + v5_trades
        profit = sum(float(trade["profit_abs"]) for trade in trades)
        return_pct = profit / WALLET * 100.0
        pf, dd = profit_factor(trades), wallet_drawdown_pct(trades)
        positions, stake = maximum_exposure(trades)
        components = {"daily_cross": summary(daily_trades), "v5": summary(v5_trades)}
        years = {year: summary([trade for trade in trades if str(trade["close_date"]).startswith(year)]) for year in ("2024", "2025")}
        metrics = {
            "trades": len(trades), "trades_per_day": len(trades) / DAYS,
            "profit_usdt": profit, "return_pct": return_pct, "profit_factor": pf,
            "wallet_drawdown_pct": dd, "return_to_drawdown": return_pct / dd if dd else None,
            "maximum_concurrent_positions": positions, "maximum_concurrent_stake_usdt": stake,
        }
        gates = {
            "frequency_1_to_2": 1 <= metrics["trades_per_day"] <= 2,
            "return_positive": return_pct > 0,
            "profit_factor_gte_1_25": pf is not None and pf >= 1.25,
            "drawdown_lte_10": dd <= 10,
            "return_dd_gte_1_5": (metrics["return_to_drawdown"] or 0) >= 1.5,
            "both_years_positive_pf_gte_1_05": all(row["profit_usdt"] > 0 and (row["profit_factor"] or 0) >= 1.05 for row in years.values()),
            "daily_positive_pf_gte_1_05": components["daily_cross"]["profit_usdt"] > 0 and (components["daily_cross"]["profit_factor"] or 0) >= 1.05,
            "v5_positive_pf_gte_1_20": components["v5"]["profit_usdt"] > 0 and (components["v5"]["profit_factor"] or 0) >= 1.20,
            "positions_lte_4": positions <= 4,
            "stake_lte_20pct": stake <= WALLET * 0.20 + 1e-9,
        }
        passed = all(gates.values())
        payload = {
            "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_validation_cycle1",
            "status": "PASS" if passed else "FAIL", "decision": "UNLOCK_CURRENT_AND_CONTINUOUS" if passed else "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": True, "live_trading_authorized": False,
            "metrics": metrics, "components": components, "years": years, "gates": gates,
            "artifacts": {"daily": {"path": daily_path.relative_to(ROOT).as_posix(), "sha256": digest(daily_path)}, "v5": {"path": v5_path.relative_to(ROOT).as_posix(), "sha256": digest(v5_path)}},
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0 if passed else 2
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"EVALUATION_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

