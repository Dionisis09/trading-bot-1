from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxDailyCrossSectionalAudit import ProfitMaxDailyCrossStop20Audit  # noqa: E402
from ProfitMaxDailyCrossSectionalV2 import ProfitMaxDailyCrossStop20  # noqa: E402


class ProfitMaxDailyCrossAuditTests(unittest.TestCase):
    def test_alpha_contract_is_inherited_unchanged(self) -> None:
        self.assertTrue(issubclass(ProfitMaxDailyCrossStop20Audit, ProfitMaxDailyCrossStop20))
        self.assertEqual(ProfitMaxDailyCrossStop20Audit.stoploss, -0.20)
        self.assertEqual(ProfitMaxDailyCrossStop20Audit.momentum_candles, 42)
        self.assertEqual(ProfitMaxDailyCrossStop20Audit.btc_gate_candles, 180)
        self.assertEqual(ProfitMaxDailyCrossStop20Audit.signal_hours_utc, (8, 20))
        self.assertEqual(ProfitMaxDailyCrossStop20Audit.hold_hours, 8)
        self.assertFalse(ProfitMaxDailyCrossStop20Audit.can_short)

    def test_config_whitelist_fails_closed(self) -> None:
        strategy = ProfitMaxDailyCrossStop20Audit.__new__(ProfitMaxDailyCrossStop20Audit)
        strategy._rank_cache = None
        strategy.config = {"exchange": {"pair_whitelist": ["BTC/USDT:USDT"]}}
        with self.assertRaisesRegex(ValueError, "frozen 50-pair"):
            strategy._build_rank_cache()


if __name__ == "__main__":
    unittest.main()

