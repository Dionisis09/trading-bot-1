#!/usr/bin/env python3
"""Freeze the three-sleeve retrospective ensemble before V2R PnL replay."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    weighted = json.loads((ROOT / "user_data/reports/profit_max_daily_v5_weighted_cycle1/decision.json").read_text(encoding="utf-8"))
    if weighted.get("decision") != "KEEP_OFFLINE_RESEARCH":
        print("FREEZE_BLOCKED: weighted-cycle lineage mismatch", file=sys.stderr)
        return 2
    daily = ROOT / weighted["artifacts"]["daily"]["path"]
    v5 = ROOT / weighted["artifacts"]["v5"]["path"]
    if digest(daily) != weighted["artifacts"]["daily"]["sha256"] or digest(v5) != weighted["artifacts"]["v5"]["sha256"]:
        print("FREEZE_BLOCKED: immutable component archive mismatch", file=sys.stderr)
        return 2
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_v5_v2r_ensemble_cycle1_locked_plan.md",
        "daily_archive": daily,
        "v5_archive": v5,
        "v2r_strategy": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "v2r_base_config": ROOT / "user_data/config-dual-futures-v2r-dry-run.json",
        "v2r_overlay": ROOT / "user_data/config-profit-max-v2r-fee075-overlay.json",
        "evaluator": ROOT / "tools/evaluate_profit_max_daily_v5_v2r_ensemble.py",
        "evaluator_tests": ROOT / "tools/test_evaluate_profit_max_daily_v5_v2r_ensemble.py",
        "weighted_decision": ROOT / "user_data/reports/profit_max_daily_v5_weighted_cycle1/decision.json",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    overlay = json.loads(inputs["v2r_overlay"].read_text(encoding="utf-8"))
    if overlay.get("strategy") != "DualTrendFuturesV2R" or overlay.get("stake_amount") != 25 or overlay.get("fee") != 0.00075:
        print("FREEZE_BLOCKED: V2R overlay mismatch", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_daily_v5_v2r_ensemble_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_V2R_REPLAY",
        "timerange": "20210101-20260801",
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
        "live_trading_authorized": False,
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "artifacts": {
            "v2r_results": "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1/v2r_results",
            "decision": "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1/decision.json",
        },
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    manifest = REPORT / "research_freeze_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
