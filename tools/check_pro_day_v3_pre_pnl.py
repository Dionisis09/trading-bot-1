#!/usr/bin/env python3
"""Fail-closed pre-PnL technical evidence for deterministic ProDayTraderV3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "freqtradeorg/freqtrade:2026.7@"
    "sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
)
CONFIG = "/freqtrade/user_data/config-pro-day-v3-cycle1-research.json"
OUTPUT = ROOT / "user_data/reports/pro_day_v3_cycle1/pre_pnl_technical_evidence.json"


class GateError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], timeout: int) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode:
        raise GateError(f"command failed ({result.returncode}): {' '.join(command)}\n{output[-4000:]}")
    return output


def test_count(output: str, expected: int, label: str) -> None:
    marker = f"Ran {expected} tests"
    if marker not in output or "OK" not in output:
        raise GateError(f"{label} did not report {marker} and OK")


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def collect(timeout: int = 240) -> dict[str, Any]:
    user_mount = f"{(ROOT / 'user_data').resolve()}:/freqtrade/user_data:ro"
    tools_mount = f"{(ROOT / 'tools').resolve()}:/freqtrade/tools:ro"
    common = [
        "docker", "run", "--rm", "--network", "none",
        "-v", user_mount, "-v", tools_mount,
    ]
    python = common + ["--entrypoint", "python", IMAGE]
    cli = common + ["--entrypoint", "freqtrade", IMAGE]

    v2 = run(
        python + ["-m", "unittest", "discover", "-s", "/freqtrade/tools",
                  "-p", "test_pro_day_trader_v2.py", "-v"],
        timeout,
    )
    test_count(v2, 11, "V2 inherited technical tests")
    v3 = run(
        python + ["-m", "unittest", "discover", "-s", "/freqtrade/tools",
                  "-p", "test_pro_day_trader_v3.py", "-v"],
        timeout,
    )
    test_count(v3, 5, "V3 deterministic tests")

    run(
        python + [
            "-c",
            (
                "from pathlib import Path; "
                "[compile(Path(p).read_text(encoding='utf-8'), p, 'exec') "
                "for p in ('/freqtrade/user_data/strategies/ProDayTraderV3.py',"
                "'/freqtrade/tools/test_pro_day_trader_v3.py')]"
            ),
        ],
        timeout,
    )
    run(
        cli + ["show-config", "--config", CONFIG,
                  "--datadir", "/freqtrade/user_data/data/binance/pro_day_v2_canonical"],
        timeout,
    )
    discovery = run(
        cli + ["list-strategies", "--config", CONFIG, "--no-color"],
        timeout,
    )
    matches = [
        line for line in discovery.splitlines()
        if "ProDayTraderV3" in line and line.count("│") >= 3
    ]
    if len(matches) != 1 or "OK" not in matches[0]:
        raise GateError("ProDayTraderV3 strategy discovery is not uniquely OK")

    audit_path = ROOT / "user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or audit.get("pnl_evaluated") is not False:
        raise GateError("canonical data audit is not a pre-PnL PASS")
    data_rows = audit.get("canonical_files", []) + audit.get("auxiliary_canonical_files", [])
    if len(data_rows) != 18:
        raise GateError("canonical inventory must contain exactly 18 files")
    for row in data_rows:
        path = ROOT / row["path"]
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise GateError(f"canonical data hash mismatch: {row.get('path')}")

    prior_path = ROOT / "user_data/reports/pro_day_v2_cycle2/final_decision.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    performance = prior.get("performance", {})
    if (
        prior.get("decision") != "REJECT_PRO_DAY_TRADER_V2"
        or performance.get("pnl_parsed") is not False
        or performance.get("qualification_backtests") != 0
    ):
        raise GateError("Cycle 2 terminal decision does not prove the no-PnL boundary")

    sources = [
        ROOT / "docs/pro_day_trader_v3_cycle1_locked_plan.md",
        ROOT / "user_data/strategies/ProDayTraderV3.py",
        ROOT / "user_data/strategies/ProDayTraderV2.py",
        ROOT / "user_data/config-pro-day-v3-cycle1-research.json",
        ROOT / "user_data/risk_policy.json",
        audit_path,
        prior_path,
        Path(__file__).resolve(),
        ROOT / "tools/test_pro_day_trader_v3.py",
    ]
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "candidate": "ProDayTraderV3",
        "cycle": "pro_day_v3_cycle1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime_image": IMAGE,
        "tests": {"inherited_v2": 11, "deterministic_v3": 5, "total": 16},
        "python_compile": "PASS",
        "config_validation": "PASS_OUTPUT_SUPPRESSED",
        "strategy_discovery": "PASS_UNIQUE_STATUS_OK",
        "canonical_data_files_rehashed": 18,
        "cycle2_terminal_decision": "PASS_NO_PNL",
        "recursive_analysis": "PENDING_AFTER_FREEZE",
        "lookahead_analysis": "LOCKED_PENDING_RECURSIVE_PASS",
        "model_training_performed": False,
        "backtest_performed": False,
        "pnl_evaluated": False,
        "live_trading_authorized": False,
        "source_sha256": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path)
            for path in sources
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args(argv)
    try:
        report = collect(args.timeout_seconds)
        atomic_write(args.output, report)
    except (GateError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "PASS", "tests": 16, "pnl_evaluated": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
