import sys
import unittest
from pathlib import Path

import pandas as pd
from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxCrossSectionalTopOne import (  # noqa: E402
    ProfitMaxCrossSectionalTopOne12h, ProfitMaxCrossSectionalTopOne16h, ProfitMaxCrossSectionalTopOne24h,
)


class TopOneTests(unittest.TestCase):
    config = {"candle_type_def": CandleType.FUTURES}

    def test_exact_variants(self):
        expected = {ProfitMaxCrossSectionalTopOne24h: 24, ProfitMaxCrossSectionalTopOne16h: 16,
                    ProfitMaxCrossSectionalTopOne12h: 12}
        for cls, hold in expected.items():
            strategy = cls(self.config)
            self.assertEqual(strategy.top_n, 1)
            self.assertEqual(strategy.momentum_candles, 180)
            self.assertEqual(strategy.hold_hours, hold)
            self.assertFalse(strategy.can_short)

    def test_only_exact_top_rank_enters(self):
        strategy = ProfitMaxCrossSectionalTopOne24h(self.config)
        frame = pd.DataFrame({"volume": [1.0, 1.0], "rank_count": [50, 50], "cross_rank": [50.0, 49.0]})
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(result["enter_long"].fillna(0).tolist(), [1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
