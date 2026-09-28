#!/usr/bin/env python3
"""Run the locked Cycle 2 recursive gate without parsing qualification PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "freqtradeorg/freqtrade@sha256:"
    "2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
)
IDENTIFIER = "proday-v2-cycle2-canonical5m-lgbm-20260811"
COUNTS = [199, 399, 799, 1599, 2399]
QUALIFICATION_COUNT = 399
MAX_VARIANCE_FRACTION = 0.0001  # 0.01%
PAIR = "BTC/USDT:USDT"
TIMERANGE = "20250701-20250801"
TARGET = "&-candidate_net_log_return"
SENTINEL = "PRO_DAY_V2_RECURSIVE_PROBE="

MANIFEST = Path("user_data/reports/pro_day_v2_cycle2/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v2_cycle2/trial_ledger.json")
CODE_FREEZE = Path("user_data/reports/pro_day_v2_cycle2/recursive_gate_code_freeze.json")
OUTPUT = Path("user_data/reports/pro_day_v2_cycle2/recursive_analysis.json")
MODEL_ROOT = Path("user_data/reports/pro_day_v2_cycle2/technical_recursive_models")
NORMAL_MODEL = Path("user_data/models") / IDENTIFIER
RUNNER = Path("tools/run_pro_day_v2_cycle2_recursive_gate.py")
TESTS = Path("tools/test_run_pro_day_v2_cycle2_recursive_gate.py")
CONFIG = Path("user_data/config-pro-day-v2-cycle2-research.json")
CANONICAL = Path("user_data/data/binance/pro_day_v2_canonical")

FEATURES = {
    "%-ret_5m_1", "%-ret_5m_3", "%-ret_5m_12", "%-ema_gap_atr_15m",
    "%-momentum_1h_24", "%-adx_1h_14", "%-trend_gap_atr_4h",
    "%-channel_position_15m_20", "%-z48_5m", "%-atr_close_5m_14",
    "%-realized_vol_5m_24h", "%-log_volume_vs_median_5m_20",
    "%-btc_momentum_1h_24", "%-btc_trend_gap_atr_4h",
    "%-btc_realized_vol_5m_24h", "%-pair_minus_btc_momentum_1h_24",
    "%-setup_T1", "%-setup_R1", "%-candidate_side",
}
SIGNALS = {"enter_long", "enter_short", "exit_long", "exit_short"}
CANDIDATES = {
    "candidate_T1_long", "candidate_T1_short",
    "candidate_R1_long", "candidate_R1_short", "candidate_any",
}


class GateError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"Invalid {label}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} root must be an object")
    return value


def atomic_write(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise GateError(f"Refusing to overwrite {path.name}") from exc
        return
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


def _manifest_record(manifest: Mapping[str, Any], relative: str) -> Mapping[str, Any]:
    stack: list[Any] = [manifest.get("files"), manifest.get("inputs")]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            if str(value.get("path", "")).replace("\\", "/") == relative:
                return value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    raise GateError(f"Manifest record missing for {relative}")


def validate_manifest(workspace: Path) -> tuple[dict[str, Any], str]:
    path = workspace / MANIFEST
    manifest = load_json(path, "Cycle 2 manifest")
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v2_cycle2":
        raise GateError("Cycle 2 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False or manifest.get("model_training_performed") is not False:
        raise GateError("Manifest pre-run boundary is invalid")
    required = (
        "docs/pro_day_trader_v2_cycle2_locked_plan.md",
        "docs/pro_day_trader_v2_locked_plan.md",
        "user_data/strategies/ProDayTraderV2.py",
        "user_data/config-pro-day-v2-cycle2-research.json",
    )
    for relative in required:
        record = _manifest_record(manifest, relative)
        target = workspace / Path(relative)
        if not target.is_file() or sha256(target) != record.get("sha256"):
            raise GateError(f"Frozen input changed: {relative}")
    params = manifest.get("frozen_parameters")
    if not isinstance(params, Mapping):
        raise GateError("Frozen parameters are missing")
    if params.get("recursive_startup_counts") != COUNTS:
        raise GateError("Recursive counts differ from freeze")
    if params.get("recursive_qualification_count") != QUALIFICATION_COUNT:
        raise GateError("Recursive qualification count differs from freeze")
    if params.get("identifier") != IDENTIFIER or params.get("purge_old_models") != 0:
        raise GateError("Cycle 2 model isolation differs from freeze")
    for record in manifest.get("artifacts", {}).values():
        if not isinstance(record, Mapping) or record.get("status") != "PLANNED_NOT_RUN":
            raise GateError("Qualification artifact state is not pre-run")
        if (workspace / Path(str(record.get("path")))).exists():
            raise GateError("A qualification artifact exists before recursive analysis")
    return manifest, sha256(path)


def freeze_code(workspace: Path) -> dict[str, Any]:
    _, manifest_hash = validate_manifest(workspace)
    runner = workspace / RUNNER
    tests = workspace / TESTS
    if not runner.is_file() or not tests.is_file():
        raise GateError("Recursive runner or tests are missing")
    output = workspace / OUTPUT
    model_root = workspace / MODEL_ROOT
    normal_model = workspace / NORMAL_MODEL
    if output.exists() or normal_model.exists():
        raise GateError("Recursive output or qualification model cache already exists")
    if model_root.exists() and (not model_root.is_dir() or any(model_root.iterdir())):
        raise GateError("Technical recursive model root is not empty")
    payload = {
        "schema_version": "1.0",
        "status": "CODE_FROZEN_BEFORE_RECURSIVE_RUN",
        "cycle": "pro_day_v2_cycle2",
        "manifest_sha256": manifest_hash,
        "runner": {"path": str(RUNNER).replace("\\", "/"), "sha256": sha256(runner)},
        "tests": {"path": str(TESTS).replace("\\", "/"), "sha256": sha256(tests)},
        "planned_output": str(OUTPUT).replace("\\", "/"),
        "pnl_parsed": False,
        "live_trading_authorized": False,
    }
    atomic_write(workspace / CODE_FREEZE, payload, exclusive=True)
    return payload


def validate_code_freeze(workspace: Path, manifest_hash: str) -> str:
    path = workspace / CODE_FREEZE
    record = load_json(path, "recursive code freeze")
    if record.get("status") != "CODE_FROZEN_BEFORE_RECURSIVE_RUN":
        raise GateError("Recursive code is not frozen")
    if record.get("manifest_sha256") != manifest_hash:
        raise GateError("Recursive code freeze references another manifest")
    for key, relative in (("runner", RUNNER), ("tests", TESTS)):
        item = record.get(key)
        if not isinstance(item, Mapping) or item.get("sha256") != sha256(workspace / relative):
            raise GateError(f"Frozen recursive {key} changed")
    return sha256(path)


def _finite_or_token(value: Any) -> float | str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "NONFINITE"
    return numeric if math.isfinite(numeric) else "NONFINITE"


def evaluate_probe(probe: Mapping[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    if probe.get("candidate_counts") != COUNTS:
        failures.append("candidate counts differ")
    if probe.get("strategy_startup_candle_count") != QUALIFICATION_COUNT:
        failures.append("strategy startup count differs")
    if probe.get("pair") != PAIR or probe.get("timerange") != TIMERANGE:
        failures.append("pair or timerange differs")
    columns = set(probe.get("full_indicator_columns", []))
    missing_features = sorted(FEATURES - columns)
    missing_candidates = sorted(CANDIDATES - columns)
    if missing_features:
        failures.append("missing frozen features: " + ",".join(missing_features))
    if missing_candidates:
        failures.append("missing candidate columns: " + ",".join(missing_candidates))
    recursive = probe.get("recursive_variance_fraction")
    if not isinstance(recursive, Mapping):
        failures.append("recursive variance mapping missing")
        recursive = {}
    violations: dict[str, Any] = {}
    signal_differences: list[str] = []
    for indicator, values in recursive.items():
        if not isinstance(values, Mapping) or str(QUALIFICATION_COUNT) not in values:
            continue
        value = _finite_or_token(values[str(QUALIFICATION_COUNT)])
        if indicator in SIGNALS:
            signal_differences.append(str(indicator))
            continue
        if indicator == TARGET:
            continue
        if value == "NONFINITE" or abs(float(value)) > MAX_VARIANCE_FRACTION:
            violations[str(indicator)] = value
    if signal_differences:
        failures.append("entry/exit signal differences found")
    if violations:
        failures.append("indicator variance exceeds 0.01% or is non-finite")
    lookahead = set(probe.get("indicator_only_lookahead_columns", []))
    unexpected_lookahead = sorted(lookahead - {TARGET})
    if unexpected_lookahead:
        failures.append("non-target indicator lookahead found")
    details = {
        "qualification_count": QUALIFICATION_COUNT,
        "maximum_variance_fraction": MAX_VARIANCE_FRACTION,
        "variance_violations": violations,
        "signal_differences": sorted(signal_differences),
        "raw_indicator_only_lookahead_columns": sorted(lookahead),
        "allowed_target_only_lookahead": TARGET if TARGET in lookahead else None,
        "unexpected_indicator_lookahead_columns": unexpected_lookahead,
        "feature_schema_complete": not missing_features,
        "candidate_schema_complete": not missing_candidates,
    }
    return not failures, failures, details


def inventory(root: Path) -> dict[str, Any]:
    records = []
    if root.is_dir():
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "file_count": len(records),
        "total_bytes": sum(row["bytes"] for row in records),
        "inventory_sha256": hashlib.sha256(encoded).hexdigest(),
        "files": records,
    }


def build_command(workspace: Path) -> list[str]:
    user_data = workspace / "user_data"
    tools = workspace / "tools"
    canonical = workspace / CANONICAL
    models = workspace / MODEL_ROOT
    return [
        "docker", "run", "--rm",
        "-v", f"{user_data.resolve()}:/freqtrade/user_data:ro",
        "-v", f"{tools.resolve()}:/freqtrade/tools:ro",
        "-v", f"{canonical.resolve()}:/canonical/futures:ro",
        "-v", f"{models.resolve()}:/freqtrade/user_data/models:rw",
        "--entrypoint", "python", IMAGE,
        "/freqtrade/tools/run_pro_day_v2_cycle2_recursive_gate.py",
        "--inside-container",
    ]


def _inside_container() -> int:
    from freqtrade.commands import Arguments
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.analysis.recursive import RecursiveAnalysis
    from freqtrade.optimize.analysis.recursive_helpers import RecursiveAnalysisSubFunctions
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.util import get_progress_tracker

    argv = [
        "recursive-analysis",
        "--config", "/freqtrade/user_data/config-pro-day-v2-cycle2-research.json",
        "--userdir", "/freqtrade/user_data",
        "--strategy", "ProDayTraderV2",
        "--freqaimodel", "LightGBMRegressor",
        "--datadir", "/canonical",
        "--timerange", TIMERANGE,
        "--pairs", PAIR,
        "--startup-candle", *map(str, COUNTS),
        "--no-color",
    ]
    args = Arguments(argv).get_parsed_arg()
    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)
    config = RecursiveAnalysisSubFunctions.calculate_config_overrides(config)
    objects = [
        item for item in StrategyResolver.search_all_objects(config, enum_failed=False, recursive=False)
        if item.get("name") == "ProDayTraderV2"
    ]
    if len(objects) != 1:
        raise GateError("ProDayTraderV2 is not uniquely discoverable inside the pinned image")
    with get_progress_tracker() as progress:
        instance = RecursiveAnalysis(config, objects[0])
        instance.start(progress)

    recursive: dict[str, dict[str, float | str]] = {}
    for indicator, values in sorted(instance.dict_recursive.items()):
        recursive[str(indicator)] = {
            str(count): _finite_or_token(value) for count, value in sorted(values.items())
        }
    full_frame = instance.full_varHolder.indicators[instance.pair_to_used]
    partial = instance.partial_varHolder_lookahead_array[0]
    partial_row = partial.indicators[instance.pair_to_used].iloc[-1]
    date_to_check = partial_row["date"]
    full_row = full_frame.loc[full_frame["date"] == date_to_check].iloc[-1]
    indicator_lookahead = sorted(str(item) for item in full_row.compare(partial_row).index)
    probe = {
        "schema_version": "1.0",
        "candidate_counts": list(instance._startup_candle),
        "strategy_startup_candle_count": instance._strat_scc,
        "pair": instance.pair_to_used,
        "timerange": TIMERANGE,
        "recursive_variance_fraction": recursive,
        "indicator_only_lookahead_columns": indicator_lookahead,
        "full_indicator_columns": [str(column) for column in full_frame.columns],
        "model_training_performed": True,
        "pnl_parsed": False,
    }
    print(SENTINEL + json.dumps(probe, sort_keys=True, allow_nan=False))
    return 0


def append_ledger(workspace: Path, record: Mapping[str, Any]) -> None:
    path = workspace / LEDGER
    ledger = load_json(path, "trial ledger")
    runs = ledger.get("qualification_runs")
    if not isinstance(runs, list):
        raise GateError("Trial ledger qualification_runs is invalid")
    if any(isinstance(item, Mapping) and item.get("kind") == "PRE_PNL_RECURSIVE_ANALYSIS" for item in runs):
        raise GateError("Recursive run is already registered")
    runs.append(dict(record))
    ledger["qualification_runs"] = runs
    atomic_write(path, ledger)


def run_gate(workspace: Path, timeout: int) -> dict[str, Any]:
    manifest, manifest_hash = validate_manifest(workspace)
    code_hash = validate_code_freeze(workspace, manifest_hash)
    output = workspace / OUTPUT
    model_root = workspace / MODEL_ROOT
    normal_model = workspace / NORMAL_MODEL
    if output.exists() or normal_model.exists():
        raise GateError("Recursive output or qualification model cache already exists")
    if model_root.exists() and (not model_root.is_dir() or any(model_root.iterdir())):
        raise GateError("Technical recursive model root is not empty")
    model_root.mkdir(parents=True, exist_ok=True)
    command = build_command(workspace)
    try:
        completed = subprocess.run(
            command, cwd=workspace, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateError("Recursive container could not complete") from exc
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    output_digest = hashlib.sha256(combined.encode("utf-8", errors="replace")).hexdigest()
    probe_lines = [line[len(SENTINEL):] for line in combined.splitlines() if line.startswith(SENTINEL)]
    probe: dict[str, Any] = {}
    failures: list[str] = []
    details: dict[str, Any] = {}
    if completed.returncode != 0:
        failures.append(f"recursive container exit {completed.returncode}")
    if len(probe_lines) != 1:
        failures.append("exact recursive probe result was not produced")
    else:
        try:
            parsed = json.loads(probe_lines[0])
            if not isinstance(parsed, dict):
                raise ValueError("probe root")
            probe = parsed
            passed, probe_failures, details = evaluate_probe(probe)
            if not passed:
                failures.extend(probe_failures)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            failures.append(f"recursive probe is invalid: {type(exc).__name__}")
    model_inventory = inventory(model_root)
    if model_inventory["file_count"] == 0:
        failures.append("technical model inventory is empty")
    report = {
        "schema_version": "1.0",
        "status": "PASS" if not failures else "FAIL",
        "decision": "CONTINUE_TO_LOOKAHEAD" if not failures else "REJECT_PRO_DAY_TRADER_V2",
        "cycle": "pro_day_v2_cycle2",
        "candidate": "ProDayTraderV2",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash,
        "code_freeze_sha256": code_hash,
        "runtime_image": IMAGE,
        "container_exit_code": completed.returncode,
        "captured_output_sha256": output_digest,
        "command_contract": {
            "pair": PAIR,
            "timerange": TIMERANGE,
            "startup_counts": COUNTS,
            "canonical_mount": "/canonical/futures:ro",
            "container_datadir": "/canonical",
            "technical_model_root": str(MODEL_ROOT).replace("\\", "/"),
            "public_exchange_metadata_only": True,
        },
        "gate_details": details,
        "failures": failures,
        "model_inventory": model_inventory,
        "model_training_performed": True,
        "qualification_model": False,
        "backtest_performed": False,
        "pnl_parsed": False,
        "live_trading_authorized": False,
    }
    atomic_write(output, report, exclusive=True)
    report_hash = sha256(output)
    append_ledger(
        workspace,
        {
            "kind": "PRE_PNL_RECURSIVE_ANALYSIS",
            "status": report["status"],
            "report_path": str(OUTPUT).replace("\\", "/"),
            "report_sha256": report_hash,
            "model_training_performed": True,
            "pnl_parsed": False,
        },
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--freeze-code", action="store_true")
    parser.add_argument("--inside-container", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside_container:
        return _inside_container()
    workspace = args.workspace.resolve()
    try:
        if args.freeze_code:
            result = freeze_code(workspace)
            print(json.dumps({"status": result["status"], "pnl_parsed": False}, sort_keys=True))
            return 0
        report = run_gate(workspace, args.timeout_seconds)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "decision": report["decision"],
                    "pnl_parsed": False,
                },
                sort_keys=True,
            )
        )
        return 0 if report["status"] == "PASS" else 2
    except (GateError, OSError, ValueError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
