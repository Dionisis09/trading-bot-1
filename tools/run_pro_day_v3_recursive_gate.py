#!/usr/bin/env python3
"""Run the frozen ProDayTraderV3 recursive gate without backtest or PnL parsing."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "freqtradeorg/freqtrade@sha256:"
    "da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
)
COUNTS = [199, 399, 799, 1599, 2399]
QUALIFICATION_COUNT = 399
MAX_VARIANCE = 0.0001
PAIR = "BTC/USDT:USDT"
TIMERANGE = "20250701-20250801"
SENTINEL = "PRO_DAY_V3_RECURSIVE_PROBE="
SIGNALS = {"enter_long", "enter_short", "exit_long", "exit_short"}
CANDIDATES = {
    "candidate_T1_long", "candidate_T1_short",
    "candidate_R1_long", "candidate_R1_short", "candidate_side",
}
MANIFEST = Path("user_data/reports/pro_day_v3_cycle1/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v3_cycle1/trial_ledger.json")
CODE_FREEZE = Path("user_data/reports/pro_day_v3_cycle1/recursive_gate_code_freeze.json")
OUTPUT = Path("user_data/reports/pro_day_v3_cycle1/recursive_analysis.json")
RUNNER = Path("tools/run_pro_day_v3_recursive_gate.py")
TESTS = Path("tools/test_run_pro_day_v3_recursive_gate.py")


class GateError(RuntimeError):
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
        raise GateError(f"invalid JSON object: {path}")
    return value


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
            raise GateError(f"refusing to overwrite {path}") from exc
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


def validate_manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / MANIFEST
    manifest = load(path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v3_cycle1":
        raise GateError("V3 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False or manifest.get("model_training_performed") is not False:
        raise GateError("V3 manifest crossed the pre-PnL boundary")
    files = manifest.get("files", {})
    for label in ("plan", "strategy", "base_strategy", "config", "risk_policy", "data_audit"):
        row = files.get(label, {})
        target = root / str(row.get("path", ""))
        if not target.is_file() or sha256(target) != row.get("sha256"):
            raise GateError(f"frozen input changed: {label}")
    parameters = manifest.get("frozen_parameters", {})
    if parameters.get("recursive_startup_counts") != COUNTS:
        raise GateError("recursive counts differ from freeze")
    if parameters.get("recursive_qualification_count") != QUALIFICATION_COUNT:
        raise GateError("recursive qualification count differs from freeze")
    for row in manifest.get("artifacts", {}).values():
        if row.get("status") != "PLANNED_NOT_RUN" or (root / row.get("path", "")).exists():
            raise GateError("qualification artifact exists before recursive gate")
    return manifest, sha256(path)


def freeze_code(root: Path) -> dict[str, Any]:
    _, manifest_hash = validate_manifest(root)
    if (root / OUTPUT).exists():
        raise GateError("recursive output already exists")
    payload = {
        "schema_version": "1.0",
        "status": "CODE_FROZEN_BEFORE_RECURSIVE_RUN",
        "cycle": "pro_day_v3_cycle1",
        "manifest_sha256": manifest_hash,
        "runner": {"path": str(RUNNER).replace("\\", "/"), "sha256": sha256(root / RUNNER)},
        "tests": {"path": str(TESTS).replace("\\", "/"), "sha256": sha256(root / TESTS)},
        "pnl_parsed": False,
        "live_trading_authorized": False,
    }
    write(root / CODE_FREEZE, payload, exclusive=True)
    return payload


def validate_code(root: Path, manifest_hash: str) -> str:
    record = load(root / CODE_FREEZE)
    if record.get("manifest_sha256") != manifest_hash:
        raise GateError("recursive code freeze references another manifest")
    for label, path in (("runner", RUNNER), ("tests", TESTS)):
        if record.get(label, {}).get("sha256") != sha256(root / path):
            raise GateError(f"frozen recursive {label} changed")
    return sha256(root / CODE_FREEZE)


def finite(value: Any) -> float | str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NONFINITE"
    return number if math.isfinite(number) else "NONFINITE"


def evaluate(probe: Mapping[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    if probe.get("candidate_counts") != COUNTS:
        failures.append("candidate counts differ")
    if probe.get("strategy_startup_candle_count") != QUALIFICATION_COUNT:
        failures.append("strategy startup count differs")
    if probe.get("pair") != PAIR or probe.get("timerange") != TIMERANGE:
        failures.append("pair or timerange differs")
    columns = set(probe.get("full_indicator_columns", []))
    missing = sorted((CANDIDATES | SIGNALS) - columns)
    if missing:
        failures.append("decision columns missing: " + ",".join(missing))
    recursive = probe.get("recursive_variance_fraction", {})
    violations: dict[str, Any] = {}
    signal_differences: list[str] = []
    for indicator, values in recursive.items():
        if not isinstance(values, Mapping) or str(QUALIFICATION_COUNT) not in values:
            continue
        value = finite(values[str(QUALIFICATION_COUNT)])
        if indicator in SIGNALS:
            signal_differences.append(str(indicator))
        elif value == "NONFINITE" or abs(float(value)) > MAX_VARIANCE:
            violations[str(indicator)] = value
    lookahead = sorted(set(probe.get("indicator_only_lookahead_columns", [])))
    if signal_differences:
        failures.append("entry/exit signal differences found")
    if violations:
        failures.append("indicator variance exceeds 0.01% or is non-finite")
    if lookahead:
        failures.append("indicator-only lookahead differences found")
    details = {
        "qualification_count": QUALIFICATION_COUNT,
        "maximum_variance_fraction": MAX_VARIANCE,
        "missing_decision_columns": missing,
        "variance_violations": violations,
        "signal_differences": sorted(signal_differences),
        "indicator_only_lookahead_columns": lookahead,
    }
    return not failures, failures, details


def build_command(root: Path) -> list[str]:
    return [
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{(root / 'tools').resolve()}:/freqtrade/tools:ro",
        "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
        "--entrypoint", "python", IMAGE,
        "/freqtrade/tools/run_pro_day_v3_recursive_gate.py", "--inside-container",
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
        "recursive-analysis", "--config", "/freqtrade/user_data/config-pro-day-v3-cycle1-research.json",
        "--userdir", "/freqtrade/user_data", "--strategy", "ProDayTraderV3",
        "--datadir", "/canonical", "--timerange", TIMERANGE,
        "--pairs", PAIR, "--startup-candle", *map(str, COUNTS), "--no-color",
    ]
    config = setup_utils_configuration(Arguments(argv).get_parsed_arg(), RunMode.UTIL_NO_EXCHANGE)
    config = RecursiveAnalysisSubFunctions.calculate_config_overrides(config)
    objects = [row for row in StrategyResolver.search_all_objects(config, enum_failed=False, recursive=False)
               if row.get("name") == "ProDayTraderV3"]
    if len(objects) != 1:
        raise GateError("ProDayTraderV3 is not uniquely discoverable")
    with get_progress_tracker() as progress:
        analysis = RecursiveAnalysis(config, objects[0])
        analysis.start(progress)
    recursive = {
        str(indicator): {str(count): finite(value) for count, value in sorted(values.items())}
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
        "timerange": TIMERANGE,
        "recursive_variance_fraction": recursive,
        "indicator_only_lookahead_columns": lookahead,
        "full_indicator_columns": [str(column) for column in full.columns],
        "model_training_performed": False,
        "backtest_performed": False,
        "pnl_parsed": False,
    }
    print(SENTINEL + json.dumps(probe, sort_keys=True, allow_nan=False))
    return 0


def append_ledger(root: Path, report: Mapping[str, Any]) -> None:
    path = root / LEDGER
    ledger = load(path)
    runs = ledger.get("qualification_runs")
    if not isinstance(runs, list) or runs:
        raise GateError("recursive qualification run already registered")
    runs.append({
        "kind": "PRE_PNL_RECURSIVE_ANALYSIS",
        "status": report["status"],
        "report_path": str(OUTPUT).replace("\\", "/"),
        "report_sha256": sha256(root / OUTPUT),
        "model_training_performed": False,
        "pnl_parsed": False,
    })
    write(path, ledger)


def run_gate(root: Path, timeout: int) -> dict[str, Any]:
    _, manifest_hash = validate_manifest(root)
    code_hash = validate_code(root, manifest_hash)
    if (root / OUTPUT).exists():
        raise GateError("recursive output already exists")
    result = subprocess.run(
        build_command(root), cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, check=False,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    probe_lines = [line[len(SENTINEL):] for line in combined.splitlines() if line.startswith(SENTINEL)]
    failures: list[str] = []
    details: dict[str, Any] = {}
    if result.returncode:
        failures.append(f"recursive container exit {result.returncode}")
    if len(probe_lines) != 1:
        failures.append("exact recursive probe was not produced")
    else:
        probe = json.loads(probe_lines[0])
        passed, probe_failures, details = evaluate(probe)
        if not passed:
            failures.extend(probe_failures)
    report = {
        "schema_version": "1.0",
        "status": "PASS" if not failures else "FAIL",
        "decision": "CONTINUE_TO_LOOKAHEAD" if not failures else "REJECT_PRO_DAY_TRADER_V3",
        "cycle": "pro_day_v3_cycle1",
        "candidate": "ProDayTraderV3",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash,
        "code_freeze_sha256": code_hash,
        "runtime_image": IMAGE,
        "container_exit_code": result.returncode,
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "command_contract": {"pair": PAIR, "timerange": TIMERANGE, "startup_counts": COUNTS},
        "gate_details": details,
        "failures": failures,
        "model_training_performed": False,
        "backtest_performed": False,
        "pnl_parsed": False,
        "live_trading_authorized": False,
    }
    write(root / OUTPUT, report, exclusive=True)
    append_ledger(root, report)
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
            result = freeze_code(args.workspace.resolve())
            print(json.dumps({"status": result["status"], "pnl_parsed": False}))
            return 0
        report = run_gate(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": report["status"], "decision": report["decision"], "pnl_parsed": False}))
        return 0 if report["status"] == "PASS" else 2
    except (GateError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
