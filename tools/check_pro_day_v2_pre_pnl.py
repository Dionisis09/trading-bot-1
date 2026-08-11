#!/usr/bin/env python3
"""Run and record ProDayTraderV2 technical gates without model fitting or PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "freqtradeorg/freqtrade@sha256:"
    "2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
)
OUTPUT = Path("user_data/reports/pro_day_v2_cycle1/pre_pnl_technical_evidence.json")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class TechnicalGateError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(runner: Runner, command: list[str], timeout: int) -> str:
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TechnicalGateError(f"Technical command could not run: {command[0]}") from exc
    if result.returncode != 0:
        raise TechnicalGateError(f"Technical command failed: {command[0]} exit={result.returncode}")
    return (result.stdout or "") + "\n" + (result.stderr or "")


def _test_count(output: str, label: str) -> int:
    matches = re.findall(r"Ran\s+(\d+)\s+tests?", output)
    if len(matches) != 1:
        raise TechnicalGateError(f"Could not prove exact test count for {label}")
    return int(matches[0])


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TechnicalGateError(f"Invalid {label}") from exc
    if not isinstance(value, dict):
        raise TechnicalGateError(f"{label} must be an object")
    return value


def collect_evidence(*, runner: Runner = subprocess.run, timeout: int = 180) -> dict[str, Any]:
    local_patterns = (
        ("canonical_data", "test_build_pro_day_v2_canonical_data.py", 4),
        ("runtime", "test_check_pro_day_v2_runtime.py", 4),
        ("freeze", "test_freeze_pro_day_v2_research.py", 5),
    )
    tests: dict[str, dict[str, Any]] = {}
    for label, pattern, expected in local_patterns:
        output = _run(
            runner,
            [sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", pattern, "-v"],
            timeout,
        )
        count = _test_count(output, label)
        if count != expected:
            raise TechnicalGateError(f"{label} test count changed: {count} != {expected}")
        tests[label] = {"status": "PASS", "tests": count, "pattern": pattern}

    user_volume = f"{(ROOT / 'user_data').resolve()}:/freqtrade/user_data"
    tools_volume = f"{(ROOT / 'tools').resolve()}:/freqtrade/tools:ro"
    strategy_output = _run(
        runner,
        [
            "docker", "run", "--rm", "--network", "none",
            "-v", user_volume, "-v", tools_volume,
            "--entrypoint", "python", IMAGE,
            "-m", "unittest", "discover", "-s", "/freqtrade/tools",
            "-p", "test_pro_day_trader_v2.py", "-v",
        ],
        timeout,
    )
    strategy_count = _test_count(strategy_output, "strategy")
    if strategy_count != 11:
        raise TechnicalGateError(f"strategy test count changed: {strategy_count} != 11")
    tests["strategy"] = {
        "status": "PASS",
        "tests": strategy_count,
        "pattern": "test_pro_day_trader_v2.py",
        "runtime_image": IMAGE,
        "network_mode": "none",
    }

    config_path = "/freqtrade/user_data/config-pro-day-v2-research.json"
    show_output = _run(
        runner,
        ["docker", "run", "--rm", "--network", "none", "-v", user_volume,
         IMAGE, "show-config", "--config", config_path],
        timeout,
    )
    # Output is deliberately discarded; only the zero exit status is evidence.
    del show_output
    discovery = _run(
        runner,
        ["docker", "run", "--rm", "--network", "none", "-v", user_volume,
         IMAGE, "list-strategies", "--config", config_path],
        timeout,
    )
    matching_lines = [line for line in discovery.splitlines() if "ProDayTraderV2" in line]
    if len(matching_lines) != 1 or "OK" not in matching_lines[0]:
        raise TechnicalGateError("ProDayTraderV2 discovery is not uniquely OK")

    compile_targets = [
        ROOT / "user_data/strategies/ProDayTraderV2.py",
        ROOT / "tools/build_pro_day_v2_canonical_data.py",
        ROOT / "tools/check_pro_day_v2_runtime.py",
        ROOT / "tools/freeze_pro_day_v2_research.py",
    ]
    _run(runner, [sys.executable, "-m", "py_compile", *map(str, compile_targets)], timeout)

    data_report = _load_json(
        ROOT / "user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json", "data report"
    )
    runtime_report = _load_json(
        ROOT / "user_data/reports/pro_day_v2_cycle1/runtime_compatibility.json", "runtime report"
    )
    if data_report.get("status") != "PASS" or data_report.get("pnl_evaluated") is not False:
        raise TechnicalGateError("Canonical data report is not a no-PnL PASS")
    if (
        runtime_report.get("status") != "PASS"
        or runtime_report.get("pnl_evaluated") is not False
        or runtime_report.get("model_training_performed") is not False
    ):
        raise TechnicalGateError("Runtime report is not a no-training/no-PnL PASS")

    sources = {
        str(path.relative_to(ROOT)).replace("\\", "/"): _hash(path)
        for path in [
            ROOT / "docs/pro_day_trader_v2_locked_plan.md",
            ROOT / "user_data/strategies/ProDayTraderV2.py",
            ROOT / "user_data/config-pro-day-v2-research.json",
            *compile_targets[1:],
            ROOT / "tools/test_build_pro_day_v2_canonical_data.py",
            ROOT / "tools/test_check_pro_day_v2_runtime.py",
            ROOT / "tools/test_freeze_pro_day_v2_research.py",
            ROOT / "tools/test_pro_day_trader_v2.py",
        ]
    }
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "candidate": "ProDayTraderV2",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tests": tests,
        "total_tests": sum(row["tests"] for row in tests.values()),
        "python_compile": "PASS",
        "config_validation": "PASS_OUTPUT_SUPPRESSED",
        "strategy_discovery": "PASS_UNIQUE_STATUS_OK",
        "data_gate": "PASS",
        "runtime_gate": "PASS",
        "source_sha256": sources,
        "network_mode_for_container_checks": "none",
        "model_training_performed": False,
        "backtest_performed": False,
        "pnl_evaluated": False,
        "live_trading_authorized": False,
        "lookahead_analysis": "PENDING_AFTER_FREEZE",
        "recursive_analysis": "PENDING_AFTER_FREEZE",
        "evidence_boundary": (
            "Unit/parity, syntax, config, discovery, data, and runtime compatibility only; "
            "no model fit, backtest, PnL, deployment, forward evidence, or live authorization."
        ),
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        report = collect_evidence(timeout=args.timeout_seconds)
        _atomic_write(args.output, report)
    except (TechnicalGateError, OSError, ValueError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": report["status"], "total_tests": report["total_tests"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
