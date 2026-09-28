#!/usr/bin/env python3
"""Cycle 2 recursive retry allowing only public exchange market metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import run_pro_day_v3_recursive_gate as gate


ROOT = Path(__file__).resolve().parents[1]
gate.MANIFEST = Path("user_data/reports/pro_day_v3_cycle2/research_freeze_manifest.json")
gate.LEDGER = Path("user_data/reports/pro_day_v3_cycle2/trial_ledger.json")
gate.CODE_FREEZE = Path("user_data/reports/pro_day_v3_cycle2/recursive_gate_code_freeze.json")
gate.OUTPUT = Path("user_data/reports/pro_day_v3_cycle2/recursive_analysis.json")
gate.RUNNER = Path("tools/run_pro_day_v3_cycle2_recursive_gate.py")
gate.TESTS = Path("tools/test_run_pro_day_v3_cycle2_recursive_gate.py")


def validate_manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / gate.MANIFEST
    manifest = gate.load(path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v3_cycle2":
        raise gate.GateError("V3 Cycle 2 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False or manifest.get("model_training_performed") is not False:
        raise gate.GateError("Cycle 2 manifest crossed the pre-PnL boundary")
    files = manifest.get("files", {})
    for label in ("plan", "strategy", "base_strategy", "config", "risk_policy", "data_audit"):
        row = files.get(label, {})
        target = root / str(row.get("path", ""))
        if not target.is_file() or gate.sha256(target) != row.get("sha256"):
            raise gate.GateError(f"frozen input changed: {label}")
    parameters = manifest.get("frozen_parameters", {})
    if parameters.get("recursive_startup_counts") != gate.COUNTS:
        raise gate.GateError("recursive counts differ from freeze")
    if parameters.get("recursive_qualification_count") != gate.QUALIFICATION_COUNT:
        raise gate.GateError("recursive qualification count differs from freeze")
    if parameters.get("public_market_metadata_transport") is not True:
        raise gate.GateError("public metadata transport is not locked")
    if parameters.get("private_api_transport") is not False:
        raise gate.GateError("private API transport is not forbidden")
    for row in manifest.get("artifacts", {}).values():
        if row.get("status") != "PLANNED_NOT_RUN" or (root / row.get("path", "")).exists():
            raise gate.GateError("qualification artifact exists before recursive gate")
    return manifest, gate.sha256(path)


def build_command(root: Path) -> list[str]:
    return [
        "docker", "run", "--rm",
        "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{(root / 'tools').resolve()}:/freqtrade/tools:ro",
        "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
        "--entrypoint", "python", gate.IMAGE,
        "/freqtrade/tools/run_pro_day_v3_cycle2_recursive_gate.py", "--inside-container",
    ]


def inside() -> int:
    from freqtrade.commands import Arguments
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.analysis.recursive import RecursiveAnalysis
    from freqtrade.optimize.analysis.recursive_helpers import RecursiveAnalysisSubFunctions
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.util import get_progress_tracker

    argv = [
        "recursive-analysis", "--config", "/freqtrade/user_data/config-pro-day-v3-cycle2-research.json",
        "--userdir", "/freqtrade/user_data", "--strategy", "ProDayTraderV3",
        "--datadir", "/canonical", "--timerange", gate.TIMERANGE,
        "--pairs", gate.PAIR, "--startup-candle", *map(str, gate.COUNTS), "--no-color",
    ]
    config = setup_utils_configuration(Arguments(argv).get_parsed_arg(), RunMode.UTIL_NO_EXCHANGE)
    config = RecursiveAnalysisSubFunctions.calculate_config_overrides(config)
    objects = [row for row in StrategyResolver.search_all_objects(config, enum_failed=False, recursive=False)
               if row.get("name") == "ProDayTraderV3"]
    if len(objects) != 1:
        raise gate.GateError("ProDayTraderV3 is not uniquely discoverable")
    with get_progress_tracker() as progress:
        analysis = RecursiveAnalysis(config, objects[0])
        analysis.start(progress)
    recursive = {
        str(indicator): {str(count): gate.finite(value) for count, value in sorted(values.items())}
        for indicator, values in sorted(analysis.dict_recursive.items())
    }
    full = analysis.full_varHolder.indicators[analysis.pair_to_used]
    partial = analysis.partial_varHolder_lookahead_array[0].indicators[analysis.pair_to_used].iloc[-1]
    full_row = full.loc[full["date"] == partial["date"]].iloc[-1]
    lookahead = sorted(str(item) for item in full_row.compare(partial).index)
    probe = {
        "candidate_counts": list(analysis._startup_candle),
        "strategy_startup_candle_count": analysis._strat_scc,
        "pair": analysis.pair_to_used,
        "timerange": gate.TIMERANGE,
        "recursive_variance_fraction": recursive,
        "indicator_only_lookahead_columns": lookahead,
        "full_indicator_columns": [str(column) for column in full.columns],
        "public_market_metadata_used": True,
        "private_api_used": False,
        "model_training_performed": False,
        "backtest_performed": False,
        "pnl_parsed": False,
    }
    print(gate.SENTINEL + json.dumps(probe, sort_keys=True, allow_nan=False))
    return 0


gate.validate_manifest = validate_manifest
gate.build_command = build_command


def run_gate(root: Path, timeout: int) -> dict[str, Any]:
    _, manifest_hash = validate_manifest(root)
    code_hash = gate.validate_code(root, manifest_hash)
    if (root / gate.OUTPUT).exists():
        raise gate.GateError("Cycle 2 recursive output already exists")
    result = subprocess.run(
        build_command(root), cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    probe_lines = [
        line[len(gate.SENTINEL):]
        for line in combined.splitlines()
        if line.startswith(gate.SENTINEL)
    ]
    failures: list[str] = []
    details: dict[str, Any] = {}
    if result.returncode:
        failures.append(f"recursive container exit {result.returncode}")
    if len(probe_lines) != 1:
        failures.append("exact recursive probe was not produced")
    else:
        probe = json.loads(probe_lines[0])
        if probe.get("public_market_metadata_used") is not True or probe.get("private_api_used") is not False:
            failures.append("transport evidence differs from locked public-only contract")
        passed, probe_failures, details = gate.evaluate(probe)
        if not passed:
            failures.extend(probe_failures)
    report = {
        "schema_version": "1.0",
        "status": "PASS" if not failures else "FAIL",
        "decision": "CONTINUE_TO_LOOKAHEAD" if not failures else "REJECT_PRO_DAY_TRADER_V3",
        "cycle": "pro_day_v3_cycle2",
        "candidate": "ProDayTraderV3",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash,
        "code_freeze_sha256": code_hash,
        "runtime_image": gate.IMAGE,
        "container_exit_code": result.returncode,
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "command_contract": {
            "pair": gate.PAIR, "timerange": gate.TIMERANGE,
            "startup_counts": gate.COUNTS, "public_market_metadata": True,
            "private_api": False,
        },
        "gate_details": details,
        "failures": failures,
        "model_training_performed": False,
        "backtest_performed": False,
        "pnl_parsed": False,
        "live_trading_authorized": False,
    }
    gate.write(root / gate.OUTPUT, report, exclusive=True)
    gate.append_ledger(root, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--freeze-code", action="store_true")
    parser.add_argument("--inside-container", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside_container:
        return inside()
    root = args.workspace.resolve()
    try:
        if args.freeze_code:
            result = gate.freeze_code(root)
            print(json.dumps({"status": result["status"], "pnl_parsed": False}))
            return 0
        report = run_gate(root, args.timeout_seconds)
        print(json.dumps({"status": report["status"], "decision": report["decision"], "pnl_parsed": False}))
        return 0 if report["status"] == "PASS" else 2
    except (gate.GateError, OSError, ValueError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
