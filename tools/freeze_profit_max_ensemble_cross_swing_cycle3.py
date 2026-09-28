#!/usr/bin/env python3
"""Freeze Ensemble Cross-Swing Cycle 3 before PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_ensemble_cross_swing_cycle3"
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"
CANDIDATES = ["ProfitMaxEnsembleCrossSwingV3Global", "ProfitMaxEnsembleCrossSwingV3PairGuard"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    files = {
        "plan": ROOT / "docs/profit_max_ensemble_cross_swing_cycle3_locked_plan.md",
        "strategy": ROOT / "user_data/strategies/ProfitMaxEnsembleCrossSwingV3.py",
        "ensemble_parent": ROOT / "user_data/strategies/ProfitMaxEnsembleCrossSwing.py",
        "swing_parent": ROOT / "user_data/strategies/DualTrendFuturesV2.py",
        "rank_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "risk_overlay": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "base_config": ROOT / "user_data/config-profit-max-liquid50-cycle1.json",
        "overlay": ROOT / "user_data/config-profit-max-ensemble-cross-swing-cycle3-overlay.json",
        "risk_policy": ROOT / "user_data/risk_policy_ensemble_cross_swing_4.json",
        "tests": ROOT / "tools/test_profit_max_ensemble_cross_swing_v3.py",
        "parent_tests": ROOT / "tools/test_profit_max_ensemble_cross_swing.py",
        "evaluator": ROOT / "tools/finalize_profit_max_core_train.py",
        "data_audit": ROOT / "user_data/reports/profit_max_liquid50_cycle1/data_quality.json",
        "prior_decision": ROOT / "user_data/reports/profit_max_ensemble_cross_swing_cycle2/train_decision.json",
        "swing_exact_fee": ROOT / "user_data/reports/profit_max_swing_cycle5/exact_fee_075_verification.json",
        "freeze": Path(__file__).resolve(),
    }
    if any(not path.is_file() or path.is_symlink() for path in files.values()):
        print("FREEZE_BLOCKED: missing or unsafe input", file=sys.stderr)
        return 2
    base = json.loads(files["base_config"].read_text(encoding="utf-8"))
    overlay = json.loads(files["overlay"].read_text(encoding="utf-8"))
    policy = json.loads(files["risk_policy"].read_text(encoding="utf-8"))
    audit = json.loads(files["data_audit"].read_text(encoding="utf-8"))
    prior = json.loads(files["prior_decision"].read_text(encoding="utf-8"))
    swing = json.loads(files["swing_exact_fee"].read_text(encoding="utf-8"))
    meta = overlay.get("profit_max_research") or {}
    if not (
        base.get("dry_run") is True and base.get("fee") == 0.00075
        and base.get("trading_mode") == "futures" and base.get("margin_mode") == "isolated"
        and len((base.get("exchange") or {}).get("pair_whitelist") or []) == 50
        and overlay.get("strategy") == CANDIDATES[0] and overlay.get("max_open_trades") == 4
        and overlay.get("stake_amount") == 50
        and meta.get("train_timerange") == "20210101-20240101"
        and meta.get("validation_timerange") == "20240101-20260101"
        and meta.get("target_trades_per_day_min") == 1.0 and meta.get("target_trades_per_day_max") == 2.0
        and meta.get("live_trading_authorized") is False
        and (policy.get("limits") or {}).get("maximum_open_trades") == 4
        and (policy.get("limits") or {}).get("maximum_total_open_stake_pct") == 20.0
        and (policy.get("live_launch") or {}).get("authorized") is False
        and audit.get("status") == "PASS" and audit.get("pnl_evaluated") is False
        and prior.get("decision") == "KEEP_OFFLINE_RESEARCH" and prior.get("validation_revealed") is False
        and swing.get("status") == "PASS_HISTORICAL_COST_DIAGNOSTIC"
        and swing.get("fee_per_side") == 0.00075 and swing.get("live_trading_authorized") is False
        and not str((base.get("exchange") or {}).get("key") or "").strip()
        and not str((base.get("exchange") or {}).get("secret") or "").strip()
    ):
        print("FREEZE_BLOCKED: contract mismatch", file=sys.stderr)
        return 2
    audited = {row["path"]: row for row in audit.get("files", [])}
    disk = sorted(DATA.glob("*.feather"))
    if len(disk) != 200 or len(audited) != 200:
        print("FREEZE_BLOCKED: inventory mismatch", file=sys.stderr)
        return 2
    data_files = []
    for path in disk:
        relative = path.relative_to(ROOT).as_posix()
        sha = digest(path)
        if path.is_symlink() or audited.get(relative, {}).get("sha256") != sha:
            print(f"FREEZE_BLOCKED: data drift {relative}", file=sys.stderr)
            return 2
        data_files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha})
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_ensemble_cross_swing_cycle3",
        "status": "RESEARCH_FROZEN_BEFORE_PNL", "pnl_parsed": False,
        "live_trading_authorized": False, "candidates": CANDIDATES,
        "runtime": "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643",
        "protections_enabled": True, "baseline_fee_per_side": 0.00075, "minimum_roundtrip_fee": 0.0015,
        "frequency_gate_trades_per_day": {"minimum": 1.0, "maximum": 2.0},
        "splits": {"train": "20210101-20240101", "validation": "20240101-20260101",
                   "current_partial": "20260101-20260801", "continuous": "20210101-20260801"},
        "files": {name: {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
                  for name, path in sorted(files.items())},
        "data_files": data_files,
        "artifacts": {"train": "user_data/reports/profit_max_ensemble_cross_swing_cycle3/train.zip",
                      "validation": "user_data/reports/profit_max_ensemble_cross_swing_cycle3/validation.zip",
                      "current_partial": "user_data/reports/profit_max_ensemble_cross_swing_cycle3/current_partial.zip",
                      "continuous": "user_data/reports/profit_max_ensemble_cross_swing_cycle3/continuous.zip"},
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    manifest = REPORT / "research_freeze_manifest.json"
    try:
        with manifest.open("xb") as stream:
            stream.write((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    except FileExistsError:
        print("FREEZE_BLOCKED: manifest exists", file=sys.stderr)
        return 3
    print(json.dumps({"status": payload["status"], "data_files": len(data_files), "sha256": digest(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
