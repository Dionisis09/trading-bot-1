#!/usr/bin/env python3
"""Freeze Cycle 2 stop/protection candidates before PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_cross_cycle2"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA_DIR = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_cross_cycle2_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalV2.py",
        "signal_parent": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectional.py",
        "rank_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "risk": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "overlay_config": ROOT / "user_data/config-profit-max-daily-cross-cycle2-overlay.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "data_quality": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "universe": ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json",
        "cycle1_manifest": ROOT / "user_data/reports/profit_max_daily_cross_cycle1/research_freeze_manifest.json",
        "cycle1_decision": ROOT / "user_data/reports/profit_max_daily_cross_cycle1/train_decision.json",
        "cycle1_post_failure": ROOT / "user_data/reports/profit_max_daily_cross_cycle1/post_failure_no_protections/backtest-result-2026-08-17_14-39-55.zip",
        "tests": ROOT / "tools/test_profit_max_daily_cross_sectional_v2.py",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    data_files = sorted(DATA_DIR.glob("*-4h-futures.feather"))
    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    overlay = json.loads(inputs["overlay_config"].read_text(encoding="utf-8"))
    decision = json.loads(inputs["cycle1_decision"].read_text(encoding="utf-8"))
    meta = overlay.get("profit_max_research") or {}
    expected = ["ProfitMaxDailyCrossStop12", "ProfitMaxDailyCrossStop16", "ProfitMaxDailyCrossStop20"]
    if not (
        len(data_files) == 50
        and decision.get("decision") == "KEEP_OFFLINE_RESEARCH"
        and decision.get("validation_revealed") is False
        and base.get("fee") == 0.00075
        and base.get("dry_run") is True
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and overlay.get("max_open_trades") == 2
        and overlay.get("stake_amount") == 50
        and meta.get("candidates") == expected
        and meta.get("candidate_stops") == [-0.12, -0.16, -0.20]
        and meta.get("protection") == {"method": "CooldownPeriod", "stop_duration_candles": 1}
        and meta.get("leverage") == 1
        and meta.get("live_trading_authorized") is False
    ):
        print("FREEZE_BLOCKED: execution/lineage contract failed", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_daily_cross_cycle2",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "candidates": expected,
        "selection": ["highest_return_to_drawdown", "higher_profit_factor", "tighter_stop"],
        "pnl_parsed": False,
        "validation_revealed": False,
        "live_trading_authorized": False,
        "fee_per_side": 0.00075,
        "files": {
            label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
            for label, path in sorted(inputs.items())
        },
        "data_files": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for path in data_files
        ],
        "artifacts": {
            "train_results": "user_data/reports/profit_max_daily_cross_cycle2/train_results",
            "train_decision": "user_data/reports/profit_max_daily_cross_cycle2/train_decision.json",
        },
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
