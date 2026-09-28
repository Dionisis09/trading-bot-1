#!/usr/bin/env python3
"""Freeze the exchange-name-only technical correction before V2R PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parent = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1/research_freeze_manifest.json"
    correction = ROOT / "user_data/config-profit-max-v2r-exchange-fix-overlay.json"
    addendum = ROOT / "docs/profit_max_daily_v5_v2r_ensemble_cycle2_technical_addendum.md"
    if not all(path.is_file() and not path.is_symlink() for path in (parent, correction, addendum)):
        print("FREEZE_BLOCKED: technical inputs missing or unsafe", file=sys.stderr)
        return 2
    value = json.loads(correction.read_text(encoding="utf-8"))
    if value != {"exchange": {"name": "binance"}}:
        print("FREEZE_BLOCKED: correction exceeds exchange-name scope", file=sys.stderr)
        return 2
    v2r_dir = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1/v2r_results"
    if not v2r_dir.is_dir() or any(v2r_dir.iterdir()):
        print("FREEZE_BLOCKED: Cycle 1 V2R directory proves output or is missing", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_daily_v5_v2r_ensemble_cycle2",
        "status": "TECHNICAL_CORRECTION_FROZEN_BEFORE_PNL",
        "parent_manifest": {"path": parent.relative_to(ROOT).as_posix(), "sha256": digest(parent)},
        "addendum": {"path": addendum.relative_to(ROOT).as_posix(), "sha256": digest(addendum)},
        "exchange_overlay": {"path": correction.relative_to(ROOT).as_posix(), "sha256": digest(correction)},
        "live_trading_authorized": False,
        "artifacts": {
            "v2r_results": "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle2/v2r_results",
            "decision": "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle2/decision.json"
        }
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    manifest = REPORT / "technical_freeze_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
