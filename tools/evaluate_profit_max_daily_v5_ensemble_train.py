#!/usr/bin/env python3
"""Evaluate the frozen daily-cross + V5 TRAIN trade streams."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WALLET = 1000.0
FEE = 0.00075
DAYS = 1095


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path, strategy_name: str, pair_count: int) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"archive integrity failed: {path}")
        results = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        configs = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(results) != 1 or len(configs) != 1:
            raise ValueError(f"archive inventory mismatch: {path}")
        value = json.loads(archive.read(results[0])).get("strategy", {}).get(strategy_name)
        config = json.loads(archive.read(configs[0]))
    pairs = (config.get("exchange") or {}).get("pair_whitelist") or []
    if not isinstance(value, dict) or not (
        config.get("dry_run_wallet") == WALLET
        and config.get("fee") == FEE
        and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "4h"
        and config.get("stake_amount") == 50
        and config.get("max_open_trades") == 2
        and len(pairs) == pair_count
        and not str((config.get("exchange") or {}).get("key") or "").strip()
        and not str((config.get("exchange") or {}).get("secret") or "").strip()
    ):
        raise ValueError(f"embedded contract mismatch: {strategy_name}")
    if value.get("timerange") != "20210101-20240101" or value.get("backtest_days") != DAYS:
        raise ValueError(f"timerange mismatch: {strategy_name}")
    trades = value.get("trades") or []
    if len(trades) != value.get("total_trades"):
        raise ValueError(f"trade reconciliation failed: {strategy_name}")
    for trade in trades:
        if trade.get("fee_open") != FEE or trade.get("fee_close") != FEE or trade.get("leverage", 1.0) != 1.0:
            raise ValueError(f"fee/leverage mismatch: {strategy_name}")
        stake = trade.get("stake_amount")
        if isinstance(stake, bool) or not isinstance(stake, (int, float)) or not math.isfinite(stake) or not 0 < stake <= 50:
            raise ValueError(f"stake mismatch: {strategy_name}")
    return value


def profit_factor(trades: list[dict]) -> float | None:
    gains = sum(max(float(trade["profit_abs"]), 0.0) for trade in trades)
    losses = -sum(min(float(trade["profit_abs"]), 0.0) for trade in trades)
    return gains / losses if losses else None


def wallet_drawdown_pct(trades: list[dict]) -> float:
    closed = defaultdict(float)
    for trade in trades:
        closed[int(trade["close_timestamp"])] += float(trade["profit_abs"])
    wallet = peak = WALLET
    maximum = 0.0
    for timestamp in sorted(closed):
        wallet += closed[timestamp]
        peak = max(peak, wallet)
        maximum = max(maximum, peak - wallet)
    return maximum / WALLET * 100.0


def maximum_exposure(trades: list[dict]) -> tuple[int, float]:
    events: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for trade in trades:
        stake = float(trade["stake_amount"])
        events[int(trade["open_timestamp"])][0] += 1
        events[int(trade["open_timestamp"])][1] += stake
        events[int(trade["close_timestamp"])][0] -= 1
        events[int(trade["close_timestamp"])][1] -= stake
    count = maximum_count = 0
    stake = maximum_stake = 0.0
    for timestamp in sorted(events):
        count += int(events[timestamp][0])
        stake += events[timestamp][1]
        maximum_count = max(maximum_count, count)
        maximum_stake = max(maximum_stake, stake)
    return maximum_count, maximum_stake


def summary(trades: list[dict]) -> dict:
    return {
        "trades": len(trades),
        "profit_usdt": sum(float(trade["profit_abs"]) for trade in trades),
        "profit_factor": profit_factor(trades),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--v5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    daily_path = (ROOT / args.daily).resolve()
    v5_path = (ROOT / args.v5).resolve()
    output = (ROOT / args.output).resolve()
    if output.exists():
        print("EVALUATION_BLOCKED: output exists", file=sys.stderr)
        return 3
    try:
        daily = load(daily_path, "ProfitMaxDailyCrossStop20", 50)
        v5 = load(v5_path, "ProfitMaxV5Asymmetric50", 6)
        daily_trades = [dict(trade, portfolio_component="daily_cross") for trade in daily["trades"]]
        v5_trades = [dict(trade, portfolio_component="v5") for trade in v5["trades"]]
        overlap = {(trade["pair"], int(trade["open_timestamp"])) for trade in daily_trades} & {(trade["pair"], int(trade["open_timestamp"])) for trade in v5_trades}
        if overlap:
            raise ValueError("exact component trade overlap is not allowed")
        trades = daily_trades + v5_trades
        profit = sum(float(trade["profit_abs"]) for trade in trades)
        return_pct = profit / WALLET * 100.0
        pf = profit_factor(trades)
        dd = wallet_drawdown_pct(trades)
        max_positions, max_stake = maximum_exposure(trades)
        components = {"daily_cross": summary(daily_trades), "v5": summary(v5_trades)}
        years = {
            year: summary([trade for trade in trades if str(trade["close_date"]).startswith(year)])
            for year in ("2021", "2022", "2023")
        }
        metrics = {
            "trades": len(trades), "trades_per_day": len(trades) / DAYS,
            "profit_usdt": profit, "return_pct": return_pct, "profit_factor": pf,
            "wallet_drawdown_pct": dd, "return_to_drawdown": return_pct / dd if dd else None,
            "maximum_concurrent_positions": max_positions, "maximum_concurrent_stake_usdt": max_stake,
        }
        gates = {
            "frequency_1_to_2": 1.0 <= metrics["trades_per_day"] <= 2.0,
            "return_gte_10": return_pct >= 10.0,
            "profit_factor_gte_1_30": pf is not None and pf >= 1.30,
            "drawdown_lte_10": dd <= 10.0,
            "return_dd_gte_2": metrics["return_to_drawdown"] is not None and metrics["return_to_drawdown"] >= 2.0,
            "all_years_positive_pf_gte_1_05": all(row["profit_usdt"] > 0 and (row["profit_factor"] or 0) >= 1.05 for row in years.values()),
            "daily_positive_pf_gte_1_15": components["daily_cross"]["profit_usdt"] > 0 and (components["daily_cross"]["profit_factor"] or 0) >= 1.15,
            "v5_positive_pf_gte_1_50": components["v5"]["profit_usdt"] > 0 and (components["v5"]["profit_factor"] or 0) >= 1.50,
            "maximum_positions_lte_4": max_positions <= 4,
            "maximum_stake_lte_20pct": max_stake <= WALLET * 0.20 + 1e-9,
        }
        passed = all(gates.values())
        payload = {
            "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_cycle1",
            "status": "PASS" if passed else "FAIL",
            "decision": "UNLOCK_TECHNICAL_GATES" if passed else "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": False, "live_trading_authorized": False,
            "fee_per_side": FEE, "metrics": metrics, "components": components,
            "years": years, "gates": gates,
            "artifacts": {
                "daily": {"path": daily_path.relative_to(ROOT).as_posix(), "sha256": digest(daily_path)},
                "v5": {"path": v5_path.relative_to(ROOT).as_posix(), "sha256": digest(v5_path)},
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0 if passed else 2
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"EVALUATION_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

