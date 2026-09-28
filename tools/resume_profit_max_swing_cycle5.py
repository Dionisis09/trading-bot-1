#!/usr/bin/env python3
"""Resume Cycle 5 from its explicit pre-PnL TRAIN artifact without rerunning TRAIN."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import run_profit_max_swing_cycle5 as base


ROOT = Path(__file__).resolve().parents[1]
ADDENDUM = Path("docs/profit_max_swing_cycle5_recovery_addendum.md")
SCRIPT = Path("tools/resume_profit_max_swing_cycle5.py")
RECOVERY_MANIFEST = base.REPORT_DIR / "recovery_freeze_manifest.json"
ORIGINAL_MANIFEST_SHA = "7813549424b491d5e7142ff5a64d714a55aaad89cb dcf4ddf3ec29ed6e533836".replace(" ", "")
TRAIN_STAGING = base.REPORT_DIR / "train_staging"
TRAIN_RECEIPT = TRAIN_STAGING / ".last_result.json"
TRAIN_META = TRAIN_STAGING / "backtest-result-2026-08-16_12-03-41.meta.json"
TRAIN_ZIP = TRAIN_STAGING / "backtest-result-2026-08-16_12-03-41.zip"
EXPECTED_TRAIN = {
    TRAIN_RECEIPT: "4c4f5e1db653805fb6b611539c4d0d68c2a294a4f6405d2636191cf32c553a1c",
    TRAIN_META: "478a373912344d66553eb52f3af1a89392d01dcfeda4e0b6b945e3b53a888aae",
    TRAIN_ZIP: "724302fcbe695f6dda046f429b03ff5f29f62541212b7c07a8fc41d40bfd104b",
}


def freeze_recovery(root: Path) -> dict[str, Any]:
    if base.sha256(root / base.MANIFEST) != ORIGINAL_MANIFEST_SHA:
        raise base.CycleError("original manifest hash differs")
    if (root / base.OUTPUT).exists() or (root / RECOVERY_MANIFEST).exists():
        raise base.CycleError("recovery output already exists")
    for relative, expected in EXPECTED_TRAIN.items():
        if not (root / relative).is_file() or base.sha256(root / relative) != expected:
            raise base.CycleError(f"TRAIN recovery input differs: {relative}")
    inputs = [ADDENDUM, SCRIPT, base.MANIFEST]
    payload = {
        "schema_version": "1.0", "status": "RECOVERY_FROZEN_BEFORE_PNL_PARSE",
        "locked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "original_manifest_sha256": ORIGINAL_MANIFEST_SHA,
        "files": {str(path).replace("\\", "/"): {"sha256": base.sha256(root / path), "size_bytes": (root / path).stat().st_size} for path in inputs},
        "train_inputs": {str(path).replace("\\", "/"): value for path, value in EXPECTED_TRAIN.items()},
        "train_rerun_allowed": False, "pnl_parsed": False, "live_trading_authorized": False,
    }
    base.write_json(root / RECOVERY_MANIFEST, payload, exclusive=True)
    return payload


def validate_recovery(root: Path) -> dict[str, Any]:
    payload = base.read_json(root / RECOVERY_MANIFEST)
    if payload.get("status") != "RECOVERY_FROZEN_BEFORE_PNL_PARSE" or payload.get("pnl_parsed") is not False:
        raise base.CycleError("recovery manifest differs")
    for relative, row in payload.get("files", {}).items():
        if not (root / relative).is_file() or base.sha256(root / relative) != row.get("sha256"):
            raise base.CycleError(f"recovery file changed: {relative}")
    for relative, expected in EXPECTED_TRAIN.items():
        if not (root / relative).is_file() or base.sha256(root / relative) != expected:
            raise base.CycleError(f"TRAIN input changed before sanitization: {relative}")
    if (root / base.OUTPUT).exists():
        raise base.CycleError("tournament output already exists")
    return payload


def sanitize(root: Path, archive: Path) -> None:
    result = subprocess.run([sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(archive)], cwd=root, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        raise base.CycleError(f"direct sanitizer failed: {(result.stderr or result.stdout or '')[-500:]}")


def parse_archive(path: Path, candidates: Sequence[str], label: str) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as zipped:
        if zipped.testzip():
            raise base.CycleError(f"corrupt archive: {label}")
        names = [name for name in zipped.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        if len(names) != 1:
            raise base.CycleError(f"ambiguous archive: {label}")
        payload = json.loads(zipped.read(names[0]))
    strategies = payload.get("strategy", {})
    if set(strategies) != set(candidates):
        raise base.CycleError(f"candidate inventory differs: {label}")
    return [base.metrics(name, strategies[name], label) for name in candidates]


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
    sanitize(root, archive)
    rows = parse_archive(archive, candidates, label)
    final = root / base.REPORT_DIR / f"{label}.zip"
    os.replace(archive, final)
    return rows, {
        "path": str(final.relative_to(root)).replace("\\", "/"), "sha256": base.sha256(final), "size_bytes": final.stat().st_size,
        "timerange": timerange, "candidates": list(candidates),
        "stdout_stderr_sha256": hashlib.sha256(((result.stdout or "") + "\n" + (result.stderr or "")).encode()).hexdigest(),
    }


def resume(root: Path, timeout: int) -> dict[str, Any]:
    validate_recovery(root)
    sanitize(root, root / TRAIN_ZIP)
    train_rows = parse_archive(root / TRAIN_ZIP, base.CANDIDATES, "train")
    if not any(base.row_passes(row, "train") for row in train_rows):
        raise base.CycleError("no eligible TRAIN pass; validation remains hidden")
    train_final = root / base.REPORT_DIR / "train.zip"
    os.replace(root / TRAIN_ZIP, train_final)
    train_artifact = {"path": str(train_final.relative_to(root)).replace("\\", "/"), "sha256": base.sha256(train_final), "size_bytes": train_final.stat().st_size, "timerange": base.SPLITS["train"], "candidates": base.CANDIDATES, "recovered_without_train_rerun": True}
    validation_rows, validation_artifact = new_split(root, "validation", base.SPLITS["validation"], base.CANDIDATES, timeout)
    winner = base.select_winner(train_rows, validation_rows)
    if winner is None:
        raise base.CycleError("no eligible validation pass")
    current_rows, current_artifact = new_split(root, "current_partial", base.SPLITS["current_partial"], base.CANDIDATES, timeout)
    continuous_candidates = ["DualTrendFuturesV2R"] if winner == "DualTrendFuturesV2R" else ["DualTrendFuturesV2R", winner]
    continuous_rows, continuous_artifact = new_split(root, "continuous", "20210101-20260801", continuous_candidates, timeout)
    for row in train_rows:
        row["gates"] = base.gates(row, "train"); row["status"] = "PASS" if base.row_passes(row, "train") else "DIAGNOSTIC" if row["strategy"] not in base.ELIGIBLE else "FAIL"
    for row in validation_rows:
        row["gates"] = base.gates(row, "validation"); row["status"] = "PASS" if base.row_passes(row, "validation") else "DIAGNOSTIC" if row["strategy"] not in base.ELIGIBLE else "FAIL"
    report = {
        "schema_version": "1.0", "cycle": "profit_max_swing_cycle5", "status": "PASS",
        "decision": "WINNER_REQUIRES_COST_AND_TECHNICAL_GATES", "winner": winner,
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "freeze_manifest_sha256": ORIGINAL_MANIFEST_SHA, "recovery_manifest_sha256": base.sha256(root / RECOVERY_MANIFEST),
        "train_rerun": False, "validation_revealed": True, "pnl_parsed": True,
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
    parser.add_argument("--freeze-recovery", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args(argv)
    try:
        payload = freeze_recovery(args.workspace.resolve()) if args.freeze_recovery else resume(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": payload["status"], "winner": payload.get("winner"), "pnl_parsed": payload.get("pnl_parsed")}, sort_keys=True))
        return 0
    except (base.CycleError, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "RECOVERY_BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
