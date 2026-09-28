#!/usr/bin/env python3
"""Freeze the marker-only evaluator correction before PnL parsing."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle2"
MANIFEST = REPORT / "research_freeze_manifest.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_v5_ensemble_cycle2_locked_plan.md",
        "cycle1_plan": ROOT / "docs/profit_max_daily_v5_ensemble_cycle1_locked_plan.md",
        "cycle1_manifest": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle1/research_freeze_manifest.json",
        "cycle1_evaluator": ROOT / "tools/evaluate_profit_max_daily_v5_ensemble_train.py",
        "evaluator": ROOT / "tools/evaluate_profit_max_daily_v5_ensemble_cycle2_train.py",
        "tests": ROOT / "tools/test_evaluate_profit_max_daily_v5_ensemble.py",
        "daily_archive": ROOT / "user_data/reports/profit_max_daily_cross_cycle2/post_failure_stop20_no_protections/backtest-result-2026-08-17_14-44-38.zip",
        "v5_archive": ROOT / "user_data/reports/profit_max_v5_repro_original_stake-2026-08-17_11-59-40.zip",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_cycle2",
        "status": "RESEARCH_FROZEN_BEFORE_PNL_PARSE", "correction": "ALLOW_EMPTY_OR_EXACT_REDACTED_MARKER_ONLY",
        "validation_revealed": False, "live_trading_authorized": False,
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "artifacts": {"train_decision": "user_data/reports/profit_max_daily_v5_ensemble_cycle2/train_decision.json"},
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
