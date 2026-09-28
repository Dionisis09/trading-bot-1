from __future__ import annotations

import unittest

from evaluate_profit_max_daily_v5_ensemble_train import maximum_exposure, profit_factor, wallet_drawdown_pct


class DailyV5EvaluatorTests(unittest.TestCase):
    def test_profit_factor_and_wallet_drawdown(self) -> None:
        trades = [
            {"profit_abs": 10.0, "close_timestamp": 2},
            {"profit_abs": -5.0, "close_timestamp": 3},
            {"profit_abs": -5.0, "close_timestamp": 3},
            {"profit_abs": 5.0, "close_timestamp": 4},
        ]
        self.assertEqual(profit_factor(trades), 1.5)
        self.assertEqual(wallet_drawdown_pct(trades), 1.0)

    def test_maximum_exposure_nets_same_timestamp_events(self) -> None:
        trades = [
            {"stake_amount": 50.0, "open_timestamp": 1, "close_timestamp": 3},
            {"stake_amount": 40.0, "open_timestamp": 2, "close_timestamp": 4},
            {"stake_amount": 30.0, "open_timestamp": 3, "close_timestamp": 5},
        ]
        self.assertEqual(maximum_exposure(trades), (2, 90.0))


if __name__ == "__main__":
    unittest.main()

