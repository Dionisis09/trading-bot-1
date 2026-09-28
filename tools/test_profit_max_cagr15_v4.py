from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from ProfitMaxCagr15V4 import ProfitMaxCagr15V4
from ProfitMaxCagr15V5 import ProfitMaxCagr15V5


class ProfitMaxCagr15V4Tests(unittest.TestCase):
    def test_fixed_leverage_is_bounded_by_exchange_maximum(self) -> None:
        strategy = ProfitMaxCagr15V4.__new__(ProfitMaxCagr15V4)
        self.assertEqual(
            strategy.leverage(
                "BTC/USDT:USDT", datetime.now(timezone.utc), 1.0, 1.0, 5.0, None, "long"
            ),
            2.5,
        )
        self.assertEqual(
            strategy.leverage(
                "BTC/USDT:USDT", datetime.now(timezone.utc), 1.0, 1.0, 2.0, None, "long"
            ),
            2.0,
        )

    def test_adapter_supplies_fixed_leverage_to_guard(self) -> None:
        strategy = ProfitMaxCagr15V4.__new__(ProfitMaxCagr15V4)
        target = "ProfessionalRisk.ProfessionalRiskMixin.confirm_trade_entry"
        with patch(target, return_value=True) as guard:
            allowed = strategy.confirm_trade_entry(
                pair="BTC/USDT:USDT",
                order_type="limit",
                amount=1.0,
                rate=100.0,
                time_in_force="GTC",
                current_time=datetime.now(timezone.utc),
                entry_tag="tag",
                side="long",
            )
        self.assertTrue(allowed)
        self.assertEqual(guard.call_args.kwargs["leverage"], 2.5)

    def test_cycle5_preserves_underlying_stop_and_uses_isolated_policy(self) -> None:
        strategy = ProfitMaxCagr15V5.__new__(ProfitMaxCagr15V5)
        strategy.config = {"user_data_dir": "/freqtrade/user_data"}
        self.assertEqual(strategy.stoploss, -0.25)
        self.assertEqual(
            strategy._risk_policy_path().as_posix(),
            "/freqtrade/user_data/risk_policy_profit_max_cagr15_cycle5.json",
        )


if __name__ == "__main__":
    unittest.main()
