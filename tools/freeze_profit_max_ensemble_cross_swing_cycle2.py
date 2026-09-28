#!/usr/bin/env python3
"""Freeze the corrected ensemble cycle before its TRAIN run."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_ensemble_cross_swing_cycle2"
MANIFEST = REPORT / "research_freeze_manifest.json"
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"
CANDIDATE = "ProfitMaxEnsembleCrossSwingV2"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    inputs = {
        "cycle1_plan": ROOT / "docs/profit_max_ensemble_cross_swing_cycle1_locked_plan.md",
        "locked_plan": ROOT / "docs/profit_max_ensemble_cross_swing_cycle2_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxEnsembleCrossSwingV2.py",
        "strategy_parent": ROOT / "user_data/strategies/ProfitMaxEnsembleCrossSwing.py",
        "swing_parent": ROOT / "user_data/strategies/DualTrendFuturesV2.py",
        "rank_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "risk_overlay": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "overlay_config": ROOT / "user_data/config-profit-max-ensemble-cross-swing-cycle2-overlay.json",
        "risk_policy": ROOT / "user_data/risk_policy_ensemble_cross_swing.json",
        "strategy_parent_tests": ROOT / "tools/test_profit_max_ensemble_cross_swing.py",
        "strategy_tests": ROOT / "tools/test_profit_max_ensemble_cross_swing_v2.py",
        "universe_selection": ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json",
        "data_quality": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "data_auditor": ROOT / "tools/audit_profit_max_liquid50_data.py",
        "cycle1_manifest": ROOT / "user_data/reports/profit_max_ensemble_cross_swing_cycle1/research_freeze_manifest.json",
        "cycle1_technical_failure": ROOT / "user_data/reports/profit_max_ensemble_cross_swing_cycle1/technical_failure.json",
        "freeze_tool": Path(__file__).resolve(),
    }
    for label, path in inputs.items():
        if not path.is_file() or path.is_symlink():
            print(f"FREEZE_BLOCKED: missing or unsafe {label}: {path}", file=sys.stderr)
            return 2
    try:
        base = json.loads(inputs["base_config"].read_text(encoding="utf-8"))
        overlay = json.loads(inputs["overlay_config"].read_text(encoding="utf-8"))
        policy = json.loads(inputs["risk_policy"].read_text(encoding="utf-8"))
        audit = json.loads(inputs["data_quality"].read_text(encoding="utf-8"))
        failure = json.loads(inputs["cycle1_technical_failure"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FREEZE_BLOCKED: invalid JSON: {exc}", file=sys.stderr)
        return 2
    meta = overlay.get("profit_max_research") or {}
    limits = policy.get("limits") or {}
    safe = (
        failure.get("status") == "TECHNICAL_FAILURE" and failure.get("pnl_valid") is False
        and failure.get("validation_revealed") is False
        and audit.get("status") == "PASS" and audit.get("pnl_evaluated") is False
        and audit.get("code_sha256") == digest(inputs["data_auditor"])
        and base.get("dry_run") is True and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated" and base.get("timeframe") == "4h"
        and base.get("fee") == 0.00075 and base.get("dry_run_wallet") == 1000
        and len((base.get("exchange") or {}).get("pair_whitelist") or []) == 50
        and overlay.get("strategy") == CANDIDATE and overlay.get("stake_amount") == 50
        and overlay.get("max_open_trades") == 3
        and meta.get("train_timerange") == "20210101-20240101"
        and meta.get("validation_timerange") == "20240101-20260101"
        and meta.get("current_partial_timerange") == "20260101-20260801"
        and meta.get("continuous_timerange") == "20210101-20260801"
        and meta.get("target_trades_per_day_min") == 1.0
        and meta.get("target_trades_per_day_max") == 2.0
        and meta.get("live_trading_authorized") is False
        and limits.get("maximum_open_trades") == 3
        and limits.get("maximum_total_open_stake_pct") == 20.0
        and (policy.get("live_launch") or {}).get("authorized") is False
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
    )
    if not safe:
        print("FREEZE_BLOCKED: contract mismatch", file=sys.stderr)
        return 2
    audited = {row["path"]: row for row in audit.get("files", [])}
    disk = sorted(path for path in DATA.glob("*.feather") if path.is_file() and not path.is_symlink())
    if len(audited) != 200 or len(disk) != 200:
        print("FREEZE_BLOCKED: expected exact 200-file inventory", file=sys.stderr)
        return 2
    data_files = []
    for path in disk:
        relative = path.relative_to(ROOT).as_posix()
        sha = digest(path)
        if audited.get(relative, {}).get("sha256") != sha or audited[relative].get("status") != "PASS":
            print(f"FREEZE_BLOCKED: data drift: {relative}", file=sys.stderr)
            return 2
        data_files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha})
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_ensemble_cross_swing_cycle2",
        "status": "RESEARCH_FROZEN_BEFORE_PNL",
        "pnl_parsed": False,
        "live_trading_authorized": False,
        "candidates": [CANDIDATE],
        "runtime": "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643",
        "protections_enabled": True,
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
            label: {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
            for label, path in sorted(inputs.items())
        },
        "data_files": data_files,
        "artifacts": {
            "train": "user_data/reports/profit_max_ensemble_cross_swing_cycle2/train.zip",
            "validation": "user_data/reports/profit_max_ensemble_cross_swing_cycle2/validation.zip",
            "current_partial": "user_data/reports/profit_max_ensemble_cross_swing_cycle2/current_partial.zip",
            "continuous": "user_data/reports/profit_max_ensemble_cross_swing_cycle2/continuous.zip",
        },
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    try:
        with MANIFEST.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    except FileExistsError:
        print(f"FREEZE_BLOCKED: manifest exists: {MANIFEST}", file=sys.stderr)
        return 3
    print(json.dumps({"status": payload["status"], "data_files": len(data_files), "sha256": digest(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
