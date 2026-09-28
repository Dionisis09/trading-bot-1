from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
sys.path.insert(0, str(STRATEGIES))

from ProfitMaxIntradayV3 import (  # noqa: E402
    ProfitMaxIntradayShortBreakEven15m,
    ProfitMaxIntradayShortProfitOnly15m,
    ProfitMaxIntradayShortProfitOnlyBreakEven15m,
)


class ProfitMaxIntradayV3Tests(unittest.TestCase):
    def test_profit_only_contract(self) -> None:
        strategy = ProfitMaxIntradayShortProfitOnly15m({})
        self.assertTrue(strategy.exit_profit_only)
        self.assertEqual(strategy.exit_profit_offset, 0.0015)
        self.assertEqual(strategy.stoploss, -0.018)
        self.assertEqual(strategy.minimal_roi, {"0": 0.024, "240": 0.012, "720": 0.005, "1440": 0.0})

    def test_break_even_is_inactive_before_threshold(self) -> None:
        strategy = ProfitMaxIntradayShortBreakEven15m({})
        trade = SimpleNamespace(is_short=True, leverage=1.0)
        value = strategy.custom_stoploss(
            "BTC/USDT:USDT", trade, datetime.now(timezone.utc), 100.0, 0.0099, False
        )
        self.assertIsNone(value)

    def test_break_even_locks_positive_open_relative_level(self) -> None:
        strategy = ProfitMaxIntradayShortProfitOnlyBreakEven15m({})
        trade = SimpleNamespace(is_short=True, leverage=1.0)
        value = strategy.custom_stoploss(
            "BTC/USDT:USDT", trade, datetime.now(timezone.utc), 99.0, 0.01, False
        )
        self.assertIsNotNone(value)
        self.assertGreater(value, 0.0)
        self.assertLess(value, 0.01)
        self.assertTrue(strategy.exit_profit_only)
        self.assertTrue(strategy.use_custom_stoploss)


if __name__ == "__main__":
    unittest.main()
