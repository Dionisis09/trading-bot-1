from __future__ import annotations

import sys
import unittest
from pathlib import Path


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
if str(STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGY_DIR))

from ProfitMaxCagr20V4 import ProfitMaxCagr20V4  # noqa: E402


class ProfitMax20V4Tests(unittest.TestCase):
    def test_leverage_and_stop_contract(self) -> None:
        self.assertEqual(ProfitMaxCagr20V4.fixed_research_leverage, 3.64)
        self.assertEqual(ProfitMaxCagr20V4.stoploss, -0.364)
        self.assertAlmostEqual(abs(ProfitMaxCagr20V4.stoploss) / 3.64, 0.10)

    def test_dedicated_policy(self) -> None:
        strategy = object.__new__(ProfitMaxCagr20V4)
        strategy.config = {"user_data_dir": "user_data"}
        self.assertEqual(strategy._risk_policy_path().name, "risk_policy_profit_max_cagr20_v4.json")


if __name__ == "__main__":
    unittest.main()
