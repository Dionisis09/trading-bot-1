#!/usr/bin/env python3
"""Freeze the selected daily cross-sectional candidate before Freqtrade PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_cross_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA_DIR = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_cross_cycle1_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectional.py",
        "strategy_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "risk": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "overlay_config": ROOT / "user_data/config-profit-max-daily-cross-cycle1-overlay.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "data_quality": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "universe": ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json",
        "diagnostic_screen": ROOT / "user_data/reports/profit_max_daily_cross_screening/train_screen.json",
        "screen_tool": ROOT / "tools/screen_profit_max_daily_cross_sectional.py",
        "tests": ROOT / "tools/test_profit_max_daily_cross_sectional.py",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    data_files = sorted(DATA_DIR.glob("*-4h-futures.feather"))
    if len(data_files) != 50 or any(path.is_symlink() for path in data_files):
        print("FREEZE_BLOCKED: exact 50-file data contract failed", file=sys.stderr)
        return 2
    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    overlay = json.loads(inputs["overlay_config"].read_text(encoding="utf-8"))
    quality = json.loads(inputs["data_quality"].read_text(encoding="utf-8"))
    screen = json.loads(inputs["diagnostic_screen"].read_text(encoding="utf-8"))
    meta = overlay.get("profit_max_research") or {}
    passers = [row for row in screen.get("results", []) if row.get("diagnostic_pass") is True]
    expected = "mom7d_0-12_8h_leader_long_btc30_positive"
    if not (
        quality.get("status") == "PASS"
        and screen.get("validation_used_for_selection") is False
        and len(passers) == 1
        and passers[0].get("candidate") == expected
        and base.get("dry_run") is True
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and base.get("fee") == 0.00075
        and overlay.get("strategy") == "ProfitMaxDailyCrossSectional"
        and overlay.get("max_open_trades") == 2
        and overlay.get("stake_amount") == 50
        and meta.get("momentum_candles") == 42
        and meta.get("btc_gate_candles") == 180
        and meta.get("signal_hours_utc") == [8, 20]
        and meta.get("hold_hours") == 8
        and meta.get("leverage") == 1
        and meta.get("live_trading_authorized") is False
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
    ):
        print("FREEZE_BLOCKED: selection/execution/data contract failed", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_daily_cross_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "selected_candidate": expected,
        "pnl_parsed": False,
        "validation_revealed": False,
        "live_trading_authorized": False,
        "fee_per_side": 0.00075,
        "splits": {
            "train": "20210101-20240101",
            "validation": "20240101-20260101",
            "current_partial": "20260101-20260801",
        },
        "files": {
            label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
            for label, path in sorted(inputs.items())
        },
        "data_files": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for path in data_files
        ],
        "artifacts": {
            "train_results": "user_data/reports/profit_max_daily_cross_cycle1/train_results",
            "train_archive": "user_data/reports/profit_max_daily_cross_cycle1/train.zip",
            "train_decision": "user_data/reports/profit_max_daily_cross_cycle1/train_decision.json",
        },
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    with MANIFEST.open("xb") as handle:
        handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
