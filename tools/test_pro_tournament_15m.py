from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProTournament15m import (  # noqa: E402
    ProMeanReversion15m,
    ProMomentumCross15m,
    ProTrendBreakout15m,
    ProTrendPullback15m,
    ProVolatilityBreakout15m,
)


class ProTournament15mTests(unittest.TestCase):
    def test_five_frozen_candidates_have_no_trade_callbacks(self) -> None:
        candidates = [ProTrendBreakout15m, ProTrendPullback15m, ProMomentumCross15m,
                      ProVolatilityBreakout15m, ProMeanReversion15m]
        self.assertEqual(len(candidates), 5)
        for candidate in candidates:
            self.assertEqual(candidate.timeframe, "15m")
            self.assertNotIn("custom_exit", candidate.__dict__)
            self.assertNotIn("custom_stoploss", candidate.__dict__)

    def test_channels_and_volume_baselines_are_shifted(self) -> None:
        frame = pd.DataFrame({
            "date": pd.date_range("2022-01-01", periods=120, freq="15min", tz="UTC"),
            "open": range(1, 121), "high": range(2, 122), "low": range(1, 121),
            "close": range(1, 121), "volume": range(1, 121),
        })
        result = ProTrendBreakout15m._base_indicators(frame)
        self.assertEqual(result.loc[20, "channel_high_prev20"], 21)
        self.assertEqual(result.loc[20, "volume_median_prev20"], 10.5)

    def test_mean_reversion_exit_is_symmetric(self) -> None:
        frame = pd.DataFrame({"z48": [-0.1, 0.1], "rsi14": [54.0, 46.0]})
        result = object.__new__(ProMeanReversion15m).populate_exit_trend(frame, {})
        self.assertEqual(result["exit_long"].tolist(), [0, 1])
        self.assertEqual(result["exit_short"].tolist(), [1, 0])


if __name__ == "__main__":
    unittest.main()

