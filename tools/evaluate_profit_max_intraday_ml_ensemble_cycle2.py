#!/usr/bin/env python3
"""Evaluate the frozen Cycle-2 ML + swing portfolio on a common wallet curve."""

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
DAYS = 730
FEE = 0.00075
START_MS = 1640995200000
END_MS = 1704067200000
CORE_PAIRS = {"BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, strategy: str, *, timeframe: str, max_open: int, stake: float, pair_count: int, timerange: str) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"ZIP integrity failed: {path}")
        results = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        configs = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(results) != 1 or len(configs) != 1:
            raise ValueError(f"archive inventory mismatch: {path}")
        payload = json.loads(archive.read(results[0])).get("strategy", {}).get(strategy)
        config = json.loads(archive.read(configs[0]))
    if not isinstance(payload, dict):
        raise ValueError(f"missing strategy {strategy}")
    pairs = set(((config.get("exchange") or {}).get("pair_whitelist") or []))
    if not (
        config.get("dry_run_wallet") == WALLET
        and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == timeframe
        and config.get("fee") == FEE
        and config.get("stake_amount") == stake
        and config.get("max_open_trades") == max_open
        and len(pairs) == pair_count
        and (pair_count != 6 or pairs == CORE_PAIRS)
        and str((config.get("exchange") or {}).get("key") or "").strip() in ("", "REDACTED")
        and str((config.get("exchange") or {}).get("secret") or "").strip() in ("", "REDACTED")
    ):
        raise ValueError(f"embedded config mismatch: {strategy}")
    if payload.get("timerange") != timerange:
        raise ValueError(f"timerange mismatch: {strategy}")
    trades = payload.get("trades") or []
    if len(trades) != payload.get("total_trades"):
        raise ValueError(f"trade count mismatch: {strategy}")
    for trade in trades:
        if trade.get("fee_open") != FEE or trade.get("fee_close") != FEE or trade.get("leverage", 1.0) != 1.0:
            raise ValueError(f"fee/leverage mismatch: {strategy}")
        value = trade.get("stake_amount")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid stake: {strategy}")
    return payload


def pf(trades: list[dict]) -> float | None:
    gains = sum(max(float(item["profit_abs"]), 0.0) for item in trades)
    losses = -sum(min(float(item["profit_abs"]), 0.0) for item in trades)
    return gains / losses if losses else None


def summary(trades: list[dict]) -> dict:
    return {"trades": len(trades), "profit_usdt": sum(float(item["profit_abs"]) for item in trades), "profit_factor": pf(trades)}


def drawdown(trades: list[dict]) -> float:
    closed = defaultdict(float)
    for item in trades:
        closed[int(item["close_timestamp"])] += float(item["profit_abs"])
    wallet = peak = WALLET
    worst = 0.0
    for timestamp in sorted(closed):
        wallet += closed[timestamp]
        peak = max(peak, wallet)
        worst = max(worst, peak - wallet)
    return worst / WALLET * 100.0


def exposure(trades: list[dict]) -> tuple[int, float]:
    events = []
    for item in trades:
        stake = float(item["stake_amount"])
        events.append((int(item["open_timestamp"]), 0, 1, stake))
        events.append((int(item["close_timestamp"]), 1, -1, -stake))
    count = 0
    value = 0.0
    max_count = 0
    max_value = 0.0
    for _, _, count_delta, stake_delta in sorted(events):
        count += count_delta
        value += stake_delta
        max_count = max(max_count, count)
        max_value = max(max_value, value)
    return max_count, max_value


def evaluate(ml: dict, v5: dict, v1: dict) -> dict:
    ml_trades = [dict(item, portfolio_component="ml") for item in ml["trades"]]
    v5_trades = [dict(item, portfolio_component="v5") for item in v5["trades"] if START_MS <= int(item["open_timestamp"]) < END_MS]
    v5_keys = {(item["pair"], int(item["open_timestamp"])) for item in v5_trades}
    raw_v1 = [dict(item, portfolio_component="v1_unique") for item in v1["trades"] if START_MS <= int(item["open_timestamp"]) < END_MS]
    v1_trades = [item for item in raw_v1 if (item["pair"], int(item["open_timestamp"])) not in v5_keys]
    selected = ml_trades + v5_trades + v1_trades
    total = sum(float(item["profit_abs"]) for item in selected)
    profit_factor = pf(selected)
    dd = drawdown(selected)
    max_count, max_stake = exposure(selected)
    components = {"ml": summary(ml_trades), "v5": summary(v5_trades), "v1_unique": summary(v1_trades)}
    years = {year: summary([item for item in selected if str(item["close_date"]).startswith(year)]) for year in ("2022", "2023")}
    rate = len(selected) / DAYS
    return_pct = total / WALLET * 100.0
    gates = {
        "frequency_1_to_2": 1.0 <= rate <= 2.0,
        "return_positive": return_pct > 0.0,
        "profit_factor_gte_1_30": profit_factor is not None and profit_factor >= 1.30,
        "wallet_dd_lte_10": dd <= 10.0,
        "return_dd_gte_2": dd > 0.0 and return_pct / dd >= 2.0,
        "both_years_positive_pf_gte_1_15": all(row["profit_usdt"] > 0 and row["profit_factor"] is not None and row["profit_factor"] >= 1.15 for row in years.values()),
        "ml_nonnegative_pf_gte_1": components["ml"]["profit_usdt"] >= 0 and components["ml"]["profit_factor"] is not None and components["ml"]["profit_factor"] >= 1.0,
        "v5_positive": components["v5"]["profit_usdt"] > 0,
        "v1_unique_positive": components["v1_unique"]["profit_usdt"] > 0,
        "v1_unique_trades_gte_20": components["v1_unique"]["trades"] >= 20,
        "maximum_positions_lte_6": max_count <= 6,
        "maximum_stake_lte_40pct": max_stake <= WALLET * 0.40 + 1e-9,
    }
    return {
        "metrics": {"trades": len(selected), "days": DAYS, "trades_per_day": rate, "profit_usdt": total, "return_pct": return_pct, "profit_factor": profit_factor, "wallet_drawdown_pct": dd, "return_to_drawdown": return_pct / dd if dd else None, "maximum_concurrent_positions": max_count, "maximum_concurrent_stake_usdt": max_stake},
        "deduplication": {"v1_raw_trades": len(raw_v1), "v1_exact_v5_overlaps_removed": len(raw_v1) - len(v1_trades), "v1_retained_trades": len(v1_trades)},
        "components": components,
        "years": years,
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--ml", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest_path = (ROOT / args.manifest).resolve()
    ml_path = (ROOT / args.ml).resolve()
    output = (ROOT / args.output).resolve()
    if output.exists():
        print(f"EVALUATION_BLOCKED: output exists: {output}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_MODEL_AND_PNL" or manifest.get("validation_revealed") is not False:
            raise ValueError("manifest state mismatch")
        for item in (manifest.get("files") or {}).values():
            path = ROOT / item["path"]
            if digest(path) != item["sha256"]:
                raise ValueError(f"frozen input changed: {item['path']}")
        v5_path = ROOT / manifest["files"]["v5_train_archive"]["path"]
        v1_path = ROOT / manifest["files"]["v1_train_archive"]["path"]
        result = evaluate(
            load(ml_path, "ProfitMaxIntradayMLV2", timeframe="15m", max_open=3, stake=75, pair_count=6, timerange="20220101-20240101"),
            load(v5_path, "ProfitMaxV5Asymmetric50", timeframe="4h", max_open=2, stake=50, pair_count=6, timerange="20210101-20240101"),
            load(v1_path, "DualTrendFuturesV1", timeframe="4h", max_open=1, stake=50, pair_count=6, timerange="20210101-20240101"),
        )
        passed = not result["failed_gates"]
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_intraday_ml_ensemble_cycle2",
            "status": "PASS" if passed else "FAIL",
            "decision": "UNLOCK_TECHNICAL_AND_VALIDATION_GATES" if passed else "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": False,
            "live_trading_authorized": False,
            "profit_guaranteed": False,
            "fee_per_side": FEE,
            "manifest": {"path": manifest_path.relative_to(ROOT).as_posix(), "sha256": digest(manifest_path)},
            "ml_archive": {"path": ml_path.relative_to(ROOT).as_posix(), "sha256": digest(ml_path)},
            **result,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "trades_per_day": result["metrics"]["trades_per_day"], "return_pct": result["metrics"]["return_pct"], "profit_factor": result["metrics"]["profit_factor"], "sha256": digest(output)}))
        return 0
    except (FileNotFoundError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"EVALUATION_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
