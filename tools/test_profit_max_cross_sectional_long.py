import sys
import unittest
from pathlib import Path

import pandas as pd
from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxCrossSectionalLong import (  # noqa: E402
    ProfitMaxCrossSectionalLong30d36h, ProfitMaxCrossSectionalLong30d48h, ProfitMaxCrossSectionalLong60d48h,
)


class LongLeaderTests(unittest.TestCase):
    config = {"candle_type_def": CandleType.FUTURES}

    def test_frozen_variants(self):
        expected = {ProfitMaxCrossSectionalLong30d48h: (180, 48),
                    ProfitMaxCrossSectionalLong60d48h: (360, 48),
                    ProfitMaxCrossSectionalLong30d36h: (180, 36)}
        for cls, values in expected.items():
            strategy = cls(self.config)
            self.assertEqual((strategy.momentum_candles, strategy.hold_hours), values)
            self.assertEqual(strategy.top_n, 2)
            self.assertFalse(strategy.can_short)

    def test_exact_top_two_and_breadth_gate(self):
        strategy = ProfitMaxCrossSectionalLong30d48h(self.config)
        frame = pd.DataFrame({"volume": [1.0, 1.0, 1.0], "rank_count": [50, 50, 34],
                              "cross_rank": [50.0, 48.0, 34.0]})
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(result["enter_long"].fillna(0).tolist(), [1.0, 0.0, 0.0])
        self.assertEqual(result["enter_short"].tolist(), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
