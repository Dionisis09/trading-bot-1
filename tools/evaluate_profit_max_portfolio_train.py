#!/usr/bin/env python3
"""Evaluate the frozen three-sleeve portfolio on a shared wallet curve."""

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
STARTING_WALLET = 1000.0
EXPECTED_DAYS = 1095
EXPECTED_FEE = 0.00075
EXPECTED_CORE_PAIRS = {
    "BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT",
    "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, strategy: str, expected_max_open: int, expected_pair_count: int) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"ZIP integrity failed: {path}")
        names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        configs = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(names) != 1:
            raise ValueError(f"result inventory mismatch: {path}")
        if len(configs) != 1:
            raise ValueError(f"config inventory mismatch: {path}")
        result = json.loads(archive.read(names[0])).get("strategy", {}).get(strategy)
        config = json.loads(archive.read(configs[0]))
    if not isinstance(result, dict):
        raise ValueError(f"missing strategy {strategy}: {path}")
    pairs = set((config.get("exchange") or {}).get("pair_whitelist") or [])
    common_contract = (
        config.get("dry_run_wallet") == STARTING_WALLET
        and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "4h"
        and config.get("fee") == EXPECTED_FEE
        and config.get("stake_amount") == 50
        and config.get("max_open_trades") == expected_max_open
        and len(pairs) == expected_pair_count
        and str((config.get("exchange") or {}).get("key") or "").strip() in ("", "REDACTED")
        and str((config.get("exchange") or {}).get("secret") or "").strip() in ("", "REDACTED")
    )
    if not common_contract:
        raise ValueError(f"embedded config contract mismatch: {strategy}")
    if expected_pair_count == 6 and pairs != EXPECTED_CORE_PAIRS:
        raise ValueError(f"embedded pair universe mismatch: {strategy}")
    if result.get("backtest_days") != EXPECTED_DAYS or result.get("timerange") != "20210101-20240101":
        raise ValueError(f"timerange mismatch: {strategy}")
    trades = result.get("trades") or []
    if len(trades) != result.get("total_trades"):
        raise ValueError(f"trade count mismatch: {strategy}")
    for trade in trades:
        if trade.get("fee_open") != EXPECTED_FEE or trade.get("fee_close") != EXPECTED_FEE:
            raise ValueError(f"fee mismatch: {strategy}")
        stake = trade.get("stake_amount")
        if isinstance(stake, bool) or not isinstance(stake, (int, float)) or not math.isfinite(stake) or not 0 < stake <= 50:
            raise ValueError(f"stake mismatch: {strategy}")
        leverage = trade.get("leverage", 1.0)
        if isinstance(leverage, bool) or not isinstance(leverage, (int, float)) or leverage != 1.0:
            raise ValueError(f"leverage mismatch: {strategy}")
    return result


def profit_factor(trades: list[dict]) -> float | None:
    gains = sum(max(float(trade["profit_abs"]), 0.0) for trade in trades)
    losses = -sum(min(float(trade["profit_abs"]), 0.0) for trade in trades)
    return gains / losses if losses else None


def wallet_drawdown_pct(trades: list[dict]) -> float:
    closed = defaultdict(float)
    for trade in trades:
        closed[int(trade["close_timestamp"])] += float(trade["profit_abs"])
    wallet = peak = STARTING_WALLET
    maximum = 0.0
    for timestamp in sorted(closed):
        wallet += closed[timestamp]
        peak = max(peak, wallet)
        maximum = max(maximum, peak - wallet)
    return maximum / STARTING_WALLET * 100.0


def maximum_exposure(trades: list[dict]) -> tuple[int, float]:
    events: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for trade in trades:
        stake = float(trade["stake_amount"])
        events[int(trade["open_timestamp"])][0] += 1.0
        events[int(trade["open_timestamp"])][1] += stake
        events[int(trade["close_timestamp"])][0] -= 1.0
        events[int(trade["close_timestamp"])][1] -= stake
    count = 0
    stake = 0.0
    maximum_count = 0
    maximum_stake = 0.0
    for timestamp in sorted(events):
        count += int(events[timestamp][0])
        stake += events[timestamp][1]
        maximum_count = max(maximum_count, count)
        maximum_stake = max(maximum_stake, stake)
    return maximum_count, maximum_stake


def summarize_component(trades: list[dict]) -> dict:
    total = sum(float(trade["profit_abs"]) for trade in trades)
    return {"trades": len(trades), "profit_usdt": total, "profit_factor": profit_factor(trades)}


def evaluate(cross: dict, v5: dict, v1: dict) -> dict:
    cross_trades = [dict(trade, portfolio_component="cross") for trade in cross["trades"]]
    v5_trades = [dict(trade, portfolio_component="v5") for trade in v5["trades"]]
    v5_keys = {(trade["pair"], int(trade["open_timestamp"])) for trade in v5_trades}
    raw_v1 = [dict(trade, portfolio_component="v1_unique") for trade in v1["trades"]]
    v1_trades = [trade for trade in raw_v1 if (trade["pair"], int(trade["open_timestamp"])) not in v5_keys]
    selected = cross_trades + v5_trades + v1_trades
    pf = profit_factor(selected)
    profit = sum(float(trade["profit_abs"]) for trade in selected)
    return_pct = profit / STARTING_WALLET * 100.0
    dd = wallet_drawdown_pct(selected)
    max_count, max_stake = maximum_exposure(selected)
    years = {}
    for year in ("2021", "2022", "2023"):
        annual = [trade for trade in selected if str(trade["close_date"]).startswith(year)]
        years[year] = summarize_component(annual)
    components = {
        "cross": summarize_component(cross_trades),
        "v5": summarize_component(v5_trades),
        "v1_unique": summarize_component(v1_trades),
    }
    rate = len(selected) / EXPECTED_DAYS
    gates = {
        "frequency_1_to_2": 1.0 <= rate <= 2.0,
        "return_positive": return_pct > 0,
        "profit_factor_gte_1_30": pf is not None and pf >= 1.30,
        "wallet_dd_lte_10": dd <= 10.0,
        "return_dd_gte_2": dd > 0 and return_pct / dd >= 2.0,
        "all_train_years_positive_pf_gte_1_15": all(
            row["profit_usdt"] > 0 and row["profit_factor"] is not None and row["profit_factor"] >= 1.15
            for row in years.values()
        ),
        "all_components_positive_pf_gte_1_10": all(
            row["profit_usdt"] > 0 and row["profit_factor"] is not None and row["profit_factor"] >= 1.10
            for row in components.values()
        ),
        "v1_unique_trades_gte_20": len(v1_trades) >= 20,
        "maximum_positions_lte_5": max_count <= 5,
        "maximum_stake_lte_20pct": max_stake <= STARTING_WALLET * 0.20 + 1e-9,
    }
    return {
        "metrics": {"trades": len(selected), "days": EXPECTED_DAYS, "trades_per_day": rate,
                    "profit_usdt": profit, "return_pct": return_pct, "profit_factor": pf,
                    "wallet_drawdown_pct": dd, "return_to_drawdown": return_pct / dd if dd else None,
                    "maximum_concurrent_positions": max_count, "maximum_concurrent_stake_usdt": max_stake},
        "deduplication": {"v1_raw_trades": len(raw_v1), "v1_exact_v5_overlaps_removed": len(raw_v1) - len(v1_trades),
                          "v1_retained_trades": len(v1_trades)},
        "components": components, "years": years, "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cross", required=True)
    parser.add_argument("--v5", required=True)
    parser.add_argument("--v1", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    paths = {name: (ROOT / value).resolve() for name, value in {"cross": args.cross, "v5": args.v5, "v1": args.v1}.items()}
    output = (ROOT / args.output).resolve()
    if output.exists():
        print(f"EVALUATION_BLOCKED: output exists: {output}", file=sys.stderr)
        return 3
    try:
        result = evaluate(load(paths["cross"], "ProfitMaxCrossSectionalTopTwo8h", 2, 50),
                          load(paths["v5"], "ProfitMaxV5Asymmetric50", 2, 6),
                          load(paths["v1"], "DualTrendFuturesV1", 1, 6))
        passed = not result["failed_gates"]
        payload = {"schema_version": "1.0", "cycle": "profit_max_portfolio_ensemble_cycle1",
                   "status": "PASS" if passed else "FAIL",
                   "decision": "UNLOCK_TECHNICAL_GATES" if passed else "KEEP_OFFLINE_RESEARCH",
                   "validation_revealed": False, "live_trading_authorized": False, "profit_guaranteed": False,
                   "fee_per_side": EXPECTED_FEE, **result,
                   "artifacts": {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
                                 for name, path in paths.items()},
                   "evaluator": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
                                 "sha256": digest(Path(__file__).resolve())}}
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"],
                          "trades_per_day": payload["metrics"]["trades_per_day"], "sha256": digest(output)}))
        return 0
    except (FileNotFoundError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"EVALUATION_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
