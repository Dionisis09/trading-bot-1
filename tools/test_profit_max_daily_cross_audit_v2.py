from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxDailyCrossSectionalAuditV2 import ProfitMaxDailyCrossStop20AuditV2  # noqa: E402


class AuditV2Tests(unittest.TestCase):
    def test_exact_frozen_universe_and_alpha(self) -> None:
        self.assertEqual(len(ProfitMaxDailyCrossStop20AuditV2.frozen_pairs), 50)
        self.assertEqual(ProfitMaxDailyCrossStop20AuditV2.frozen_pairs[0], "BTC/USDT:USDT")
        self.assertEqual(ProfitMaxDailyCrossStop20AuditV2.frozen_pairs[-1], "1INCH/USDT:USDT")
        self.assertEqual(len(set(ProfitMaxDailyCrossStop20AuditV2.frozen_pairs)), 50)
        self.assertEqual(ProfitMaxDailyCrossStop20AuditV2.stoploss, -0.20)
        self.assertEqual(ProfitMaxDailyCrossStop20AuditV2.signal_hours_utc, (8, 20))
        self.assertEqual(ProfitMaxDailyCrossStop20AuditV2.hold_hours, 8)


if __name__ == "__main__":
    unittest.main()

