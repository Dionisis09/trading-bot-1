#!/usr/bin/env python3
"""Freeze, backtest, and evaluate the three-sleeve ProfitMax20 V4 portfolio."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run_profit_max20_v2 as executor
import run_profit_max20_v3 as previous


common = executor.common
ROOT = common.ROOT
REPORT_DIR = Path("user_data/reports/profit_max20_v4")
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DECISION = REPORT_DIR / "decision.json"
PERIODS = common.PERIODS
SOURCE_FILES = (
    Path("docs/profit_max20_v4_locked_plan.md"),
    Path("tools/run_profit_max20_v1.py"),
    Path("tools/run_profit_max20_v2.py"),
    Path("tools/run_profit_max20_v3.py"),
    Path("tools/run_profit_max20_v4.py"),
    Path("tools/test_profit_max20_v2.py"),
    Path("tools/test_profit_max20_v3.py"),
    Path("tools/test_profit_max20_v4.py"),
    Path("user_data/config-profit-max-cagr20-v4.json"),
    Path("user_data/config-profit-max-liquid50-cycle1.json"),
    Path("user_data/config-profit-max20-daily-v4-overlay.json"),
    Path("user_data/config-profit-max-swing-cycle5.json"),
    Path("user_data/config-profit-max20-v2r-v4-overlay.json"),
    Path("user_data/risk_policy_profit_max_cagr20_v4.json"),
    Path("user_data/risk_policy.json"),
    Path("user_data/strategies/ProfitMaxCagr20V4.py"),
    *previous.SOURCE_FILES,
)


def validate_contracts() -> None:
    swing = common.read_json(ROOT / "user_data/config-profit-max-cagr20-v4.json")
    daily_base = common.read_json(ROOT / "user_data/config-profit-max-liquid50-cycle1.json")
    daily = common.read_json(ROOT / "user_data/config-profit-max20-daily-v4-overlay.json")
    v2r_base = common.read_json(ROOT / "user_data/config-profit-max-swing-cycle5.json")
    v2r = common.read_json(ROOT / "user_data/config-profit-max20-v2r-v4-overlay.json")
    policy = common.read_json(ROOT / "user_data/risk_policy_profit_max_cagr20_v4.json")
    for config in (swing, daily_base, v2r_base):
        if config.get("dry_run") is not True:
            raise common.CycleError("all base configs must remain dry-run")
        if config.get("exchange", {}).get("key") or config.get("exchange", {}).get("secret"):
            raise common.CycleError("credentials found")
    research = swing.get("profit_max_research", {})
    daily_research = daily.get("profit_max_research", {})
    v2r_research = v2r.get("profit_max_research", {})
    if any(item.get("status") != "LOCKED_BEFORE_PNL" for item in (research, daily_research, v2r_research)):
        raise common.CycleError("V4 inputs are not locked before PnL")
    if research.get("leverage") != 3.64 or swing.get("max_open_trades") != 1 or swing.get("stake_amount") != 300:
        raise common.CycleError("swing contract mismatch")
    if daily.get("stake_amount") != 10 or daily.get("max_open_trades") != 2 or daily_research.get("rank_count") != 2:
        raise common.CycleError("activity contract mismatch")
    if v2r.get("stake_amount") != 25 or v2r.get("max_open_trades") != 2 or v2r_research.get("leverage") != 1:
        raise common.CycleError("V2R contract mismatch")
    if any(config.get("fee") != common.BASE_FEE for config in (swing, daily, v2r)):
        raise common.CycleError("fee contract mismatch")
    if policy.get("live_launch", {}).get("authorized") is not False:
        raise common.CycleError("live launch must remain unauthorized")


def freeze() -> dict[str, Any]:
    if (ROOT / REPORT_DIR).exists():
        raise common.CycleError("V4 report directory already exists")
    validate_contracts()
    paths = list(dict.fromkeys([*SOURCE_FILES, *common.data_files(ROOT)]))
    missing = [path.as_posix() for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise common.CycleError(f"missing frozen inputs: {missing}")
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max20_v4",
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
        raise common.CycleError("invalid V4 freeze manifest")
    for relative, evidence in manifest.get("files", {}).items():
        path = ROOT / relative
        if not path.is_file() or common.sha256(path) != evidence.get("sha256"):
            raise common.CycleError(f"frozen input changed: {relative}")


def evaluate_period(label: str, timerange: str, days: int) -> dict[str, Any]:
    swing, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_swing.zip", "ProfitMaxCagr20V4", timerange, days, 3.64
    )
    activity, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_daily.zip", "ProfitMaxDailyTop2ActivityV1", timerange, days, 1.0
    )
    diversifier, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_v2r.zip", "DualTrendFuturesV2R", timerange, days, 1.0
    )
    combined = [dict(trade, portfolio_component="swing") for trade in swing]
    combined.extend(dict(trade, portfolio_component="activity") for trade in activity)
    combined.extend(dict(trade, portfolio_component="v2r") for trade in diversifier)
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
        "severe_drawdown_lte_21": severe["realized_drawdown_pct"] <= 21.0,
        "maximum_margin_lte_25pct": exposure["maximum_concurrent_margin_usdt"] <= 250.0 + 1e-9,
        "maximum_notional_lte_76pct": exposure["maximum_concurrent_notional_usdt"] <= 760.0 + 1e-9,
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
            "v2r": common.metrics(diversifier, days, 0.0),
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
        executor.REPORT_DIR = REPORT_DIR
        artifacts: dict[str, Any] = {}
        for label, (timerange, _) in PERIODS.items():
            artifacts[f"{label}_swing"] = executor.backtest(
                f"{label}_swing", timerange, "ProfitMaxCagr20V4",
                (Path("user_data/config-profit-max-cagr20-v4.json"),),
                Path("user_data/data/binance"), args.timeout,
            )
            artifacts[f"{label}_daily"] = executor.backtest(
                f"{label}_daily", timerange, "ProfitMaxDailyTop2ActivityV1",
                (
                    Path("user_data/config-profit-max-liquid50-cycle1.json"),
                    Path("user_data/config-profit-max20-daily-v4-overlay.json"),
                ),
                Path("user_data/data/binance/profit_max_liquid50_cycle1_source"), args.timeout,
            )
            artifacts[f"{label}_v2r"] = executor.backtest(
                f"{label}_v2r", timerange, "DualTrendFuturesV2R",
                (
                    Path("user_data/config-profit-max-swing-cycle5.json"),
                    Path("user_data/config-profit-max20-v2r-v4-overlay.json"),
                ),
                Path("user_data/data/binance"), args.timeout,
            )
        verify_freeze()
        results = {
            label: evaluate_period(label, timerange, days)
            for label, (timerange, days) in PERIODS.items()
        }
        primary_pass = results["rolling_five_year"]["status"] == "PASS"
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max20_v4",
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
        print(f"PROFIT_MAX20_V4_BLOCKED: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
