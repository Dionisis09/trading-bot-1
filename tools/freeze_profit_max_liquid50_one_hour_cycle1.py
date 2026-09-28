#!/usr/bin/env python3
"""Freeze all Liquid50 1h Cycle 1 inputs before any PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_liquid50_one_hour_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_one_hour_cycle1_source/futures"
CANDIDATES = ["ProfitMaxLiquid50OneHour30", "ProfitMaxLiquid50OneHour60", "ProfitMaxLiquid50OneHour120"]
RUNTIME = "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def fail(message: str) -> int:
    print(f"FREEZE_BLOCKED: {message}", file=sys.stderr)
    return 2


def main() -> int:
    inputs = {
        "locked_plan": ROOT / "docs/profit_max_liquid50_1h_cycle1_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxLiquid50OneHour.py",
        "qualified_strategy": ROOT / "user_data/strategies/ProfitMaxSwingV5.py",
        "risk_overlay": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "signal_parent_v1": ROOT / "user_data/strategies/DualTrendFuturesV1.py",
        "signal_parent_v2": ROOT / "user_data/strategies/DualTrendFuturesV2.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "config": ROOT / "user_data/config-profit-max-liquid50-one-hour-cycle1.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "universe_selection": ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json",
        "data_auditor": ROOT / "tools/audit_profit_max_liquid50_one_hour_data.py",
        "data_quality": REPORT / "data_quality.json",
        "strategy_tests": ROOT / "tools/test_profit_max_liquid50_one_hour.py",
        "prior_cycle_manifest": ROOT / "user_data/reports/profit_max_liquid50_cycle1/research_freeze_manifest.json",
        "prior_cycle_decision": ROOT / "user_data/reports/profit_max_liquid50_cycle1/train_decision.json",
        "freeze_tool": Path(__file__).resolve(),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            return fail(f"missing or unsafe {label}: {path}")
    try:
        config = json.loads(inputs["config"].read_text(encoding="utf-8"))
        audit = json.loads(inputs["data_quality"].read_text(encoding="utf-8"))
        universe = json.loads(inputs["universe_selection"].read_text(encoding="utf-8"))
        prior = json.loads(inputs["prior_cycle_decision"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"invalid JSON input: {exc}")
    pairs = [row["freqtrade_pair"] for row in universe.get("selected", [])]
    meta = config.get("profit_max_research") or {}
    exchange = config.get("exchange") or {}
    safe = (
        prior.get("decision") == "KEEP_OFFLINE_RESEARCH" and prior.get("validation_revealed") is False
        and audit.get("status") == "PASS" and audit.get("pnl_evaluated") is False
        and audit.get("summary") == {"pairs": 50, "files_passed": 200, "files_failed": 0}
        and audit.get("universe_sha256") == digest(inputs["universe_selection"])
        and audit.get("config_sha256") == digest(inputs["config"])
        and audit.get("code_sha256") == digest(inputs["data_auditor"])
        and len(pairs) == 50 and len(set(pairs)) == 50 and exchange.get("pair_whitelist") == pairs
        and config.get("dry_run") is True and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated" and config.get("timeframe") == "1h"
        and config.get("fee") == 0.00075 and config.get("max_open_trades") == 5
        and config.get("stake_amount") == 50 and config.get("dry_run_wallet") == 1000
        and meta.get("train_timerange") == "20210101-20240101"
        and meta.get("validation_timerange") == "20240101-20260101"
        and meta.get("current_partial_timerange") == "20260101-20260801"
        and meta.get("continuous_timerange") == "20210101-20260801"
        and meta.get("target_trades_per_day_min") == 1.0 and meta.get("target_trades_per_day_max") == 2.0
        and meta.get("leverage") == 1 and meta.get("protections_enabled_in_backtest") is True
        and meta.get("live_trading_authorized") is False
        and not str(exchange.get("key") or "").strip() and not str(exchange.get("secret") or "").strip()
    )
    if not safe:
        return fail("pre-PnL data/config/prior-cycle contract mismatch")

    audited = audit.get("files") or []
    disk = sorted(path for path in DATA.glob("*.feather") if path.is_file() and not path.is_symlink())
    if len(audited) != 200 or len(disk) != 200:
        return fail(f"expected 200 audited and disk files; got {len(audited)} and {len(disk)}")
    audited_by_path = {row["path"]: row for row in audited}
    data_files = []
    for path in disk:
        relative = path.relative_to(ROOT).as_posix()
        row = audited_by_path.get(relative)
        sha = digest(path)
        if row is None or row.get("status") != "PASS" or row.get("sha256") != sha:
            return fail(f"data audit/hash drift: {relative}")
        data_files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha})

    payload = {
        "schema_version": "1.0", "cycle": "profit_max_liquid50_one_hour_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_PNL", "pnl_parsed": False,
        "live_trading_authorized": False, "candidates": CANDIDATES,
        "runtime": RUNTIME, "protections_enabled": True,
        "baseline_fee_per_side": 0.00075, "minimum_roundtrip_fee": 0.0015,
        "frequency_gate_trades_per_day": {"minimum": 1.0, "maximum": 2.0},
        "splits": {"train": "20210101-20240101", "validation": "20240101-20260101",
                   "current_partial": "20260101-20260801", "continuous": "20210101-20260801"},
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
                  for label, path in sorted(inputs.items())},
        "data_files": data_files,
        "artifacts": {"train": "user_data/reports/profit_max_liquid50_one_hour_cycle1/train.zip",
                      "validation": "user_data/reports/profit_max_liquid50_one_hour_cycle1/validation.zip",
                      "current_partial": "user_data/reports/profit_max_liquid50_one_hour_cycle1/current_partial.zip",
                      "continuous": "user_data/reports/profit_max_liquid50_one_hour_cycle1/continuous.zip"},
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
