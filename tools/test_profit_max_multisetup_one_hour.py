import sys
import unittest
from pathlib import Path

import pandas as pd
from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxMultiSetupOneHour import (  # noqa: E402
    ProfitMaxOneHourBreakout, ProfitMaxOneHourHybrid, ProfitMaxOneHourPullback,
)


class MultiSetupTests(unittest.TestCase):
    config = {"candle_type_def": CandleType.FUTURES}

    def test_fixed_candidate_contract(self):
        expected = {ProfitMaxOneHourPullback: "pullback", ProfitMaxOneHourBreakout: "breakout", ProfitMaxOneHourHybrid: "hybrid"}
        for cls, mode in expected.items():
            strategy = cls(self.config)
            self.assertEqual(strategy.setup_mode, mode)
            self.assertEqual(strategy.timeframe, "1h")
            self.assertEqual(strategy.stoploss, -0.04)
            self.assertEqual(strategy.leverage("BTC/USDT:USDT", pd.Timestamp("2023-01-01"), 1, 1, 10, None, "long"), 1.0)

    def test_breakout_channels_are_prior_only(self):
        frame = pd.DataFrame({
            "open": [float(x + 1) for x in range(100)], "high": [float(x + 2) for x in range(100)],
            "low": [float(x + 0.5) for x in range(100)], "close": [float(x + 1) for x in range(100)],
            "volume": [1.0] * 100,
        })
        result = ProfitMaxOneHourHybrid(self.config).populate_indicators(frame, {})
        self.assertEqual(result.loc[24, "prior_high_24"], 25.0)
        self.assertEqual(result.loc[24, "prior_low_24"], 0.5)

    def test_protections_are_hour_normalized(self):
        protections = ProfitMaxOneHourHybrid(self.config).protections
        self.assertEqual(protections[0]["stop_duration_candles"], 8)
        self.assertEqual(protections[1]["lookback_period_candles"], 168)
        self.assertEqual(protections[2]["lookback_period_candles"], 720)


if __name__ == "__main__":
    unittest.main()
