from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxDailyCrossSectionalV3 import ProfitMaxDailyCrossBreadthBonus  # noqa: E402


class ProfitMaxDailyCrossV3Tests(unittest.TestCase):
    def test_frozen_contract(self) -> None:
        strategy = ProfitMaxDailyCrossBreadthBonus.__new__(ProfitMaxDailyCrossBreadthBonus)
        self.assertEqual(strategy.stoploss, -0.20)
        self.assertEqual(strategy.signal_hours_utc, (8, 12, 20))
        self.assertEqual(strategy.bonus_signal_hour_utc, 12)
        self.assertEqual(strategy.breadth_minimum, 0.70)
        self.assertEqual(strategy.protections, [])
        self.assertEqual(strategy.hold_hours, 8)
        self.assertFalse(strategy.can_short)

    def test_bonus_requires_breadth_70(self) -> None:
        strategy = ProfitMaxDailyCrossBreadthBonus.__new__(ProfitMaxDailyCrossBreadthBonus)
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime([
                    "2023-01-01T08:00:00Z",
                    "2023-01-01T12:00:00Z",
                    "2023-01-02T12:00:00Z",
                    "2023-01-01T20:00:00Z",
                ]),
                "volume": [1.0] * 4,
                "rank_count": [50] * 4,
                "cross_rank": [50.0] * 4,
                "btc_bull": [True] * 4,
                "breadth": [0.1, 0.6999, 0.70, 0.1],
            }
        )
        result = strategy.populate_entry_trend(frame, {"pair": "ETH/USDT:USDT"})
        self.assertEqual(result["enter_long"].fillna(0).tolist(), [1.0, 0.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()

