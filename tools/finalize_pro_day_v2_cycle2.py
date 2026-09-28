#!/usr/bin/env python3
"""Finalize the terminal pre-PnL Cycle 2 technical decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from run_pro_day_v2_cycle2_recursive_gate import GateError, atomic_write, load_json


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("user_data/reports/pro_day_v2_cycle2/research_freeze_manifest.json")
CODE_FREEZE = Path("user_data/reports/pro_day_v2_cycle2/recursive_gate_code_freeze.json")
RECURSIVE = Path("user_data/reports/pro_day_v2_cycle2/recursive_analysis.json")
OUTPUT = Path("user_data/reports/pro_day_v2_cycle2/final_decision.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(workspace: Path) -> dict[str, Any]:
    manifest_path = workspace / MANIFEST
    code_path = workspace / CODE_FREEZE
    recursive_path = workspace / RECURSIVE
    manifest = load_json(manifest_path, "Cycle 2 manifest")
    code = load_json(code_path, "recursive code freeze")
    recursive = load_json(recursive_path, "recursive report")
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v2_cycle2":
        raise GateError("Cycle 2 manifest is not frozen")
    if code.get("manifest_sha256") != sha256(manifest_path):
        raise GateError("Recursive code freeze is not linked to the manifest")
    if recursive.get("manifest_sha256") != sha256(manifest_path):
        raise GateError("Recursive report is not linked to the manifest")
    if recursive.get("code_freeze_sha256") != sha256(code_path):
        raise GateError("Recursive report is not linked to the code freeze")
    if recursive.get("status") != "FAIL" or recursive.get("decision") != "REJECT_PRO_DAY_TRADER_V2":
        raise GateError("Cycle 2 recursive state is not a terminal rejection")
    if recursive.get("pnl_parsed") is not False or recursive.get("backtest_performed") is not False:
        raise GateError("Cycle 2 crossed the no-PnL boundary")
    failures = recursive.get("failures")
    if not isinstance(failures, list) or not failures:
        raise GateError("Cycle 2 recursive failures are missing")
    return {
        "schema_version": "1.0",
        "cycle": "pro_day_v2_cycle2",
        "candidate": "ProDayTraderV2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision": "REJECT_PRO_DAY_TRADER_V2",
        "decision_stage": "PRE_PNL_RECURSIVE_GATE",
        "gates": {
            "canonical_data": "PASS",
            "runtime_compatibility": "PASS",
            "unit_config_discovery": "PASS_33_TESTS",
            "recursive_analysis": "FAIL",
            "lookahead_analysis": "NOT_RUN_AFTER_RECURSIVE_FAIL",
            "train_oos": "NOT_RUN_AFTER_TECHNICAL_FAIL",
            "validation_oos": "LOCKED_NOT_REVEALED",
            "current_partial_oos": "LOCKED_NOT_REVEALED",
        },
        "recursive_failures": failures,
        "recursive_gate_details": recursive.get("gate_details"),
        "evidence": {
            "manifest_sha256": sha256(manifest_path),
            "code_freeze_sha256": sha256(code_path),
            "recursive_report_sha256": sha256(recursive_path),
        },
        "performance": {
            "status": "NOT_RUN_BY_LOCKED_TECHNICAL_GATE",
            "qualification_backtests": 0,
            "pnl_parsed": False,
            "profitability_claim": False,
        },
        "technical_model_activity": {
            "performed": True,
            "qualification_model": False,
            "purpose": "recursive indicator and FreqAI compatibility only",
        },
        "next_safe_action": (
            "Open a separately locked deterministic 5m cycle with FreqAI shadow-only; "
            "do not relax Cycle 2 after observing its technical result."
        ),
        "active_v1_v2r_changed": False,
        "deployment_performed": False,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        output = args.workspace.resolve() / OUTPUT
        if output.exists():
            existing = load_json(output, "Cycle 2 final decision")
            expected = build(args.workspace.resolve())
            stable = {k: v for k, v in existing.items() if k != "generated_at_utc"}
            expected_stable = {k: v for k, v in expected.items() if k != "generated_at_utc"}
            if stable != expected_stable:
                raise GateError("Existing final decision differs from current evidence")
            report = existing
        else:
            report = build(args.workspace.resolve())
            atomic_write(output, report, exclusive=True)
    except (GateError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FINALIZATION_REFUSED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"decision": report["decision"], "pnl_parsed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
