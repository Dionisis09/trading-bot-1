#!/usr/bin/env python3
"""Fail-closed Cycle 2 shared-wallet TRAIN evaluator."""

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
DAYS = 1095
FEE = 0.00075
CORE = {"BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def reverify_manifest(path: Path) -> tuple[dict, int]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_CYCLE2_PNL":
        raise ValueError("manifest status mismatch")
    count = 0
    for section in ("files", "data_files"):
        values = manifest.get(section) or {}
        rows = values.values() if isinstance(values, dict) else values
        for row in rows:
            target = ROOT / row["path"]
            if not target.is_file() or target.is_symlink() or sha(target) != row["sha256"]:
                raise ValueError(f"frozen input drift: {row['path']}")
            count += 1
    return manifest, count


def load(path: Path, strategy: str, stake: float, max_open: int, pair_count: int) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"ZIP integrity failed: {path}")
        results = [n for n in archive.namelist() if n.endswith(".json") and not n.endswith("_config.json")]
        configs = [n for n in archive.namelist() if n.endswith("_config.json")]
        if len(results) != 1 or len(configs) != 1:
            raise ValueError(f"archive inventory mismatch: {path}")
        result = json.loads(archive.read(results[0])).get("strategy", {}).get(strategy)
        config = json.loads(archive.read(configs[0]))
    exchange = config.get("exchange") or {}
    pairs = set(exchange.get("pair_whitelist") or [])
    if not (
        isinstance(result, dict) and result.get("timerange") == "20210101-20240101"
        and result.get("backtest_days") == DAYS
        and config.get("dry_run_wallet") == WALLET
        and config.get("trading_mode") == "futures" and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "4h" and config.get("fee") == FEE
        and config.get("stake_amount") == stake and config.get("max_open_trades") == max_open
        and len(pairs) == pair_count and (pair_count != 6 or pairs == CORE)
        and str(exchange.get("key") or "").strip() in ("", "REDACTED")
        and str(exchange.get("secret") or "").strip() in ("", "REDACTED")
    ):
        raise ValueError(f"embedded contract mismatch: {strategy}")
    trades = result.get("trades") or []
    if len(trades) != result.get("total_trades"):
        raise ValueError(f"trade reconciliation mismatch: {strategy}")
    for trade in trades:
        actual = trade.get("stake_amount")
        leverage = trade.get("leverage", 1.0)
        if trade.get("fee_open") != FEE or trade.get("fee_close") != FEE:
            raise ValueError(f"fee mismatch: {strategy}")
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or not 0 < actual <= stake * 1.30 + 1e-9:
            raise ValueError(f"realized stake outside locked tolerance: {strategy}")
        if isinstance(leverage, bool) or not isinstance(leverage, (int, float)) or leverage != 1.0:
            raise ValueError(f"leverage mismatch: {strategy}")
    return result


def pf(trades: list[dict]) -> float | None:
    gains = sum(max(float(t["profit_abs"]), 0.0) for t in trades)
    losses = -sum(min(float(t["profit_abs"]), 0.0) for t in trades)
    return gains / losses if losses else None


def dd_pct(trades: list[dict]) -> float:
    closes = defaultdict(float)
    for trade in trades:
        closes[int(trade["close_timestamp"])] += float(trade["profit_abs"])
    equity = peak = WALLET
    maximum = 0.0
    for timestamp in sorted(closes):
        equity += closes[timestamp]
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum / WALLET * 100.0


def exposure(trades: list[dict]) -> tuple[int, float]:
    events = defaultdict(lambda: [0, 0.0])
    for trade in trades:
        events[int(trade["open_timestamp"])][0] += 1
        events[int(trade["open_timestamp"])][1] += float(trade["stake_amount"])
        events[int(trade["close_timestamp"])][0] -= 1
        events[int(trade["close_timestamp"])][1] -= float(trade["stake_amount"])
    count = maximum_count = 0
    stake = maximum_stake = 0.0
    for timestamp in sorted(events):
        count += events[timestamp][0]
        stake += events[timestamp][1]
        maximum_count = max(maximum_count, count)
        maximum_stake = max(maximum_stake, stake)
    return maximum_count, maximum_stake


def summary(trades: list[dict]) -> dict:
    return {"trades": len(trades), "profit_usdt": sum(float(t["profit_abs"]) for t in trades), "profit_factor": pf(trades)}


def evaluate(cross: dict, liquid: dict, v5: dict) -> dict:
    cross_trades = [dict(t, portfolio_component="cross") for t in cross["trades"]]
    v5_trades = [dict(t, portfolio_component="v5") for t in v5["trades"]]
    protected = {(t["pair"], int(t["open_timestamp"])) for t in cross_trades + v5_trades}
    liquid_raw = [dict(t, portfolio_component="liquid_unique") for t in liquid["trades"]]
    liquid_unique = [t for t in liquid_raw if (t["pair"], int(t["open_timestamp"])) not in protected]
    selected = cross_trades + liquid_unique + v5_trades
    profit = sum(float(t["profit_abs"]) for t in selected)
    overall_pf = pf(selected)
    drawdown = dd_pct(selected)
    maximum_count, maximum_stake = exposure(selected)
    years = {year: summary([t for t in selected if str(t["close_date"]).startswith(year)]) for year in ("2021", "2022", "2023")}
    components = {"cross": summary(cross_trades), "liquid_unique": summary(liquid_unique), "v5": summary(v5_trades)}
    rate = len(selected) / DAYS
    return_pct = profit / WALLET * 100.0
    gates = {
        "frequency_1_to_2": 1.0 <= rate <= 2.0,
        "return_positive": return_pct > 0,
        "profit_factor_gte_1_50": overall_pf is not None and overall_pf >= 1.50,
        "wallet_dd_lte_10": drawdown <= 10.0,
        "return_dd_gte_3": drawdown > 0 and return_pct / drawdown >= 3.0,
        "all_years_positive_pf_gte_1_15": all(r["profit_usdt"] > 0 and r["profit_factor"] is not None and r["profit_factor"] >= 1.15 for r in years.values()),
        "all_components_positive_pf_gte_1_10": all(r["profit_usdt"] > 0 and r["profit_factor"] is not None and r["profit_factor"] >= 1.10 for r in components.values()),
        "liquid_unique_trades_gte_250": len(liquid_unique) >= 250,
        "maximum_positions_lte_6": maximum_count <= 6,
        "maximum_stake_lte_20pct": maximum_stake <= 200.0 + 1e-9,
    }
    return {
        "metrics": {"trades": len(selected), "days": DAYS, "trades_per_day": rate, "profit_usdt": profit, "return_pct": return_pct, "profit_factor": overall_pf, "wallet_drawdown_pct": drawdown, "return_to_drawdown": return_pct / drawdown if drawdown else None, "maximum_concurrent_positions": maximum_count, "maximum_concurrent_stake_usdt": maximum_stake},
        "deduplication": {"liquid_raw_trades": len(liquid_raw), "liquid_overlaps_removed": len(liquid_raw) - len(liquid_unique), "liquid_retained_trades": len(liquid_unique)},
        "components": components, "years": years, "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("manifest", "cross", "liquid", "v5", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    paths = {name: (ROOT / getattr(args, name)).resolve() for name in ("manifest", "cross", "liquid", "v5")}
    output = (ROOT / args.output).resolve()
    if output.exists():
        print("EVALUATION_BLOCKED: output exists", file=sys.stderr)
        return 3
    try:
        manifest, verified = reverify_manifest(paths["manifest"])
        planned = manifest.get("artifacts") or {}
        for name in ("cross", "liquid", "v5"):
            if paths[name].relative_to(ROOT).as_posix() != planned.get(f"{name}_train"):
                raise ValueError(f"artifact path mismatch: {name}")
        result = evaluate(load(paths["cross"], "ProfitMaxCrossSectionalTopTwo8h", 12.5, 2, 50), load(paths["liquid"], "ProfitMaxLiquid50V1", 25, 5, 50), load(paths["v5"], "ProfitMaxV5Asymmetric50", 100, 2, 6))
        passed = not result["failed_gates"]
        payload = {"schema_version": "1.0", "cycle": "profit_max_portfolio_ensemble_cycle2", "status": "PASS" if passed else "FAIL", "decision": "UNLOCK_TECHNICAL_GATES" if passed else "KEEP_OFFLINE_RESEARCH", "validation_revealed": False, "live_trading_authorized": False, "profit_guaranteed": False, "fee_per_side": FEE, "freeze_manifest_sha256": sha(paths["manifest"]), "frozen_inputs_reverified": verified, **result, "artifacts": {name: {"path": paths[name].relative_to(ROOT).as_posix(), "sha256": sha(paths[name])} for name in ("cross", "liquid", "v5")}}
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "trades_per_day": result["metrics"]["trades_per_day"], "return_pct": result["metrics"]["return_pct"], "profit_factor": result["metrics"]["profit_factor"], "drawdown_pct": result["metrics"]["wallet_drawdown_pct"], "sha256": sha(output)}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"EVALUATION_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
