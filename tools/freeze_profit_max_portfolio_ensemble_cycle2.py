#!/usr/bin/env python3
"""Freeze Cycle 2 source, configuration, and data before component PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_portfolio_ensemble_cycle2"
LIQUID_DATA = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"
CORE_DATA = ROOT / "user_data/data/binance/futures"
CORE_PAIRS = ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE")
CORE_SUFFIXES = ("4h-futures.feather", "1d-futures.feather", "1h-funding_rate.feather", "1h-mark.feather")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    files = {
        "plan": ROOT / "docs/profit_max_portfolio_ensemble_cycle2_locked_plan.md",
        "evaluator": ROOT / "tools/evaluate_profit_max_portfolio_cycle2_train.py",
        "evaluator_tests": ROOT / "tools/test_evaluate_profit_max_portfolio_cycle2_train.py",
        "freeze": Path(__file__).resolve(),
        "liquid_base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "core_base_config": ROOT / "user_data/config-profit-max-swing-cycle5.json",
        "cross_overlay": ROOT / "user_data/config-profit-max-portfolio-cycle2-cross-overlay.json",
        "liquid_overlay": ROOT / "user_data/config-profit-max-portfolio-cycle2-liquid-overlay.json",
        "v5_overlay": ROOT / "user_data/config-profit-max-portfolio-cycle2-v5-overlay.json",
        "cross_strategy": ROOT / "user_data/strategies/ProfitMaxCrossSectionalShortHorizon.py",
        "cross_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "liquid_strategy": ROOT / "user_data/strategies/ProfitMaxLiquid50V1.py",
        "v5_strategy": ROOT / "user_data/strategies/ProfitMaxSwingV5.py",
        "v1_parent": ROOT / "user_data/strategies/DualTrendFuturesV1.py",
        "v2_parent": ROOT / "user_data/strategies/DualTrendFuturesV2.py",
        "risk_parent": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "liquid_data_audit": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "cycle1_freeze": ROOT / "user_data/reports/profit_max_portfolio_ensemble_cycle1/research_freeze_manifest.json",
        "cycle1_v5": ROOT / "user_data/reports/profit_max_portfolio_ensemble_cycle1/v5_train.zip",
        "cycle1_v1": ROOT / "user_data/reports/profit_max_portfolio_ensemble_cycle1/v1_train.zip",
    }
    if any(not path.is_file() or path.is_symlink() for path in files.values()):
        print("FREEZE_BLOCKED: missing or unsafe input", file=sys.stderr)
        return 2
    try:
        liquid_base = json.loads(files["liquid_base_config"].read_text(encoding="utf-8"))
        core_base = json.loads(files["core_base_config"].read_text(encoding="utf-8"))
        audit = json.loads(files["liquid_data_audit"].read_text(encoding="utf-8"))
        overlays = {name: json.loads(files[f"{name}_overlay"].read_text(encoding="utf-8")) for name in ("cross", "liquid", "v5")}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FREEZE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    expected = {
        "cross": ("ProfitMaxCrossSectionalTopTwo8h", 2, 12.5),
        "liquid": ("ProfitMaxLiquid50V1", 5, 25),
        "v5": ("ProfitMaxV5Asymmetric50", 2, 100),
    }
    overlay_ok = all(overlays[name].get("strategy") == row[0] and overlays[name].get("max_open_trades") == row[1] and overlays[name].get("stake_amount") == row[2] and overlays[name].get("fee") == 0.00075 and overlays[name].get("initial_state") == "stopped" for name, row in expected.items())
    bases_ok = all(base.get("dry_run") is True and base.get("dry_run_wallet") == 1000 and base.get("trading_mode") == "futures" and base.get("margin_mode") == "isolated" and base.get("timeframe") == "4h" and not str((base.get("exchange") or {}).get("key") or "").strip() and not str((base.get("exchange") or {}).get("secret") or "").strip() for base in (liquid_base, core_base))
    if not (overlay_ok and bases_ok and len((liquid_base.get("exchange") or {}).get("pair_whitelist") or []) == 50 and len((core_base.get("exchange") or {}).get("pair_whitelist") or []) == 6 and audit.get("status") == "PASS" and audit.get("pnl_evaluated") is False):
        print("FREEZE_BLOCKED: contract mismatch", file=sys.stderr)
        return 2
    liquid_paths = sorted(LIQUID_DATA.glob("*.feather"))
    core_paths = [CORE_DATA / f"{pair}_USDT_USDT-{suffix}" for pair in CORE_PAIRS for suffix in CORE_SUFFIXES]
    if len(liquid_paths) != 200 or len(core_paths) != 24 or any(not p.is_file() or p.is_symlink() for p in liquid_paths + core_paths):
        print("FREEZE_BLOCKED: data inventory mismatch", file=sys.stderr)
        return 2
    planned = {name: (REPORT / f"{name}_train.zip").relative_to(ROOT).as_posix() for name in ("cross", "liquid", "v5")}
    planned["train_decision"] = (REPORT / "train_decision.json").relative_to(ROOT).as_posix()
    if any((ROOT / path).exists() for path in planned.values()):
        print("FREEZE_BLOCKED: planned output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_portfolio_ensemble_cycle2",
        "status": "RESEARCH_FROZEN_BEFORE_CYCLE2_PNL", "pnl_parsed": False,
        "validation_revealed": False, "live_trading_authorized": False, "profit_guaranteed": False,
        "runtime": "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643",
        "train_timerange": "20210101-20240101", "fee_per_side": 0.00075,
        "files": {name: {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)} for name, path in sorted(files.items())},
        "data_files": [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)} for path in liquid_paths + core_paths],
        "artifacts": planned,
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / "research_freeze_manifest.json"
    try:
        with target.open("xb") as stream:
            stream.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    except FileExistsError:
        print("FREEZE_BLOCKED: manifest exists", file=sys.stderr)
        return 3
    print(json.dumps({"status": payload["status"], "data_files": len(payload["data_files"]), "sha256": sha(target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
