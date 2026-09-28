#!/usr/bin/env python3
"""Freeze the ProfitMax FreqAI cycle before model training or PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_intraday_ml_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA = ROOT / "user_data/data/binance/profit_max_intraday_ml_cycle1_canonical/futures"
MODELS = REPORT / "models"
RESULTS = REPORT / "train_results"
IMAGE = "freqtradeorg/freqtrade:2026.7_freqai@sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
CANDIDATE = "ProfitMaxIntradayMLV1"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    cycle3 = ROOT / "user_data/reports/profit_max_intraday_cycle3"
    inputs = {
        "plan": ROOT / "docs/profit_max_intraday_ml_cycle1_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxIntradayMLV1.py",
        "parent_strategy_v2": ROOT / "user_data/strategies/ProfitMaxIntradayV2.py",
        "parent_strategy_v1": ROOT / "user_data/strategies/ProfitMaxIntradayV1.py",
        "indicator_strategy": ROOT / "user_data/strategies/ProTournament15m.py",
        "base_config": ROOT / "user_data/config-profit-max-intraday-cycle1.json",
        "ml_config": ROOT / "user_data/config-profit-max-intraday-ml-cycle1.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "strategy_tests": ROOT / "tools/test_profit_max_intraday_ml_v1.py",
        "data_builder": ROOT / "tools/build_profit_max_intraday_ml_data.py",
        "data_audit": REPORT / "canonical_data_audit.json",
        "cycle3_decision": cycle3 / "train_decision.json",
        "cycle3_archive": cycle3 / "train.zip",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    if MODELS.exists() or RESULTS.exists():
        print("FREEZE_BLOCKED: model or result directory already exists", file=sys.stderr)
        return 2
    audit = json.loads(inputs["data_audit"].read_text(encoding="utf-8"))
    decision = json.loads(inputs["cycle3_decision"].read_text(encoding="utf-8"))
    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    ml = json.loads(inputs["ml_config"].read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or audit.get("pnl_evaluated") is not False:
        print("FREEZE_BLOCKED: data audit is not pre-PnL PASS", file=sys.stderr)
        return 2
    if decision.get("status") != "FAIL" or decision.get("validation_revealed") is not False or decision.get("deterministic_exit_tuning_closed") is not True:
        print("FREEZE_BLOCKED: deterministic lineage is not closed", file=sys.stderr)
        return 2
    metadata = ml.get("profit_max_intraday_research") or {}
    freqai = ml.get("freqai") or {}
    features = freqai.get("feature_parameters") or {}
    model = freqai.get("model_training_parameters") or {}
    safe = (
        base.get("dry_run") is True
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and base.get("fee") == 0.00075
        and base.get("stake_amount") == 75
        and base.get("max_open_trades") == 3
        and len(((base.get("exchange") or {}).get("pair_whitelist") or [])) == 6
        and ml.get("freqaimodel") == "LightGBMRegressor"
        and freqai.get("identifier") == "profit-max-intraday-ml-cycle1-20260816"
        and freqai.get("train_period_days") == 365
        and freqai.get("backtest_period_days") == 30
        and freqai.get("purge_old_models") == 0
        and features.get("include_shifted_candles") == 0
        and features.get("buffer_train_data_candles") == 17
        and (freqai.get("data_split_parameters") or {}).get("shuffle") is False
        and model.get("n_estimators") == 200
        and model.get("max_depth") == 4
        and model.get("deterministic") is True
        and metadata.get("target_roundtrip_fee") == 0.0015
        and metadata.get("prediction_threshold") == 0.0
        and metadata.get("model_can_only_veto") is True
        and metadata.get("live_trading_authorized") is False
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
    )
    if not safe:
        print("FREEZE_BLOCKED: execution/model safety contract failed", file=sys.stderr)
        return 2
    data_files = sorted(path for path in DATA.iterdir() if path.is_file() and not path.is_symlink())
    if len(data_files) != 30:
        print(f"FREEZE_BLOCKED: expected 30 canonical files, found {len(data_files)}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_intraday_ml_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_MODEL_AND_PNL",
        "model_training_performed": False,
        "pnl_parsed": False,
        "live_trading_authorized": False,
        "candidate": CANDIDATE,
        "runtime": IMAGE,
        "baseline_fee_per_side": 0.00075,
        "minimum_roundtrip_fee": 0.0015,
        "frequency_gate_trades_per_day": {"minimum": 1.0, "maximum": 2.0},
        "feature_count": 15,
        "prediction_threshold": 0.0,
        "splits": {"initial_model_history": "20210101-20220101", "train_oos": "20220101-20240101", "validation_oos": "20240101-20260101", "current_partial_oos": "20260101-20260801"},
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "data_files": [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for path in data_files],
        "artifacts": {"models": "user_data/reports/profit_max_intraday_ml_cycle1/models", "train_results": "user_data/reports/profit_max_intraday_ml_cycle1/train_results", "train_archive": "user_data/reports/profit_max_intraday_ml_cycle1/train.zip"},
    }
    try:
        with MANIFEST.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    except FileExistsError:
        print(f"FREEZE_BLOCKED: manifest already exists: {MANIFEST}", file=sys.stderr)
        return 3
    print(json.dumps({"status": payload["status"], "data_files": len(data_files), "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
