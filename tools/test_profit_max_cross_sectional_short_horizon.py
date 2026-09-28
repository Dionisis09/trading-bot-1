import sys
import unittest
from pathlib import Path

from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxCrossSectionalShortHorizon import (  # noqa: E402
    ProfitMaxCrossSectionalTopOne4h, ProfitMaxCrossSectionalTopOne8h, ProfitMaxCrossSectionalTopTwo8h,
)


class ShortHorizonTests(unittest.TestCase):
    config = {"candle_type_def": CandleType.FUTURES}

    def test_exact_locked_variants(self):
        expected = {ProfitMaxCrossSectionalTopOne8h: (1, 8),
                    ProfitMaxCrossSectionalTopOne4h: (1, 4),
                    ProfitMaxCrossSectionalTopTwo8h: (2, 8)}
        for cls, values in expected.items():
            strategy = cls(self.config)
            self.assertEqual((strategy.top_n, strategy.hold_hours), values)
            self.assertEqual(strategy.momentum_candles, 180)
            self.assertFalse(strategy.can_short)
            self.assertEqual(strategy.stoploss, -0.08)


if __name__ == "__main__":
    unittest.main()
