#!/usr/bin/env python3
"""Freeze the portfolio ensemble contract before new component PnL is generated."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_portfolio_ensemble_cycle1"
DATA = ROOT / "user_data/data/binance/futures"
PAIRS = ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE")
PAIR_NAMES = {f"{pair}/USDT:USDT" for pair in PAIRS}
DATA_SUFFIXES = (
    "4h-futures.feather",
    "1d-futures.feather",
    "1h-funding_rate.feather",
    "1h-mark.feather",
)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def validate_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("cross archive integrity failure")
        configs = [name for name in archive.namelist() if name.endswith("_config.json")]
        results = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        if len(configs) != 1 or len(results) != 1:
            raise ValueError("cross archive inventory mismatch")
        config = json.loads(archive.read(configs[0]))
        result = json.loads(archive.read(results[0])).get("strategy", {}).get("ProfitMaxCrossSectionalTopTwo8h")
    exchange = config.get("exchange") or {}
    if not (
        config.get("dry_run_wallet") == 1000
        and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "4h"
        and config.get("fee") == 0.00075
        and config.get("stake_amount") == 50
        and config.get("max_open_trades") == 2
        and len(exchange.get("pair_whitelist") or []) == 50
        and str(exchange.get("key") or "").strip() in ("", "REDACTED")
        and str(exchange.get("secret") or "").strip() in ("", "REDACTED")
        and isinstance(result, dict)
        and result.get("timerange") == "20210101-20240101"
        and result.get("backtest_days") == 1095
        and result.get("total_trades") == 936
    ):
        raise ValueError("cross archive contract mismatch")


def main() -> int:
    files = {
        "plan": ROOT / "docs/profit_max_portfolio_ensemble_cycle1_locked_plan.md",
        "evaluator": ROOT / "tools/evaluate_profit_max_portfolio_train.py",
        "evaluator_tests": ROOT / "tools/test_evaluate_profit_max_portfolio_train.py",
        "freeze": Path(__file__).resolve(),
        "base_config": ROOT / "user_data/config-profit-max-swing-cycle5.json",
        "v5_overlay": ROOT / "user_data/config-profit-max-portfolio-v5-train-overlay.json",
        "v1_overlay": ROOT / "user_data/config-profit-max-portfolio-v1-train-overlay.json",
        "portfolio_risk_policy": ROOT / "user_data/risk_policy_profit_max_portfolio.json",
        "runtime_risk_policy": ROOT / "user_data/risk_policy.json",
        "v5_strategy": ROOT / "user_data/strategies/ProfitMaxSwingV5.py",
        "v1_strategy": ROOT / "user_data/strategies/DualTrendFuturesV1.py",
        "v2_parent": ROOT / "user_data/strategies/DualTrendFuturesV2.py",
        "risk_parent": ROOT / "user_data/strategies/DualTrendFuturesRisk.py",
        "professional_risk": ROOT / "user_data/strategies/ProfessionalRisk.py",
        "cross_strategy": ROOT / "user_data/strategies/ProfitMaxCrossSectionalShortHorizon.py",
        "cross_parent": ROOT / "user_data/strategies/ProfitMaxCrossSectional.py",
        "cross_archive": ROOT / "user_data/reports/profit_max_cross_sectional_short_horizon_cycle1/train.zip",
        "cross_decision": ROOT / "user_data/reports/profit_max_cross_sectional_short_horizon_cycle1/train_decision.json",
        "cross_freeze": ROOT / "user_data/reports/profit_max_cross_sectional_short_horizon_cycle1/research_freeze_manifest.json",
        "v5_exact_fee_evidence": ROOT / "user_data/reports/profit_max_swing_cycle5/exact_fee_075_verification.json",
    }
    if any(not safe_file(path) for path in files.values()):
        print("FREEZE_BLOCKED: missing or unsafe input", file=sys.stderr)
        return 2
    try:
        base = json.loads(files["base_config"].read_text(encoding="utf-8"))
        v5_overlay = json.loads(files["v5_overlay"].read_text(encoding="utf-8"))
        v1_overlay = json.loads(files["v1_overlay"].read_text(encoding="utf-8"))
        policy = json.loads(files["portfolio_risk_policy"].read_text(encoding="utf-8"))
        cross_decision = json.loads(files["cross_decision"].read_text(encoding="utf-8"))
        cross_freeze = json.loads(files["cross_freeze"].read_text(encoding="utf-8"))
        v5_evidence = json.loads(files["v5_exact_fee_evidence"].read_text(encoding="utf-8"))
        validate_archive(files["cross_archive"])
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"FREEZE_BLOCKED: {exc}", file=sys.stderr)
        return 2

    exchange = base.get("exchange") or {}
    limits = policy.get("limits") or {}
    if not (
        base.get("dry_run") is True
        and base.get("dry_run_wallet") == 1000
        and base.get("trading_mode") == "futures"
        and base.get("margin_mode") == "isolated"
        and base.get("timeframe") == "4h"
        and set(exchange.get("pair_whitelist") or []) == PAIR_NAMES
        and not str(exchange.get("key") or "").strip()
        and not str(exchange.get("secret") or "").strip()
        and v5_overlay == {
            "bot_name": "profit-max-portfolio-v5-train-research",
            "strategy": "ProfitMaxV5Asymmetric50", "initial_state": "stopped",
            "max_open_trades": 2, "stake_amount": 50, "fee": 0.00075,
        }
        and v1_overlay == {
            "bot_name": "profit-max-portfolio-v1-train-research",
            "strategy": "DualTrendFuturesV1", "initial_state": "stopped",
            "max_open_trades": 1, "stake_amount": 50, "fee": 0.00075,
        }
        and limits.get("maximum_open_trades") == 5
        and limits.get("maximum_total_open_stake_pct") == 20.0
        and (policy.get("live_launch") or {}).get("authorized") is False
        and (policy.get("live_launch") or {}).get("maximum_leverage") == 1.0
        and cross_decision.get("decision") == "KEEP_OFFLINE_RESEARCH"
        and cross_decision.get("validation_revealed") is False
        and cross_decision.get("fee_per_side") == 0.00075
        and (cross_decision.get("train_archive") or {}).get("sha256") == digest(files["cross_archive"])
        and cross_freeze.get("status") == "RESEARCH_FROZEN_BEFORE_PNL"
        and v5_evidence.get("status") == "PASS_HISTORICAL_COST_DIAGNOSTIC"
        and v5_evidence.get("fee_per_side") == 0.00075
        and v5_evidence.get("live_trading_authorized") is False
    ):
        print("FREEZE_BLOCKED: contract mismatch", file=sys.stderr)
        return 2

    data_paths = [DATA / f"{pair}_USDT_USDT-{suffix}" for pair in PAIRS for suffix in DATA_SUFFIXES]
    if len(data_paths) != 24 or any(not safe_file(path) for path in data_paths):
        print("FREEZE_BLOCKED: data inventory mismatch", file=sys.stderr)
        return 2
    planned = {
        "v5_train": REPORT / "v5_train.zip",
        "v1_train": REPORT / "v1_train.zip",
        "train_decision": REPORT / "train_decision.json",
    }
    if any(path.exists() for path in planned.values()):
        print("FREEZE_BLOCKED: planned output already exists", file=sys.stderr)
        return 3

    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_portfolio_ensemble_cycle1",
        "status": "RESEARCH_FROZEN_BEFORE_NEW_COMPONENT_PNL",
        "pnl_parsed": False,
        "validation_revealed": False,
        "live_trading_authorized": False,
        "profit_guaranteed": False,
        "runtime": "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643",
        "train_timerange": "20210101-20240101",
        "fee_per_side": 0.00075,
        "components": {
            "cross": {"strategy": "ProfitMaxCrossSectionalTopTwo8h", "reserved_slots": 2, "source": "frozen_archive"},
            "v5": {"strategy": "ProfitMaxV5Asymmetric50", "reserved_slots": 2, "source": "new_backtest"},
            "v1": {"strategy": "DualTrendFuturesV1", "reserved_slots": 1, "source": "new_backtest_deduplicated"},
        },
        "files": {
            name: {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
            for name, path in sorted(files.items())
        },
        "data_files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(data_paths)
        ],
        "artifacts": {name: path.relative_to(ROOT).as_posix() for name, path in planned.items()},
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    manifest = REPORT / "research_freeze_manifest.json"
    try:
        with manifest.open("xb") as stream:
            stream.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    except FileExistsError:
        print("FREEZE_BLOCKED: manifest exists", file=sys.stderr)
        return 3
    print(json.dumps({"status": payload["status"], "data_files": len(data_paths), "sha256": digest(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
