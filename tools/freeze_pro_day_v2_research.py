#!/usr/bin/env python3
"""Freeze every ProDayTraderV2 input before model fitting or qualification PnL."""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from freeze_pro_day_research import (
    FreezeError,
    _literal_assignment,
    _return_literals,
    descriptor,
    load_json_object,
    locked_at_utc,
    portable_path,
    resolve_input,
    sha256_file,
    validate_no_secret_json,
    validate_risk_policy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "ProDayTraderV2"
CYCLE = "pro_day_v2_cycle1"
IMAGE = (
    "freqtradeorg/freqtrade@sha256:"
    "2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
)
DIGEST = "sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
IDENTIFIER = "proday-v2-cycle1-canonical5m-lgbm-20260811"

DEFAULT_PLAN = Path("docs/pro_day_trader_v2_locked_plan.md")
DEFAULT_STRATEGY = Path("user_data/strategies/ProDayTraderV2.py")
DEFAULT_CONFIG = Path("user_data/config-pro-day-v2-research.json")
DEFAULT_RISK = Path("user_data/risk_policy.json")
DEFAULT_DATA_AUDIT = Path("user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json")
DEFAULT_DATA_CHECKSUM = Path(
    "user_data/reports/pro_day_v2_cycle1/canonical_data_audit.sha256"
)
DEFAULT_RUNTIME = Path("user_data/reports/pro_day_v2_cycle1/runtime_compatibility.json")
DEFAULT_TECHNICAL = Path(
    "user_data/reports/pro_day_v2_cycle1/pre_pnl_technical_evidence.json"
)
DEFAULT_GENERATOR = Path("tools/build_pro_day_v2_canonical_data.py")
DEFAULT_RUNTIME_CHECKER = Path("tools/check_pro_day_v2_runtime.py")
DEFAULT_OUTPUT = Path("user_data/reports/pro_day_v2_cycle1/research_freeze_manifest.json")
DEFAULT_LEDGER = Path("user_data/reports/pro_day_v2_cycle1/trial_ledger.json")

PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT")
TIMEFRAMES = ("5m", "15m", "1h", "4h")
ROW_COUNTS = {"5m": 596_160, "15m": 198_720, "1h": 49_680, "4h": 12_420}
FEATURES = (
    "%-ret_5m_1",
    "%-ret_5m_3",
    "%-ret_5m_12",
    "%-ema_gap_atr_15m",
    "%-momentum_1h_24",
    "%-adx_1h_14",
    "%-trend_gap_atr_4h",
    "%-channel_position_15m_20",
    "%-z48_5m",
    "%-atr_close_5m_14",
    "%-realized_vol_5m_24h",
    "%-log_volume_vs_median_5m_20",
    "%-btc_momentum_1h_24",
    "%-btc_trend_gap_atr_4h",
    "%-btc_realized_vol_5m_24h",
    "%-pair_minus_btc_momentum_1h_24",
    "%-setup_T1",
    "%-setup_R1",
    "%-candidate_side",
)
ARTIFACTS = {
    "canonical": Path("user_data/backtest_results/prodayv2-cycle1-canonical.zip"),
    "train": Path("user_data/backtest_results/prodayv2-cycle1-train.zip"),
    "validation": Path("user_data/backtest_results/prodayv2-cycle1-validation.zip"),
    "current_partial": Path(
        "user_data/backtest_results/prodayv2-cycle1-current-partial.zip"
    ),
}


def _equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise FreezeError(f"{label} differs from the locked value")


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise FreezeError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FreezeError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise FreezeError(f"{label} must be finite")
    return result


def validate_plan(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    required = (
        "LOCKED_BEFORE_FIRST_V2_PNL_RUN",
        CANDIDATE,
        CYCLE,
        "freqtradeorg/freqtrade:2026.7_freqai@" + DIGEST,
        "target[t] = s * log(open[t+13] / open[t+1]) - 0.0026",
        "TRAIN OOS: `[2022-01-01, 2024-01-01)`",
        "VALIDATION OOS: `[2024-01-01, 2026-01-01)`",
        "APPROVE_SEPARATE_DRY_RUN",
    )
    missing = [value for value in required if value not in text]
    if missing:
        raise FreezeError("Locked plan markers are missing: " + ", ".join(missing))


def validate_strategy(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise FreezeError(f"Invalid strategy syntax: {exc}") from exc
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == CANDIDATE]
    if len(classes) != 1:
        raise FreezeError(f"Strategy must define exactly one {CANDIDATE}")
    cls = classes[0]
    expected_assignments = {
        "timeframe": "5m",
        "can_short": True,
        "position_adjustment_enable": False,
        "target_column": "&-candidate_net_log_return",
        "target_horizon_candles": 12,
        "target_cost_hurdle": 0.0026,
        "risk_per_trade_fraction": 0.0025,
        "maximum_single_trade_stake_fraction": 0.10,
        "atr_sizing_multiple": 1.5,
    }
    for name, expected in expected_assignments.items():
        _equal(_literal_assignment(cls, name), expected, f"strategy.{name}")
    startup = _literal_assignment(cls, "startup_candle_count")
    if startup not in (199, 399, 799, 1599, 3199, 6399, 12799):
        raise FreezeError("strategy.startup_candle_count is outside the locked recursive set")
    _equal(tuple(_literal_assignment(cls, "FEATURE_COLUMNS") or ()), FEATURES, "strategy features")
    leverage = [
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "leverage"
    ]
    if len(leverage) != 1 or any(value not in (1, 1.0) for value in _return_literals(leverage[0])):
        raise FreezeError("Strategy leverage callback is not a literal 1x fail-safe")
    required_methods = {
        "feature_engineering_standard",
        "set_freqai_targets",
        "populate_indicators",
        "populate_entry_trend",
        "custom_stake_amount",
        "custom_stoploss",
        "custom_exit",
    }
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    if not required_methods <= methods:
        raise FreezeError("Strategy is missing locked FreqAI/risk methods")
    return {"startup_candle_count": startup, "feature_count": len(FEATURES)}


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    validate_no_secret_json(config, "ProDayTraderV2 config")
    expected_top = {
        "strategy": CANDIDATE,
        "freqaimodel": "LightGBMRegressor",
        "dry_run": True,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "max_open_trades": 2,
        "stake_currency": "USDT",
        "stake_amount": 100,
        "timeframe": "5m",
        "fee": 0.0005,
        "datadir": "user_data/data/binance/pro_day_v2_canonical",
        "initial_state": "stopped",
        "force_entry_enable": False,
    }
    for key, expected in expected_top.items():
        _equal(config.get(key), expected, f"config.{key}")
    if _finite(config.get("dry_run_wallet"), "dry_run_wallet") <= 0:
        raise FreezeError("dry_run_wallet must be positive")
    exchange = config.get("exchange")
    if not isinstance(exchange, Mapping):
        raise FreezeError("config.exchange must be an object")
    _equal(exchange.get("name"), "binance", "exchange.name")
    _equal(exchange.get("pair_whitelist"), list(PAIRS), "exchange.pair_whitelist")
    _equal(exchange.get("pair_blacklist"), [], "exchange.pair_blacklist")
    for key in ("key", "secret", "password", "uid"):
        if exchange.get(key) not in (None, ""):
            raise FreezeError(f"exchange.{key} must remain empty")

    freqai = config.get("freqai")
    if not isinstance(freqai, Mapping):
        raise FreezeError("config.freqai must be an object")
    expected_freqai = {
        "enabled": True,
        "identifier": IDENTIFIER,
        "train_period_days": 365,
        "backtest_period_days": 30,
        "expiration_hours": 12,
        "purge_old_models": 2,
        "save_backtest_models": True,
    }
    for key, expected in expected_freqai.items():
        _equal(freqai.get(key), expected, f"freqai.{key}")
    expected_feature_params = {
        "include_timeframes": list(TIMEFRAMES),
        "include_corr_pairlist": ["BTC/USDT:USDT"],
        "label_period_candles": 12,
        "include_shifted_candles": 0,
        "indicator_periods_candles": [14],
        "buffer_train_data_candles": 13,
        "principal_component_analysis": False,
        "DI_threshold": 0.0,
        "use_SVM_to_remove_outliers": False,
        "use_DBSCAN_to_remove_outliers": False,
        "noise_standard_deviation": 0.0,
        "shuffle_after_split": False,
        "reverse_train_test_order": False,
    }
    _equal(freqai.get("feature_parameters"), expected_feature_params, "freqai.feature_parameters")
    _equal(
        freqai.get("data_split_parameters"),
        {"test_size": 0, "shuffle": False, "random_state": 20260811},
        "freqai.data_split_parameters",
    )
    expected_model = {
        "n_estimators": 200,
        "learning_rate": 0.03,
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 200,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "n_jobs": 2,
        "deterministic": True,
        "force_col_wise": True,
        "random_state": 20260811,
        "random_seed": 20260811,
        "data_random_seed": 20260811,
        "feature_fraction_seed": 20260811,
        "bagging_seed": 20260811,
    }
    _equal(freqai.get("model_training_parameters"), expected_model, "model parameters")
    metadata = config.get("pro_day_v2_research")
    if not isinstance(metadata, Mapping):
        raise FreezeError("config.pro_day_v2_research is missing")
    expected_meta = {
        "cycle": CYCLE,
        "status": "LOCKED_BEFORE_FIRST_V2_PNL_RUN",
        "plan": "docs/pro_day_trader_v2_locked_plan.md",
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
    }
    _equal(metadata, expected_meta, "config.pro_day_v2_research")
    return {
        "pairs": list(PAIRS),
        "timeframes": list(TIMEFRAMES),
        "model": "LightGBMRegressor",
        "identifier": IDENTIFIER,
        "train_period_days": 365,
        "backtest_period_days": 30,
        "buffer_train_data_candles": 13,
        "target_horizon_candles": 12,
        "target_cost_hurdle": 0.0026,
        "data_dir": expected_top["datadir"],
    }


def _verify_record(root: Path, record: Mapping[str, Any], label: str) -> dict[str, Any]:
    if record.get("status") != "PASS":
        raise FreezeError(f"{label} status is not PASS")
    raw_path = record.get("path")
    expected_hash = record.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise FreezeError(f"{label} lacks path/hash")
    path = resolve_input(root, raw_path)
    current = descriptor(path, root)
    if current["sha256"] != expected_hash:
        raise FreezeError(f"{label} changed after data audit")
    return current


def validate_data_audit(audit: Mapping[str, Any], root: Path) -> dict[str, Any]:
    _equal(audit.get("schema_version"), "1.0", "data audit schema")
    _equal(audit.get("cycle_id"), CYCLE, "data audit cycle")
    _equal(audit.get("status"), "PASS", "data audit status")
    _equal(audit.get("decision"), "READY_FOR_PRE_PNL_TECHNICAL_GATES", "data decision")
    _equal(audit.get("pnl_evaluated"), False, "data audit pnl_evaluated")
    _equal(audit.get("failures"), [], "data audit failures")
    summary = audit.get("summary")
    expected_summary = {
        "source_files_passed": 3,
        "source_files_required": 3,
        "auxiliary_source_files_passed": 6,
        "auxiliary_source_files_required": 6,
        "canonical_files_passed": 12,
        "canonical_files_required": 12,
        "auxiliary_files_passed": 6,
        "auxiliary_files_required": 6,
        "roundtrip_checks_passed": 9,
        "roundtrip_checks_required": 9,
        "partial_aggregate_bins": 0,
    }
    _equal(summary, expected_summary, "data audit summary")
    policy = audit.get("policy")
    if not isinstance(policy, Mapping):
        raise FreezeError("data audit policy is missing")
    _equal(policy.get("pairs"), list(PAIRS), "data pairs")
    _equal(policy.get("row_counts_per_pair"), ROW_COUNTS, "data row counts")
    _equal(policy.get("start_utc"), "2020-12-01T00:00:00Z", "data start")
    _equal(policy.get("end_exclusive_utc"), "2026-08-02T00:00:00Z", "data end")

    collections = {
        "source_files": 3,
        "auxiliary_source_files": 6,
        "canonical_files": 12,
        "auxiliary_canonical_files": 6,
    }
    frozen: dict[str, list[dict[str, Any]]] = {}
    for name, count in collections.items():
        rows = audit.get(name)
        if not isinstance(rows, list) or len(rows) != count:
            raise FreezeError(f"data audit {name} count differs from locked value")
        frozen[name] = [_verify_record(root, row, f"{name}[{index}]") for index, row in enumerate(rows)]

    expected_names = {
        f"{pair.split('/')[0]}_USDT_USDT-{timeframe}-futures.feather"
        for pair in PAIRS
        for timeframe in TIMEFRAMES
    } | {
        f"{pair.split('/')[0]}_USDT_USDT-1h-{kind}.feather"
        for pair in PAIRS
        for kind in ("funding_rate", "mark")
    }
    canonical_dir = root / "user_data/data/binance/pro_day_v2_canonical"
    actual_names = {path.name for path in canonical_dir.iterdir() if path.is_file()}
    _equal(actual_names, expected_names, "canonical data inventory")

    code_hashes = audit.get("code_hashes")
    if not isinstance(code_hashes, Mapping):
        raise FreezeError("data audit code hashes are missing")
    for role in ("generator_source", "audit_source"):
        record = code_hashes.get(role)
        if not isinstance(record, Mapping):
            raise FreezeError(f"data audit {role} is missing")
        path = resolve_input(root, record.get("path", ""))
        if sha256_file(path) != record.get("sha256"):
            raise FreezeError(f"data audit {role} changed")
    return frozen


def validate_runtime(report: Mapping[str, Any]) -> None:
    _equal(report.get("schema_version"), "1.0", "runtime schema")
    _equal(report.get("status"), "PASS", "runtime status")
    _equal(report.get("candidate"), CANDIDATE, "runtime candidate")
    _equal(report.get("image"), IMAGE, "runtime image")
    _equal(report.get("expected_digest"), DIGEST, "runtime digest")
    _equal(report.get("network_mode"), "none", "runtime network mode")
    _equal(report.get("model_training_performed"), False, "runtime model training")
    _equal(report.get("pnl_evaluated"), False, "runtime pnl")
    _equal(report.get("live_trading_authorized"), False, "runtime live authorization")
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or not checks or not all(value is True for value in checks.values()):
        raise FreezeError("runtime compatibility checks are not all true")


def validate_technical_evidence(report: Mapping[str, Any]) -> None:
    _equal(report.get("schema_version"), "1.0", "technical evidence schema")
    _equal(report.get("status"), "PASS", "technical evidence status")
    _equal(report.get("candidate"), CANDIDATE, "technical evidence candidate")
    _equal(report.get("total_tests"), 24, "technical evidence test count")
    _equal(report.get("python_compile"), "PASS", "python compile status")
    _equal(
        report.get("config_validation"),
        "PASS_OUTPUT_SUPPRESSED",
        "config validation status",
    )
    _equal(
        report.get("strategy_discovery"),
        "PASS_UNIQUE_STATUS_OK",
        "strategy discovery status",
    )
    for field in ("model_training_performed", "backtest_performed", "pnl_evaluated"):
        _equal(report.get(field), False, f"technical evidence {field}")
    _equal(report.get("live_trading_authorized"), False, "technical live authorization")


def _planned_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for label, relative in ARTIFACTS.items():
        path = resolve_input(root, relative)
        if path.exists():
            raise FreezeError(f"Planned artifact already exists before freeze: {relative}")
        result[label] = {
            "path": portable_path(path, root),
            "filename": path.name,
            "sha256": None,
            "status": "PLANNED_NOT_RUN",
        }
    return result


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FreezeError(f"Refusing to overwrite immutable file: {path}") from exc


def freeze_research(
    *,
    project_root: Path = PROJECT_ROOT,
    output_path: str | Path = DEFAULT_OUTPUT,
    ledger_path: str | Path = DEFAULT_LEDGER,
    write_output: bool = True,
    lock_time_utc: str | None = None,
    require_technical_evidence: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = project_root.resolve()
    paths = {
        "plan": resolve_input(root, DEFAULT_PLAN),
        "strategy": resolve_input(root, DEFAULT_STRATEGY),
        "config": resolve_input(root, DEFAULT_CONFIG),
        "risk_policy": resolve_input(root, DEFAULT_RISK),
        "data_audit": resolve_input(root, DEFAULT_DATA_AUDIT),
        "data_audit_checksum": resolve_input(root, DEFAULT_DATA_CHECKSUM),
        "runtime_compatibility": resolve_input(root, DEFAULT_RUNTIME),
        "data_generator": resolve_input(root, DEFAULT_GENERATOR),
        "runtime_checker": resolve_input(root, DEFAULT_RUNTIME_CHECKER),
    }
    technical_path = resolve_input(root, DEFAULT_TECHNICAL)
    require_technical = write_output if require_technical_evidence is None else require_technical_evidence
    if technical_path.is_file():
        paths["pre_pnl_technical_evidence"] = technical_path
    elif require_technical:
        raise FreezeError("Missing pre-PnL technical evidence for final freeze")
    validate_plan(paths["plan"])
    strategy_info = validate_strategy(paths["strategy"])
    config = load_json_object(paths["config"], "V2 research config")
    frozen_parameters = validate_config(config)
    risk = load_json_object(paths["risk_policy"], "risk policy")
    validate_risk_policy(risk)
    audit = load_json_object(paths["data_audit"], "V2 data audit")
    data_records = validate_data_audit(audit, root)
    checksum_tokens = paths["data_audit_checksum"].read_text(encoding="utf-8").split()
    if not checksum_tokens or checksum_tokens[0].lower() != sha256_file(paths["data_audit"]):
        raise FreezeError("Data-audit checksum sidecar does not match")
    runtime = load_json_object(paths["runtime_compatibility"], "V2 runtime report")
    validate_runtime(runtime)
    if "pre_pnl_technical_evidence" in paths:
        technical = load_json_object(
            paths["pre_pnl_technical_evidence"], "pre-PnL technical evidence"
        )
        validate_technical_evidence(technical)
    files = {name: descriptor(path, root) for name, path in paths.items()}
    artifacts = _planned_artifacts(root)
    locked_at = lock_time_utc or locked_at_utc()
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "RESEARCH_FROZEN",
        "candidate": CANDIDATE,
        "cycle": CYCLE,
        "locked_at_utc": locked_at,
        "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False,
        "model_training_performed": False,
        "files": files,
        "inputs": {
            "plan": files["plan"],
            "strategy": files["strategy"],
            "research_config": files["config"],
            "risk_policy": files["risk_policy"],
            "data_audit": files["data_audit"],
            "runtime_compatibility": files["runtime_compatibility"],
        },
        "data_files": data_records,
        "frozen_parameters": {
            **frozen_parameters,
            **strategy_info,
            "runtime_image": IMAGE,
            "runtime_digest": DIGEST,
            "initial_history": "20210101-20220101",
            "train_timerange": "20220101-20240101",
            "validation_timerange": "20240101-20260101",
            "current_partial_timerange": "20260101-20260801",
            "canonical_timerange": "20220101-20260801",
            "earliest_fill": "next_5m_open",
            "closed_candles_only": True,
            "features": list(FEATURES),
        },
        "artifacts": artifacts,
        "technical_evidence": {
            "data_gate": "PASS",
            "runtime_gate": "PASS",
            "unit_tests": (
                "PASS_24"
                if "pre_pnl_technical_evidence" in paths
                else "PENDING_REGISTRATION"
            ),
            "config_validation": (
                "PASS_OUTPUT_SUPPRESSED"
                if "pre_pnl_technical_evidence" in paths
                else "PENDING_REGISTRATION"
            ),
            "strategy_discovery": (
                "PASS_UNIQUE_STATUS_OK"
                if "pre_pnl_technical_evidence" in paths
                else "PENDING_REGISTRATION"
            ),
            "lookahead_analysis": "PENDING",
            "recursive_analysis": "PENDING",
        },
        "active_strategies_changed": False,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
        "evidence_boundary": (
            "Immutable pre-PnL freeze only. No model was fit and no backtest result, "
            "trade, PnL, profitability, forward, deployment, or live evidence was parsed."
        ),
    }
    ledger = {
        "schema_version": "1.0",
        "cycle": CYCLE,
        "candidate": CANDIDATE,
        "created_at_utc": locked_at,
        "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"],
        "config_sha256": files["config"]["sha256"],
        "pnl_parsed": False,
        "qualification_runs": [],
        "parameter_trials": [],
        "post_result_edits_allowed": False,
        "live_trading_authorized": False,
    }
    if write_output:
        output = resolve_input(root, output_path)
        ledger_file = resolve_input(root, ledger_path)
        if output.exists() or ledger_file.exists():
            raise FreezeError("Freeze manifest/trial ledger already exists; refusing overwrite")
        _write_exclusive(ledger_file, ledger)
        try:
            _write_exclusive(output, manifest)
        except Exception:
            ledger_file.unlink(missing_ok=True)
            raise
    return manifest, ledger


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest, _ = freeze_research(
            project_root=args.project_root,
            output_path=args.output,
            ledger_path=args.ledger,
            write_output=not args.check_only,
        )
    except (FreezeError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "candidate": manifest["candidate"],
                "qualification_state": manifest["qualification_state"],
                "pnl_parsed": False,
                "write_output": not args.check_only,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
