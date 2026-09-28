import sys
import unittest
from pathlib import Path

import pandas as pd
from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxCrossSectional import (  # noqa: E402
    ProfitMaxCrossSectional7dNeutral, ProfitMaxCrossSectional30dNeutral, ProfitMaxCrossSectional7dRegime,
)


class _DataProvider:
    def __init__(self):
        dates = pd.date_range("2020-01-01", periods=1305, freq="4h", tz="UTC")
        self.frames = {
            "BTC/USDT:USDT": pd.DataFrame({"date": dates, "close": [100 + i for i in range(len(dates))]}),
            "ETH/USDT:USDT": pd.DataFrame({"date": dates, "close": [100 + 2 * i for i in range(len(dates))]}),
            "BNB/USDT:USDT": pd.DataFrame({"date": dates, "close": [100 + 0.5 * i for i in range(len(dates))]}),
        }

    def current_whitelist(self):
        return list(self.frames)

    def get_pair_dataframe(self, pair, timeframe):
        return self.frames[pair]


class CrossSectionalTests(unittest.TestCase):
    config = {"candle_type_def": CandleType.FUTURES}

    def test_fixed_candidate_contract(self):
        expected = {ProfitMaxCrossSectional7dNeutral: (42, False),
                    ProfitMaxCrossSectional30dNeutral: (180, False),
                    ProfitMaxCrossSectional7dRegime: (42, True)}
        for cls, values in expected.items():
            strategy = cls(self.config)
            self.assertEqual((strategy.momentum_candles, strategy.regime_gated), values)
            self.assertEqual(strategy.stoploss, -0.08)
            self.assertEqual(strategy.hold_hours, 24)

    def test_rank_uses_only_trailing_completed_values(self):
        strategy = ProfitMaxCrossSectional7dNeutral(self.config)
        strategy.dp = _DataProvider()
        cache = strategy._build_rank_cache()
        at = cache.index[42]
        self.assertEqual(cache.loc[at, "rank_count"], 3)
        self.assertEqual(cache.loc[at, "rank::ETH/USDT:USDT"], 3.0)
        self.assertEqual(cache.loc[at, "rank::BNB/USDT:USDT"], 1.0)

    def test_rank_requires_minimum_breadth_and_next_candle_engine_semantics(self):
        strategy = ProfitMaxCrossSectional7dNeutral(self.config)
        frame = pd.DataFrame({"volume": [1.0], "rank_count": [3], "cross_rank": [3.0], "btc_bull": [True]})
        result = strategy.populate_entry_trend(frame, {})
        self.assertFalse(bool(result.get("enter_long", pd.Series([0])).fillna(0).iloc[0]))


if __name__ == "__main__":
    unittest.main()
