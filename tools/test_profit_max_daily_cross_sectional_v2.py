from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxDailyCrossSectional import ProfitMaxDailyCrossSectional  # noqa: E402
from ProfitMaxDailyCrossSectionalV2 import (  # noqa: E402
    ProfitMaxDailyCrossStop12,
    ProfitMaxDailyCrossStop16,
    ProfitMaxDailyCrossStop20,
)


class ProfitMaxDailyCrossV2Tests(unittest.TestCase):
    def test_only_stop_and_protection_horizon_change(self) -> None:
        expected = {
            ProfitMaxDailyCrossStop12: -0.12,
            ProfitMaxDailyCrossStop16: -0.16,
            ProfitMaxDailyCrossStop20: -0.20,
        }
        for candidate, stop in expected.items():
            strategy = candidate.__new__(candidate)
            self.assertTrue(issubclass(candidate, ProfitMaxDailyCrossSectional))
            self.assertEqual(candidate.stoploss, stop)
            self.assertEqual(candidate.momentum_candles, 42)
            self.assertEqual(candidate.btc_gate_candles, 180)
            self.assertEqual(candidate.signal_hours_utc, (8, 20))
            self.assertEqual(candidate.hold_hours, 8)
            self.assertFalse(candidate.can_short)
            self.assertEqual(
                strategy.protections,
                [{"method": "CooldownPeriod", "stop_duration_candles": 1}],
            )


if __name__ == "__main__":
    unittest.main()

