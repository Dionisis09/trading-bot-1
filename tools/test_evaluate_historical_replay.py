from __future__ import annotations

import unittest
from datetime import datetime, timezone

from evaluate_historical_replay import (
    FULL_YEARS,
    PAIRS,
    diagnostic_gates,
    index_rows,
    replay_diagnostics,
    strategy_rows,
)


def trade(pair: str, closed: str, profit: float, *, short: bool = False) -> dict:
    return {
        "pair": pair,
        "close_date": closed,
        "profit_abs": profit,
        "amount": 1.0,
        "open_rate": 100.0,
        "close_rate": 100.0,
        "funding_fees": 0.0,
        "is_short": short,
    }


class HistoricalReplayTests(unittest.TestCase):
    def test_builds_chronological_year_quarter_pair_and_direction_views(self):
        trades = [
            trade(PAIRS[0], "2021-03-31T00:00:00Z", 2.0),
            trade(PAIRS[1], "2022-07-01T00:00:00Z", -1.0, short=True),
        ]
        rows = strategy_rows("DualTrendFuturesV2R", trades)
        indexed = index_rows(rows)
        self.assertEqual(indexed[("DualTrendFuturesV2R", "year", "2021", "standard")]["trades"], 1)
        self.assertEqual(indexed[("DualTrendFuturesV2R", "quarter", "2021-Q1", "standard")]["trades"], 1)
        self.assertEqual(indexed[("DualTrendFuturesV2R", "pair", PAIRS[2], "standard")]["trades"], 0)
        self.assertEqual(indexed[("DualTrendFuturesV2R", "direction", "short", "standard")]["trades"], 1)

    def test_gates_fail_closed_when_reconciliation_or_breadth_is_missing(self):
        trades = []
        for year in FULL_YEARS:
            trades.extend(
                [
                    trade(PAIRS[0], f"{year}-03-01T00:00:00Z", 3.0),
                    trade(PAIRS[0], f"{year}-03-02T00:00:00Z", -1.0),
                ]
            )
        rows = strategy_rows("DualTrendFuturesV2R", trades)
        rows.extend(strategy_rows("DualTrendFuturesV1", trades))
        gates = diagnostic_gates(
            rows,
            {"DualTrendFuturesV1": True, "DualTrendFuturesV2R": False},
        )
        statuses = {item["name"]: item["status"] for item in gates}
        self.assertEqual(statuses["source_reconciliation"], "FAIL")
        self.assertEqual(statuses["positive_pair_breadth"], "FAIL")

    def test_diagnostics_keep_weak_periods_visible(self):
        trades = []
        for year in FULL_YEARS:
            trades.extend(
                [
                    trade(PAIRS[0], f"{year}-03-01T00:00:00Z", 3.0),
                    trade(PAIRS[0], f"{year}-03-02T00:00:00Z", -1.0),
                ]
            )
        trades.append(trade(PAIRS[0], "2026-07-01T00:00:00Z", -2.0))
        rows = strategy_rows("DualTrendFuturesV2R", trades)
        rows.extend(strategy_rows("DualTrendFuturesV1", trades))
        diagnostics = replay_diagnostics(rows)
        self.assertIn("2026-Q3", diagnostics["negative_standard_quarters"])
        self.assertIn(PAIRS[1], diagnostics["pairs_with_no_trades"])


if __name__ == "__main__":
    unittest.main()
