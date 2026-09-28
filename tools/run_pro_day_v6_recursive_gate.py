#!/usr/bin/env python3
"""Run frozen V6 recursive analysis before lookahead or PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import run_pro_day_v3_recursive_gate as base


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION = 2399
base.QUALIFICATION_COUNT = QUALIFICATION
base.MANIFEST = Path("user_data/reports/pro_day_v6_cycle1/research_freeze_manifest.json")
base.LEDGER = Path("user_data/reports/pro_day_v6_cycle1/trial_ledger.json")
base.CODE_FREEZE = Path("user_data/reports/pro_day_v6_cycle1/recursive_gate_code_freeze.json")
base.OUTPUT = Path("user_data/reports/pro_day_v6_cycle1/recursive_analysis.json")
base.RUNNER = Path("tools/run_pro_day_v6_recursive_gate.py")
base.TESTS = Path("tools/test_run_pro_day_v6_recursive_gate.py")


def validate_manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / base.MANIFEST
    manifest = base.load(path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v6_cycle1":
        raise base.GateError("V6 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False:
        raise base.GateError("manifest crossed PnL boundary")
    for label in ("plan", "strategy", "v5_parent", "config", "risk_policy", "data_audit"):
        row = manifest.get("files", {}).get(label, {})
        path = root / str(row.get("path", ""))
        if not path.is_file() or base.sha256(path) != row.get("sha256"):
            raise base.GateError(f"frozen input changed: {label}")
    params = manifest.get("frozen_parameters", {})
    if params.get("recursive_startup_counts") != base.COUNTS or params.get("recursive_qualification_count") != QUALIFICATION:
        raise base.GateError("recursive contract differs")
    for row in manifest.get("artifacts", {}).values():
        if row.get("status") != "PLANNED_NOT_RUN" or (root / row.get("path", "")).exists():
            raise base.GateError("qualification artifact exists")
    return manifest, base.sha256(root / base.MANIFEST)


def evaluate(probe: Mapping[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    if probe.get("candidate_counts") != base.COUNTS or probe.get("strategy_startup_candle_count") != QUALIFICATION:
        failures.append("startup contract differs")
    columns = set(probe.get("full_indicator_columns", []))
    missing = sorted(base.CANDIDATES - columns)
    if missing:
        failures.append("candidate columns missing: " + ",".join(missing))
    violations: dict[str, Any] = {}
    signals: list[str] = []
    for indicator, values in probe.get("recursive_variance_fraction", {}).items():
        if not isinstance(values, Mapping) or str(QUALIFICATION) not in values:
            continue
        value = base.finite(values[str(QUALIFICATION)])
        if indicator in base.SIGNALS:
            signals.append(str(indicator))
        elif value == "NONFINITE" or abs(float(value)) > base.MAX_VARIANCE:
            violations[str(indicator)] = value
    lookahead = sorted(set(probe.get("indicator_only_lookahead_columns", [])))
    if signals:
        failures.append("entry/exit signal differences found")
    if violations:
        failures.append("indicator variance exceeds 0.01%")
    if lookahead:
        failures.append("indicator-only lookahead differences found")
    details = {"qualification_count": QUALIFICATION, "missing_candidate_columns": missing,
               "variance_violations": violations, "signal_differences": sorted(signals),
               "indicator_only_lookahead_columns": lookahead}
    return not failures, failures, details


def build_command(root: Path) -> list[str]:
    return ["docker", "run", "--rm",
            "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
            "-v", f"{(root / 'tools').resolve()}:/freqtrade/tools:ro",
            "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
            "--entrypoint", "python", base.IMAGE,
            "/freqtrade/tools/run_pro_day_v6_recursive_gate.py", "--inside-container"]


def inside() -> int:
    from freqtrade.commands import Arguments
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.analysis.recursive import RecursiveAnalysis
    from freqtrade.optimize.analysis.recursive_helpers import RecursiveAnalysisSubFunctions
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.util import get_progress_tracker

    argv = ["recursive-analysis", "--config", "/freqtrade/user_data/config-pro-day-v6-cycle1-research.json",
            "--userdir", "/freqtrade/user_data", "--strategy", "ProDayTraderV6",
            "--datadir", "/canonical", "--timerange", base.TIMERANGE,
            "--pairs", base.PAIR, "--startup-candle", *map(str, base.COUNTS), "--no-color"]
    config = setup_utils_configuration(Arguments(argv).get_parsed_arg(), RunMode.UTIL_NO_EXCHANGE)
    config = RecursiveAnalysisSubFunctions.calculate_config_overrides(config)
    objects = [row for row in StrategyResolver.search_all_objects(config, enum_failed=False, recursive=False)
               if row.get("name") == "ProDayTraderV6"]
    if len(objects) != 1:
        raise base.GateError("ProDayTraderV6 is not uniquely discoverable")
    with get_progress_tracker() as progress:
        analysis = RecursiveAnalysis(config, objects[0]); analysis.start(progress)
    full = analysis.full_varHolder.indicators[analysis.pair_to_used]
    partial = analysis.partial_varHolder_lookahead_array[0].indicators[analysis.pair_to_used].iloc[-1]
    full_row = full.loc[full["date"] == partial["date"]].iloc[-1]
    probe = {
        "candidate_counts": list(analysis._startup_candle),
        "strategy_startup_candle_count": analysis._strat_scc,
        "pair": analysis.pair_to_used, "timerange": base.TIMERANGE,
        "recursive_variance_fraction": {
            str(indicator): {str(count): base.finite(value) for count, value in sorted(values.items())}
            for indicator, values in sorted(analysis.dict_recursive.items())
        },
        "indicator_only_lookahead_columns": sorted(str(item) for item in full_row.compare(partial).index),
        "full_indicator_columns": [str(column) for column in full.columns],
        "public_market_metadata_used": True, "private_api_used": False,
        "model_training_performed": False, "backtest_performed": False, "pnl_parsed": False,
    }
    print(base.SENTINEL + json.dumps(probe, sort_keys=True, allow_nan=False))
    return 0


base.validate_manifest = validate_manifest
base.build_command = build_command


def run_gate(root: Path, timeout: int) -> dict[str, Any]:
    _, manifest_hash = validate_manifest(root)
    code_hash = base.validate_code(root, manifest_hash)
    result = subprocess.run(build_command(root), cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    lines = [line[len(base.SENTINEL):] for line in combined.splitlines() if line.startswith(base.SENTINEL)]
    failures: list[str] = []
    details: dict[str, Any] = {}
    if result.returncode:
        failures.append(f"recursive container exit {result.returncode}")
    if len(lines) != 1:
        failures.append("exact recursive probe missing")
    else:
        passed, more, details = evaluate(json.loads(lines[0]))
        if not passed:
            failures.extend(more)
    report = {
        "schema_version": "1.0", "status": "PASS" if not failures else "FAIL",
        "decision": "CONTINUE_TO_LOOKAHEAD" if not failures else "REJECT_PRO_DAY_TRADER_V6",
        "cycle": "pro_day_v6_cycle1", "candidate": "ProDayTraderV6",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "code_freeze_sha256": code_hash,
        "runtime_image": base.IMAGE, "container_exit_code": result.returncode,
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "gate_details": details, "failures": failures,
        "model_training_performed": False, "backtest_performed": False,
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    base.write(root / base.OUTPUT, report, exclusive=True)
    base.append_ledger(root, report)
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
    try:
        if args.freeze_code:
            record = base.freeze_code(args.workspace.resolve())
            print(json.dumps({"status": record["status"], "pnl_parsed": False})); return 0
        report = run_gate(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": report["status"], "decision": report["decision"], "pnl_parsed": False}))
        return 0 if report["status"] == "PASS" else 2
    except (base.GateError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
