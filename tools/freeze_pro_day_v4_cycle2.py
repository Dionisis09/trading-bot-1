#!/usr/bin/env python3
"""Freeze V4 Cycle 2 lookahead-only retry before any performance PnL."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import freeze_pro_day_v3_cycle1 as base


ROOT = Path(__file__).resolve().parents[1]
PLAN = Path("docs/pro_day_trader_v4_cycle2_locked_plan.md")
OUTPUT = Path("user_data/reports/pro_day_v4_cycle2/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v4_cycle2/trial_ledger.json")
HASHES = {
    "strategy": "ecca8f37bf162bd6f1e9d8d0bb6ccc06910e3c65ab95c9b4a06ba8cd99c1fcea",
    "config": "307fa8d43b0356b28a7b0e451c57cc59ad35b969bb1a0351e3d23c8f9d666c26",
    "cycle1_plan": "8428e1380f3ca439f252fb119211105fdcaa0a559e6c07e6f49a540641352745",
    "cycle1_manifest": "bf30614be68d1889aa8d886e3c8c832c555aca19af9f80d41a4915b72ad141c8",
    "recursive_pass": "436c6b45bf31ac0b955cda8b173be6d7c2ab1b14a97fa83f69bc4794c0f43850",
    "lookahead_fail": "3859eed0f56dec648eab15934d73fe7964ecc9a0ae2ad4a8757e9a6a7a131c62",
    "failed_runner": "66b5ed1df09069acc93b5a414c716517ac784b4373b73b160a42df25def448a6",
}


def freeze(root: Path = ROOT, write_output: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "plan": root / PLAN,
        "strategy": root / "user_data/strategies/ProDayTraderV4.py",
        "config": root / "user_data/config-pro-day-v4-cycle1-research.json",
        "risk_policy": root / base.RISK,
        "data_audit": root / base.AUDIT,
        "cycle1_plan": root / "docs/pro_day_trader_v4_cycle1_locked_plan.md",
        "cycle1_manifest": root / "user_data/reports/pro_day_v4_cycle1/research_freeze_manifest.json",
        "recursive_pass": root / "user_data/reports/pro_day_v4_cycle1/recursive_analysis.json",
        "lookahead_fail": root / "user_data/reports/pro_day_v4_cycle1/lookahead_analysis.json",
        "failed_runner": root / "tools/run_pro_day_v4_lookahead_gate.py",
        "freezer": Path(__file__).resolve(),
    }
    for label, path in paths.items():
        if not path.is_file():
            raise base.FreezeError(f"missing {label}")
    for label, expected in HASHES.items():
        if base.sha256_file(paths[label]) != expected:
            raise base.FreezeError(f"{label} SHA256 mismatch")
    plan = paths["plan"].read_text(encoding="utf-8")
    for marker in (*HASHES.values(), "LOCKED_BEFORE_FIRST_V4_CYCLE2_PNL_RUN", 'price_side="other"'):
        if marker not in plan:
            raise base.FreezeError(f"plan marker missing: {marker}")
    recursive = base.load(paths["recursive_pass"], "recursive PASS")
    base.equal(recursive.get("status"), "PASS", "recursive status")
    base.equal(recursive.get("decision"), "CONTINUE_TO_LOOKAHEAD", "recursive decision")
    failed = base.load(paths["lookahead_fail"], "failed lookahead")
    base.equal(failed.get("status"), "FAIL", "lookahead status")
    base.equal(failed.get("container_exit_code"), 1, "lookahead exit")
    base.equal(failed.get("gate_details"), {}, "lookahead must have no probe")
    for report in (recursive, failed):
        base.equal(report.get("pnl_parsed"), False, "prior pnl boundary")
        base.equal(report.get("live_trading_authorized"), False, "prior live boundary")
    data_files = base.validate_data(base.load(paths["data_audit"], "data audit"), root)
    artifacts = {}
    for label, name in {"train": "train", "validation": "validation", "current_partial": "current-partial", "canonical": "canonical"}.items():
        relative = Path(f"user_data/backtest_results/prodayv4-cycle2-{name}.zip")
        if (root / relative).exists():
            raise base.FreezeError(f"planned artifact exists: {relative}")
        artifacts[label] = {"path": str(relative).replace("\\", "/"), "filename": relative.name,
                            "sha256": None, "status": "PLANNED_NOT_RUN"}
    if (root / "user_data/reports/pro_day_v4_cycle2/lookahead_analysis.json").exists():
        raise base.FreezeError("Cycle 2 lookahead output exists")
    files = {label: base.descriptor(path, root) for label, path in paths.items()}
    locked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0", "status": "RESEARCH_FROZEN",
        "candidate": "ProDayTraderV4", "cycle": "pro_day_v4_cycle2",
        "locked_at_utc": locked, "qualification_state": "LOOKAHEAD_RETRY_NO_PNL_PARSED",
        "pnl_parsed": False, "model_training_performed": False,
        "files": files, "data_files": data_files,
        "frozen_parameters": {
            "runtime_image": base.IMAGE, "runtime_digest": base.DIGEST,
            "lookahead_timerange": "20240101-20260101",
            "lookahead_pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
            "minimum_trade_amount": 100, "targeted_trade_amount": 120,
            "transient_market_entry_price_side": "other",
            "transient_market_exit_price_side": "other",
            "transient_order_book_pricing": False,
            "trading_config_changed": False, "private_api_transport": False,
            "train_timerange": "20220101-20240101",
        },
        "artifacts": artifacts,
        "technical_evidence": {"recursive_analysis": "PASS_FROM_CYCLE1", "lookahead_analysis": "PENDING_RETRY"},
        "active_strategies_changed": False, "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
    }
    ledger = {
        "schema_version": "1.0", "cycle": "pro_day_v4_cycle2", "candidate": "ProDayTraderV4",
        "created_at_utc": locked, "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"], "config_sha256": files["config"]["sha256"],
        "qualification_runs": [{"kind": "PRE_PNL_RECURSIVE_ANALYSIS", "status": "PASS_REFERENCED_CYCLE1",
                                "report_sha256": HASHES["recursive_pass"], "pnl_parsed": False}],
        "parameter_trials": [], "pnl_parsed": False,
        "post_result_edits_allowed": False, "live_trading_authorized": False,
    }
    if write_output:
        if (root / OUTPUT).exists() or (root / LEDGER).exists():
            raise base.FreezeError("Cycle 2 manifest or ledger exists")
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
