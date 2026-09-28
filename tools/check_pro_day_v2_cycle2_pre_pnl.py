#!/usr/bin/env python3
"""Record Cycle 2 technical evidence before recursive analysis or PnL."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import check_pro_day_v2_pre_pnl as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "user_data/reports/pro_day_v2_cycle2/pre_pnl_technical_evidence.json"
CONFIG = "/freqtrade/user_data/config-pro-day-v2-cycle2-research.json"


def collect_evidence(
    *, runner: base.Runner = subprocess.run, timeout: int = 240
) -> dict[str, Any]:
    evidence = base.collect_evidence(runner=runner, timeout=timeout)

    cycle2_tests = (
        ("cycle2_config", "test_pro_day_v2_cycle2_config.py", 4),
        ("cycle2_freeze", "test_freeze_pro_day_v2_cycle2.py", 5),
    )
    cycle2_rows: dict[str, dict[str, Any]] = {}
    for label, pattern, expected in cycle2_tests:
        output = base._run(
            runner,
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tools",
                "-p",
                pattern,
                "-v",
            ],
            timeout,
        )
        count = base._test_count(output, label)
        if count != expected:
            raise base.TechnicalGateError(
                f"{label} test count changed: {count} != {expected}"
            )
        cycle2_rows[label] = {"status": "PASS", "tests": count, "pattern": pattern}

    user_volume = f"{(ROOT / 'user_data').resolve()}:/freqtrade/user_data:ro"
    show_output = base._run(
        runner,
        [
            "docker", "run", "--rm", "--network", "none",
            "-v", user_volume, base.IMAGE,
            "show-config", "--config", CONFIG,
        ],
        timeout,
    )
    del show_output
    discovery = base._run(
        runner,
        [
            "docker", "run", "--rm", "--network", "none",
            "-v", user_volume, base.IMAGE,
            "list-strategies", "--config", CONFIG, "--no-color",
        ],
        timeout,
    )
    matching = [
        line for line in discovery.splitlines()
        if line.lstrip().startswith("│") and "ProDayTraderV2" in line
    ]
    if len(matching) != 1 or "OK" not in matching[0]:
        raise base.TechnicalGateError("Cycle 2 strategy discovery is not uniquely OK")

    compile_targets = [
        ROOT / "tools/test_pro_day_v2_cycle2_config.py",
        ROOT / "tools/check_pro_day_v2_cycle2_pre_pnl.py",
        ROOT / "tools/freeze_pro_day_v2_cycle2.py",
    ]
    base._run(
        runner,
        [sys.executable, "-m", "py_compile", *map(str, compile_targets)],
        timeout,
    )

    cycle1_decision = base._load_json(
        ROOT / "user_data/reports/pro_day_v2_cycle1/final_decision.json",
        "Cycle 1 final decision",
    )
    performance = cycle1_decision.get("performance")
    if (
        cycle1_decision.get("decision") != "REJECT_PRO_DAY_TRADER_V2"
        or cycle1_decision.get("decision_stage") != "PRE_PNL_TECHNICAL_GATE"
        or not isinstance(performance, dict)
        or performance.get("pnl_parsed") is not False
        or performance.get("qualification_backtests") != 0
    ):
        raise base.TechnicalGateError("Cycle 1 did not terminate cleanly before PnL")

    tests = dict(evidence["tests"])
    tests.update(cycle2_rows)
    cycle2_sources = [
        ROOT / "docs/pro_day_trader_v2_cycle2_locked_plan.md",
        ROOT / "user_data/config-pro-day-v2-cycle2-research.json",
        ROOT / "tools/test_pro_day_v2_cycle2_config.py",
        ROOT / "tools/test_freeze_pro_day_v2_cycle2.py",
        ROOT / "tools/check_pro_day_v2_cycle2_pre_pnl.py",
        ROOT / "tools/freeze_pro_day_v2_cycle2.py",
        ROOT / "user_data/reports/pro_day_v2_cycle1/final_decision.json",
    ]
    sources = dict(evidence["source_sha256"])
    sources.update(
        {
            str(path.relative_to(ROOT)).replace("\\", "/"): base._hash(path)
            for path in cycle2_sources
        }
    )
    evidence.update(
        {
            "cycle": "pro_day_v2_cycle2",
            "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "tests": tests,
            "total_tests": sum(row["tests"] for row in tests.values()),
            "source_sha256": sources,
            "cycle1_terminal_decision": "PASS_NO_PNL",
            "cycle2_config_validation": "PASS_OUTPUT_SUPPRESSED",
            "cycle2_strategy_discovery": "PASS_UNIQUE_STATUS_OK",
            "recursive_analysis": "PENDING_AFTER_FREEZE",
            "lookahead_analysis": "PENDING_AFTER_RECURSIVE_PASS",
        }
    )
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args(argv)
    try:
        report = collect_evidence(timeout=args.timeout_seconds)
        base._atomic_write(args.output, report)
    except (base.TechnicalGateError, OSError, ValueError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "cycle": report["cycle"],
                "total_tests": report["total_tests"],
                "pnl_evaluated": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
