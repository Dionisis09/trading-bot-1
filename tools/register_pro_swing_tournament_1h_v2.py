#!/usr/bin/env python3
"""Register the completed fixed tournament from its exact Freqtrade receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import run_pro_swing_tournament_1h as tournament


ROOT = Path(__file__).resolve().parents[1]
FREEZE = tournament.REPORT_DIR / "registration_freeze_v2.json"
RUNNER = Path("tools/register_pro_swing_tournament_1h_v2.py")
TESTS = Path("tools/test_register_pro_swing_tournament_1h_v2.py")


def validate_frozen(root: Path) -> tuple[dict[str, Any], str]:
    manifest = tournament.load(root / tournament.MANIFEST)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("candidates") != tournament.CANDIDATES:
        raise tournament.TournamentError("manifest differs")
    if manifest.get("pnl_parsed") is not False or manifest.get("validation_revealed") is not False:
        raise tournament.TournamentError("manifest crossed evidence boundary")
    for relative, row in manifest.get("files", {}).items():
        path = root / relative
        if not path.is_file() or tournament.sha256(path) != row.get("sha256"):
            raise tournament.TournamentError(f"frozen file changed: {relative}")
    if (root / tournament.ARTIFACT).exists() or (root / tournament.OUTPUT).exists():
        raise tournament.TournamentError("final TRAIN output already exists")
    return manifest, tournament.sha256(root / tournament.MANIFEST)


def parse_archive(path: Path, expected_source_hash: str) -> list[dict[str, Any]]:
    expected_members = {f"_{name}.py" for name in tournament.CANDIDATES}
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise tournament.TournamentError(f"corrupt ZIP member: {bad}")
        names = archive.namelist()
        result_names = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
        source_names = [name for name in names if any(name.endswith(suffix) for suffix in expected_members)]
        if len(result_names) != 1 or len(source_names) != len(tournament.CANDIDATES):
            raise tournament.TournamentError("tournament archive member inventory differs")
        if len(set(source_names)) != len(source_names):
            raise tournament.TournamentError("duplicate embedded strategy source")
        if any(hashlib.sha256(archive.read(name)).hexdigest() != expected_source_hash for name in source_names):
            raise tournament.TournamentError("embedded tournament source differs")
        result = json.loads(archive.read(result_names[0]))
    strategies = result.get("strategy", {})
    if set(strategies) != set(tournament.CANDIDATES):
        raise tournament.TournamentError("result candidate inventory differs")
    rows = []
    for name in tournament.CANDIDATES:
        payload = strategies[name]
        if payload.get("timerange") != tournament.TIMERANGE or payload.get("timeframe") != "1h":
            raise tournament.TournamentError(f"result contract differs: {name}")
        if payload.get("pairlist") != tournament.PAIRS:
            raise tournament.TournamentError(f"result pairlist differs: {name}")
        rows.append(tournament.evaluate_strategy(name, payload))
    return rows


def freeze_registration(root: Path) -> dict[str, Any]:
    manifest, manifest_hash = validate_frozen(root)
    receipt, archive, metadata = tournament.resolve_receipt(root / tournament.STAGING)
    payload = {
        "schema_version": "1.0", "status": "REGISTRATION_AND_ARTIFACT_FROZEN_BEFORE_PNL_PARSE",
        "manifest_sha256": manifest_hash,
        "registration_runner_sha256": tournament.sha256(root / RUNNER),
        "registration_tests_sha256": tournament.sha256(root / TESTS),
        "receipt_sha256": tournament.sha256(receipt),
        "archive_sha256_before_parse": tournament.sha256(archive),
        "archive_size_bytes": archive.stat().st_size,
        "metadata_sha256": tournament.sha256(metadata),
        "sanitizer_already_completed_by_frozen_runner": True,
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    tournament.write(root / FREEZE, payload, exclusive=True)
    return payload


def register(root: Path) -> dict[str, Any]:
    manifest, manifest_hash = validate_frozen(root)
    receipt, archive, metadata = tournament.resolve_receipt(root / tournament.STAGING)
    frozen = tournament.load(root / FREEZE)
    checks = {
        "manifest_sha256": manifest_hash,
        "registration_runner_sha256": tournament.sha256(root / RUNNER),
        "registration_tests_sha256": tournament.sha256(root / TESTS),
        "receipt_sha256": tournament.sha256(receipt),
        "archive_sha256_before_parse": tournament.sha256(archive),
        "metadata_sha256": tournament.sha256(metadata),
    }
    if any(frozen.get(key) != value for key, value in checks.items()):
        raise tournament.TournamentError("registration freeze differs")
    source_hash = manifest["files"][str(tournament.STRATEGY).replace("\\", "/")]["sha256"]
    rows = parse_archive(archive, source_hash)
    passed = [row for row in rows if row["status"] == "PASS"]
    passed.sort(key=lambda row: (-row["metrics"]["return_pct"], -row["metrics"]["profit_factor"], row["metrics"]["wallet_drawdown_pct"]))
    winner = passed[0]["strategy"] if passed else None
    final = root / tournament.ARTIFACT
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(archive, final)
    report = {
        "schema_version": "1.0", "status": "PASS" if winner else "FAIL",
        "decision": "CONTINUE_WINNER_TO_TECHNICAL_GATES" if winner else "KEEP_OFFLINE_RESEARCH",
        "cycle": "pro_swing_tournament_1h_cycle3",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "registration_freeze_sha256": tournament.sha256(root / FREEZE),
        "winner": winner, "candidate_results": rows,
        "artifact": {"path": str(tournament.ARTIFACT).replace("\\", "/"),
                     "sha256": tournament.sha256(final), "size_bytes": final.stat().st_size,
                     "selected_by": "exact_isolated_freqtrade_receipt", "sanitized": True},
        "receipt_sha256": checks["receipt_sha256"], "metadata_sha256": checks["metadata_sha256"],
        "train_runs": 1, "candidate_trials": len(tournament.CANDIDATES),
        "validation_revealed": False, "pnl_parsed": True, "live_trading_authorized": False,
    }
    tournament.write(root / tournament.OUTPUT, report, exclusive=True)
    ledger = tournament.load(root / tournament.LEDGER)
    ledger.update({"train_runs": 1, "pnl_parsed": True, "winner": winner,
                   "report_sha256": tournament.sha256(root / tournament.OUTPUT)})
    tournament.write(root / tournament.LEDGER, ledger)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args(argv); root = args.workspace.resolve()
    try:
        result = freeze_registration(root) if args.freeze else register(root)
        if args.freeze:
            print(json.dumps({"status": result["status"], "pnl_parsed": False})); return 0
        print(json.dumps({"status": result["status"], "decision": result["decision"], "winner": result["winner"],
                          "results": {row["strategy"]: row["metrics"] for row in result["candidate_results"]}}))
        return 0 if result["status"] == "PASS" else 2
    except (tournament.TournamentError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "REGISTRATION_BLOCKED", "error": str(exc)})); return 2


if __name__ == "__main__":
    raise SystemExit(main())

