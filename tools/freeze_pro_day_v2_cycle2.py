#!/usr/bin/env python3
"""Fail-closed immutable freeze for ProDayTraderV2 Cycle 2."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import freeze_pro_day_v2_research as base


ROOT = Path(__file__).resolve().parents[1]
CYCLE = "pro_day_v2_cycle2"
IDENTIFIER = "proday-v2-cycle2-canonical5m-lgbm-20260811"
BASE_PLAN_SHA = "707793fc95cc99f9663e354ed5ddae90cfb753a48e773d46ac1759d11bc11e6d"
STRATEGY_SHA = "6041f416e4c951b83b5f9cef5438319fd4f24d1d296eb37fd499415a00e47f45"
CYCLE1_DECISION_SHA = "fdac3459fb940617371fb772ec5819e8254dc0a53d3ca0c78134f793c2b87dc9"
DATA_AUDIT_SHA = "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772"
RUNTIME_SHA = "155dbfe16892d5d4616ee1186d29678ea2baaab51cb84ea1673caaa7ed22ca1b"
COUNTS = [199, 399, 799, 1599, 2399]

PLAN = Path("docs/pro_day_trader_v2_cycle2_locked_plan.md")
BASE_PLAN = Path("docs/pro_day_trader_v2_locked_plan.md")
STRATEGY = Path("user_data/strategies/ProDayTraderV2.py")
CONFIG = Path("user_data/config-pro-day-v2-cycle2-research.json")
BASE_CONFIG = Path("user_data/config-pro-day-v2-research.json")
RISK = Path("user_data/risk_policy.json")
DATA_AUDIT = Path("user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json")
DATA_CHECKSUM = Path("user_data/reports/pro_day_v2_cycle1/canonical_data_audit.sha256")
RUNTIME = Path("user_data/reports/pro_day_v2_cycle1/runtime_compatibility.json")
CYCLE1_DECISION = Path("user_data/reports/pro_day_v2_cycle1/final_decision.json")
TECHNICAL = Path("user_data/reports/pro_day_v2_cycle2/pre_pnl_technical_evidence.json")
OUTPUT = Path("user_data/reports/pro_day_v2_cycle2/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v2_cycle2/trial_ledger.json")

ARTIFACTS = {
    "train": Path("user_data/backtest_results/prodayv2-cycle2-train.zip"),
    "validation": Path("user_data/backtest_results/prodayv2-cycle2-validation.zip"),
    "current_partial": Path("user_data/backtest_results/prodayv2-cycle2-current-partial.zip"),
    "canonical": Path("user_data/backtest_results/prodayv2-cycle2-canonical.zip"),
}


def _equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise base.FreezeError(f"{label} differs from the Cycle 2 locked value")


def _require_sha(path: Path, expected: str, label: str) -> None:
    if base.sha256_file(path) != expected:
        raise base.FreezeError(f"{label} SHA256 mismatch")


def validate_plan(paths: Mapping[str, Path]) -> None:
    _require_sha(paths["base_plan"], BASE_PLAN_SHA, "base plan")
    _require_sha(paths["strategy"], STRATEGY_SHA, "strategy")
    _require_sha(paths["cycle1_decision"], CYCLE1_DECISION_SHA, "Cycle 1 decision")
    _require_sha(paths["data_audit"], DATA_AUDIT_SHA, "data audit")
    _require_sha(paths["runtime_compatibility"], RUNTIME_SHA, "runtime report")
    text = paths["plan"].read_text(encoding="utf-8")
    required = (
        "LOCKED_BEFORE_FIRST_V2_CYCLE2_PNL_RUN",
        BASE_PLAN_SHA,
        STRATEGY_SHA,
        CYCLE1_DECISION_SHA,
        "[199, 399, 799, 1599, 2399]",
        "`freqai.purge_old_models` is set to `0`",
        "`/canonical/futures`",
        "`&-candidate_net_log_return`",
        "`20240101-20260101`",
        "`minimum_trade_amount=100`",
        "`targeted_trade_amount=120`",
        "APPROVE_SEPARATE_DRY_RUN",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise base.FreezeError("Cycle 2 plan markers missing: " + ", ".join(missing))


def validate_config(config: Mapping[str, Any], base_config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(config))
    normalized["bot_name"] = base_config.get("bot_name")
    freqai = normalized.get("freqai")
    if not isinstance(freqai, dict):
        raise base.FreezeError("Cycle 2 freqai config is missing")
    base_freqai = base_config.get("freqai")
    if not isinstance(base_freqai, Mapping):
        raise base.FreezeError("Base freqai config is missing")
    freqai["identifier"] = base_freqai.get("identifier")
    freqai["purge_old_models"] = base_freqai.get("purge_old_models")
    normalized["pro_day_v2_research"] = copy.deepcopy(
        base_config.get("pro_day_v2_research")
    )
    _equal(normalized, dict(base_config), "normalized Cycle 2 config")
    inherited = base.validate_config(normalized)

    _equal(config.get("bot_name"), "pro-day-trader-v2-cycle2-research", "bot_name")
    actual_freqai = config.get("freqai")
    if not isinstance(actual_freqai, Mapping):
        raise base.FreezeError("Cycle 2 freqai config is missing")
    _equal(actual_freqai.get("identifier"), IDENTIFIER, "freqai.identifier")
    _equal(actual_freqai.get("purge_old_models"), 0, "freqai.purge_old_models")
    metadata = config.get("pro_day_v2_research")
    expected_metadata = {
        "cycle": CYCLE,
        "status": "LOCKED_BEFORE_FIRST_V2_CYCLE2_PNL_RUN",
        "plan": str(PLAN).replace("\\", "/"),
        "base_plan": str(BASE_PLAN).replace("\\", "/"),
        "canonical_timerange": "20210101-20260801",
        "initial_model_history": "20210101-20220101",
        "train_oos": "20220101-20240101",
        "validation_oos": "20240101-20260101",
        "current_partial_oos": "20260101-20260801",
        "qualification_only": True,
        "leverage": 1,
        "live_trading_authorized": False,
        "automatic_feature_expansion": False,
        "target_horizon_base_candles": 12,
        "target_cost_hurdle": 0.0026,
        "recursive_startup_counts": COUNTS,
        "canonical_container_datadir": "/canonical",
        "canonical_futures_mount": "/canonical/futures",
        "retain_all_fold_models_for_audit": True,
    }
    _equal(metadata, expected_metadata, "Cycle 2 metadata")
    return {
        **inherited,
        "identifier": IDENTIFIER,
        "purge_old_models": 0,
        "recursive_startup_counts": COUNTS,
        "recursive_qualification_count": 399,
        "canonical_container_datadir": "/canonical",
        "canonical_futures_mount": "/canonical/futures",
        "lookahead_timerange": "20240101-20260101",
        "lookahead_minimum_trade_amount": 100,
        "lookahead_targeted_trade_amount": 120,
        "lookahead_allowed_target_only": "&-candidate_net_log_return",
    }


def validate_cycle1_decision(report: Mapping[str, Any]) -> None:
    _equal(report.get("decision"), "REJECT_PRO_DAY_TRADER_V2", "Cycle 1 decision")
    _equal(report.get("decision_stage"), "PRE_PNL_TECHNICAL_GATE", "Cycle 1 stage")
    performance = report.get("performance")
    if not isinstance(performance, Mapping):
        raise base.FreezeError("Cycle 1 performance boundary is missing")
    _equal(performance.get("pnl_parsed"), False, "Cycle 1 pnl_parsed")
    _equal(performance.get("qualification_backtests"), 0, "Cycle 1 backtests")


def validate_technical(report: Mapping[str, Any]) -> None:
    _equal(report.get("schema_version"), "1.0", "technical schema")
    _equal(report.get("status"), "PASS", "technical status")
    _equal(report.get("candidate"), "ProDayTraderV2", "technical candidate")
    _equal(report.get("cycle"), CYCLE, "technical cycle")
    _equal(report.get("total_tests"), 33, "technical test count")
    _equal(report.get("cycle1_terminal_decision"), "PASS_NO_PNL", "Cycle 1 boundary")
    for field in ("model_training_performed", "backtest_performed", "pnl_evaluated"):
        _equal(report.get(field), False, f"technical {field}")
    _equal(report.get("live_trading_authorized"), False, "technical live authorization")


def _empty_or_absent(path: Path, label: str) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise base.FreezeError(f"{label} must be absent or empty before freeze")


def _planned_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for label, relative in ARTIFACTS.items():
        path = base.resolve_input(root, relative)
        if path.exists():
            raise base.FreezeError(f"Cycle 2 artifact already exists: {relative}")
        records[label] = {
            "path": base.portable_path(path, root),
            "filename": path.name,
            "sha256": None,
            "status": "PLANNED_NOT_RUN",
        }
    return records


def freeze(
    *, project_root: Path = ROOT, write_output: bool = True,
    output_path: Path = OUTPUT, ledger_path: Path = LEDGER,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = project_root.resolve()
    paths = {
        "plan": base.resolve_input(root, PLAN),
        "base_plan": base.resolve_input(root, BASE_PLAN),
        "strategy": base.resolve_input(root, STRATEGY),
        "config": base.resolve_input(root, CONFIG),
        "base_config": base.resolve_input(root, BASE_CONFIG),
        "risk_policy": base.resolve_input(root, RISK),
        "data_audit": base.resolve_input(root, DATA_AUDIT),
        "data_audit_checksum": base.resolve_input(root, DATA_CHECKSUM),
        "runtime_compatibility": base.resolve_input(root, RUNTIME),
        "cycle1_decision": base.resolve_input(root, CYCLE1_DECISION),
        "pre_pnl_technical_evidence": base.resolve_input(root, TECHNICAL),
        "data_generator": base.resolve_input(root, base.DEFAULT_GENERATOR),
        "runtime_checker": base.resolve_input(root, base.DEFAULT_RUNTIME_CHECKER),
        "cycle2_config_tests": base.resolve_input(root, Path("tools/test_pro_day_v2_cycle2_config.py")),
        "cycle2_freeze_tests": base.resolve_input(root, Path("tools/test_freeze_pro_day_v2_cycle2.py")),
        "cycle2_pre_pnl_checker": base.resolve_input(root, Path("tools/check_pro_day_v2_cycle2_pre_pnl.py")),
        "cycle2_freezer": Path(__file__).resolve(),
    }
    for label, path in paths.items():
        if not path.is_file():
            raise base.FreezeError(f"Missing {label}: {path}")
    validate_plan(paths)
    strategy_info = base.validate_strategy(paths["strategy"])
    config = base.load_json_object(paths["config"], "Cycle 2 config")
    base_config = base.load_json_object(paths["base_config"], "base V2 config")
    frozen_parameters = validate_config(config, base_config)
    risk = base.load_json_object(paths["risk_policy"], "risk policy")
    base.validate_risk_policy(risk)
    audit = base.load_json_object(paths["data_audit"], "canonical data audit")
    data_records = base.validate_data_audit(audit, root)
    checksum = paths["data_audit_checksum"].read_text(encoding="utf-8").split()
    if not checksum or checksum[0].lower() != base.sha256_file(paths["data_audit"]):
        raise base.FreezeError("Canonical data checksum sidecar mismatch")
    runtime = base.load_json_object(paths["runtime_compatibility"], "runtime report")
    base.validate_runtime(runtime)
    cycle1 = base.load_json_object(paths["cycle1_decision"], "Cycle 1 decision")
    validate_cycle1_decision(cycle1)
    technical = base.load_json_object(paths["pre_pnl_technical_evidence"], "Cycle 2 technical evidence")
    validate_technical(technical)

    _empty_or_absent(root / "user_data/models" / IDENTIFIER, "qualification model cache")
    _empty_or_absent(root / "user_data/reports/pro_day_v2_cycle2/technical_recursive_models", "recursive model cache")
    _empty_or_absent(root / "user_data/reports/pro_day_v2_cycle2/technical_lookahead_models", "lookahead model cache")

    files = {name: base.descriptor(path, root) for name, path in paths.items()}
    artifacts = _planned_artifacts(root)
    locked_at = base.locked_at_utc()
    manifest = {
        "schema_version": "1.0",
        "status": "RESEARCH_FROZEN",
        "candidate": "ProDayTraderV2",
        "cycle": CYCLE,
        "locked_at_utc": locked_at,
        "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False,
        "model_training_performed": False,
        "files": files,
        "inputs": {
            "plan": files["plan"],
            "base_plan": files["base_plan"],
            "strategy": files["strategy"],
            "research_config": files["config"],
            "risk_policy": files["risk_policy"],
            "data_audit": files["data_audit"],
            "runtime_compatibility": files["runtime_compatibility"],
            "cycle1_terminal_decision": files["cycle1_decision"],
        },
        "data_files": data_records,
        "frozen_parameters": {
            **frozen_parameters,
            **strategy_info,
            "runtime_image": base.IMAGE,
            "runtime_digest": base.DIGEST,
            "initial_history": "20210101-20220101",
            "train_timerange": "20220101-20240101",
            "validation_timerange": "20240101-20260101",
            "current_partial_timerange": "20260101-20260801",
            "canonical_timerange": "20220101-20260801",
            "earliest_fill": "next_5m_open",
            "closed_candles_only": True,
            "features": list(base.FEATURES),
            "technical_recursive_model_root": "user_data/reports/pro_day_v2_cycle2/technical_recursive_models",
            "technical_lookahead_model_root": "user_data/reports/pro_day_v2_cycle2/technical_lookahead_models",
        },
        "artifacts": artifacts,
        "technical_evidence": {
            "data_gate": "PASS",
            "runtime_gate": "PASS",
            "unit_tests": "PASS_33",
            "config_validation": "PASS_OUTPUT_SUPPRESSED",
            "strategy_discovery": "PASS_UNIQUE_STATUS_OK",
            "recursive_analysis": "PENDING",
            "lookahead_analysis": "LOCKED_PENDING_RECURSIVE_PASS",
        },
        "active_strategies_changed": False,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
        "evidence_boundary": (
            "Immutable Cycle 2 pre-PnL freeze. No qualification model, backtest, "
            "trade, PnL, deployment, dry-run, or live authorization was created."
        ),
    }
    ledger = {
        "schema_version": "1.0",
        "cycle": CYCLE,
        "candidate": "ProDayTraderV2",
        "created_at_utc": locked_at,
        "plan_sha256": files["plan"]["sha256"],
        "base_plan_sha256": files["base_plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"],
        "config_sha256": files["config"]["sha256"],
        "pnl_parsed": False,
        "qualification_runs": [],
        "parameter_trials": [],
        "post_result_edits_allowed": False,
        "live_trading_authorized": False,
    }
    if write_output:
        output = base.resolve_input(root, output_path)
        ledger_file = base.resolve_input(root, ledger_path)
        if output.exists() or ledger_file.exists():
            raise base.FreezeError("Cycle 2 manifest or ledger already exists")
        base._write_exclusive(ledger_file, ledger)
        try:
            base._write_exclusive(output, manifest)
        except Exception:
            ledger_file.unlink(missing_ok=True)
            raise
    return manifest, ledger


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest, _ = freeze(
            project_root=args.project_root,
            write_output=not args.check_only,
        )
    except (base.FreezeError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "cycle": manifest["cycle"],
                "qualification_state": manifest["qualification_state"],
                "pnl_parsed": False,
                "write_output": not args.check_only,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
