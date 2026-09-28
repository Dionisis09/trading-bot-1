#!/usr/bin/env python3
"""Freeze all ProfitMaxIntraday Cycle 3 inputs before its only TRAIN PnL run."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "user_data/reports/profit_max_intraday_cycle3"
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DATA_ROOT = ROOT / "user_data/data/binance/profit_max_intraday_cycle1_canonical/futures"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main() -> int:
    cycle1 = ROOT / "user_data/reports/profit_max_intraday_cycle1"
    cycle2 = ROOT / "user_data/reports/profit_max_intraday_cycle2"
    inputs = {
        "plan": ROOT / "docs/profit_max_intraday_cycle3_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxIntradayV3.py",
        "parent_strategy": ROOT / "user_data/strategies/ProfitMaxIntradayV2.py",
        "root_strategy": ROOT / "user_data/strategies/ProfitMaxIntradayV1.py",
        "base_config": ROOT / "user_data/config-profit-max-intraday-cycle1.json",
        "config_override": ROOT / "user_data/config-profit-max-intraday-cycle3-override.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "strategy_tests": ROOT / "tools/test_profit_max_intraday_v3.py",
        "data_audit": cycle1 / "canonical_data_audit.json",
        "cycle1_freeze_manifest": cycle1 / "research_freeze_manifest.json",
        "cycle2_freeze_manifest": cycle2 / "research_freeze_manifest.json",
        "cycle2_train_decision": cycle2 / "train_decision.json",
        "cycle2_train_archive": cycle2 / "train.zip",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2

    audit = json.loads(inputs["data_audit"].read_text(encoding="utf-8"))
    decision = json.loads(inputs["cycle2_train_decision"].read_text(encoding="utf-8"))
    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    override = json.loads(inputs["config_override"].read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or audit.get("pnl_evaluated") is not False:
        print("FREEZE_BLOCKED: canonical data audit is invalid", file=sys.stderr)
        return 2
    if decision.get("status") != "FAIL" or decision.get("validation_revealed") is not False:
        print("FREEZE_BLOCKED: Cycle 2 is not a terminal TRAIN failure", file=sys.stderr)
        return 2
    metadata = override.get("profit_max_intraday_research") or {}
    pairs = ((base.get("exchange") or {}).get("pair_whitelist") or [])
    safe = (
        base.get("dry_run") is True
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and base.get("fee") == 0.00075
        and base.get("max_open_trades") == 3
        and base.get("stake_amount") == 75
        and len(pairs) == 6
        and metadata.get("cycle") == "profit_max_intraday_cycle3"
        and metadata.get("status") == "LOCKED_BEFORE_CYCLE3_PNL"
        and metadata.get("target_trades_per_day_min") == 1.0
        and metadata.get("target_trades_per_day_max") == 2.0
        and metadata.get("live_trading_authorized") is False
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
    )
    if not safe:
        print("FREEZE_BLOCKED: config safety/frequency/fee contract failed", file=sys.stderr)
        return 2

    data_files = sorted(path for path in DATA_ROOT.iterdir() if path.is_file() and not path.is_symlink())
    if len(data_files) != 30:
        print(f"FREEZE_BLOCKED: expected 30 canonical files, found {len(data_files)}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_intraday_cycle3",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "pnl_parsed": False,
        "live_trading_authorized": False,
        "baseline_fee_per_side": 0.00075,
        "minimum_roundtrip_fee": 0.0015,
        "frequency_gate_trades_per_day": {"minimum": 1.0, "maximum": 2.0},
        "candidates": [
            "ProfitMaxIntradayShortProfitOnly15m",
            "ProfitMaxIntradayShortBreakEven15m",
            "ProfitMaxIntradayShortProfitOnlyBreakEven15m",
        ],
        "splits": {
            "train": "20220101-20240101",
            "validation": "20240101-20260101",
            "current_partial": "20260101-20260801",
        },
        "runtime": "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643",
        "parent_cycle": {"decision": "KEEP_OFFLINE_RESEARCH", "validation_revealed": False},
        "files": {
            label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
            for label, path in sorted(inputs.items())
        },
        "data_files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in data_files
        ],
        "artifacts": {
            "train": "user_data/reports/profit_max_intraday_cycle3/train.zip",
            "validation": "user_data/reports/profit_max_intraday_cycle3/validation.zip",
            "current_partial": "user_data/reports/profit_max_intraday_cycle3/current_partial.zip",
        },
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
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
