#!/usr/bin/env python3
"""Freeze the bounded stop-loss cycle before PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_cross_stop_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_cross_stop_cycle1_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxCrossSectionalStop.py",
        "signal_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectionalShortHorizon.py",
        "rank_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectionalLong.py",
        "base_strategy": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "risk": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "overlay_config": ROOT / "user_data/config-profit-max-cross-stop-cycle1-overlay.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "data_quality": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "data_manifest": ROOT / "user_data/reports/profit_max_cross_sectional_short_horizon_cycle1/research_freeze_manifest.json",
        "reproduced_baseline": ROOT / "user_data/reports/profit_max_cross_repro_original_stake-2026-08-17_11-57-21.zip",
        "v5_train": ROOT / "user_data/reports/profit_max_v5_repro_original_stake-2026-08-17_11-59-40.zip",
        "v1_train": ROOT / "user_data/reports/profit_max_v1_repro_original_stake-2026-08-17_12-00-05.zip",
        "tests": ROOT / "tools/test_profit_max_cross_stop.py",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    overlay = json.loads(inputs["overlay_config"].read_text(encoding="utf-8"))
    quality = json.loads(inputs["data_quality"].read_text(encoding="utf-8"))
    meta = overlay.get("profit_max_research") or {}
    if not (
        quality.get("status") == "PASS"
        and base.get("dry_run") is True
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and base.get("fee") == 0.00075
        and overlay.get("max_open_trades") == 2
        and overlay.get("stake_amount") == 50
        and meta.get("candidate_stops") == [-0.02, -0.04, -0.06]
        and meta.get("leverage") == 1
        and meta.get("live_trading_authorized") is False
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
    ):
        print("FREEZE_BLOCKED: execution/data contract failed", file=sys.stderr)
        return 2
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_cross_stop_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "pnl_parsed": False,
        "validation_revealed": False,
        "live_trading_authorized": False,
        "fee_per_side": 0.00075,
        "candidates": ["ProfitMaxCrossTopTwo8hStop2", "ProfitMaxCrossTopTwo8hStop4", "ProfitMaxCrossTopTwo8hStop6"],
        "selection": ["highest_return_to_drawdown", "higher_profit_factor", "tighter_stop"],
        "splits": {"train": "20210101-20240101", "validation": "20240101-20260101", "current_partial": "20260101-20260801"},
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "artifacts": {"train_results": "user_data/reports/profit_max_cross_stop_cycle1/train_results", "train_archive": "user_data/reports/profit_max_cross_stop_cycle1/train.zip", "train_decision": "user_data/reports/profit_max_cross_stop_cycle1/train_decision.json"},
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    with MANIFEST.open("xb") as handle:
        handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
