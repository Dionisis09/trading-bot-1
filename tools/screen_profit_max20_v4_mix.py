#!/usr/bin/env python3
"""Read-only sizing screen for a V3 swing/activity plus V2R portfolio."""

from __future__ import annotations

import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_profit_max20_v1 as common  # noqa: E402


V2R_ARCHIVE = ROOT / "user_data/reports/profit_max_daily_v5_v2r_ensemble_cycle3/v2r_results/backtest-result-2026-08-17_15-28-47.zip"


def old_v2r(start: str, end: str) -> list[dict]:
    with zipfile.ZipFile(V2R_ARCHIVE) as archive:
        name = next(
            item for item in archive.namelist()
            if item.endswith(".json") and not item.endswith("_config.json")
        )
        trades = json.loads(archive.read(name))["strategy"]["DualTrendFuturesV2R"]["trades"]
    return [trade for trade in trades if start <= trade["close_date"][:10] < end]


def scale_swing(trades: list[dict], leverage: float) -> list[dict]:
    ratio = leverage / 3.78
    result = []
    for source in trades:
        trade = deepcopy(source)
        trade["amount"] = float(trade["amount"]) * ratio
        trade["profit_abs"] = float(trade["profit_abs"]) * ratio
        trade["leverage"] = leverage
        result.append(trade)
    return result


def scale_linear(trades: list[dict], ratio: float) -> list[dict]:
    result = []
    for source in trades:
        trade = deepcopy(source)
        trade["amount"] = float(trade["amount"]) * ratio
        trade["stake_amount"] = float(trade["stake_amount"]) * ratio
        trade["profit_abs"] = float(trade["profit_abs"]) * ratio
        result.append(trade)
    return result


def main() -> None:
    periods = {
        "rolling": ("rolling_five_year", "2021-08-01", "2026-08-01"),
        "calendar": ("calendar_five_year", "2021-01-01", "2026-01-01"),
    }
    output = {}
    for leverage in (3.45, 3.50, 3.55, 3.60, 3.62, 3.64):
        for v2r_scale in (1.0, 1.5, 2.0):
            rows = {}
            for period, (label, start, end) in periods.items():
                timerange, days = common.PERIODS[label]
                swing, _ = common.load_archive(
                    ROOT / f"user_data/reports/profit_max20_v3/{label}_swing.zip",
                    "ProfitMaxCagr20V3", timerange, days, 3.78,
                )
                activity, _ = common.load_archive(
                    ROOT / f"user_data/reports/profit_max20_v3/{label}_daily.zip",
                    "ProfitMaxDailyTop2ActivityV1", timerange, days, 1.0,
                )
                trades = scale_swing(swing, leverage) + activity + scale_linear(old_v2r(start, end), v2r_scale)
                baseline = common.metrics(trades, days, 0.0)
                severe = common.metrics(trades, days, 0.001)
                exposure = common.maximum_exposure(trades)
                rows[period] = {
                    "trades_per_day": baseline["trades_per_day"],
                    "baseline_cagr_pct": baseline["cagr_pct"],
                    "severe_cagr_pct": severe["cagr_pct"],
                    "baseline_drawdown_pct": baseline["realized_drawdown_pct"],
                    "severe_drawdown_pct": severe["realized_drawdown_pct"],
                    "severe_profit_factor": severe["profit_factor"],
                    **exposure,
                }
            output[f"swing_{leverage}_v2r_{v2r_scale}"] = rows
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
