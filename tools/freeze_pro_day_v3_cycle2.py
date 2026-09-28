#!/usr/bin/env python3
"""Freeze the transport-only ProDayTraderV3 Cycle 2 retry before any PnL."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import freeze_pro_day_v3_cycle1 as base


ROOT = Path(__file__).resolve().parents[1]
PLAN = Path("docs/pro_day_trader_v3_cycle2_locked_plan.md")
CONFIG = Path("user_data/config-pro-day-v3-cycle2-research.json")
OLD_CONFIG = Path("user_data/config-pro-day-v3-cycle1-research.json")
OLD_PLAN = Path("docs/pro_day_trader_v3_cycle1_locked_plan.md")
OLD_MANIFEST = Path("user_data/reports/pro_day_v3_cycle1/research_freeze_manifest.json")
OLD_RECURSIVE = Path("user_data/reports/pro_day_v3_cycle1/recursive_analysis.json")
DIAGNOSTIC = Path("user_data/reports/pro_day_v3_cycle1/runtime_diagnostic.json")
OUTPUT = Path("user_data/reports/pro_day_v3_cycle2/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v3_cycle2/trial_ledger.json")
EXPECTED = {
    "strategy": "73c78608f8cf048874282621c87f1e05948c90ea66b710800d162c7741402804",
    "config": "be4fbf4f35aca78586a5e6a80c28b1f46b912c18712f111c01ed45bbde280e21",
    "old_plan": "bf7a41190fc20e2d16f6fd8d0aa1cc571ee02c77e24f9805fac5b0e8a824712c",
    "old_manifest": "83b2e4f79d5e3ade690621faf374574f1d3d480f8c138e3c76aa642193a69ba9",
    "old_recursive": "cbf9247bac16919d1886a17ac508294976d00f3d3cef10e26e3c7a49f97d5774",
    "old_runner": "29748ce84ae70bcc09e3117d1d5a21892332d6a845dc881d21f5aad203a4e74d",
}


def validate_retry_config(current: dict[str, Any], previous: dict[str, Any]) -> None:
    normalized = copy.deepcopy(current)
    normalized["bot_name"] = previous["bot_name"]
    normalized["pro_day_v3_research"] = copy.deepcopy(previous["pro_day_v3_research"])
    base.equal(normalized, previous, "normalized Cycle 2 config")
    meta = current.get("pro_day_v3_research", {})
    base.equal(meta.get("cycle"), "pro_day_v3_cycle2", "Cycle 2 id")
    base.equal(meta.get("status"), "LOCKED_BEFORE_FIRST_V3_CYCLE2_PNL_RUN", "Cycle 2 status")
    base.equal(meta.get("technical_public_market_metadata"), True, "public metadata transport")
    base.equal(meta.get("live_trading_authorized"), False, "live authorization")
    base.equal(meta.get("ml_order_gate"), False, "ML order gate")


def freeze(root: Path = ROOT, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "plan": root / PLAN,
        "strategy": root / base.STRATEGY,
        "base_strategy": root / base.BASE_STRATEGY,
        "config": root / CONFIG,
        "previous_config": root / OLD_CONFIG,
        "risk_policy": root / base.RISK,
        "data_audit": root / base.AUDIT,
        "cycle1_plan": root / OLD_PLAN,
        "cycle1_manifest": root / OLD_MANIFEST,
        "cycle1_recursive": root / OLD_RECURSIVE,
        "cycle1_runtime_diagnostic": root / DIAGNOSTIC,
        "cycle1_runner": root / "tools/run_pro_day_v3_recursive_gate.py",
        "strategy_tests": root / "tools/test_pro_day_trader_v3.py",
        "freezer": Path(__file__).resolve(),
    }
    for label, path in paths.items():
        if not path.is_file():
            raise base.FreezeError(f"missing {label}: {path}")
    for label, expected in (
        ("strategy", EXPECTED["strategy"]), ("config", EXPECTED["config"]),
        ("cycle1_plan", EXPECTED["old_plan"]), ("cycle1_manifest", EXPECTED["old_manifest"]),
        ("cycle1_recursive", EXPECTED["old_recursive"]), ("cycle1_runner", EXPECTED["old_runner"]),
    ):
        if base.sha256_file(paths[label]) != expected:
            raise base.FreezeError(f"{label} SHA256 mismatch")
    plan = paths["plan"].read_text(encoding="utf-8")
    for marker in (*EXPECTED.values(), "LOCKED_BEFORE_FIRST_V3_CYCLE2_PNL_RUN", "[199, 399, 799, 1599, 2399]"):
        if marker not in plan:
            raise base.FreezeError(f"Cycle 2 plan marker missing: {marker}")
    current = base.load(paths["config"], "Cycle 2 config")
    previous = base.load(paths["previous_config"], "Cycle 1 config")
    validate_retry_config(current, previous)
    data_files = base.validate_data(base.load(paths["data_audit"], "data audit"), root)
    recursive = base.load(paths["cycle1_recursive"], "Cycle 1 recursive report")
    base.equal(recursive.get("status"), "FAIL", "Cycle 1 recursive status")
    base.equal(recursive.get("container_exit_code"), 1, "Cycle 1 container exit")
    for field in ("model_training_performed", "backtest_performed", "pnl_parsed", "live_trading_authorized"):
        base.equal(recursive.get(field), False, f"Cycle 1 {field}")
    diagnostic = base.load(paths["cycle1_runtime_diagnostic"], "runtime diagnostic")
    base.equal(diagnostic.get("cause"), "PUBLIC_MARKET_METADATA_BLOCKED_BY_NETWORK_NONE", "diagnostic cause")
    base.equal(diagnostic.get("result_reused_for_qualification"), False, "diagnostic qualification reuse")

    artifacts = {}
    for label, name in {
        "train": "train", "validation": "validation",
        "current_partial": "current-partial", "canonical": "canonical",
    }.items():
        relative = Path(f"user_data/backtest_results/prodayv3-cycle2-{name}.zip")
        if (root / relative).exists():
            raise base.FreezeError(f"planned artifact exists: {relative}")
        artifacts[label] = {"path": str(relative).replace("\\", "/"), "filename": relative.name,
                            "sha256": None, "status": "PLANNED_NOT_RUN"}
    if (root / "user_data/reports/pro_day_v3_cycle2/recursive_analysis.json").exists():
        raise base.FreezeError("Cycle 2 recursive output exists before freeze")
    files = {label: base.descriptor(path, root) for label, path in paths.items()}
    locked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0", "status": "RESEARCH_FROZEN",
        "candidate": "ProDayTraderV3", "cycle": "pro_day_v3_cycle2",
        "locked_at_utc": locked, "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False, "model_training_performed": False,
        "files": files, "data_files": data_files,
        "frozen_parameters": {
            "runtime_image": base.IMAGE, "runtime_digest": base.DIGEST,
            "timeframe": "5m", "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
            "recursive_startup_counts": [199, 399, 799, 1599, 2399],
            "recursive_qualification_count": 399,
            "public_market_metadata_transport": True,
            "private_api_transport": False, "ml_order_gate": False, "leverage": 1,
            "train_timerange": "20220101-20240101",
            "validation_timerange": "20240101-20260101",
            "current_partial_timerange": "20260101-20260801",
        },
        "artifacts": artifacts,
        "technical_evidence": {"recursive_analysis": "PENDING", "lookahead_analysis": "LOCKED_PENDING_RECURSIVE_PASS"},
        "active_strategies_changed": False, "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
    }
    ledger = {
        "schema_version": "1.0", "cycle": "pro_day_v3_cycle2", "candidate": "ProDayTraderV3",
        "created_at_utc": locked, "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"], "config_sha256": files["config"]["sha256"],
        "qualification_runs": [], "parameter_trials": [], "pnl_parsed": False,
        "post_result_edits_allowed": False, "live_trading_authorized": False,
    }
    if write_output:
        if (root / OUTPUT).exists() or (root / LEDGER).exists():
            raise base.FreezeError("Cycle 2 manifest or ledger already exists")
        base.write_exclusive(root / LEDGER, ledger)
        try:
            base.write_exclusive(root / OUTPUT, manifest)
        except Exception:
            (root / LEDGER).unlink(missing_ok=True)
            raise
    return manifest, ledger


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result, _ = freeze(write_output=not args.check_only)
    except (base.FreezeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": result["status"], "cycle": result["cycle"], "pnl_parsed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
