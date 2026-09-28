#!/usr/bin/env python3
"""Freeze the selected Cycle 3 candidate before Freqtrade PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_cross_cycle3"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    inputs = {
        "plan": ROOT / "docs/profit_max_daily_cross_cycle3_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalV3.py",
        "stop_parent": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectionalV2.py",
        "signal_parent": ROOT / "user_data/strategies/ProfitMaxDailyCrossSectional.py",
        "rank_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "risk": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "overlay_config": ROOT / "user_data/config-profit-max-daily-cross-cycle3-overlay.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "data_quality": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "universe": ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json",
        "screen": ROOT / "user_data/reports/profit_max_daily_cross_cycle3_screen/train_screen.json",
        "screen_tool": ROOT / "tools/screen_profit_max_daily_cross_cycle3.py",
        "cycle2_decision": ROOT / "user_data/reports/profit_max_daily_cross_cycle2/train_decision.json",
        "cycle2_post_failure": ROOT / "user_data/reports/profit_max_daily_cross_cycle2/post_failure_stop20_no_protections/backtest-result-2026-08-17_14-44-38.zip",
        "tests": ROOT / "tools/test_profit_max_daily_cross_sectional_v3.py",
        "freeze_tool": Path(__file__),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    screen = json.loads(inputs["screen"].read_text(encoding="utf-8"))
    overlay = json.loads(inputs["overlay_config"].read_text(encoding="utf-8"))
    base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
    decision = json.loads(inputs["cycle2_decision"].read_text(encoding="utf-8"))
    passers = [row for row in screen["results"] if row["pass"]]
    meta = overlay["profit_max_research"]
    expected = "base_0_12_bonus_16_breadth70"
    data_files = sorted(DATA.glob("*-4h-futures.feather"))
    if not (
        len(data_files) == 50
        and len(passers) == 1 and passers[0]["candidate"] == expected
        and screen["validation_used_for_selection"] is False
        and decision["decision"] == "KEEP_OFFLINE_RESEARCH"
        and decision["validation_revealed"] is False
        and base["fee"] == 0.00075 and base["dry_run"] is True
        and overlay["strategy"] == "ProfitMaxDailyCrossBreadthBonus"
        and overlay["max_open_trades"] == 2 and overlay["stake_amount"] == 50
        and meta["selected_screen_candidate"] == expected
        and meta["base_signal_hours_utc"] == [8, 20]
        and meta["bonus_signal_hour_utc"] == 12
        and meta["bonus_breadth_minimum"] == 0.70
        and meta["stoploss"] == -0.20 and meta["protection_plugins"] == []
        and meta["leverage"] == 1 and meta["live_trading_authorized"] is False
    ):
        print("FREEZE_BLOCKED: selection/execution contract failed", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_cross_cycle3",
        "status": "RESEARCH_FROZEN_BEFORE_PNL", "selected": "ProfitMaxDailyCrossBreadthBonus",
        "pnl_parsed": False, "validation_revealed": False, "live_trading_authorized": False,
        "fee_per_side": 0.00075,
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "data_files": [{"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for path in data_files],
        "artifacts": {"train_results": "user_data/reports/profit_max_daily_cross_cycle3/train_results", "train_decision": "user_data/reports/profit_max_daily_cross_cycle3/train_decision.json"},
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
