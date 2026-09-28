#!/usr/bin/env python3
"""Freeze the frequency-preserving ML ensemble before any Cycle-2 PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_intraday_ml_ensemble_cycle2"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA = ROOT / "user_data/data/binance/profit_max_intraday_ml_cycle1_canonical/futures"
MODELS = REPORT / "models"
RESULTS = REPORT / "train_results"
IMAGE = "freqtradeorg/freqtrade:2026.7_freqai@sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
THRESHOLD = -0.0135255


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    prior = ROOT / "user_data/reports/profit_max_intraday_ml_cycle1"
    inputs = {
        "plan": ROOT / "docs/profit_max_intraday_ml_ensemble_cycle2_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxIntradayMLV2.py",
        "ml_parent": ROOT / "user_data/strategies/ProfitMaxIntradayMLV1.py",
        "deterministic_parent_v2": ROOT / "user_data/strategies/ProfitMaxIntradayV2.py",
        "deterministic_parent_v1": ROOT / "user_data/strategies/ProfitMaxIntradayV1.py",
        "base_config": ROOT / "user_data/config-profit-max-intraday-cycle1.json",
        "ml_config": ROOT / "user_data/config-profit-max-intraday-ml-ensemble-cycle2.json",
        "strategy_tests": ROOT / "tools/test_profit_max_intraday_ml_v2.py",
        "data_audit": prior / "canonical_data_audit.json",
        "prior_ml_decision": prior / "train_decision.json",
        "prior_ranking_diagnostic": prior / "ranking_diagnostic.json",
        "v5_train_archive": ROOT / "user_data/reports/profit_max_v5_repro_original_stake-2026-08-17_11-59-40.zip",
        "v1_train_archive": ROOT / "user_data/reports/profit_max_v1_repro_original_stake-2026-08-17_12-00-05.zip",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    if MANIFEST.exists() or MODELS.exists() or RESULTS.exists():
        print("FREEZE_BLOCKED: Cycle-2 output already exists", file=sys.stderr)
        return 3

    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    config = json.loads(inputs["ml_config"].read_text(encoding="utf-8"))
    audit = json.loads(inputs["data_audit"].read_text(encoding="utf-8"))
    decision = json.loads(inputs["prior_ml_decision"].read_text(encoding="utf-8"))
    ranking = json.loads(inputs["prior_ranking_diagnostic"].read_text(encoding="utf-8"))
    freqai = config.get("freqai") or {}
    features = freqai.get("feature_parameters") or {}
    model = freqai.get("model_training_parameters") or {}
    meta = config.get("profit_max_intraday_research") or {}
    rank_800 = ((ranking.get("top_rank_subsets") or {}).get("800") or {})
    safe = (
        audit.get("status") == "PASS"
        and audit.get("pnl_evaluated") is False
        and decision.get("status") == "FAIL"
        and decision.get("validation_revealed") is False
        and ranking.get("qualification_evidence") is False
        and rank_800.get("trades") == 800
        and rank_800.get("trades_per_day", 0) > 1.0
        and abs(float(rank_800.get("minimum_prediction")) - THRESHOLD) < 1e-6
        and base.get("dry_run") is True
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and base.get("fee") == 0.00075
        and base.get("stake_amount") == 75
        and base.get("max_open_trades") == 3
        and len(((base.get("exchange") or {}).get("pair_whitelist") or [])) == 6
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
        and config.get("strategy") == "ProfitMaxIntradayMLV2"
        and config.get("freqaimodel") == "LightGBMRegressor"
        and freqai.get("identifier") == "profit-max-intraday-ml-ensemble-cycle2-20260817"
        and freqai.get("train_period_days") == 365
        and freqai.get("backtest_period_days") == 30
        and freqai.get("purge_old_models") == 0
        and features.get("include_shifted_candles") == 0
        and features.get("buffer_train_data_candles") == 17
        and (freqai.get("data_split_parameters") or {}).get("shuffle") is False
        and model.get("n_estimators") == 200
        and model.get("max_depth") == 4
        and model.get("deterministic") is True
        and meta.get("prediction_threshold") == THRESHOLD
        and meta.get("target_roundtrip_fee") == 0.0015
        and meta.get("model_can_only_veto") is True
        and meta.get("live_trading_authorized") is False
    )
    if not safe:
        print("FREEZE_BLOCKED: source, diagnostic, execution, or model contract failed", file=sys.stderr)
        return 2

    data_files = sorted(path for path in DATA.iterdir() if path.is_file() and not path.is_symlink())
    if len(data_files) != 30:
        print(f"FREEZE_BLOCKED: expected 30 canonical data files, found {len(data_files)}", file=sys.stderr)
        return 2

    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_intraday_ml_ensemble_cycle2",
        "status": "RESEARCH_FROZEN_BEFORE_MODEL_AND_PNL",
        "model_training_performed": False,
        "pnl_parsed": False,
        "validation_revealed": False,
        "live_trading_authorized": False,
        "runtime": IMAGE,
        "candidate": "ProfitMaxIntradayMLV2",
        "prediction_threshold": THRESHOLD,
        "fee_per_side": 0.00075,
        "splits": {
            "initial_model_history": "20210101-20220101",
            "train_oos": "20220101-20240101",
            "validation_oos": "20240101-20260101",
            "current_partial_oos": "20260101-20260801",
        },
        "portfolio": {
            "ml": {"strategy": "ProfitMaxIntradayMLV2", "slots": 3, "stake": 75},
            "v5": {"strategy": "ProfitMaxV5Asymmetric50", "slots": 2, "stake": 50},
            "v1": {"strategy": "DualTrendFuturesV1", "slots": 1, "stake": 50},
        },
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "data_files": [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for path in data_files],
        "artifacts": {
            "models": "user_data/reports/profit_max_intraday_ml_ensemble_cycle2/models",
            "train_results": "user_data/reports/profit_max_intraday_ml_ensemble_cycle2/train_results",
            "ml_train_archive": "user_data/reports/profit_max_intraday_ml_ensemble_cycle2/ml_train.zip",
            "train_decision": "user_data/reports/profit_max_intraday_ml_ensemble_cycle2/train_decision.json",
        },
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    with MANIFEST.open("xb") as handle:
        handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    print(json.dumps({"status": payload["status"], "data_files": len(data_files), "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
