#!/usr/bin/env python3
"""Register and evaluate the already-completed V5 TRAIN run from its exact receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import run_pro_day_v5_train as train


ROOT = Path(__file__).resolve().parents[1]
CODE_FREEZE = Path("user_data/reports/pro_day_v5_cycle1/train_registration_code_freeze.json")
RUNNER = Path("tools/register_pro_day_v5_train_run.py")
TESTS = Path("tools/test_register_pro_day_v5_train_run.py")
RECEIPT = train.STAGING / ".last_result.json"


def validate_inputs_for_registration(root: Path) -> tuple[dict[str, Any], str, str, str]:
    """Validate the frozen cycle while allowing only the completed receipt run in staging."""
    manifest_path = root / train.MANIFEST
    manifest = train.load(manifest_path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v5_cycle1":
        raise train.TrainError("V5 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False:
        raise train.TrainError("manifest crossed PnL boundary")
    for label in ("plan", "strategy", "v4_parent", "config", "risk_policy", "data_audit"):
        row = manifest.get("files", {}).get(label, {})
        path = root / str(row.get("path", ""))
        if not path.is_file() or train.sha256(path) != row.get("sha256"):
            raise train.TrainError(f"frozen input changed: {label}")
    artifact = manifest.get("artifacts", {}).get("train", {})
    if artifact.get("path") != str(train.ARTIFACT).replace("\\", "/") or artifact.get("status") != "PLANNED_NOT_RUN":
        raise train.TrainError("TRAIN artifact contract differs")
    for label, relative, decision in (
        ("recursive", train.RECURSIVE, "CONTINUE_TO_LOOKAHEAD"),
        ("lookahead", train.LOOKAHEAD, "CONTINUE_TO_TRAIN"),
    ):
        report = train.load(root / relative)
        if report.get("status") != "PASS" or report.get("decision") != decision or report.get("pnl_parsed") is not False:
            raise train.TrainError(f"{label} gate is not a pre-PnL PASS")
    if (root / train.ARTIFACT).exists() or (root / train.OUTPUT).exists():
        raise train.TrainError("final TRAIN artifact/evaluation exists")
    return manifest, train.sha256(manifest_path), train.sha256(root / train.RECURSIVE), train.sha256(root / train.LOOKAHEAD)


def resolve_receipt(root: Path) -> tuple[Path, Path, Path]:
    staging = root / train.STAGING
    receipt_path = root / RECEIPT
    receipt = train.load(receipt_path)
    if set(receipt) != {"latest_backtest"}:
        raise train.TrainError("TRAIN receipt schema differs")
    filename = receipt["latest_backtest"]
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".zip"):
        raise train.TrainError("TRAIN receipt filename is invalid")
    archive = staging / filename
    meta = staging / f"{Path(filename).stem}.meta.json"
    if not archive.is_file() or not meta.is_file():
        raise train.TrainError("receipt artifact or metadata is missing")
    inventories = {
        "zip": sorted(path.name for path in staging.glob("*.zip")),
        "meta": sorted(path.name for path in staging.glob("*.meta.json")),
        "receipt": sorted(path.name for path in staging.glob(".last_result.json")),
    }
    if inventories != {"zip": [archive.name], "meta": [meta.name], "receipt": [".last_result.json"]}:
        raise train.TrainError("staging inventory is not exactly the receipt run")
    return receipt_path, archive, meta


def freeze_code(root: Path) -> dict[str, Any]:
    manifest, manifest_hash, recursive_hash, lookahead_hash = validate_inputs_for_registration(root)
    receipt, archive, meta = resolve_receipt(root)
    if (root / train.ARTIFACT).exists() or (root / train.OUTPUT).exists():
        raise train.TrainError("final TRAIN artifact/evaluation exists")
    payload = {
        "schema_version": "1.0", "status": "CODE_AND_ARTIFACT_FROZEN_BEFORE_PNL_PARSE",
        "cycle": "pro_day_v5_cycle1", "manifest_sha256": manifest_hash,
        "recursive_sha256": recursive_hash, "lookahead_sha256": lookahead_hash,
        "original_train_runner_sha256": train.sha256(root / train.RUNNER),
        "original_train_code_freeze_sha256": train.sha256(root / train.CODE_FREEZE),
        "registration_runner": {"path": str(RUNNER).replace("\\", "/"), "sha256": train.sha256(root / RUNNER)},
        "registration_tests": {"path": str(TESTS).replace("\\", "/"), "sha256": train.sha256(root / TESTS)},
        "receipt": {"path": str(RECEIPT).replace("\\", "/"), "sha256": train.sha256(receipt)},
        "staged_archive": {"path": str(archive.relative_to(root)).replace("\\", "/"),
                           "filename": archive.name, "sha256_before_sanitize": train.sha256(archive),
                           "size_bytes": archive.stat().st_size},
        "staged_metadata": {"path": str(meta.relative_to(root)).replace("\\", "/"), "sha256": train.sha256(meta)},
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    train.write(root / CODE_FREEZE, payload, exclusive=True)
    return payload


def validate_code(root: Path, archive: Path) -> tuple[dict[str, Any], str]:
    record = train.load(root / CODE_FREEZE)
    if record.get("status") != "CODE_AND_ARTIFACT_FROZEN_BEFORE_PNL_PARSE":
        raise train.TrainError("registration code/artifact is not frozen")
    if record.get("registration_runner", {}).get("sha256") != train.sha256(root / RUNNER):
        raise train.TrainError("registration runner changed")
    if record.get("registration_tests", {}).get("sha256") != train.sha256(root / TESTS):
        raise train.TrainError("registration tests changed")
    if record.get("staged_archive", {}).get("sha256_before_sanitize") != train.sha256(archive):
        raise train.TrainError("staged archive changed before sanitizer")
    original_freeze = train.load(root / train.CODE_FREEZE)
    if original_freeze.get("runner", {}).get("sha256") != train.sha256(root / train.RUNNER):
        raise train.TrainError("original frozen TRAIN runner changed")
    if record.get("original_train_code_freeze_sha256") != train.sha256(root / train.CODE_FREEZE):
        raise train.TrainError("original TRAIN code-freeze record changed")
    return record, train.sha256(root / CODE_FREEZE)


def register(root: Path) -> dict[str, Any]:
    manifest, manifest_hash, recursive_hash, lookahead_hash = validate_inputs_for_registration(root)
    receipt, archive, meta = resolve_receipt(root)
    freeze, freeze_hash = validate_code(root, archive)
    sanitizer = subprocess.run(
        [sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(archive)],
        cwd=root, capture_output=True, text=True, timeout=120, check=False,
    )
    if sanitizer.returncode:
        raise train.TrainError("TRAIN archive sanitizer failed")
    evaluation, reconciliation = train.evaluate_archive(
        archive, manifest["files"]["strategy"]["sha256"]
    )
    final = root / train.ARTIFACT
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(archive, final)
    report = {
        "schema_version": "1.0", "status": evaluation["status"],
        "decision": "CONTINUE_TO_VALIDATION" if evaluation["status"] == "PASS" else "KEEP_OFFLINE_RESEARCH",
        "cycle": "pro_day_v5_cycle1", "candidate": "ProDayTraderV5",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "recursive_sha256": recursive_hash,
        "lookahead_sha256": lookahead_hash, "registration_freeze_sha256": freeze_hash,
        "original_receipt_sha256": freeze["receipt"]["sha256"],
        "original_staged_archive_sha256": freeze["staged_archive"]["sha256_before_sanitize"],
        "artifact": {"path": str(train.ARTIFACT).replace("\\", "/"), "filename": final.name,
                     "sha256": train.sha256(final), "size_bytes": final.stat().st_size,
                     "sanitized": True, "selected_by": "exact_isolated_freqtrade_receipt"},
        "gates": evaluation["gates"], "metrics": evaluation["metrics"],
        "reconciliation": reconciliation,
        "pnl_parsed": True, "backtest_runs": 1,
        "validation_run": False, "current_run": False,
        "live_trading_authorized": False,
    }
    train.write(root / train.OUTPUT, report, exclusive=True)
    train.append_ledger(root, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--freeze-code", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.freeze_code:
            result = freeze_code(args.workspace.resolve())
            print(json.dumps({"status": result["status"], "pnl_parsed": False})); return 0
        report = register(args.workspace.resolve())
        print(json.dumps({"status": report["status"], "decision": report["decision"],
                          "trades": report["metrics"]["trades"],
                          "return_pct": report["metrics"]["return_pct"],
                          "profit_factor": report["metrics"]["profit_factor"],
                          "drawdown_pct": report["metrics"]["wallet_max_drawdown_pct"]}))
        return 0 if report["status"] == "PASS" else 2
    except (train.TrainError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REGISTRATION_BLOCKED", "error": str(exc)})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
