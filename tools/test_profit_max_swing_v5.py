import unittest
from unittest.mock import patch
import sys
from pathlib import Path

import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from ProfitMaxSwingV5 import (
    ProfitMaxV5Asymmetric50,
    ProfitMaxV5Balanced,
    ProfitMaxV5LongOnly,
    ProfitMaxV5SelectiveShort,
)
from DualTrendFuturesRisk import DualTrendFuturesV2R


def candidate_frame(descending: bool) -> pd.DataFrame:
    values = list(range(100, 50, -1)) if descending else list(range(50, 100))
    return pd.DataFrame({
        "ema200_1d": values,
        "enter_short": [1] * 50,
        "enter_tag": ["daily_bear_breakdown_30_confluence_3of4"] * 50,
    })


class ProfitMaxSwingV5Tests(unittest.TestCase):
    def test_half_short_stake_preserves_long_stake(self):
        strategy = object.__new__(ProfitMaxV5Asymmetric50)
        with patch.object(DualTrendFuturesV2R, "custom_stake_amount", return_value=80.0):
            self.assertEqual(strategy.custom_stake_amount(side="long"), 80.0)
            self.assertEqual(strategy.custom_stake_amount(side="short"), 40.0)

    def test_selective_short_blocks_non_declining_regime(self):
        strategy = object.__new__(ProfitMaxV5SelectiveShort)
        frame = candidate_frame(descending=False)
        with patch.object(DualTrendFuturesV2R, "populate_entry_trend", return_value=frame):
            result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(int(result["enter_short"].sum()), 0)

    def test_selective_short_allows_signal_after_seven_day_decline(self):
        strategy = object.__new__(ProfitMaxV5SelectiveShort)
        frame = candidate_frame(descending=True)
        with patch.object(DualTrendFuturesV2R, "populate_entry_trend", return_value=frame):
            result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(int(result["enter_short"].sum()), 8)

    def test_balanced_combines_filter_and_half_short_stake(self):
        self.assertTrue(issubclass(ProfitMaxV5Balanced, ProfitMaxV5SelectiveShort.__bases__[0]))
        strategy = object.__new__(ProfitMaxV5Balanced)
        with patch.object(DualTrendFuturesV2R, "custom_stake_amount", return_value=80.0):
            self.assertEqual(strategy.custom_stake_amount(side="short"), 40.0)

    def test_long_only_disables_and_clears_short_signals(self):
        strategy = object.__new__(ProfitMaxV5LongOnly)
        frame = candidate_frame(descending=True)
        with patch.object(DualTrendFuturesV2R, "populate_entry_trend", return_value=frame):
            result = strategy.populate_entry_trend(frame, {})
        self.assertFalse(strategy.can_short)
        self.assertEqual(int(result["enter_short"].sum()), 0)


if __name__ == "__main__":
    unittest.main()
