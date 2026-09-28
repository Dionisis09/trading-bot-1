#!/usr/bin/env python3
"""Freeze complete V2R base-config correction before any V2R PnL."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle3"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    inputs = {
        "cycle1_manifest": ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1/research_freeze_manifest.json",
        "cycle2_manifest": ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle2/technical_freeze_manifest.json",
        "addendum": ROOT / "docs/profit_max_daily_v5_v2r_ensemble_cycle3_technical_addendum.md",
        "complete_v2r_base": ROOT / "user_data/config-profit-max-v2r-dry-run.json",
        "v2r_overlay": ROOT / "user_data/config-profit-max-v2r-fee075-overlay.json",
        "freeze_tool": Path(__file__),
    }
    if not all(path.is_file() and not path.is_symlink() for path in inputs.values()):
        print("FREEZE_BLOCKED: technical inputs missing or unsafe", file=sys.stderr)
        return 2
    cycle1_dir = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle1/v2r_results"
    cycle2_dir = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle2/v2r_results"
    if any(directory.is_dir() and any(directory.iterdir()) for directory in (cycle1_dir, cycle2_dir)):
        print("FREEZE_BLOCKED: prior V2R output exists", file=sys.stderr)
        return 2
    base = json.loads(inputs["complete_v2r_base"].read_text(encoding="utf-8"))
    overlay = json.loads(inputs["v2r_overlay"].read_text(encoding="utf-8"))
    pairs = (base.get("exchange") or {}).get("pair_whitelist") or []
    if not (base.get("dry_run_wallet") == 1000 and base.get("trading_mode") == "futures" and base.get("margin_mode") == "isolated" and base.get("timeframe") == "4h" and len(pairs) == 6 and base.get("pairlists") == [{"method": "StaticPairList"}]):
        print("FREEZE_BLOCKED: complete base semantic mismatch", file=sys.stderr)
        return 2
    if overlay.get("stake_amount") != 25 or overlay.get("fee") != 0.00075:
        print("FREEZE_BLOCKED: allocation/fee mismatch", file=sys.stderr)
        return 2
    if REPORT.exists():
        print("FREEZE_BLOCKED: output exists", file=sys.stderr)
        return 3
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_daily_v5_v2r_ensemble_cycle3",
        "status": "COMPLETE_BASE_CORRECTION_FROZEN_BEFORE_PNL",
        "files": {label: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for label, path in sorted(inputs.items())},
        "live_trading_authorized": False,
        "artifacts": {
            "v2r_results": "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle3/v2r_results",
            "decision": "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle3/decision.json"
        }
    }
    REPORT.mkdir(parents=True, exist_ok=False)
    manifest = REPORT / "technical_freeze_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sha256": digest(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
