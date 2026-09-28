#!/usr/bin/env python3
"""Freeze ProDayTraderV5 before recursive/lookahead/PnL runs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import freeze_pro_day_v3_cycle1 as base


ROOT = Path(__file__).resolve().parents[1]
PLAN = Path("docs/pro_day_trader_v5_cycle1_locked_plan.md")
OUTPUT = Path("user_data/reports/pro_day_v5_cycle1/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v5_cycle1/trial_ledger.json")
HASHES = {
    "strategy": "eaa5cd47f6750a697c1cf32400fd641347a0bd95c3a2e0e4de60c4e5528e0b9f",
    "config": "c633792072936197ef565112c8374d592dd72259e5b3cbe1bf26ef809d1b72f8",
    "data_audit": "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772",
    "v4_recursive": "436c6b45bf31ac0b955cda8b173be6d7c2ab1b14a97fa83f69bc4794c0f43850",
    "v4_lookahead": "4c56a3861c64a0405c187381fdd35bf0d9f92d61f211c6b2c2a41e526b8b6ac2",
}


def freeze(root: Path = ROOT, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "plan": root / PLAN,
        "strategy": root / "user_data/strategies/ProDayTraderV5.py",
        "v4_parent": root / "user_data/strategies/ProDayTraderV4.py",
        "config": root / "user_data/config-pro-day-v5-cycle1-research.json",
        "risk_policy": root / base.RISK,
        "data_audit": root / base.AUDIT,
        "v4_recursive": root / "user_data/reports/pro_day_v4_cycle1/recursive_analysis.json",
        "v4_lookahead": root / "user_data/reports/pro_day_v4_cycle3/lookahead_analysis.json",
        "strategy_tests": root / "tools/test_pro_day_trader_v5.py",
        "freezer": Path(__file__).resolve(),
    }
    for label, path in paths.items():
        if not path.is_file():
            raise base.FreezeError(f"missing {label}")
    for label, expected in HASHES.items():
        if base.sha256_file(paths[label]) != expected:
            raise base.FreezeError(f"{label} SHA256 mismatch")
    text = paths["plan"].read_text(encoding="utf-8")
    for marker in (*HASHES.values(), "LOCKED_BEFORE_FIRST_V5_PNL_RUN", "APPROVE_SEPARATE_DRY_RUN"):
        if marker not in text:
            raise base.FreezeError(f"plan marker missing: {marker}")
    source = paths["strategy"].read_text(encoding="utf-8")
    for marker in ("class ProDayTraderV5(ProDayTraderV4)", "def populate_exit_trend", "def custom_stake_amount", "def custom_exit"):
        if marker not in source:
            raise base.FreezeError(f"strategy marker missing: {marker}")
    config = base.load(paths["config"], "V5 config")
    for field, expected in (("strategy", "ProDayTraderV5"), ("dry_run", True),
                            ("initial_state", "stopped"), ("timeframe", "5m"),
                            ("trading_mode", "futures"), ("margin_mode", "isolated")):
        base.equal(config.get(field), expected, field)
    if "freqai" in config or "freqaimodel" in config:
        raise base.FreezeError("ML config must be absent")
    meta = config.get("pro_day_v5_research", {})
    base.equal(meta.get("recursive_qualification_count"), 2399, "qualification count")
    base.equal(meta.get("live_trading_authorized"), False, "live authorization")
    data_files = base.validate_data(base.load(paths["data_audit"], "data audit"), root)
    previous = base.load(paths["v4_lookahead"], "V4 lookahead")
    base.equal(previous.get("status"), "FAIL", "V4 lookahead status")
    base.equal(previous.get("pnl_parsed"), False, "V4 pnl boundary")
    base.equal(previous.get("gate_details", {}).get("false_indicators"), [], "V4 indicator bias")
    artifacts = {}
    for label, name in {"train": "train", "validation": "validation", "current_partial": "current-partial", "canonical": "canonical"}.items():
        relative = Path(f"user_data/backtest_results/prodayv5-cycle1-{name}.zip")
        if (root / relative).exists():
            raise base.FreezeError(f"artifact exists: {relative}")
        artifacts[label] = {"path": str(relative).replace("\\", "/"), "filename": relative.name,
                            "sha256": None, "status": "PLANNED_NOT_RUN"}
    if (root / "user_data/reports/pro_day_v5_cycle1/recursive_analysis.json").exists():
        raise base.FreezeError("V5 recursive output exists")
    files = {label: base.descriptor(path, root) for label, path in paths.items()}
    locked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0", "status": "RESEARCH_FROZEN",
        "candidate": "ProDayTraderV5", "cycle": "pro_day_v5_cycle1",
        "locked_at_utc": locked, "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False, "model_training_performed": False,
        "files": files, "data_files": data_files,
        "frozen_parameters": {
            "runtime_image": base.IMAGE, "runtime_digest": base.DIGEST,
            "timeframe": "5m", "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
            "trend_regime": "4h_ema20_ema50_with_ema50_slope3",
            "exit_policy": "vectorized_r1_or_t1_plus_causal_time_callbacks",
            "stake_policy": "wallet_0.25pct_over_4pct_stop",
            "recursive_startup_counts": [199, 399, 799, 1599, 2399],
            "recursive_qualification_count": 2399,
            "lookahead_timerange": "20240101-20260101",
            "lookahead_minimum": 100, "lookahead_targeted": 120,
            "lookahead_market_price_side": "other", "lookahead_order_book": True,
            "private_api_transport": False, "ml_order_gate": False, "leverage": 1,
            "train_timerange": "20220101-20240101",
        },
        "artifacts": artifacts,
        "technical_evidence": {"strategy_tests": "PASS_4", "config_validation": "PASS_OUTPUT_SUPPRESSED",
                               "strategy_discovery": "PASS_UNIQUE_STATUS_OK", "recursive_analysis": "PENDING",
                               "lookahead_analysis": "LOCKED_PENDING_RECURSIVE_PASS"},
        "active_strategies_changed": False, "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
    }
    ledger = {
        "schema_version": "1.0", "cycle": "pro_day_v5_cycle1", "candidate": "ProDayTraderV5",
        "created_at_utc": locked, "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"], "config_sha256": files["config"]["sha256"],
        "qualification_runs": [], "parameter_trials": [], "pnl_parsed": False,
        "post_result_edits_allowed": False, "live_trading_authorized": False,
    }
    if write_output:
        if (root / OUTPUT).exists() or (root / LEDGER).exists():
            raise base.FreezeError("V5 manifest or ledger exists")
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
