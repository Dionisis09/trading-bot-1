#!/usr/bin/env python3
"""Locate the severe-cost drawdown window of the leading retrospective mix."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_profit_max20_v1 as common  # noqa: E402
from screen_profit_max20_v4_mix import old_v2r, scale_swing  # noqa: E402


def main() -> None:
    swing, _ = common.load_archive(
        ROOT / "user_data/reports/profit_max20_v3/rolling_five_year_swing.zip",
        "ProfitMaxCagr20V3", "20210801-20260801", 1826, 3.78,
    )
    activity, _ = common.load_archive(
        ROOT / "user_data/reports/profit_max20_v3/rolling_five_year_daily.zip",
        "ProfitMaxDailyTop2ActivityV1", "20210801-20260801", 1826, 1.0,
    )
    tagged = [("swing", trade) for trade in scale_swing(swing, 3.64)]
    tagged += [("activity", trade) for trade in activity]
    tagged += [("v2r", trade) for trade in old_v2r("2021-08-01", "2026-08-01")]
    profits: dict[int, float] = defaultdict(float)
    for _, trade in tagged:
        extra = 0.001 * float(trade["amount"]) * (
            float(trade["open_rate"]) + float(trade["close_rate"])
        )
        profits[int(trade["close_timestamp"])] += float(trade["profit_abs"]) - extra
    equity = peak = 1000.0
    peak_time = trough_time = current_peak_time = None
    maximum = 0.0
    for timestamp in sorted(profits):
        equity += profits[timestamp]
        if equity > peak:
            peak = equity
            current_peak_time = timestamp
        drawdown = peak - equity
        if drawdown > maximum:
            maximum = drawdown
            peak_time = current_peak_time
            trough_time = timestamp
    print({"peak_time": peak_time, "trough_time": trough_time, "drawdown_usdt": maximum})
    for component, trade in sorted(tagged, key=lambda item: item[1]["close_timestamp"]):
        if peak_time is not None and peak_time < int(trade["close_timestamp"]) <= trough_time:
            extra = 0.001 * float(trade["amount"]) * (
                float(trade["open_rate"]) + float(trade["close_rate"])
            )
            print(
                component,
                trade["pair"],
                trade["open_date"],
                trade["close_date"],
                trade.get("enter_tag"),
                trade.get("exit_reason"),
                round(float(trade["profit_abs"]) - extra, 4),
            )


if __name__ == "__main__":
    main()
