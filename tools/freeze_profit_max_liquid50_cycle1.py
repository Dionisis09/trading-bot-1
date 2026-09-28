#!/usr/bin/env python3
"""Freeze Liquid50 Cycle 1 inputs before the first performance run."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "user_data/reports/profit_max_liquid50_cycle1"
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DATA_ROOT = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"
RUNTIME = (
    "freqtradeorg/freqtrade:2026.7@"
    "sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def blocked(message: str) -> int:
    print(f"FREEZE_BLOCKED: {message}", file=sys.stderr)
    return 2


def main() -> int:
    inputs = {
        "locked_plan": ROOT / "docs/profit_max_liquid50_cycle1_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxLiquid50V1.py",
        "qualified_strategy": ROOT / "user_data/strategies/ProfitMaxSwingV5.py",
        "risk_overlay": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "signal_parent_v1": ROOT / "user_data/strategies/DualTrendFuturesV1.py",
        "signal_parent_v2": ROOT / "user_data/strategies/DualTrendFuturesV2.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "risk_policy": ROOT / "user_data/risk_policy.json",
        "universe_selector": ROOT / "tools/select_profit_max_liquid_universe.py",
        "universe_selection": REPORT_DIR / "universe_selection.json",
        "data_auditor": ROOT / "tools/audit_profit_max_liquid50_data.py",
        "data_quality": REPORT_DIR / "data_quality.json",
        "strategy_tests": ROOT / "tools/test_profit_max_liquid50_v1.py",
        "prior_technical_qualification": ROOT / "user_data/reports/profit_max_swing_cycle5/technical_qualification.json",
        "prior_tournament": ROOT / "user_data/reports/profit_max_swing_cycle5/tournament.json",
        "prior_execution_stress": ROOT / "user_data/reports/profit_max_swing_cycle5/execution_stress.json",
        "freeze_tool": Path(__file__).resolve(),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            return blocked(f"missing or unsafe {label}: {path}")

    try:
        config = json.loads(inputs["config"].read_text(encoding="utf-8"))
        universe = json.loads(inputs["universe_selection"].read_text(encoding="utf-8"))
        audit = json.loads(inputs["data_quality"].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return blocked(f"invalid JSON input: {exc}")

    selected_pairs = [row.get("freqtrade_pair") for row in universe.get("selected", [])]
    metadata = config.get("profit_max_research") or {}
    exchange = config.get("exchange") or {}
    safe = (
        universe.get("status") == "FROZEN_BEFORE_DATA_AND_PNL"
        and len(selected_pairs) == 50
        and len(set(selected_pairs)) == 50
        and exchange.get("pair_whitelist") == selected_pairs
        and config.get("strategy") == "ProfitMaxLiquid50V1"
        and config.get("dry_run") is True
        and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "4h"
        and config.get("fee") == 0.00075
        and config.get("max_open_trades") == 5
        and config.get("stake_amount") == 50
        and config.get("dry_run_wallet") == 1000
        and metadata.get("train_timerange") == "20210101-20240101"
        and metadata.get("validation_timerange") == "20240101-20260101"
        and metadata.get("current_partial_timerange") == "20260101-20260801"
        and metadata.get("continuous_timerange") == "20210101-20260801"
        and metadata.get("target_trades_per_day_min") == 1.0
        and metadata.get("target_trades_per_day_max") == 2.0
        and metadata.get("leverage") == 1
        and metadata.get("live_trading_authorized") is False
        and not str(exchange.get("key") or "").strip()
        and not str(exchange.get("secret") or "").strip()
    )
    if not safe:
        return blocked("config, universe, fee, frequency, or safety contract mismatch")
    if (
        audit.get("status") != "PASS"
        or audit.get("pnl_evaluated") is not False
        or audit.get("summary") != {"pairs": 50, "files_passed": 200, "files_failed": 0}
        or audit.get("universe_sha256") != digest(inputs["universe_selection"])
        or audit.get("config_sha256") != digest(inputs["config"])
        or audit.get("code_sha256") != digest(inputs["data_auditor"])
    ):
        return blocked("data audit is not a current pre-PnL PASS")

    audited = audit.get("files") or []
    if len(audited) != 200:
        return blocked(f"expected 200 audited files, found {len(audited)}")
    data_files = []
    seen = set()
    for row in audited:
        relative = row.get("path")
        if not isinstance(relative, str) or relative in seen:
            return blocked("invalid or duplicate audited data path")
        seen.add(relative)
        path = ROOT / relative
        try:
            path.relative_to(DATA_ROOT)
        except ValueError:
            return blocked(f"data path outside frozen root: {relative}")
        if not path.is_file() or path.is_symlink():
            return blocked(f"missing or unsafe audited data file: {relative}")
        sha256 = digest(path)
        if row.get("sha256") != sha256 or row.get("status") != "PASS":
            return blocked(f"data hash/status drift: {relative}")
        data_files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256})

    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_liquid50_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "pnl_parsed": False,
        "live_trading_authorized": False,
        "candidate": "ProfitMaxLiquid50V1",
        "runtime": RUNTIME,
        "baseline_fee_per_side": 0.00075,
        "minimum_roundtrip_fee": 0.0015,
        "frequency_gate_trades_per_day": {"minimum": 1.0, "maximum": 2.0},
        "splits": {
            "train": "20210101-20240101",
            "validation": "20240101-20260101",
            "current_partial": "20260101-20260801",
            "continuous": "20210101-20260801",
        },
        "files": {
            label: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for label, path in sorted(inputs.items())
        },
        "data_files": sorted(data_files, key=lambda row: row["path"]),
        "artifacts": {
            "train": "user_data/reports/profit_max_liquid50_cycle1/train.zip",
            "validation": "user_data/reports/profit_max_liquid50_cycle1/validation.zip",
            "current_partial": "user_data/reports/profit_max_liquid50_cycle1/current_partial.zip",
            "continuous": "user_data/reports/profit_max_liquid50_cycle1/continuous.zip",
        },
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
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
