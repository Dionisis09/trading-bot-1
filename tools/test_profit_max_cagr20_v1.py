from __future__ import annotations

import sys
import unittest
from pathlib import Path


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
if str(STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGY_DIR))

from ProfitMaxCagr20V1 import ProfitMaxCagr20V1  # noqa: E402


class ProfitMaxCagr20V1Tests(unittest.TestCase):
    def test_locked_leverage_and_price_stop(self) -> None:
        self.assertEqual(ProfitMaxCagr20V1.fixed_research_leverage, 3.5)
        self.assertEqual(ProfitMaxCagr20V1.stoploss, -0.35)
        self.assertAlmostEqual(
            abs(ProfitMaxCagr20V1.stoploss) / ProfitMaxCagr20V1.fixed_research_leverage,
            0.10,
        )

    def test_live_launch_is_not_implicitly_enabled(self) -> None:
        strategy = object.__new__(ProfitMaxCagr20V1)
        strategy.config = {"user_data_dir": "user_data"}
        self.assertEqual(
            strategy._risk_policy_path().name,
            "risk_policy_profit_max_cagr20_v1.json",
        )


if __name__ == "__main__":
    unittest.main()
