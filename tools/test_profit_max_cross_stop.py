from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxCrossSectionalShortHorizon import ProfitMaxCrossSectionalTopTwo8h  # noqa: E402
from ProfitMaxCrossSectionalStop import (  # noqa: E402
    ProfitMaxCrossTopTwo8hStop2,
    ProfitMaxCrossTopTwo8hStop4,
    ProfitMaxCrossTopTwo8hStop6,
)


class ProfitMaxCrossStopTests(unittest.TestCase):
    def test_only_stoploss_changes(self) -> None:
        expected = {
            ProfitMaxCrossTopTwo8hStop2: -0.02,
            ProfitMaxCrossTopTwo8hStop4: -0.04,
            ProfitMaxCrossTopTwo8hStop6: -0.06,
        }
        for candidate, stop in expected.items():
            self.assertTrue(issubclass(candidate, ProfitMaxCrossSectionalTopTwo8h))
            self.assertEqual(candidate.stoploss, stop)
            self.assertEqual(candidate.momentum_candles, 180)
            self.assertEqual(candidate.hold_hours, 8)
            self.assertEqual(candidate.top_n, 2)
            self.assertFalse(candidate.can_short)
            self.assertFalse(candidate.trailing_stop)


if __name__ == "__main__":
    unittest.main()
