#!/usr/bin/env python3
"""Freeze the isolated ProDayTraderV6 cycle before technical or PnL runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import freeze_pro_day_v3_cycle1 as base


ROOT = Path(__file__).resolve().parents[1]
PLAN = Path("docs/pro_day_trader_v6_cycle1_locked_plan.md")
OUTPUT = Path("user_data/reports/pro_day_v6_cycle1/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v6_cycle1/trial_ledger.json")
HASHES = {
    "strategy": "1f70917dd14aa6fe7cec243ff3a2290759e138357ee25f288eb0ea7f499ad33c",
    "config": "d5ceaf71bd8c3582532cd710bc8396c96019fd8d37859da47a5829df728fc48d",
    "strategy_tests": "11663caceb8688faf784b115771f107290593e8691c6d05a1ca0868205341f35",
    "data_audit": "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772",
    "risk_policy": "6a3e073fd08b21d645b0d4b4151022bef79adc610d8c130b36554a01e6f51e80",
}


def freeze(root: Path = ROOT, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "plan": root / PLAN,
        "strategy": root / "user_data/strategies/ProDayTraderV6.py",
        "v5_parent": root / "user_data/strategies/ProDayTraderV5.py",
        "config": root / "user_data/config-pro-day-v6-cycle1-research.json",
        "risk_policy": root / "user_data/risk_policy.json",
        "data_audit": root / "user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json",
        "strategy_tests": root / "tools/test_pro_day_trader_v6.py",
        "freezer": Path(__file__).resolve(),
        "v5_train": root / "user_data/reports/pro_day_v5_cycle1/train_evaluation.json",
    }
    for label, path in paths.items():
        if not path.is_file():
            raise base.FreezeError(f"missing {label}")
    for label, expected in HASHES.items():
        if base.sha256_file(paths[label]) != expected:
            raise base.FreezeError(f"{label} SHA256 mismatch")
    previous = base.load(paths["v5_train"], "V5 TRAIN")
    base.equal(previous.get("status"), "FAIL", "V5 TRAIN status")
    base.equal(previous.get("decision"), "KEEP_OFFLINE_RESEARCH", "V5 TRAIN decision")
    base.equal(previous.get("pnl_parsed"), True, "V5 TRAIN PnL boundary")
    source = paths["strategy"].read_text(encoding="utf-8")
    for marker in ("class ProDayTraderV6(ProDayTraderV5)", "candidate_T1_long", "T1_15m_ema_cross", "T1_time_stop_720m"):
        if marker not in source:
            raise base.FreezeError(f"strategy marker missing: {marker}")
    config = base.load(paths["config"], "V6 config")
    for field, expected in (("strategy", "ProDayTraderV6"), ("dry_run", True),
                            ("initial_state", "stopped"), ("timeframe", "5m"),
                            ("trading_mode", "futures"), ("margin_mode", "isolated")):
        base.equal(config.get(field), expected, field)
    if "freqai" in config or "freqaimodel" in config:
        raise base.FreezeError("ML config must be absent")
    meta = config.get("pro_day_v6_research", {})
    base.equal(meta.get("recursive_qualification_count"), 2399, "qualification count")
    base.equal(meta.get("live_trading_authorized"), False, "live authorization")
    data_files = base.validate_data(base.load(paths["data_audit"], "data audit"), root)
    artifacts = {}
    for label, name in {"train": "train", "validation": "validation", "current_partial": "current-partial", "canonical": "canonical"}.items():
        relative = Path(f"user_data/backtest_results/prodayv6-cycle1-{name}.zip")
        if (root / relative).exists():
            raise base.FreezeError(f"artifact exists: {relative}")
        artifacts[label] = {"path": str(relative).replace("\\", "/"), "filename": relative.name,
                            "sha256": None, "status": "PLANNED_NOT_RUN"}
    report_dir = root / "user_data/reports/pro_day_v6_cycle1"
    if report_dir.exists() and any(report_dir.iterdir()):
        raise base.FreezeError("V6 report directory is not empty")
    files = {label: base.descriptor(path, root) for label, path in paths.items()}
    locked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0", "status": "RESEARCH_FROZEN", "candidate": "ProDayTraderV6",
        "cycle": "pro_day_v6_cycle1", "locked_at_utc": locked,
        "qualification_state": "NOT_STARTED_NO_PNL_PARSED", "pnl_parsed": False,
        "model_training_performed": False, "files": files, "data_files": data_files,
        "frozen_parameters": {
            "runtime_image": base.IMAGE, "runtime_digest": base.DIGEST, "timeframe": "5m",
            "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
            "entry_policy": "T1_only", "exit_policy": "direction_matched_15m_T1_only_plus_720m_fail_safe",
            "recursive_startup_counts": [199, 399, 799, 1599, 2399],
            "recursive_qualification_count": 2399, "lookahead_timerange": "20240101-20260101",
            "lookahead_minimum": 100, "lookahead_targeted": 120,
            "lookahead_market_price_side": "other", "lookahead_order_book": True,
            "train_timerange": "20220101-20240101", "private_api_transport": False,
            "ml_order_gate": False, "leverage": 1,
        },
        "artifacts": artifacts, "active_strategies_changed": False,
        "live_trading_authorized": False, "automatic_promotion_authorized": False,
    }
    ledger = {
        "schema_version": "1.0", "cycle": "pro_day_v6_cycle1", "candidate": "ProDayTraderV6",
        "created_at_utc": locked, "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"], "config_sha256": files["config"]["sha256"],
        "qualification_runs": [], "parameter_trials": [], "pnl_parsed": False,
        "post_result_edits_allowed": False, "live_trading_authorized": False,
    }
    if write_output:
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
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)})); return 2
    print(json.dumps({"status": manifest["status"], "cycle": manifest["cycle"], "pnl_parsed": False})); return 0


if __name__ == "__main__":
    raise SystemExit(main())

