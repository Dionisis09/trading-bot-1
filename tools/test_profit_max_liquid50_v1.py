from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxLiquid50V1 import ProfitMaxLiquid50V1  # noqa: E402
from ProfitMaxSwingV5 import ProfitMaxV5Asymmetric50  # noqa: E402


class ProfitMaxLiquid50V1Tests(unittest.TestCase):
    def test_strategy_is_identity_subclass(self) -> None:
        self.assertTrue(issubclass(ProfitMaxLiquid50V1, ProfitMaxV5Asymmetric50))
        self.assertNotIn("populate_entry_trend", ProfitMaxLiquid50V1.__dict__)
        self.assertNotIn("populate_exit_trend", ProfitMaxLiquid50V1.__dict__)
        self.assertEqual(ProfitMaxLiquid50V1.short_stake_multiplier, 0.50)
        self.assertEqual(ProfitMaxLiquid50V1.timeframe, "4h")

    def test_config_matches_frozen_universe_and_fee(self) -> None:
        config = json.loads((ROOT / "user_data/config-profit-max-liquid50-cycle1.json").read_text(encoding="utf-8"))
        universe = json.loads((ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json").read_text(encoding="utf-8"))
        expected = [row["freqtrade_pair"] for row in universe["selected"]]
        self.assertEqual(config["exchange"]["pair_whitelist"], expected)
        self.assertEqual(config["fee"], 0.00075)
        self.assertEqual(config["max_open_trades"], 5)
        self.assertEqual(config["stake_amount"], 50)
        self.assertTrue(config["dry_run"])
        self.assertFalse(config["profit_max_research"]["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()
