import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evaluate_profit_max_portfolio_cycle2_train import evaluate, exposure, dd_pct  # noqa: E402


def trade(pair, opened, closed, profit, date="2021-01-01 04:00:00+00:00", stake=10.0):
    return {"pair": pair, "open_timestamp": opened, "close_timestamp": closed,
            "open_date": "2021-01-01 00:00:00+00:00", "close_date": date,
            "profit_abs": profit, "stake_amount": stake, "fee_open": 0.00075,
            "fee_close": 0.00075, "leverage": 1.0}


class Cycle2EvaluatorTests(unittest.TestCase):
    def test_liquid_duplicates_against_cross_or_v5_are_removed(self):
        cross = {"trades": [trade("A", 1, 2, 1)]}
        v5 = {"trades": [trade("B", 3, 4, 1)]}
        liquid = {"trades": [trade("A", 1, 5, 9), trade("B", 3, 6, 9), trade("C", 7, 8, 1)]}
        result = evaluate(cross, liquid, v5)
        self.assertEqual(result["deduplication"], {"liquid_raw_trades": 3, "liquid_overlaps_removed": 2, "liquid_retained_trades": 1})

    def test_exposure_is_half_open_at_equal_timestamp(self):
        self.assertEqual(exposure([trade("A", 1, 3, 1, stake=20), trade("B", 3, 4, 1, stake=30)]), (1, 30.0))

    def test_drawdown_groups_simultaneous_closes(self):
        self.assertEqual(dd_pct([trade("A", 1, 3, -10), trade("B", 1, 3, 5)]), 0.5)


if __name__ == "__main__":
    unittest.main()
