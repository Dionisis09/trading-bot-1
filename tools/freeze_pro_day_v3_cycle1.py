#!/usr/bin/env python3
"""Create the immutable pre-PnL research freeze for ProDayTraderV3 Cycle 1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CYCLE = "pro_day_v3_cycle1"
CANDIDATE = "ProDayTraderV3"
DIGEST = "sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
IMAGE = f"freqtradeorg/freqtrade:2026.7@{DIGEST}"
PLAN = Path("docs/pro_day_trader_v3_cycle1_locked_plan.md")
STRATEGY = Path("user_data/strategies/ProDayTraderV3.py")
BASE_STRATEGY = Path("user_data/strategies/ProDayTraderV2.py")
CONFIG = Path("user_data/config-pro-day-v3-cycle1-research.json")
RISK = Path("user_data/risk_policy.json")
AUDIT = Path("user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json")
PRIOR = Path("user_data/reports/pro_day_v2_cycle2/final_decision.json")
TECHNICAL = Path("user_data/reports/pro_day_v3_cycle1/pre_pnl_technical_evidence.json")
OUTPUT = Path("user_data/reports/pro_day_v3_cycle1/research_freeze_manifest.json")
LEDGER = Path("user_data/reports/pro_day_v3_cycle1/trial_ledger.json")

EXPECTED = {
    "strategy": "73c78608f8cf048874282621c87f1e05948c90ea66b710800d162c7741402804",
    "base_strategy": "6041f416e4c951b83b5f9cef5438319fd4f24d1d296eb37fd499415a00e47f45",
    "config": "b71ff01b880122fa60c956739b186ed028de2a60f2a4c3867c28cce2d1f268bb",
    "audit": "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772",
    "prior": "a66944317b0563fd6603323df7ae54872e8a3bd1095173220930d677b8148280",
}
ARTIFACTS = {
    label: Path(f"user_data/backtest_results/prodayv3-cycle1-{name}.zip")
    for label, name in {
        "train": "train",
        "validation": "validation",
        "current_partial": "current-partial",
        "canonical": "canonical",
    }.items()
}


class FreezeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def descriptor(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(root)).replace("\\", "/"),
        "filename": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreezeError(f"{label} must be a JSON object")
    return value


def equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise FreezeError(f"{label} differs from the locked value")


def validate_plan(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    markers = (
        "LOCKED_BEFORE_FIRST_V3_PNL_RUN",
        CANDIDATE,
        DIGEST,
        EXPECTED["strategy"],
        EXPECTED["base_strategy"],
        EXPECTED["config"],
        EXPECTED["audit"],
        EXPECTED["prior"],
        "[199, 399, 799, 1599, 2399]",
        "APPROVE_SEPARATE_DRY_RUN",
    )
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise FreezeError("locked plan markers missing: " + ", ".join(missing))


def validate_config(config: Mapping[str, Any]) -> None:
    equal(config.get("strategy"), CANDIDATE, "strategy")
    equal(config.get("initial_state"), "stopped", "initial_state")
    equal(config.get("dry_run"), True, "dry_run")
    equal(config.get("trading_mode"), "futures", "trading_mode")
    equal(config.get("margin_mode"), "isolated", "margin_mode")
    equal(config.get("timeframe"), "5m", "timeframe")
    equal(config.get("max_open_trades"), 2, "max_open_trades")
    equal(config.get("fee"), 0.0005, "fee")
    equal(config.get("stake_currency"), "USDT", "stake_currency")
    if "freqai" in config or "freqaimodel" in config:
        raise FreezeError("FreqAI must be absent from deterministic Cycle 1")
    exchange = config.get("exchange", {})
    equal(
        exchange.get("pair_whitelist"),
        ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
        "pair whitelist",
    )
    meta = config.get("pro_day_v3_research", {})
    equal(meta.get("cycle"), CYCLE, "cycle")
    equal(meta.get("ml_order_gate"), False, "ml_order_gate")
    equal(meta.get("live_trading_authorized"), False, "live authorization")
    equal(meta.get("leverage"), 1, "leverage")
    equal(meta.get("recursive_startup_counts"), [199, 399, 799, 1599, 2399], "recursive counts")


def validate_data(audit: Mapping[str, Any], root: Path) -> list[dict[str, Any]]:
    equal(audit.get("status"), "PASS", "canonical audit status")
    equal(audit.get("pnl_evaluated"), False, "canonical audit pnl_evaluated")
    rows = list(audit.get("canonical_files", [])) + list(audit.get("auxiliary_canonical_files", []))
    if len(rows) != 18:
        raise FreezeError("canonical inventory must contain 18 files")
    frozen: list[dict[str, Any]] = []
    for row in rows:
        path = root / row["path"]
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            raise FreezeError(f"canonical data hash mismatch: {row.get('path')}")
        frozen.append(descriptor(path, root))
    return frozen


def write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FreezeError(f"refusing to overwrite immutable file: {path}") from exc


def freeze(root: Path = ROOT, write: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "plan": root / PLAN,
        "strategy": root / STRATEGY,
        "base_strategy": root / BASE_STRATEGY,
        "config": root / CONFIG,
        "risk_policy": root / RISK,
        "data_audit": root / AUDIT,
        "cycle2_terminal_decision": root / PRIOR,
        "pre_pnl_technical_evidence": root / TECHNICAL,
        "pre_pnl_checker": root / "tools/check_pro_day_v3_pre_pnl.py",
        "strategy_tests": root / "tools/test_pro_day_trader_v3.py",
        "freeze_tests": root / "tools/test_freeze_pro_day_v3_cycle1.py",
        "freezer": Path(__file__).resolve(),
    }
    for label, path in paths.items():
        if not path.is_file():
            raise FreezeError(f"missing {label}: {path}")
    validate_plan(paths["plan"])
    for label in ("strategy", "base_strategy", "config", "data_audit"):
        if sha256_file(paths[label]) != EXPECTED[label if label != "data_audit" else "audit"]:
            raise FreezeError(f"{label} SHA256 mismatch")
    if sha256_file(paths["cycle2_terminal_decision"]) != EXPECTED["prior"]:
        raise FreezeError("Cycle 2 terminal decision SHA256 mismatch")
    config = load(paths["config"], "research config")
    validate_config(config)
    data_files = validate_data(load(paths["data_audit"], "canonical data audit"), root)
    technical = load(paths["pre_pnl_technical_evidence"], "pre-PnL technical evidence")
    equal(technical.get("status"), "PASS", "technical status")
    equal(technical.get("tests", {}).get("total"), 16, "technical test count")
    for field in ("model_training_performed", "backtest_performed", "pnl_evaluated", "live_trading_authorized"):
        equal(technical.get(field), False, f"technical {field}")
    prior = load(paths["cycle2_terminal_decision"], "Cycle 2 decision")
    equal(prior.get("performance", {}).get("qualification_backtests"), 0, "prior qualification backtests")
    equal(prior.get("performance", {}).get("pnl_parsed"), False, "prior pnl parsed")

    artifacts: dict[str, dict[str, Any]] = {}
    for label, relative in ARTIFACTS.items():
        path = root / relative
        if path.exists():
            raise FreezeError(f"planned artifact already exists: {relative}")
        artifacts[label] = {
            "path": str(relative).replace("\\", "/"),
            "filename": path.name,
            "sha256": None,
            "status": "PLANNED_NOT_RUN",
        }
    for relative in (
        "user_data/reports/pro_day_v3_cycle1/recursive_analysis.json",
        "user_data/reports/pro_day_v3_cycle1/lookahead_analysis.json",
    ):
        if (root / relative).exists():
            raise FreezeError(f"technical result already exists before freeze: {relative}")

    files = {label: descriptor(path, root) for label, path in paths.items()}
    locked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0",
        "status": "RESEARCH_FROZEN",
        "candidate": CANDIDATE,
        "cycle": CYCLE,
        "locked_at_utc": locked_at,
        "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False,
        "model_training_performed": False,
        "files": files,
        "data_files": data_files,
        "frozen_parameters": {
            "runtime_image": IMAGE,
            "runtime_digest": DIGEST,
            "timeframe": "5m",
            "informative_timeframes": ["15m", "1h", "4h"],
            "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"],
            "recursive_startup_counts": [199, 399, 799, 1599, 2399],
            "recursive_qualification_count": 399,
            "lookahead_timerange": "20240101-20260101",
            "train_timerange": "20220101-20240101",
            "validation_timerange": "20240101-20260101",
            "current_partial_timerange": "20260101-20260801",
            "ml_order_gate": False,
            "leverage": 1,
            "earliest_fill": "next_5m_open",
        },
        "artifacts": artifacts,
        "technical_evidence": {
            "data_gate": "PASS",
            "unit_tests": "PASS_16",
            "config_validation": "PASS_OUTPUT_SUPPRESSED",
            "strategy_discovery": "PASS_UNIQUE_STATUS_OK",
            "recursive_analysis": "PENDING",
            "lookahead_analysis": "LOCKED_PENDING_RECURSIVE_PASS",
        },
        "active_strategies_changed": False,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
    }
    ledger = {
        "schema_version": "1.0",
        "cycle": CYCLE,
        "candidate": CANDIDATE,
        "created_at_utc": locked_at,
        "plan_sha256": files["plan"]["sha256"],
        "strategy_sha256": files["strategy"]["sha256"],
        "base_strategy_sha256": files["base_strategy"]["sha256"],
        "config_sha256": files["config"]["sha256"],
        "qualification_runs": [],
        "parameter_trials": [],
        "pnl_parsed": False,
        "post_result_edits_allowed": False,
        "live_trading_authorized": False,
    }
    if write:
        output = root / OUTPUT
        ledger_path = root / LEDGER
        if output.exists() or ledger_path.exists():
            raise FreezeError("manifest or ledger already exists")
        write_exclusive(ledger_path, ledger)
        try:
            write_exclusive(output, manifest)
        except Exception:
            ledger_path.unlink(missing_ok=True)
            raise
    return manifest, ledger


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest, _ = freeze(write=not args.check_only)
    except (FreezeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "RESEARCH_FROZEN", "cycle": CYCLE, "pnl_parsed": False,
                      "write_output": not args.check_only}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
