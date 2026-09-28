#!/usr/bin/env python3
"""Run and evaluate the single frozen V5 TRAIN performance backtest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "freqtradeorg/freqtrade@sha256:"
    "da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
)
TIMERANGE = "20220101-20240101"
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"]
MANIFEST = Path("user_data/reports/pro_day_v5_cycle1/research_freeze_manifest.json")
RECURSIVE = Path("user_data/reports/pro_day_v5_cycle1/recursive_analysis.json")
LOOKAHEAD = Path("user_data/reports/pro_day_v5_cycle1/lookahead_analysis.json")
LEDGER = Path("user_data/reports/pro_day_v5_cycle1/trial_ledger.json")
CODE_FREEZE = Path("user_data/reports/pro_day_v5_cycle1/train_gate_code_freeze.json")
OUTPUT = Path("user_data/reports/pro_day_v5_cycle1/train_evaluation.json")
ARTIFACT = Path("user_data/backtest_results/prodayv5-cycle1-train.zip")
STAGING = Path("user_data/reports/pro_day_v5_cycle1/train_staging")
RUNNER = Path("tools/run_pro_day_v5_train.py")
TESTS = Path("tools/test_run_pro_day_v5_train.py")


class TrainError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TrainError(f"invalid JSON object: {path}")
    return value


def write(path: Path, payload: Mapping[str, Any], exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise TrainError(f"refusing to overwrite {path}") from exc
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_inputs(root: Path) -> tuple[dict[str, Any], str, str, str]:
    manifest_path = root / MANIFEST
    manifest = load(manifest_path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v5_cycle1":
        raise TrainError("V5 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False:
        raise TrainError("manifest crossed PnL boundary")
    for label in ("plan", "strategy", "v4_parent", "config", "risk_policy", "data_audit"):
        row = manifest.get("files", {}).get(label, {})
        path = root / str(row.get("path", ""))
        if not path.is_file() or sha256(path) != row.get("sha256"):
            raise TrainError(f"frozen input changed: {label}")
    artifact = manifest.get("artifacts", {}).get("train", {})
    if artifact.get("path") != str(ARTIFACT).replace("\\", "/") or artifact.get("status") != "PLANNED_NOT_RUN":
        raise TrainError("TRAIN artifact contract differs")
    for label, relative, decision in (
        ("recursive", RECURSIVE, "CONTINUE_TO_LOOKAHEAD"),
        ("lookahead", LOOKAHEAD, "CONTINUE_TO_TRAIN"),
    ):
        report = load(root / relative)
        if report.get("status") != "PASS" or report.get("decision") != decision or report.get("pnl_parsed") is not False:
            raise TrainError(f"{label} gate is not a pre-PnL PASS")
    if (root / ARTIFACT).exists() or (root / OUTPUT).exists():
        raise TrainError("TRAIN artifact or evaluation already exists")
    if (root / STAGING).exists() and any((root / STAGING).iterdir()):
        raise TrainError("TRAIN staging directory is not empty")
    return manifest, sha256(manifest_path), sha256(root / RECURSIVE), sha256(root / LOOKAHEAD)


def freeze_code(root: Path) -> dict[str, Any]:
    _, manifest_hash, recursive_hash, lookahead_hash = validate_inputs(root)
    payload = {
        "schema_version": "1.0", "status": "CODE_FROZEN_BEFORE_TRAIN",
        "cycle": "pro_day_v5_cycle1", "manifest_sha256": manifest_hash,
        "recursive_sha256": recursive_hash, "lookahead_sha256": lookahead_hash,
        "runner": {"path": str(RUNNER).replace("\\", "/"), "sha256": sha256(root / RUNNER)},
        "tests": {"path": str(TESTS).replace("\\", "/"), "sha256": sha256(root / TESTS)},
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    write(root / CODE_FREEZE, payload, exclusive=True)
    return payload


def validate_code(root: Path, manifest_hash: str, recursive_hash: str, lookahead_hash: str) -> str:
    record = load(root / CODE_FREEZE)
    if (record.get("manifest_sha256"), record.get("recursive_sha256"), record.get("lookahead_sha256")) != (
        manifest_hash, recursive_hash, lookahead_hash
    ):
        raise TrainError("TRAIN code freeze references different evidence")
    for label, relative in (("runner", RUNNER), ("tests", TESTS)):
        if record.get(label, {}).get("sha256") != sha256(root / relative):
            raise TrainError(f"frozen TRAIN {label} changed")
    return sha256(root / CODE_FREEZE)


def build_command(root: Path) -> list[str]:
    staging = root / STAGING
    return [
        "docker", "run", "--rm",
        "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
        "-v", f"{staging.resolve()}:/freqtrade/user_data/backtest_results:rw",
        "--entrypoint", "freqtrade", IMAGE,
        "backtesting", "--config", "/freqtrade/user_data/config-pro-day-v5-cycle1-research.json",
        "--userdir", "/freqtrade/user_data", "--strategy", "ProDayTraderV5",
        "--datadir", "/canonical", "--timerange", TIMERANGE,
        "--pairs", *PAIRS, "--export", "trades",
        "--backtest-filename", f"/freqtrade/user_data/backtest_results/{ARTIFACT.name}",
        "--cache", "none", "--no-color",
    ]


def reconcile(payload: Mapping[str, Any]) -> dict[str, Any]:
    trades = payload.get("trades")
    if not isinstance(trades, list):
        raise TrainError("TRAIN trades are missing")
    profits = [float(row["profit_abs"]) for row in trades]
    if any(not math.isfinite(value) for value in profits):
        raise TrainError("non-finite trade profit")
    total = sum(profits)
    gains = sum(value for value in profits if value > 0.0)
    losses_abs = -sum(value for value in profits if value < 0.0)
    pf = gains / losses_abs if losses_abs > 0.0 else None
    wins = sum(value > 0.0 for value in profits)
    losses = sum(value < 0.0 for value in profits)
    draws = len(profits) - wins - losses
    if len(trades) != int(payload.get("total_trades", -1)):
        raise TrainError("trade count reconciliation failed")
    if abs(total - float(payload.get("profit_total_abs"))) > 1e-6:
        raise TrainError("absolute profit reconciliation failed")
    source_pf = payload.get("profit_factor")
    if pf is None or source_pf is None or abs(pf - float(source_pf)) > 1e-12:
        raise TrainError("profit factor reconciliation failed")
    if (wins, losses, draws) != (int(payload.get("wins", -1)), int(payload.get("losses", -1)), int(payload.get("draws", -1))):
        raise TrainError("win/loss/draw reconciliation failed")
    return {
        "trade_count": len(trades), "profit_abs": total, "profit_factor": pf,
        "wins": wins, "losses": losses, "draws": draws,
        "pair_counts": {pair: sum(row.get("pair") == pair for row in trades) for pair in PAIRS},
        "tag_counts": {tag: sum(row.get("enter_tag") == tag for row in trades)
                       for tag in ("T1_long", "T1_short", "R1_long", "R1_short")},
        "long_count": sum(not bool(row.get("is_short")) for row in trades),
        "short_count": sum(bool(row.get("is_short")) for row in trades),
    }


def evaluate_archive(path: Path, frozen_strategy_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise TrainError(f"corrupt ZIP member: {bad}")
        names = archive.namelist()
        result_names = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
        config_names = [name for name in names if name.endswith("_config.json")]
        strategy_names = [name for name in names if name.endswith("_ProDayTraderV5.py")]
        if not (len(result_names) == len(config_names) == len(strategy_names) == 1):
            raise TrainError("archive member inventory is ambiguous")
        source = archive.read(strategy_names[0])
        if hashlib.sha256(source).hexdigest() != frozen_strategy_hash:
            raise TrainError("embedded strategy differs from frozen source")
        config = json.loads(archive.read(config_names[0]))
        result = json.loads(archive.read(result_names[0]))
    exchange = config.get("exchange", {})
    for key in ("key", "secret", "password", "uid"):
        value = exchange.get(key)
        if value not in (None, "", "REDACTED", "__REDACTED__"):
            raise TrainError(f"archive config contains non-redacted exchange {key}")
    if config.get("strategy") != "ProDayTraderV5" or config.get("dry_run") is not True:
        raise TrainError("archive config strategy/dry-run differs")
    if config.get("trading_mode") != "futures" or config.get("margin_mode") != "isolated":
        raise TrainError("archive futures mode differs")
    strategies = result.get("strategy", {})
    if list(strategies) != ["ProDayTraderV5"]:
        raise TrainError("result strategy inventory differs")
    payload = strategies["ProDayTraderV5"]
    if payload.get("timerange") != TIMERANGE or payload.get("timeframe") != "5m":
        raise TrainError("result timerange/timeframe differs")
    if payload.get("pairlist") != PAIRS:
        raise TrainError("result pairlist differs")
    reconciliation = reconcile(payload)
    total_trades = reconciliation["trade_count"]
    return_fraction = float(payload.get("profit_total"))
    pf = float(payload.get("profit_factor"))
    drawdown = float(payload.get("max_drawdown_account"))
    values = (return_fraction, pf, drawdown)
    if any(not math.isfinite(value) for value in values) or drawdown < 0.0:
        raise TrainError("non-finite TRAIN metric")
    return_dd = return_fraction / drawdown if drawdown > 0.0 else (math.inf if return_fraction > 0 else None)
    gates = {
        "trades_gte_120": total_trades >= 120,
        "return_positive": return_fraction > 0.0,
        "profit_factor_gte_1_25": pf >= 1.25,
        "wallet_drawdown_lte_12pct": drawdown <= 0.12,
        "return_to_drawdown_gte_1": return_dd is not None and return_dd >= 1.0,
    }
    metrics = {
        "trades": total_trades, "return_fraction": return_fraction,
        "return_pct": return_fraction * 100.0, "profit_factor": pf,
        "wallet_max_drawdown_fraction": drawdown, "wallet_max_drawdown_pct": drawdown * 100.0,
        "return_to_drawdown": return_dd,
        "starting_balance": float(payload.get("starting_balance")),
        "final_balance": float(payload.get("final_balance")),
    }
    return {"status": "PASS" if all(gates.values()) else "FAIL", "gates": gates, "metrics": metrics}, reconciliation


def append_ledger(root: Path, report: Mapping[str, Any]) -> None:
    path = root / LEDGER
    ledger = load(path)
    runs = ledger.get("qualification_runs")
    if not isinstance(runs, list) or len(runs) != 2:
        raise TrainError("TRAIN must follow recursive and lookahead exactly once")
    runs.append({"kind": "TRAIN_PERFORMANCE_BACKTEST", "status": report["status"],
                 "report_path": str(OUTPUT).replace("\\", "/"),
                 "report_sha256": sha256(root / OUTPUT), "artifact_sha256": report["artifact"]["sha256"],
                 "pnl_parsed": True})
    ledger["qualification_runs"] = runs
    ledger["pnl_parsed"] = True
    write(path, ledger)


def run_train(root: Path, timeout: int) -> dict[str, Any]:
    manifest, manifest_hash, recursive_hash, lookahead_hash = validate_inputs(root)
    code_hash = validate_code(root, manifest_hash, recursive_hash, lookahead_hash)
    staging = root / STAGING
    staging.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(build_command(root), cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    staged = staging / ARTIFACT.name
    if result.returncode or not staged.is_file():
        raise TrainError(f"TRAIN backtest failed before artifact validation (exit {result.returncode})")
    sanitize = subprocess.run([sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(staged)],
                              cwd=root, capture_output=True, text=True, timeout=120, check=False)
    if sanitize.returncode:
        raise TrainError("TRAIN archive sanitizer failed")
    frozen_strategy_hash = manifest["files"]["strategy"]["sha256"]
    evaluation, reconciliation = evaluate_archive(staged, frozen_strategy_hash)
    final = root / ARTIFACT
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, final)
    report = {
        "schema_version": "1.0", "status": evaluation["status"],
        "decision": "CONTINUE_TO_VALIDATION" if evaluation["status"] == "PASS" else "KEEP_OFFLINE_RESEARCH",
        "cycle": "pro_day_v5_cycle1", "candidate": "ProDayTraderV5",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "recursive_sha256": recursive_hash,
        "lookahead_sha256": lookahead_hash, "code_freeze_sha256": code_hash,
        "runtime_image": IMAGE, "container_exit_code": result.returncode,
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "artifact": {"path": str(ARTIFACT).replace("\\", "/"), "filename": final.name,
                     "sha256": sha256(final), "size_bytes": final.stat().st_size, "sanitized": True},
        "gates": evaluation["gates"], "metrics": evaluation["metrics"],
        "reconciliation": reconciliation,
        "pnl_parsed": True, "validation_run": False, "current_run": False,
        "live_trading_authorized": False,
    }
    write(root / OUTPUT, report, exclusive=True)
    append_ledger(root, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--freeze-code", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.freeze_code:
            record = freeze_code(args.workspace.resolve())
            print(json.dumps({"status": record["status"], "pnl_parsed": False})); return 0
        report = run_train(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": report["status"], "decision": report["decision"],
                          "trades": report["metrics"]["trades"],
                          "return_pct": report["metrics"]["return_pct"],
                          "profit_factor": report["metrics"]["profit_factor"],
                          "drawdown_pct": report["metrics"]["wallet_max_drawdown_pct"]}))
        return 0 if report["status"] == "PASS" else 2
    except (TrainError, OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "TRAIN_BLOCKED", "error": str(exc)})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
