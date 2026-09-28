#!/usr/bin/env python3
"""Freeze weighted portfolio allocation before continuous replay."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_weighted_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_v5_weighted_cycle1_locked_plan.md",
        "daily_strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalAuditV2.py",
        "v5_strategy": ROOT / "user_data/strategies/ProfitMaxSwingV5.py",
        "base_daily_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "daily_overlay": ROOT / "user_data/config-profit-max-daily-cross-stake20-overlay.json",
        "base_v5_config": ROOT / "user_data/config-profit-max-v2r-dry-run.json",
        "v5_overlay": ROOT / "user_data/config-profit-max-portfolio-v5-train-overlay.json",
        "evaluator": ROOT / "tools/evaluate_profit_max_daily_v5_weighted_continuous.py",
        "evaluator_tests": ROOT / "tools/test_evaluate_profit_max_daily_v5_weighted_continuous.py",
        "failed_validation": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_validation_cycle1/validation_decision.json",
        "technical_decision": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle4/technical_decision_v2.json",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    failed_validation = json.loads(inputs["failed_validation"].read_text(encoding="utf-8"))
    technical_decision = json.loads(inputs["technical_decision"].read_text(encoding="utf-8"))
    daily_overlay = json.loads(inputs["daily_overlay"].read_text(encoding="utf-8"))
    v5_overlay = json.loads(inputs["v5_overlay"].read_text(encoding="utf-8"))
    if failed_validation.get("decision") != "KEEP_OFFLINE_RESEARCH":
        print("FREEZE_BLOCKED: failed-validation lineage missing", file=sys.stderr)
        return 2
    if technical_decision.get("status") != "PASS" or technical_decision.get("decision") != "UNLOCK_VALIDATION_ONCE":
        print("FREEZE_BLOCKED: technical-gate lineage missing", file=sys.stderr)
        return 2
    if daily_overlay.get("strategy") != "ProfitMaxDailyCrossStop20AuditV2" or daily_overlay.get("stake_amount") != 20:
        print("FREEZE_BLOCKED: daily allocation mismatch", file=sys.stderr)
        return 2
    if v5_overlay.get("strategy") != "ProfitMaxV5Asymmetric50" or v5_overlay.get("stake_amount") != 50:
        print("FREEZE_BLOCKED: V5 allocation mismatch", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_v5_weighted_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_CONTINUOUS_REPLAY", "timerange": "20210101-20260801",
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT", "live_trading_authorized": False,
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "artifacts": {"daily_results": "user_data/reports/profit_max_daily_v5_weighted_cycle1/daily_results", "v5_results": "user_data/reports/profit_max_daily_v5_weighted_cycle1/v5_results", "decision": "user_data/reports/profit_max_daily_v5_weighted_cycle1/decision.json"},
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
