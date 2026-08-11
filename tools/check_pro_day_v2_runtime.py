#!/usr/bin/env python3
"""Validate the pinned ProDayTraderV2 FreqAI image without training or PnL."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "freqtradeorg/freqtrade@sha256:"
    "2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
)
EXPECTED_DIGEST = "sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000"
DEFAULT_OUTPUT = Path("user_data/reports/pro_day_v2_cycle1/runtime_compatibility.json")


class RuntimeCheckError(RuntimeError):
    """Raised when the research-only runtime fails closed validation."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(runner: Runner, command: list[str], timeout: int) -> str:
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeCheckError(f"Command could not run: {command[0]}: {exc}") from exc
    if result.returncode != 0:
        # Do not echo stderr: third-party diagnostics can contain host-specific data.
        raise RuntimeCheckError(f"Command failed closed: {command[0]} exit={result.returncode}")
    return result.stdout.strip()


def _parse_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeCheckError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeCheckError(f"{label} must return a JSON object")
    return value


def validate_runtime(*, runner: Runner = subprocess.run, timeout: int = 30) -> dict[str, Any]:
    inspect_raw = _run(runner, ["docker", "image", "inspect", IMAGE], timeout)
    try:
        inspect_list = json.loads(inspect_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeCheckError("docker image inspect did not return valid JSON") from exc
    if not isinstance(inspect_list, list) or len(inspect_list) != 1 or not isinstance(inspect_list[0], dict):
        raise RuntimeCheckError("docker image inspect returned an unexpected payload")
    inspected = inspect_list[0]
    config = inspected.get("Config")
    if not isinstance(config, dict):
        raise RuntimeCheckError("Image Config metadata is missing")
    repo_digests = inspected.get("RepoDigests")
    expected_repo_digest = f"freqtradeorg/freqtrade@{EXPECTED_DIGEST}"
    checks = {
        "repo_digest": isinstance(repo_digests, list) and expected_repo_digest in repo_digests,
        "architecture": inspected.get("Architecture") == "amd64",
        "operating_system": inspected.get("Os") == "linux",
        "user": config.get("User") == "ftuser",
        "working_directory": config.get("WorkingDir") == "/freqtrade",
    }

    probe_code = (
        "import json,platform,sys,freqtrade,lightgbm,datasieve;"
        "from freqtrade.freqai.prediction_models.LightGBMRegressor "
        "import LightGBMRegressor;"
        "print(json.dumps({'freqtrade':freqtrade.__version__,"
        "'lightgbm':lightgbm.__version__,'datasieve':True,"
        "'model':LightGBMRegressor.__name__,'machine':platform.machine(),"
        "'python':platform.python_version()}))"
    )
    probe_raw = _run(
        runner,
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            IMAGE,
            "-c",
            probe_code,
        ],
        timeout,
    )
    probe = _parse_object(probe_raw.splitlines()[-1] if probe_raw else "", "runtime probe")
    checks.update(
        {
            "freqtrade_version": probe.get("freqtrade") == "2026.7",
            "lightgbm_version": probe.get("lightgbm") == "4.7.0",
            "datasieve_import": probe.get("datasieve") is True,
            "lightgbm_regressor": probe.get("model") == "LightGBMRegressor",
            "container_machine": probe.get("machine") in {"x86_64", "amd64"},
        }
    )
    status = "PASS" if all(checks.values()) else "TECHNICAL_BLOCKED"
    return {
        "schema_version": "1.0",
        "status": status,
        "checked_at_utc": utc_now(),
        "candidate": "ProDayTraderV2",
        "image": IMAGE,
        "expected_digest": EXPECTED_DIGEST,
        "checks": checks,
        "versions": {
            "freqtrade": probe.get("freqtrade"),
            "lightgbm": probe.get("lightgbm"),
            "python": probe.get("python"),
        },
        "network_mode": "none",
        "model_training_performed": False,
        "pnl_evaluated": False,
        "live_trading_authorized": False,
        "evidence_boundary": (
            "Local image metadata and import compatibility only; no model fit, backtest, "
            "exchange call, profitability evidence, deployment, or live authorization."
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
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        report = validate_runtime(timeout=args.timeout_seconds)
        _atomic_write(args.output, report)
    except (RuntimeCheckError, OSError, ValueError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
