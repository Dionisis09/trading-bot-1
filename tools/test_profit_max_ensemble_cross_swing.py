import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from DualTrendFuturesV2 import DualTrendFuturesV2  # noqa: E402
from ProfitMaxEnsembleCrossSwing import ProfitMaxEnsembleCrossSwingV1  # noqa: E402


class ProfitMaxEnsembleCrossSwingTests(unittest.TestCase):
    def strategy(self):
        return object.__new__(ProfitMaxEnsembleCrossSwingV1)

    @staticmethod
    def entry_frame():
        return pd.DataFrame(
            {
                "volume": [1.0, 1.0, 1.0],
                "rank_count": [50.0, 50.0, 50.0],
                "cross_rank": [49.0, 50.0, 1.0],
                "enter_long": [0, 1, 0],
                "enter_short": [0, 0, 1],
                "enter_tag": [None, "daily_bull", "daily_bear"],
            }
        )

    def test_swing_has_priority_and_non_swing_pair_only_uses_cross_entry(self):
        strategy = self.strategy()
        frame = self.entry_frame()
        with patch.object(DualTrendFuturesV2, "populate_entry_trend", return_value=frame.copy()):
            result = strategy.populate_entry_trend(frame.copy(), {"pair": "BTC/USDT:USDT"})
        self.assertEqual(result.loc[0, "enter_long"], 1)
        self.assertEqual(result.loc[0, "enter_tag"], "xsmom_top2_180_8h_long")
        self.assertEqual(result.loc[1, "enter_tag"], "swing_daily_bull")
        self.assertEqual(result.loc[2, "enter_tag"], "swing_daily_bear")

        with patch.object(DualTrendFuturesV2, "populate_entry_trend", return_value=frame.copy()):
            alt = strategy.populate_entry_trend(frame.copy(), {"pair": "SOL/USDT:USDT"})
        self.assertEqual(list(alt["enter_short"]), [0, 0, 0])
        self.assertEqual(alt.loc[0, "enter_long"], 1)
        self.assertEqual(alt.loc[1, "enter_long"], 1)
        self.assertEqual(alt.loc[1, "enter_tag"], "xsmom_top2_180_8h_long")

    def test_cross_exit_is_exactly_eight_hours(self):
        strategy = self.strategy()
        opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trade = SimpleNamespace(enter_tag="xsmom_top2_180_8h_long", open_date_utc=opened, is_short=False)
        self.assertIsNone(strategy.custom_exit("BTC/USDT:USDT", trade, opened + timedelta(hours=7), 1, 0))
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", trade, opened + timedelta(hours=8), 1, 0),
            "xsmom_fixed_8h_rebalance",
        )

    def test_swing_exit_uses_analyzed_direction_and_unknown_tag_fails_closed(self):
        strategy = self.strategy()
        opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
        strategy.dp = SimpleNamespace(
            get_analyzed_dataframe=lambda **kwargs: (
                pd.DataFrame({"exit_long": [1], "exit_short": [0], "exit_tag": ["channel"]}),
                None,
            )
        )
        swing = SimpleNamespace(enter_tag="swing_daily_bull", open_date_utc=opened, is_short=False)
        self.assertEqual(strategy.custom_exit("BTC/USDT:USDT", swing, opened, 1, 0), "swing_channel")
        unknown = SimpleNamespace(enter_tag=None, open_date_utc=opened, is_short=False)
        self.assertIsNone(strategy.custom_exit("BTC/USDT:USDT", unknown, opened + timedelta(days=2), 1, 0))

    def test_half_short_stake_and_fixed_leverage(self):
        strategy = self.strategy()
        with patch("ProfitMaxCrossSectional.AtrExposureRiskMixin.custom_stake_amount", return_value=40.0):
            self.assertEqual(strategy.custom_stake_amount(side="long"), 40.0)
            self.assertEqual(strategy.custom_stake_amount(side="short"), 20.0)
        self.assertEqual(strategy.leverage("BTC/USDT:USDT", datetime.now(timezone.utc), 1, 5, 20, None, "long"), 1.0)

    def test_locked_contract(self):
        strategy = self.strategy()
        self.assertEqual(strategy.timeframe, "4h")
        self.assertEqual(strategy.momentum_candles, 180)
        self.assertEqual(strategy.top_n, 2)
        self.assertEqual(strategy.hold_hours, 8)
        self.assertEqual(strategy.stoploss, -0.08)
        self.assertFalse(strategy.use_exit_signal)
        self.assertEqual(len(strategy.swing_pairs), 6)


if __name__ == "__main__":
    unittest.main()
