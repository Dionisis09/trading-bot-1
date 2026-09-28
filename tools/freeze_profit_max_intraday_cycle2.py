#!/usr/bin/env python3
"""Freeze all ProfitMaxIntraday Cycle 2 inputs before its only TRAIN PnL run."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "user_data/reports/profit_max_intraday_cycle2"
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DATA_ROOT = ROOT / "user_data/data/binance/profit_max_intraday_cycle1_canonical/futures"
CYCLE1_REPORT_DIR = ROOT / "user_data/reports/profit_max_intraday_cycle1"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_intraday_cycle2_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxIntradayV2.py",
        "parent_strategy": ROOT / "user_data/strategies/ProfitMaxIntradayV1.py",
        "root_strategy": ROOT / "user_data/strategies/ProTournament15m.py",
        "base_config": ROOT / "user_data/config-profit-max-intraday-cycle1.json",
        "config_override": ROOT / "user_data/config-profit-max-intraday-cycle2-override.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "strategy_tests": ROOT / "tools/test_profit_max_intraday_v2.py",
        "data_builder": ROOT / "tools/build_profit_max_intraday_data.py",
        "data_audit": CYCLE1_REPORT_DIR / "canonical_data_audit.json",
        "cycle1_freeze_manifest": CYCLE1_REPORT_DIR / "research_freeze_manifest.json",
        "cycle1_train_decision": CYCLE1_REPORT_DIR / "train_decision.json",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2

    audit = json.loads(inputs["data_audit"].read_text(encoding="utf-8"))
    cycle1_freeze = json.loads(inputs["cycle1_freeze_manifest"].read_text(encoding="utf-8"))
    cycle1_decision = json.loads(inputs["cycle1_train_decision"].read_text(encoding="utf-8"))
    base_config = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    override = json.loads(inputs["config_override"].read_text(encoding="utf-8"))

    if audit.get("status") != "PASS" or audit.get("pnl_evaluated") is not False:
        print("FREEZE_BLOCKED: canonical data audit is not pre-PnL PASS", file=sys.stderr)
        return 2
    if cycle1_freeze.get("status") != "RESEARCH_FROZEN_BEFORE_PNL":
        print("FREEZE_BLOCKED: Cycle 1 freeze evidence is invalid", file=sys.stderr)
        return 2
    if cycle1_decision.get("status") != "FAIL" or cycle1_decision.get("validation_revealed") is not False:
        print("FREEZE_BLOCKED: Cycle 1 terminal decision is not the expected TRAIN failure", file=sys.stderr)
        return 2

    pairs = ((base_config.get("exchange") or {}).get("pair_whitelist") or [])
    expected_pairs = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "BNB/USDT:USDT",
        "XRP/USDT:USDT",
        "ADA/USDT:USDT",
        "DOGE/USDT:USDT",
    ]
    base_metadata = base_config.get("profit_max_intraday_research") or {}
    override_metadata = override.get("profit_max_intraday_research") or {}
    safe = (
        base_config.get("dry_run") is True
        and base_config.get("trading_mode") == "futures"
        and base_config.get("margin_mode") == "isolated"
        and base_config.get("fee") == 0.00075
        and base_config.get("max_open_trades") == 3
        and base_config.get("stake_amount") == 75
        and pairs == expected_pairs
        and base_metadata.get("target_trades_per_day_min") == 1.0
        and base_metadata.get("target_trades_per_day_max") == 2.0
        and base_metadata.get("live_trading_authorized") is False
        and override_metadata.get("cycle") == "profit_max_intraday_cycle2"
        and override_metadata.get("status") == "LOCKED_BEFORE_CYCLE2_PNL"
        and override_metadata.get("target_trades_per_day_min") == 1.0
        and override_metadata.get("target_trades_per_day_max") == 2.0
        and override_metadata.get("live_trading_authorized") is False
        and not str((base_config.get("exchange") or {}).get("key") or "").strip()
        and not str((base_config.get("exchange") or {}).get("secret") or "").strip()
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
        "cycle": "profit_max_intraday_cycle2",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "pnl_parsed": False,
        "live_trading_authorized": False,
        "baseline_fee_per_side": 0.00075,
        "minimum_roundtrip_fee": 0.0015,
        "frequency_gate_trades_per_day": {"minimum": 1.0, "maximum": 2.0},
        "candidates": [
            "ProfitMaxIntradayShortTight15m",
            "ProfitMaxIntradayShortBase15m",
            "ProfitMaxIntradayAsymmetric15m",
        ],
        "splits": {
            "train": "20220101-20240101",
            "validation": "20240101-20260101",
            "current_partial": "20260101-20260801",
        },
        "runtime": "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643",
        "parent_cycle": {
            "decision": "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": False,
            "fixed_hypothesis": "cycle1_short_breakout_exit_and_risk_handling",
        },
        "files": {
            label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
            for label, path in sorted(inputs.items())
        },
        "data_files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for path in data_files
        ],
        "artifacts": {
            "train": "user_data/reports/profit_max_intraday_cycle2/train.zip",
            "validation": "user_data/reports/profit_max_intraday_cycle2/validation.zip",
            "current_partial": "user_data/reports/profit_max_intraday_cycle2/current_partial.zip",
        },
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with MANIFEST.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        print(f"FREEZE_BLOCKED: manifest already exists: {MANIFEST}", file=sys.stderr)
        return 3
    print(json.dumps({"status": payload["status"], "data_files": len(data_files), "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
