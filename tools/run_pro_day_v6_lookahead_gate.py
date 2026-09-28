#!/usr/bin/env python3
"""Run frozen V6 all-pair lookahead analysis without parsing PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import run_pro_day_v4_lookahead_gate as gate


ROOT = Path(__file__).resolve().parents[1]
gate.REQUIRED_TAGS = ["T1_long", "T1_short"]
gate.MANIFEST = Path("user_data/reports/pro_day_v6_cycle1/research_freeze_manifest.json")
gate.RECURSIVE = Path("user_data/reports/pro_day_v6_cycle1/recursive_analysis.json")
gate.LEDGER = Path("user_data/reports/pro_day_v6_cycle1/trial_ledger.json")
gate.CODE_FREEZE = Path("user_data/reports/pro_day_v6_cycle1/lookahead_gate_code_freeze.json")
gate.OUTPUT = Path("user_data/reports/pro_day_v6_cycle1/lookahead_analysis.json")
gate.RUNNER = Path("tools/run_pro_day_v6_lookahead_gate.py")
gate.TESTS = Path("tools/test_run_pro_day_v6_lookahead_gate.py")


def validate_inputs(root: Path) -> tuple[str, str]:
    manifest_path = root / gate.MANIFEST
    manifest = gate.load(manifest_path)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("cycle") != "pro_day_v6_cycle1":
        raise gate.common.GateError("V6 manifest is not frozen")
    if manifest.get("pnl_parsed") is not False:
        raise gate.common.GateError("manifest crossed PnL boundary")
    for label in ("plan", "strategy", "v5_parent", "config", "risk_policy", "data_audit"):
        row = manifest.get("files", {}).get(label, {})
        path = root / str(row.get("path", ""))
        if not path.is_file() or gate.sha256(path) != row.get("sha256"):
            raise gate.common.GateError(f"frozen input changed: {label}")
    params = manifest.get("frozen_parameters", {})
    if params.get("lookahead_market_price_side") != "other" or params.get("lookahead_order_book") is not True:
        raise gate.common.GateError("lookahead pricing contract differs")
    for row in manifest.get("artifacts", {}).values():
        if row.get("status") != "PLANNED_NOT_RUN" or (root / row.get("path", "")).exists():
            raise gate.common.GateError("qualification artifact exists")
    recursive_path = root / gate.RECURSIVE
    recursive = gate.load(recursive_path)
    if recursive.get("status") != "PASS" or recursive.get("decision") != "CONTINUE_TO_LOOKAHEAD":
        raise gate.common.GateError("V6 recursive gate did not pass")
    if recursive.get("pnl_parsed") is not False:
        raise gate.common.GateError("recursive crossed PnL boundary")
    return gate.sha256(manifest_path), gate.sha256(recursive_path)


def build_command(root: Path) -> list[str]:
    return ["docker", "run", "--rm",
            "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
            "-v", f"{(root / 'tools').resolve()}:/freqtrade/tools:ro",
            "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
            "--entrypoint", "python", gate.IMAGE,
            "/freqtrade/tools/run_pro_day_v6_lookahead_gate.py", "--inside-container"]


def inside() -> int:
    from freqtrade.commands import Arguments
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.analysis.lookahead_helpers import LookaheadAnalysisSubFunctions
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.util import get_progress_tracker

    argv = ["lookahead-analysis", "--config", "/freqtrade/user_data/config-pro-day-v6-cycle1-research.json",
            "--userdir", "/freqtrade/user_data", "--strategy", "ProDayTraderV6",
            "--datadir", "/canonical", "--timerange", gate.TIMERANGE,
            "--pairs", *gate.PAIRS, "--minimum-trade-amount", str(gate.MINIMUM),
            "--targeted-trade-amount", str(gate.TARGETED), "--no-color"]
    config = setup_utils_configuration(Arguments(argv).get_parsed_arg(), RunMode.UTIL_NO_EXCHANGE)
    config = LookaheadAnalysisSubFunctions.calculate_config_overrides(config)
    config["entry_pricing"] = dict(config["entry_pricing"])
    config["exit_pricing"] = dict(config["exit_pricing"])
    config["entry_pricing"].update({"price_side": "other", "use_order_book": True})
    config["exit_pricing"].update({"price_side": "other", "use_order_book": True})
    objects = [row for row in StrategyResolver.search_all_objects(config, enum_failed=False, recursive=False)
               if row.get("name") == "ProDayTraderV6"]
    if len(objects) != 1:
        raise gate.common.GateError("ProDayTraderV6 is not uniquely discoverable")
    with get_progress_tracker() as progress:
        instance = LookaheadAnalysisSubFunctions.initialize_single_lookahead_analysis(config, objects[0], progress)
    analysis = instance.current_analysis
    trades = instance.full_varHolder.result["results"]
    probe = {
        "analyzed_signals": int(analysis.total_signals), "has_bias": bool(analysis.has_bias),
        "false_entry_signals": int(analysis.false_entry_signals),
        "false_exit_signals": int(analysis.false_exit_signals),
        "false_indicators": sorted(str(value) for value in analysis.false_indicators),
        "failed_bias_check": bool(instance.failed_bias_check), "full_trade_count": int(len(trades)),
        "full_trade_tag_counts": {str(key): int(value) for key, value in trades["enter_tag"].fillna("").value_counts().items()},
        "full_trade_pair_counts": {str(key): int(value) for key, value in trades["pair"].value_counts().items()},
        "transient_entry_price_side": "other", "transient_exit_price_side": "other",
        "transient_order_book_pricing": True,
        "public_market_metadata_used": True, "private_api_used": False,
        "pnl_fields_parsed": False,
    }
    print(gate.SENTINEL + json.dumps(probe, sort_keys=True, allow_nan=False))
    return 0


gate.validate_inputs = validate_inputs
gate.build_command = build_command


def run_gate(root: Path, timeout: int) -> dict[str, Any]:
    manifest_hash, recursive_hash = validate_inputs(root)
    code_hash = gate.validate_code(root, manifest_hash, recursive_hash)
    result = subprocess.run(build_command(root), cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    lines = [line[len(gate.SENTINEL):] for line in combined.splitlines() if line.startswith(gate.SENTINEL)]
    failures: list[str] = []
    details: dict[str, Any] = {}
    if result.returncode:
        failures.append(f"lookahead container exit {result.returncode}")
    if len(lines) != 1:
        failures.append("exact lookahead probe missing")
    else:
        probe = json.loads(lines[0])
        if probe.get("transient_order_book_pricing") is not True:
            failures.append("transient pricing contract differs")
        passed, more, details = gate.evaluate(probe)
        if not passed:
            failures.extend(more)
    report = {
        "schema_version": "1.0", "status": "PASS" if not failures else "FAIL",
        "decision": "CONTINUE_TO_TRAIN" if not failures else "REJECT_PRO_DAY_TRADER_V6",
        "cycle": "pro_day_v6_cycle1", "candidate": "ProDayTraderV6",
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "recursive_report_sha256": recursive_hash,
        "code_freeze_sha256": code_hash, "runtime_image": gate.IMAGE,
        "container_exit_code": result.returncode,
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "gate_details": details, "failures": failures,
        "bias_analysis_backtests_performed": True,
        "qualification_performance_backtest_performed": False,
        "pnl_parsed": False, "live_trading_authorized": False,
    }
    gate.write(root / gate.OUTPUT, report, exclusive=True)
    gate.append_ledger(root, report)
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
            record = gate.freeze_code(args.workspace.resolve())
            print(json.dumps({"status": record["status"], "pnl_parsed": False})); return 0
        report = run_gate(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": report["status"], "decision": report["decision"], "pnl_parsed": False}))
        return 0 if report["status"] == "PASS" else 2
    except (gate.common.GateError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "TECHNICAL_BLOCKED", "error": str(exc)})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
