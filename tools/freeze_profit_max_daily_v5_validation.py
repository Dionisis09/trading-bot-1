#!/usr/bin/env python3
"""Freeze validation evaluator and fixed inputs before the daily validation run."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_ensemble_validation_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_v5_ensemble_cycle1_locked_plan.md",
        "technical_decision": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle4/technical_decision_v2.json",
        "strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalAuditV2.py",
        "config": ROOT / "user_data/config-profit-max-daily-cross-audit-v2-overlay.json",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "evaluator": ROOT / "tools/evaluate_profit_max_daily_v5_ensemble_validation.py",
        "v5_validation": ROOT / "user_data/reports/profit_max_portfolio_ensemble_cycle3/v5_validation.zip",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    technical = json.loads(inputs["technical_decision"].read_text(encoding="utf-8"))
    if technical.get("decision") != "UNLOCK_VALIDATION_ONCE" or technical.get("validation_revealed") is not False:
        print("FREEZE_BLOCKED: validation is not unlocked", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_validation_cycle1",
        "status": "VALIDATION_FROZEN_BEFORE_DAILY_PNL", "timerange": "20240101-20260101",
        "validation_revealed": False, "live_trading_authorized": False,
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "artifacts": {"daily_results": "user_data/reports/profit_max_daily_v5_ensemble_validation_cycle1/daily_results", "decision": "user_data/reports/profit_max_daily_v5_ensemble_validation_cycle1/validation_decision.json"},
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
