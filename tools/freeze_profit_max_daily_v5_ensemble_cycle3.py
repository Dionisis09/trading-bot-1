#!/usr/bin/env python3
"""Freeze the auditability-only daily variant before equivalence replay."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle3"
MANIFEST = REPORT / "research_freeze_manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_v5_ensemble_cycle3_technical_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalAudit.py",
        "parent_strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalV2.py",
        "signal_parent": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectional.py",
        "config": ROOT / "user_data/config-profit-max-daily-cross-audit-overlay.json",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "parent_archive": ROOT / "user_data/reports/profit_max_daily_cross_cycle2/post_failure_stop20_no_protections/backtest-result-2026-08-17_14-44-38.zip",
        "ensemble_train": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle2/train_decision.json",
        "parity_tool": ROOT / "tools/compare_profit_max_daily_audit_parity.py",
        "tests": ROOT / "tools/test_profit_max_daily_cross_audit.py",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    decision = json.loads(inputs["ensemble_train"].read_text(encoding="utf-8"))
    if decision.get("decision") != "UNLOCK_TECHNICAL_GATES" or decision.get("validation_revealed") is not False:
        print("FREEZE_BLOCKED: ensemble TRAIN gate unavailable", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_cycle3",
        "status": "RESEARCH_FROZEN_BEFORE_EQUIVALENCE_PNL", "validation_revealed": False,
        "live_trading_authorized": False,
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "artifacts": {"audit_results": "user_data/reports/profit_max_daily_v5_ensemble_cycle3/audit_results", "parity": "user_data/reports/profit_max_daily_v5_ensemble_cycle3/parity.json"},
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
