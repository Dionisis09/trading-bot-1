from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
if str(STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGY_DIR))

from ProfitMaxCagr20V2 import ProfitMaxCagr20V2  # noqa: E402
from ProfitMaxDailyTop2ActivityV1 import ProfitMaxDailyTop2ActivityV1  # noqa: E402


class ProfitMax20V2Tests(unittest.TestCase):
    def test_leverage_preserves_underlying_stop_distance(self) -> None:
        self.assertEqual(ProfitMaxCagr20V2.fixed_research_leverage, 3.76)
        self.assertEqual(ProfitMaxCagr20V2.stoploss, -0.376)
        self.assertAlmostEqual(abs(ProfitMaxCagr20V2.stoploss) / 3.76, 0.10)

    def test_top_two_rank_filter(self) -> None:
        strategy = object.__new__(ProfitMaxDailyTop2ActivityV1)
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01 08:00Z"] * 3),
            "volume": [1.0, 1.0, 1.0],
            "rank_count": [50.0, 50.0, 50.0],
            "cross_rank": [50.0, 49.0, 48.0],
            "btc_bull": [True, True, True],
        })
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(result["enter_long"].fillna(0).tolist(), [1.0, 1.0, 0.0])
        self.assertEqual(result["enter_short"].tolist(), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
