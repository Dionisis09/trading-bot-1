import sys
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from run_profit_max_swing_cycle5 import gates, row_passes, select_winner


def row(strategy, split, ret=10.0, pf=1.5, dd=4.0, trades=120, longs=60, shorts=60, ratio=2.5):
    return {
        "strategy": strategy, "split": split, "return_pct": ret, "profit_factor": pf,
        "wallet_drawdown_pct": dd, "trades": trades, "long_trades": longs, "short_trades": shorts,
        "return_to_drawdown": ratio, "year_profit_abs_usdt": {"2024": 10.0, "2025": 10.0},
    }


class Cycle5RunnerTests(unittest.TestCase):
    def test_train_gate_requires_side_breadth(self):
        candidate = row("ProfitMaxV5Asymmetric50", "train", shorts=24)
        self.assertFalse(row_passes(candidate, "train"))
        self.assertFalse(gates(candidate, "train")["short_gte_25"])

    def test_validation_gate_requires_each_year_positive(self):
        candidate = row("ProfitMaxV5Balanced", "validation", trades=80, longs=40, shorts=40)
        candidate["year_profit_abs_usdt"]["2025"] = -1
        self.assertFalse(row_passes(candidate, "validation"))

    def test_long_only_is_never_eligible(self):
        candidate = row("ProfitMaxV5LongOnly", "train", ret=100, pf=10, ratio=20, shorts=0)
        self.assertFalse(row_passes(candidate, "train"))

    def test_selection_uses_validation_return_to_drawdown(self):
        names = ["DualTrendFuturesV2R", "ProfitMaxV5Asymmetric50"]
        train = [row(name, "train") for name in names]
        validation = [row(names[0], "validation", trades=80, longs=40, shorts=40, ratio=2.0), row(names[1], "validation", trades=80, longs=40, shorts=40, ratio=3.0)]
        self.assertEqual(select_winner(train, validation), names[1])


if __name__ == "__main__":
    unittest.main()
