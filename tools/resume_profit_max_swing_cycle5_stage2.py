#!/usr/bin/env python3
"""Finish Cycle 5 from fixed TRAIN and VALIDATION artifacts with bounded sanitizer retry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import run_profit_max_swing_cycle5 as base
import resume_profit_max_swing_cycle5 as stage1


ROOT = Path(__file__).resolve().parents[1]
ADDENDUM = Path("docs/profit_max_swing_cycle5_stage2_addendum.md")
SCRIPT = Path("tools/resume_profit_max_swing_cycle5_stage2.py")
MANIFEST = base.REPORT_DIR / "stage2_freeze_manifest.json"
TRAIN = base.REPORT_DIR / "train.zip"
VALIDATION_RECEIPT = base.REPORT_DIR / "validation_staging/.last_result.json"
VALIDATION_META = base.REPORT_DIR / "validation_staging/backtest-result-2026-08-16_12-05-51.meta.json"
VALIDATION_ZIP = base.REPORT_DIR / "validation_staging/backtest-result-2026-08-16_12-05-51.zip"
EXPECTED = {
    TRAIN: "9322c63edc16c4d561b1ee542fd7e689078ab3e8621235c8d779c6ead4ce7dea",
    VALIDATION_RECEIPT: "638718e42026e2abe1d4ff5f966ab8512b8c5099e74c49da5938dc4dbfa3f181",
    VALIDATION_META: "7f17732b65ac82ef44ee7153d26e1013e57bed66314f951326ff8760dd227b1f",
    VALIDATION_ZIP: "a118650371ebc44eeac28b588607c6aecefac583578de970e4df6f4857067387",
}


def freeze(root: Path) -> dict[str, Any]:
    if (root / MANIFEST).exists() or (root / base.OUTPUT).exists():
        raise base.CycleError("stage 2 output already exists")
    for relative, expected in EXPECTED.items():
        if not (root / relative).is_file() or base.sha256(root / relative) != expected:
            raise base.CycleError(f"stage 2 input differs: {relative}")
    files = [ADDENDUM, SCRIPT, base.MANIFEST, stage1.RECOVERY_MANIFEST]
    payload = {
        "schema_version": "1.0", "status": "STAGE2_FROZEN_BEFORE_VALIDATION_PNL_PARSE",
        "locked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": {str(path).replace("\\", "/"): {"sha256": base.sha256(root / path), "size_bytes": (root / path).stat().st_size} for path in files},
        "inputs": {str(path).replace("\\", "/"): expected for path, expected in EXPECTED.items()},
        "train_rerun_allowed": False, "validation_rerun_allowed": False, "pnl_parsed": False,
        "live_trading_authorized": False,
    }
    base.write_json(root / MANIFEST, payload, exclusive=True)
    return payload


def validate(root: Path) -> None:
    payload = base.read_json(root / MANIFEST)
    if payload.get("status") != "STAGE2_FROZEN_BEFORE_VALIDATION_PNL_PARSE" or payload.get("pnl_parsed") is not False:
        raise base.CycleError("stage 2 manifest differs")
    for relative, row in payload.get("files", {}).items():
        if not (root / relative).is_file() or base.sha256(root / relative) != row.get("sha256"):
            raise base.CycleError(f"stage 2 frozen file changed: {relative}")
    for relative, expected in EXPECTED.items():
        if not (root / relative).is_file() or base.sha256(root / relative) != expected:
            raise base.CycleError(f"stage 2 input changed: {relative}")
    if (root / base.OUTPUT).exists():
        raise base.CycleError("tournament output already exists")


def sanitize_retry(root: Path, archive: Path) -> int:
    last = ""
    for attempt in range(1, 6):
        result = subprocess.run([sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(archive)], cwd=root, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode == 0:
            return attempt
        last = (result.stderr or result.stdout or "")[-500:]
        if attempt < 5:
            time.sleep(2)
    raise base.CycleError(f"sanitizer failed after 5 same-file attempts: {last}")


def new_split(root: Path, label: str, timerange: str, candidates: Sequence[str], timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    staging = root / base.REPORT_DIR / f"{label}_staging"
    staging.mkdir(parents=True, exist_ok=False)
    command = [
        "docker", "run", "--rm", "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{staging.resolve()}:/freqtrade/user_data/backtest_results:rw", "--entrypoint", "freqtrade", base.IMAGE,
        "backtesting", "--config", "/freqtrade/user_data/config-profit-max-swing-cycle5.json", "--userdir", "/freqtrade/user_data",
        "--strategy-list", *candidates, "--datadir", "/freqtrade/user_data/data/binance", "--timerange", timerange,
        "--pairs", *base.PAIRS, "--export", "trades", "--cache", "none", "--no-color",
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if result.returncode:
        raise base.CycleError(f"{label} backtest exit {result.returncode}")
    receipt = base.read_json(staging / ".last_result.json")
    filename = receipt.get("latest_backtest")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise base.CycleError(f"invalid receipt: {label}")
    archive = staging / filename
    attempts = sanitize_retry(root, archive)
    rows = stage1.parse_archive(archive, candidates, label)
    final = root / base.REPORT_DIR / f"{label}.zip"
    os.replace(archive, final)
    return rows, {
        "path": str(final.relative_to(root)).replace("\\", "/"), "sha256": base.sha256(final), "size_bytes": final.stat().st_size,
        "timerange": timerange, "candidates": list(candidates), "sanitizer_attempts": attempts,
        "stdout_stderr_sha256": hashlib.sha256(((result.stdout or "") + "\n" + (result.stderr or "")).encode()).hexdigest(),
    }


def resume(root: Path, timeout: int) -> dict[str, Any]:
    validate(root)
    validation_sanitize_attempts = sanitize_retry(root, root / VALIDATION_ZIP)
    train_rows = stage1.parse_archive(root / TRAIN, base.CANDIDATES, "train")
    validation_rows = stage1.parse_archive(root / VALIDATION_ZIP, base.CANDIDATES, "validation")
    winner = base.select_winner(train_rows, validation_rows)
    if winner is None:
        raise base.CycleError("no eligible validation pass")
    validation_final = root / base.REPORT_DIR / "validation.zip"
    os.replace(root / VALIDATION_ZIP, validation_final)
    validation_artifact = {"path": str(validation_final.relative_to(root)).replace("\\", "/"), "sha256": base.sha256(validation_final), "size_bytes": validation_final.stat().st_size, "timerange": base.SPLITS["validation"], "candidates": base.CANDIDATES, "sanitizer_attempts": validation_sanitize_attempts, "recovered_without_validation_rerun": True}
    current_rows, current_artifact = new_split(root, "current_partial", base.SPLITS["current_partial"], base.CANDIDATES, timeout)
    continuous_candidates = ["DualTrendFuturesV2R"] if winner == "DualTrendFuturesV2R" else ["DualTrendFuturesV2R", winner]
    continuous_rows, continuous_artifact = new_split(root, "continuous", "20210101-20260801", continuous_candidates, timeout)
    for row in train_rows:
        row["gates"] = base.gates(row, "train"); row["status"] = "PASS" if base.row_passes(row, "train") else "DIAGNOSTIC" if row["strategy"] not in base.ELIGIBLE else "FAIL"
    for row in validation_rows:
        row["gates"] = base.gates(row, "validation"); row["status"] = "PASS" if base.row_passes(row, "validation") else "DIAGNOSTIC" if row["strategy"] not in base.ELIGIBLE else "FAIL"
    train_artifact = {"path": str(TRAIN).replace("\\", "/"), "sha256": base.sha256(root / TRAIN), "size_bytes": (root / TRAIN).stat().st_size, "timerange": base.SPLITS["train"], "candidates": base.CANDIDATES, "recovered_without_train_rerun": True}
    report = {
        "schema_version": "1.0", "cycle": "profit_max_swing_cycle5", "status": "PASS",
        "decision": "WINNER_REQUIRES_COST_AND_TECHNICAL_GATES", "winner": winner,
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "freeze_manifest_sha256": base.sha256(root / base.MANIFEST), "stage2_manifest_sha256": base.sha256(root / MANIFEST),
        "train_rerun": False, "validation_rerun": False, "validation_revealed": True, "pnl_parsed": True,
        "live_trading_authorized": False, "profit_guaranteed": False,
        "results": {"train": train_rows, "validation": validation_rows, "current_partial": current_rows, "continuous": continuous_rows},
        "artifacts": {"train": train_artifact, "validation": validation_artifact, "current_partial": current_artifact, "continuous": continuous_artifact},
        "evidence_boundary": "All historical periods were already seen; this is robustness evidence, not a sealed holdout or a profit guarantee.",
    }
    base.write_json(root / base.OUTPUT, report, exclusive=True)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--freeze-stage2", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args(argv)
    try:
        payload = freeze(args.workspace.resolve()) if args.freeze_stage2 else resume(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": payload["status"], "winner": payload.get("winner"), "pnl_parsed": payload.get("pnl_parsed")}, sort_keys=True))
        return 0
    except (base.CycleError, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "STAGE2_BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
