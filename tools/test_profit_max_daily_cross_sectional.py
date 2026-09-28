from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxDailyCrossSectional import ProfitMaxDailyCrossSectional  # noqa: E402


class ProfitMaxDailyCrossSectionalTests(unittest.TestCase):
    def test_frozen_parameters(self) -> None:
        self.assertFalse(ProfitMaxDailyCrossSectional.can_short)
        self.assertEqual(ProfitMaxDailyCrossSectional.timeframe, "4h")
        self.assertEqual(ProfitMaxDailyCrossSectional.momentum_candles, 42)
        self.assertEqual(ProfitMaxDailyCrossSectional.btc_gate_candles, 180)
        self.assertEqual(ProfitMaxDailyCrossSectional.signal_hours_utc, (8, 20))
        self.assertEqual(ProfitMaxDailyCrossSectional.hold_hours, 8)
        self.assertEqual(ProfitMaxDailyCrossSectional.stoploss, -0.08)

    def test_only_leader_enters_at_frozen_signal_hours_with_positive_gate(self) -> None:
        strategy = ProfitMaxDailyCrossSectional.__new__(ProfitMaxDailyCrossSectional)
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2023-01-01T08:00:00Z", "2023-01-01T12:00:00Z", "2023-01-01T20:00:00Z"]
                ),
                "volume": [1.0, 1.0, 1.0],
                "rank_count": [50, 50, 50],
                "cross_rank": [50.0, 50.0, 49.0],
                "btc_bull": [True, True, True],
            }
        )
        result = strategy.populate_entry_trend(frame, {"pair": "ETH/USDT:USDT"})
        self.assertEqual(result["enter_long"].fillna(0).tolist(), [1.0, 0.0, 0.0])
        self.assertEqual(result["enter_short"].tolist(), [0, 0, 0])

    def test_gate_and_minimum_breadth_fail_closed(self) -> None:
        strategy = ProfitMaxDailyCrossSectional.__new__(ProfitMaxDailyCrossSectional)
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-01T20:00:00Z"] * 3),
                "volume": [1.0, 1.0, 0.0],
                "rank_count": [50, 34, 50],
                "cross_rank": [50.0, 34.0, 50.0],
                "btc_bull": [False, True, True],
            }
        )
        result = strategy.populate_entry_trend(frame, {"pair": "ETH/USDT:USDT"})
        self.assertEqual(int(result["enter_long"].fillna(0).sum()), 0)

    def test_time_exit_is_exactly_eight_hours(self) -> None:
        strategy = ProfitMaxDailyCrossSectional.__new__(ProfitMaxDailyCrossSectional)
        opened = datetime(2023, 1, 1, tzinfo=timezone.utc)
        trade = SimpleNamespace(open_date_utc=opened)
        self.assertIsNone(strategy.custom_exit("BTC/USDT:USDT", trade, opened + pd.Timedelta(hours=4), 1, 0))
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", trade, opened + pd.Timedelta(hours=8), 1, 0),
            "fixed_8h_exit",
        )


if __name__ == "__main__":
    unittest.main()

