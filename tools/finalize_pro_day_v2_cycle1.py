#!/usr/bin/env python3
"""Finalize the frozen V2 Cycle 1 after its pre-PnL recursive gate failed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("user_data/reports/pro_day_v2_cycle1/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v2_cycle1/trial_ledger.json")
OUTPUT = Path("user_data/reports/pro_day_v2_cycle1/final_decision.json")
REQUESTED_COUNTS = [199, 399, 799, 1599, 3199, 6399, 12799]


class FinalizationError(RuntimeError):
    pass


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"Invalid {label}") from exc
    if not isinstance(value, dict):
        raise FinalizationError(f"{label} must be an object")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def validate_frozen_state(manifest: Mapping[str, Any], root: Path = ROOT) -> None:
    expected = {
        "status": "RESEARCH_FROZEN",
        "candidate": "ProDayTraderV2",
        "cycle": "pro_day_v2_cycle1",
        "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False,
        "model_training_performed": False,
        "live_trading_authorized": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise FinalizationError(f"Frozen manifest {key} differs from expected pre-PnL state")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {
        "canonical", "train", "validation", "current_partial"
    }:
        raise FinalizationError("Frozen artifact inventory is incomplete")
    for label, record in artifacts.items():
        if not isinstance(record, Mapping) or record.get("status") != "PLANNED_NOT_RUN":
            raise FinalizationError(f"Artifact {label} is not in planned/not-run state")
        raw_path = record.get("path")
        if not isinstance(raw_path, str):
            raise FinalizationError(f"Artifact {label} path is invalid")
        if (root / raw_path).exists():
            raise FinalizationError(f"Artifact {label} exists despite the pre-PnL failure")


def build_decision(*, root: Path = ROOT, generated_at: str | None = None) -> dict[str, Any]:
    manifest_path = root / MANIFEST
    ledger_path = root / LEDGER
    manifest = _load(manifest_path, "freeze manifest")
    ledger = _load(ledger_path, "trial ledger")
    validate_frozen_state(manifest, root)
    if ledger.get("pnl_parsed") is not False or ledger.get("parameter_trials") != []:
        raise FinalizationError("Trial ledger contains PnL or parameter trials")
    model_root = root / "user_data/models/proday-v2-cycle1-canonical5m-lgbm-20260811"
    model_files = 0
    prediction_files = 0
    if model_root.is_dir():
        model_files = sum(1 for path in model_root.rglob("*_model.joblib") if path.is_file())
        prediction_files = sum(
            1 for path in model_root.rglob("*_prediction.feather") if path.is_file()
        )
    return {
        "schema_version": "1.0",
        "candidate": "ProDayTraderV2",
        "cycle": "pro_day_v2_cycle1",
        "generated_at_utc": generated_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision": "REJECT_PRO_DAY_TRADER_V2",
        "decision_stage": "PRE_PNL_TECHNICAL_GATE",
        "manifest": {
            "path": _portable(manifest_path),
            "sha256": _sha(manifest_path),
            "status": manifest["status"],
        },
        "gates": {
            "canonical_data": "PASS",
            "runtime_compatibility": "PASS",
            "unit_config_discovery": "PASS_24_TESTS",
            "recursive_analysis": "FAIL_CLI_STARTUP_LIMIT",
            "lookahead_analysis": "NOT_RUN_AFTER_RECURSIVE_FAIL",
            "train_oos": "NOT_RUN_AFTER_TECHNICAL_FAIL",
            "validation_oos": "LOCKED_NOT_REVEALED",
            "current_partial_oos": "LOCKED_NOT_REVEALED",
            "execution_stress": "NOT_RUN",
        },
        "recursive_failure": {
            "tool": "freqtrade 2026.7 recursive-analysis",
            "requested_startup_counts": REQUESTED_COUNTS,
            "strategy_startup_candle_count": 399,
            "first_unsupported_locked_count": 3199,
            "reported_binance_5m_recursive_limit": 2494,
            "status": "TERMINATED_WITH_FREQTRADE_CONFIGURATION_ERROR",
            "reason": (
                "The locked recursive set requires 3199/6399/12799 candles, while the "
                "official tool refuses counts above the reported Binance 5m limit of 2494."
            ),
            "canonical_data_mount": "read_only_bind_to_/canonical/futures",
            "public_exchange_metadata_used": True,
            "exchange_credentials_present": False,
        },
        "technical_model_activity": {
            "performed": True,
            "purpose": "recursive indicator/model compatibility only",
            "qualification_model": False,
            "model_files_currently_present": model_files,
            "prediction_files_currently_present": prediction_files,
        },
        "performance": {
            "status": "NOT_RUN_BY_LOCKED_TECHNICAL_GATE",
            "qualification_backtests": 0,
            "pnl_parsed": False,
            "profitability_claim": False,
        },
        "active_v1_v2r_changed": False,
        "deployment_performed": False,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
        "next_safe_action": (
            "A new, separately frozen cycle may reuse the unchanged candidate only with "
            "technically supported recursive counts and a new FreqAI identifier."
        ),
        "evidence_boundary": (
            "Terminal Cycle 1 technical decision before qualification PnL. No historical "
            "return, profit factor, drawdown, validation, current, dry-run, or live claim."
        ),
    }


def _atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize(*, root: Path = ROOT) -> dict[str, Any]:
    output = root / OUTPUT
    if output.is_file():
        existing = _load(output, "existing final decision")
        if existing.get("decision") != "REJECT_PRO_DAY_TRADER_V2":
            raise FinalizationError("Existing final decision conflicts")
        return existing
    decision = build_decision(root=root)
    ledger_path = root / LEDGER
    ledger = _load(ledger_path, "trial ledger")
    ledger["qualification_runs"] = [
        {
            "kind": "PRE_PNL_RECURSIVE_ANALYSIS",
            "status": "FAIL_CLI_STARTUP_LIMIT",
            "requested_startup_counts": REQUESTED_COUNTS,
            "first_unsupported_count": 3199,
            "pnl_parsed": False,
            "model_training_performed": True,
        }
    ]
    _atomic(ledger_path, ledger)
    _atomic(output, decision)
    return decision


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        decision = finalize()
    except (FinalizationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FINALIZATION_REFUSED", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "decision": decision["decision"],
                "performance": decision["performance"]["status"],
                "pnl_parsed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
