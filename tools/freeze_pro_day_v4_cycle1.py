#!/usr/bin/env python3
"""Freeze ProDayTraderV4 before recursive analysis or any PnL run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import freeze_pro_day_v3_cycle1 as base


ROOT = Path(__file__).resolve().parents[1]
PLAN = Path("docs/pro_day_trader_v4_cycle1_locked_plan.md")
STRATEGY = Path("user_data/strategies/ProDayTraderV4.py")
CONFIG = Path("user_data/config-pro-day-v4-cycle1-research.json")
OUTPUT = Path("user_data/reports/pro_day_v4_cycle1/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v4_cycle1/trial_ledger.json")
EXPECTED = {
    "strategy": "ecca8f37bf162bd6f1e9d8d0bb6ccc06910e3c65ab95c9b4a06ba8cd99c1fcea",
    "config": "307fa8d43b0356b28a7b0e451c57cc59ad35b969bb1a0351e3d23c8f9d666c26",
    "data_audit": "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772",
    "v3_cycle1_manifest": "83b2e4f79d5e3ade690621faf374574f1d3d480f8c138e3c76aa642193a69ba9",
    "v3_cycle2_manifest": "f0dd6a265a9aff832a5d9f2349bce08bb8b216859c92d441df81fd0f8703d570",
    "v3_cycle2_recursive": "9f2e95aa83d78c00aa9707e01853b62b707a41d864e8ef222aa03bac6d7dfc30",
}


def validate_strategy(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    for marker in (
        "class ProDayTraderV4(ProDayTraderV3)",
        "startup_candle_count = 2399",
        'informative_timeframe != "4h"',
        'frame["ema20"] = ta.EMA(frame, timeperiod=20)',
        'frame["ema50"] = ta.EMA(frame, timeperiod=50)',
    ):
        if marker not in source:
            raise base.FreezeError(f"V4 strategy marker missing: {marker}")
    if "ema200" in source:
        raise base.FreezeError("V4 wrapper must not calculate EMA200")


def validate_config(config: dict[str, Any]) -> None:
    base.equal(config.get("strategy"), "ProDayTraderV4", "strategy")
    for field, value in (
        ("initial_state", "stopped"), ("dry_run", True), ("trading_mode", "futures"),
        ("margin_mode", "isolated"), ("timeframe", "5m"), ("max_open_trades", 2),
        ("fee", 0.0005),
    ):
        base.equal(config.get(field), value, field)
    if "freqai" in config or "freqaimodel" in config:
        raise base.FreezeError("ML must be absent")
    meta = config.get("pro_day_v4_research", {})
    base.equal(meta.get("cycle"), "pro_day_v4_cycle1", "cycle")
    base.equal(meta.get("recursive_qualification_count"), 2399, "qualification count")
    base.equal(meta.get("recursive_startup_counts"), [199, 399, 799, 1599, 2399], "startup counts")
    base.equal(meta.get("technical_public_market_metadata"), True, "public metadata")
    base.equal(meta.get("live_trading_authorized"), False, "live authorization")


def freeze(root: Path = ROOT, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "plan": root / PLAN,
        "strategy": root / STRATEGY,
        "deterministic_parent": root / base.STRATEGY,
        "indicator_parent": root / base.BASE_STRATEGY,
        "config": root / CONFIG,
        "risk_policy": root / base.RISK,
        "data_audit": root / base.AUDIT,
        "v3_cycle1_manifest": root / "user_data/reports/pro_day_v3_cycle1/research_freeze_manifest.json",
        "v3_cycle2_manifest": root / "user_data/reports/pro_day_v3_cycle2/research_freeze_manifest.json",
        "v3_cycle2_recursive": root / "user_data/reports/pro_day_v3_cycle2/recursive_analysis.json",
        "strategy_tests": root / "tools/test_pro_day_trader_v4.py",
        "freezer": Path(__file__).resolve(),
    }
    for label, path in paths.items():
        if not path.is_file():
            raise base.FreezeError(f"missing {label}: {path}")
    for label, expected in EXPECTED.items():
        if base.sha256_file(paths[label]) != expected:
            raise base.FreezeError(f"{label} SHA256 mismatch")
    plan = paths["plan"].read_text(encoding="utf-8")
    for marker in (*EXPECTED.values(), "LOCKED_BEFORE_FIRST_V4_PNL_RUN", "qualification count 2399"):
        if marker not in plan:
            raise base.FreezeError(f"plan marker missing: {marker}")
    validate_strategy(paths["strategy"])
    validate_config(base.load(paths["config"], "V4 config"))
    data_files = base.validate_data(base.load(paths["data_audit"], "data audit"), root)
    previous = base.load(paths["v3_cycle2_recursive"], "V3 Cycle 2 recursive")
    base.equal(previous.get("status"), "FAIL", "V3 recursive status")
    base.equal(previous.get("gate_details", {}).get("indicator_only_lookahead_columns"), [], "V3 lookahead differences")
    base.equal(previous.get("gate_details", {}).get("signal_differences"), [], "V3 signal differences")
    for field in ("model_training_performed", "backtest_performed", "pnl_parsed", "live_trading_authorized"):
        base.equal(previous.get(field), False, f"V3 {field}")
    artifacts = {}
    for label, name in {"train": "train", "validation": "validation", "current_partial": "current-partial", "canonical": "canonical"}.items():
        relative = Path(f"user_data/backtest_results/prodayv4-cycle1-{name}.zip")
        if (root / relative).exists():
            raise base.FreezeError(f"planned artifact exists: {relative}")
        artifacts[label] = {"path": str(relative).replace("\\", "/"), "filename": relative.name,
                            "sha256": None, "status": "PLANNED_NOT_RUN"}
    if (root / "user_data/reports/pro_day_v4_cycle1/recursive_analysis.json").exists():
        raise base.FreezeError("V4 recursive output exists before freeze")
    files = {label: base.descriptor(path, root) for label, path in paths.items()}
    locked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0", "status": "RESEARCH_FROZEN",
        "candidate": "ProDayTraderV4", "cycle": "pro_day_v4_cycle1",
        "locked_at_utc": locked, "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False, "model_training_performed": False,
        "files": files, "data_files": data_files,
        "frozen_parameters": {
            "runtime_image": base.IMAGE, "runtime_digest": base.DIGEST,
            "timeframe": "5m", "informative_timeframes": ["15m", "1h", "4h"],
            "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
            "trend_regime": "4h_ema20_ema50_with_ema50_slope3",
            "recursive_startup_counts": [199, 399, 799, 1599, 2399],
            "recursive_qualification_count": 2399,
            "public_market_metadata_transport": True, "private_api_transport": False,
            "ml_order_gate": False, "leverage": 1,
            "train_timerange": "20220101-20240101",
            "validation_timerange": "20240101-20260101",
            "current_partial_timerange": "20260101-20260801",
        },
        "artifacts": artifacts,
        "technical_evidence": {"strategy_tests": "PASS_4", "config_validation": "PASS_OUTPUT_SUPPRESSED",
                               "strategy_discovery": "PASS_UNIQUE_STATUS_OK", "recursive_analysis": "PENDING",
                               "lookahead_analysis": "LOCKED_PENDING_RECURSIVE_PASS"},
        "active_strategies_changed": False, "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
    }
    ledger = {
        "schema_version": "1.0", "cycle": "pro_day_v4_cycle1", "candidate": "ProDayTraderV4",
        "created_at_utc": locked, "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"], "config_sha256": files["config"]["sha256"],
        "qualification_runs": [], "parameter_trials": [], "pnl_parsed": False,
        "post_result_edits_allowed": False, "live_trading_authorized": False,
    }
    if write_output:
        if (root / OUTPUT).exists() or (root / LEDGER).exists():
            raise base.FreezeError("V4 manifest or ledger exists")
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
        manifest, _ = freeze(write_output=not args.check_only)
    except (base.FreezeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": manifest["status"], "cycle": manifest["cycle"], "pnl_parsed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
