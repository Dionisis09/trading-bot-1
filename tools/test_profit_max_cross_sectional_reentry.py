import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxCrossSectionalReentry import (  # noqa: E402
    ProfitMaxCrossSectionalTopTwo8hFastReentry,
    ProfitMaxCrossSectionalTopTwo8hFastReentryPositive,
)


class ProfitMaxCrossSectionalReentryTests(unittest.TestCase):
    def test_only_cooldown_changes_in_protection_contract(self):
        strategy = object.__new__(ProfitMaxCrossSectionalTopTwo8hFastReentry)
        self.assertEqual(strategy.hold_hours, 8)
        self.assertEqual(strategy.momentum_candles, 180)
        self.assertEqual(strategy.top_n, 2)
        self.assertEqual(strategy.protections[0], {"method": "CooldownPeriod", "stop_duration_candles": 1})
        self.assertEqual(strategy.protections[1]["method"], "StoplossGuard")
        self.assertEqual(strategy.protections[2]["method"], "MaxDrawdown")

    def test_positive_candidate_is_an_explicit_separate_class(self):
        self.assertTrue(issubclass(ProfitMaxCrossSectionalTopTwo8hFastReentryPositive, ProfitMaxCrossSectionalTopTwo8hFastReentry.__bases__[0]))


if __name__ == "__main__":
    unittest.main()
