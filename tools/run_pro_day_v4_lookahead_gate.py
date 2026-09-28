#!/usr/bin/env python3
"""Run frozen all-pair V4 lookahead analysis without exposing PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import run_pro_day_v3_recursive_gate as common


ROOT = Path(__file__).resolve().parents[1]
IMAGE = common.IMAGE
TIMERANGE = "20240101-20260101"
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"]
MINIMUM = 100
TARGETED = 120
REQUIRED_TAGS = ["T1_long", "T1_short", "R1_long", "R1_short"]
SENTINEL = "PRO_DAY_V4_LOOKAHEAD_PROBE="
MANIFEST = Path("user_data/reports/pro_day_v4_cycle1/research_freeze_manifest.json")
RECURSIVE = Path("user_data/reports/pro_day_v4_cycle1/recursive_analysis.json")
LEDGER = Path("user_data/reports/pro_day_v4_cycle1/trial_ledger.json")
CODE_FREEZE = Path("user_data/reports/pro_day_v4_cycle1/lookahead_gate_code_freeze.json")
OUTPUT = Path("user_data/reports/pro_day_v4_cycle1/lookahead_analysis.json")
RUNNER = Path("tools/run_pro_day_v4_lookahead_gate.py")
TESTS = Path("tools/test_run_pro_day_v4_lookahead_gate.py")


def sha256(path: Path) -> str:
    return common.sha256(path)


def load(path: Path) -> dict[str, Any]:
    return common.load(path)


def validate_inputs(root: Path) -> tuple[str, str]:
    manifest_path = root / MANIFEST
    manifest = load(manifest_path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v4_cycle1":
        raise common.GateError("V4 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False:
        raise common.GateError("manifest crossed PnL boundary")
    for label in ("plan", "strategy", "config", "risk_policy", "data_audit"):
        row = manifest.get("files", {}).get(label, {})
        path = root / str(row.get("path", ""))
        if not path.is_file() or sha256(path) != row.get("sha256"):
            raise common.GateError(f"frozen input changed: {label}")
    for row in manifest.get("artifacts", {}).values():
        if row.get("status") != "PLANNED_NOT_RUN" or (root / row.get("path", "")).exists():
            raise common.GateError("qualification artifact exists before lookahead")
    recursive_path = root / RECURSIVE
    recursive = load(recursive_path)
    if recursive.get("status") != "PASS" or recursive.get("decision") != "CONTINUE_TO_LOOKAHEAD":
        raise common.GateError("recursive gate did not pass")
    if recursive.get("pnl_parsed") is not False or recursive.get("backtest_performed") is not False:
        raise common.GateError("recursive evidence boundary differs")
    return sha256(manifest_path), sha256(recursive_path)


def write(path: Path, payload: Mapping[str, Any], exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise common.GateError(f"refusing to overwrite {path}") from exc
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def freeze_code(root: Path) -> dict[str, Any]:
    manifest_hash, recursive_hash = validate_inputs(root)
    if (root / OUTPUT).exists():
        raise common.GateError("lookahead output already exists")
    payload = {
        "schema_version": "1.0", "status": "CODE_FROZEN_BEFORE_LOOKAHEAD_RUN",
        "cycle": "pro_day_v4_cycle1", "manifest_sha256": manifest_hash,
        "recursive_report_sha256": recursive_hash,
        "runner": {"path": str(RUNNER).replace("\\", "/"), "sha256": sha256(root / RUNNER)},
        "tests": {"path": str(TESTS).replace("\\", "/"), "sha256": sha256(root / TESTS)},
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    write(root / CODE_FREEZE, payload, exclusive=True)
    return payload


def validate_code(root: Path, manifest_hash: str, recursive_hash: str) -> str:
    record = load(root / CODE_FREEZE)
    if record.get("manifest_sha256") != manifest_hash or record.get("recursive_report_sha256") != recursive_hash:
        raise common.GateError("lookahead code freeze references different evidence")
    for label, relative in (("runner", RUNNER), ("tests", TESTS)):
        if record.get(label, {}).get("sha256") != sha256(root / relative):
            raise common.GateError(f"frozen lookahead {label} changed")
    return sha256(root / CODE_FREEZE)


def evaluate(probe: Mapping[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    total = probe.get("analyzed_signals")
    if not isinstance(total, int) or total < MINIMUM:
        failures.append("fewer than 100 analyzed signals")
    if probe.get("has_bias") is not False:
        failures.append("lookahead bias detected")
    if probe.get("false_entry_signals") != 0 or probe.get("false_exit_signals") != 0:
        failures.append("entry or exit signal bias detected")
    if probe.get("false_indicators") != []:
        failures.append("biased indicator columns detected")
    tags = probe.get("full_trade_tag_counts", {})
    missing_tags = [tag for tag in REQUIRED_TAGS if not isinstance(tags.get(tag), int) or tags.get(tag) < 1]
    if missing_tags:
        failures.append("missing setup-side representation: " + ",".join(missing_tags))
    pairs = probe.get("full_trade_pair_counts", {})
    missing_pairs = [pair for pair in PAIRS if not isinstance(pairs.get(pair), int) or pairs.get(pair) < 1]
    if missing_pairs:
        failures.append("missing pair representation: " + ",".join(missing_pairs))
    if probe.get("public_market_metadata_used") is not True or probe.get("private_api_used") is not False:
        failures.append("transport contract differs")
    details = {
        "analyzed_signals": total,
        "minimum_signals": MINIMUM,
        "targeted_signals": TARGETED,
        "has_bias": probe.get("has_bias"),
        "false_entry_signals": probe.get("false_entry_signals"),
        "false_exit_signals": probe.get("false_exit_signals"),
        "false_indicators": probe.get("false_indicators"),
        "full_trade_count": probe.get("full_trade_count"),
        "full_trade_tag_counts": tags,
        "full_trade_pair_counts": pairs,
        "missing_tags": missing_tags,
        "missing_pairs": missing_pairs,
    }
    return not failures, failures, details


def build_command(root: Path) -> list[str]:
    return [
        "docker", "run", "--rm",
        "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{(root / 'tools').resolve()}:/freqtrade/tools:ro",
        "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
        "--entrypoint", "python", IMAGE,
        "/freqtrade/tools/run_pro_day_v4_lookahead_gate.py", "--inside-container",
    ]


def inside() -> int:
    from freqtrade.commands import Arguments
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.analysis.lookahead_helpers import LookaheadAnalysisSubFunctions
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.util import get_progress_tracker

    argv = [
        "lookahead-analysis", "--config", "/freqtrade/user_data/config-pro-day-v4-cycle1-research.json",
        "--userdir", "/freqtrade/user_data", "--strategy", "ProDayTraderV4",
        "--datadir", "/canonical", "--timerange", TIMERANGE,
        "--pairs", *PAIRS, "--minimum-trade-amount", str(MINIMUM),
        "--targeted-trade-amount", str(TARGETED), "--no-color",
    ]
    config = setup_utils_configuration(Arguments(argv).get_parsed_arg(), RunMode.UTIL_NO_EXCHANGE)
    config = LookaheadAnalysisSubFunctions.calculate_config_overrides(config)
    objects = [row for row in StrategyResolver.search_all_objects(config, enum_failed=False, recursive=False)
               if row.get("name") == "ProDayTraderV4"]
    if len(objects) != 1:
        raise common.GateError("ProDayTraderV4 is not uniquely discoverable")
    with get_progress_tracker() as progress:
        instance = LookaheadAnalysisSubFunctions.initialize_single_lookahead_analysis(
            config, objects[0], progress
        )
    analysis = instance.current_analysis
    trades = instance.full_varHolder.result["results"]
    tags = {str(key): int(value) for key, value in trades["enter_tag"].fillna("").value_counts().items()}
    pairs = {str(key): int(value) for key, value in trades["pair"].value_counts().items()}
    probe = {
        "analyzed_signals": int(analysis.total_signals),
        "has_bias": bool(analysis.has_bias),
        "false_entry_signals": int(analysis.false_entry_signals),
        "false_exit_signals": int(analysis.false_exit_signals),
        "false_indicators": sorted(str(value) for value in analysis.false_indicators),
        "failed_bias_check": bool(instance.failed_bias_check),
        "full_trade_count": int(len(trades)),
        "full_trade_tag_counts": tags,
        "full_trade_pair_counts": pairs,
        "public_market_metadata_used": True,
        "private_api_used": False,
        "pnl_fields_parsed": False,
    }
    print(SENTINEL + json.dumps(probe, sort_keys=True, allow_nan=False))
    return 0


def append_ledger(root: Path, report: Mapping[str, Any]) -> None:
    path = root / LEDGER
    ledger = load(path)
    runs = ledger.get("qualification_runs")
    if not isinstance(runs, list) or len(runs) != 1 or runs[0].get("kind") != "PRE_PNL_RECURSIVE_ANALYSIS":
        raise common.GateError("lookahead must follow exactly one recursive run")
    runs.append({
        "kind": "PRE_PNL_LOOKAHEAD_ANALYSIS", "status": report["status"],
        "report_path": str(OUTPUT).replace("\\", "/"), "report_sha256": sha256(root / OUTPUT),
        "backtest_engine_used_for_bias_analysis": True, "pnl_parsed": False,
    })
    write(path, ledger)


def run_gate(root: Path, timeout: int) -> dict[str, Any]:
    manifest_hash, recursive_hash = validate_inputs(root)
    code_hash = validate_code(root, manifest_hash, recursive_hash)
    if (root / OUTPUT).exists():
        raise common.GateError("lookahead output exists")
    result = subprocess.run(build_command(root), cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    lines = [line[len(SENTINEL):] for line in combined.splitlines() if line.startswith(SENTINEL)]
    failures: list[str] = []
    details: dict[str, Any] = {}
    if result.returncode:
        failures.append(f"lookahead container exit {result.returncode}")
    if len(lines) != 1:
        failures.append("exact lookahead probe was not produced")
    else:
        passed, more, details = evaluate(json.loads(lines[0]))
        if not passed:
            failures.extend(more)
    report = {
        "schema_version": "1.0", "status": "PASS" if not failures else "FAIL",
        "decision": "CONTINUE_TO_TRAIN" if not failures else "REJECT_PRO_DAY_TRADER_V4",
        "cycle": "pro_day_v4_cycle1", "candidate": "ProDayTraderV4",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "recursive_report_sha256": recursive_hash,
        "code_freeze_sha256": code_hash, "runtime_image": IMAGE,
        "container_exit_code": result.returncode,
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "command_contract": {"timerange": TIMERANGE, "pairs": PAIRS,
                             "minimum_trade_amount": MINIMUM, "targeted_trade_amount": TARGETED,
                             "public_market_metadata": True, "private_api": False},
        "gate_details": details, "failures": failures,
        "bias_analysis_backtests_performed": True,
        "qualification_performance_backtest_performed": False,
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    write(root / OUTPUT, report, exclusive=True)
    append_ledger(root, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--freeze-code", action="store_true")
    parser.add_argument("--inside-container", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside_container:
        return inside()
    try:
        if args.freeze_code:
            record = freeze_code(args.workspace.resolve())
            print(json.dumps({"status": record["status"], "pnl_parsed": False}))
            return 0
        report = run_gate(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": report["status"], "decision": report["decision"], "pnl_parsed": False}))
        return 0 if report["status"] == "PASS" else 2
    except (common.GateError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
