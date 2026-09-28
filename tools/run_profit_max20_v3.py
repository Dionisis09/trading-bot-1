#!/usr/bin/env python3
"""Freeze, execute, and evaluate the isolated ProfitMax20 V3 portfolio."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run_profit_max20_v2 as previous


common = previous.common
ROOT = common.ROOT
REPORT_DIR = Path("user_data/reports/profit_max20_v3")
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DECISION = REPORT_DIR / "decision.json"
PERIODS = common.PERIODS
SOURCE_FILES = (
    Path("docs/profit_max20_v3_locked_plan.md"),
    Path("tools/run_profit_max20_v1.py"),
    Path("tools/run_profit_max20_v2.py"),
    Path("tools/run_profit_max20_v3.py"),
    Path("tools/test_profit_max20_v2.py"),
    Path("tools/test_profit_max20_v3.py"),
    Path("user_data/config-profit-max-cagr20-v3.json"),
    Path("user_data/config-profit-max-liquid50-cycle1.json"),
    Path("user_data/config-profit-max20-daily-v3-overlay.json"),
    Path("user_data/risk_policy_profit_max_cagr20_v3.json"),
    Path("user_data/strategies/ProfitMaxCagr20V3.py"),
    *previous.SOURCE_FILES,
)


def validate_contracts() -> None:
    swing = common.read_json(ROOT / "user_data/config-profit-max-cagr20-v3.json")
    daily = common.read_json(ROOT / "user_data/config-profit-max-liquid50-cycle1.json")
    overlay = common.read_json(ROOT / "user_data/config-profit-max20-daily-v3-overlay.json")
    policy = common.read_json(ROOT / "user_data/risk_policy_profit_max_cagr20_v3.json")
    if swing.get("dry_run") is not True or daily.get("dry_run") is not True:
        raise common.CycleError("both configs must remain dry-run")
    for config in (swing, daily):
        if config.get("exchange", {}).get("key") or config.get("exchange", {}).get("secret"):
            raise common.CycleError("credentials found")
    research = swing.get("profit_max_research", {})
    activity = overlay.get("profit_max_research", {})
    if research.get("status") != "LOCKED_BEFORE_PNL" or activity.get("status") != "LOCKED_BEFORE_PNL":
        raise common.CycleError("candidate is not locked before PnL")
    if research.get("leverage") != 3.78 or swing.get("max_open_trades") != 1 or swing.get("stake_amount") != 300:
        raise common.CycleError("swing contract mismatch")
    if activity.get("rank_count") != 2 or overlay.get("stake_amount") != 10 or overlay.get("max_open_trades") != 2:
        raise common.CycleError("activity contract mismatch")
    limits = policy.get("limits", {})
    if limits.get("maximum_wallet_drawdown_pct") != 25.0 or limits.get("maximum_total_open_stake_pct") != 20.0:
        raise common.CycleError("risk policy mismatch")
    if policy.get("live_launch", {}).get("authorized") is not False:
        raise common.CycleError("live launch must remain unauthorized")


def freeze() -> dict[str, Any]:
    if (ROOT / REPORT_DIR).exists():
        raise common.CycleError("V3 report directory already exists")
    validate_contracts()
    paths = list(dict.fromkeys([*SOURCE_FILES, *common.data_files(ROOT)]))
    missing = [path.as_posix() for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise common.CycleError(f"missing frozen inputs: {missing}")
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max20_v3",
        "status": "RESEARCH_FROZEN",
        "locked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pnl_parsed": False,
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
        "live_trading_authorized": False,
        "files": {
            path.as_posix(): {
                "sha256": common.sha256(ROOT / path),
                "size_bytes": (ROOT / path).stat().st_size,
            }
            for path in paths
        },
    }
    common.write_json(ROOT / MANIFEST, payload, exclusive=True)
    return payload


def verify_freeze() -> None:
    manifest = common.read_json(ROOT / MANIFEST)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("pnl_parsed") is not False:
        raise common.CycleError("invalid V3 freeze manifest")
    for relative, evidence in manifest.get("files", {}).items():
        path = ROOT / relative
        if not path.is_file() or common.sha256(path) != evidence.get("sha256"):
            raise common.CycleError(f"frozen input changed: {relative}")


def evaluate_period(label: str, timerange: str, days: int) -> dict[str, Any]:
    swing, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_swing.zip", "ProfitMaxCagr20V3", timerange, days, 3.78
    )
    activity, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_daily.zip", "ProfitMaxDailyTop2ActivityV1", timerange, days, 1.0
    )
    combined = [dict(trade, portfolio_component="swing") for trade in swing]
    combined.extend(dict(trade, portfolio_component="activity") for trade in activity)
    baseline = common.metrics(combined, days, 0.0)
    severe = common.metrics(combined, days, common.SEVERE_EXTRA_COST_PER_SIDE)
    exposure = common.maximum_exposure(combined)
    baseline_years = baseline["year_profit_usdt"]
    severe_years = severe["year_profit_usdt"]
    gates = {
        "trades_per_day_gte_1": baseline["trades_per_day"] >= 1.0,
        "baseline_cagr_gte_20": baseline["cagr_pct"] >= 20.0,
        "severe_cagr_gte_20": severe["cagr_pct"] >= 20.0,
        "baseline_profit_factor_gte_1_50": baseline["profit_factor"] >= 1.50,
        "severe_profit_factor_gte_1_50": severe["profit_factor"] >= 1.50,
        "baseline_drawdown_lte_20": baseline["realized_drawdown_pct"] <= 20.0,
        "severe_drawdown_lte_20": severe["realized_drawdown_pct"] <= 20.0,
        "maximum_margin_lte_25pct": exposure["maximum_concurrent_margin_usdt"] <= 250.0 + 1e-9,
        "maximum_notional_lte_75pct": exposure["maximum_concurrent_notional_usdt"] <= 750.0 + 1e-9,
        "no_baseline_segment_below_minus_2pct": all(value >= -20.0 for value in baseline_years.values()),
        "no_severe_segment_below_minus_2pct": all(value >= -20.0 for value in severe_years.values()),
        "at_least_four_positive_baseline_segments": sum(value > 0 for value in baseline_years.values()) >= 4,
        "at_least_four_positive_severe_segments": sum(value > 0 for value in severe_years.values()) >= 4,
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "timerange": timerange,
        "baseline": baseline,
        "severe_cost": severe,
        "exposure": exposure,
        "components": {
            "swing": common.metrics(swing, days, 0.0),
            "activity": common.metrics(activity, days, 0.0),
        },
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    try:
        manifest = freeze()
        verify_freeze()
        previous.REPORT_DIR = REPORT_DIR
        artifacts: dict[str, Any] = {}
        for label, (timerange, _) in PERIODS.items():
            artifacts[f"{label}_swing"] = previous.backtest(
                f"{label}_swing", timerange, "ProfitMaxCagr20V3",
                (Path("user_data/config-profit-max-cagr20-v3.json"),),
                Path("user_data/data/binance"), args.timeout,
            )
            artifacts[f"{label}_daily"] = previous.backtest(
                f"{label}_daily", timerange, "ProfitMaxDailyTop2ActivityV1",
                (
                    Path("user_data/config-profit-max-liquid50-cycle1.json"),
                    Path("user_data/config-profit-max20-daily-v3-overlay.json"),
                ),
                Path("user_data/data/binance/profit_max_liquid50_cycle1_source"), args.timeout,
            )
        verify_freeze()
        results = {
            label: evaluate_period(label, timerange, days)
            for label, (timerange, days) in PERIODS.items()
        }
        primary_pass = results["rolling_five_year"]["status"] == "PASS"
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max20_v3",
            "status": "PASS" if primary_pass else "FAIL",
            "decision": "APPROVE_CREDENTIAL_FREE_ISOLATED_DRY_RUN_ONLY" if primary_pass else "KEEP_OFFLINE_RESEARCH",
            "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "primary_period": "rolling_five_year",
            "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
            "profit_guaranteed": False,
            "live_trading_authorized": False,
            "automatic_promotion_authorized": False,
            "freeze_manifest_sha256": common.sha256(ROOT / MANIFEST),
            "frozen_file_count": len(manifest["files"]),
            "results": results,
            "artifacts": artifacts,
        }
        common.write_json(ROOT / DECISION, payload, exclusive=True)
        print(json.dumps({
            "status": payload["status"], "decision": payload["decision"],
            "rolling": results["rolling_five_year"],
            "calendar": results["calendar_five_year"],
        }, indent=2, allow_nan=False))
        return 0 if primary_pass else 2
    except Exception as exc:
        print(f"PROFIT_MAX20_V3_BLOCKED: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
