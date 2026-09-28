from __future__ import annotations

import unittest

from evaluate_profit_max_daily_v5_v2r_ensemble import stressed


class ThreeSleeveEvaluatorTests(unittest.TestCase):
    def test_stress_charges_both_sides(self) -> None:
        result = stressed([
            {"profit_abs": 2.0, "stake_amount": 100.0, "close_timestamp": 1},
            {"profit_abs": -1.0, "stake_amount": 50.0, "close_timestamp": 2},
        ], 0.0005)
        self.assertAlmostEqual(result["profit_usdt"], 0.85)


if __name__ == "__main__":
    unittest.main()
