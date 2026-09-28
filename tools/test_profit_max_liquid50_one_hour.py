import json
import sys
import unittest
from pathlib import Path

import pandas as pd
from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxLiquid50OneHour import (  # noqa: E402
    ProfitMaxLiquid50OneHour30,
    ProfitMaxLiquid50OneHour60,
    ProfitMaxLiquid50OneHour120,
)


class OneHourStrategyTests(unittest.TestCase):
    strategy_config = {"candle_type_def": CandleType.FUTURES}

    def test_fixed_horizons_and_runtime_contract(self):
        expected = {
            ProfitMaxLiquid50OneHour30: (30, 10),
            ProfitMaxLiquid50OneHour60: (60, 20),
            ProfitMaxLiquid50OneHour120: (120, 40),
        }
        for strategy_class, horizons in expected.items():
            strategy = strategy_class(self.strategy_config)
            self.assertEqual(strategy.timeframe, "1h")
            self.assertEqual((strategy.entry_channel_hours, strategy.exit_channel_hours), horizons)
            self.assertEqual(strategy.leverage("BTC/USDT:USDT", pd.Timestamp("2023-01-01"), 1, 1, 10, None, "long"), 1.0)

    def test_channels_are_shifted_and_horizon_specific(self):
        frame = pd.DataFrame(
            {
                "open": [float(value) for value in range(200)],
                "high": [float(value) for value in range(1, 201)],
                "low": [float(value) for value in range(200)],
                "close": [float(value) for value in range(200)],
                "volume": [1.0] * 200,
            }
        )
        for strategy_class in (ProfitMaxLiquid50OneHour30, ProfitMaxLiquid50OneHour60, ProfitMaxLiquid50OneHour120):
            strategy = strategy_class(self.strategy_config)
            populated = strategy.populate_indicators(frame.copy(), {})
            at = strategy.entry_channel_hours
            self.assertEqual(populated.loc[at, "entry_high"], float(at))
            self.assertEqual(populated.loc[at, "entry_low"], 0.0)

    def test_config_contract(self):
        config = json.loads((ROOT / "user_data/config-profit-max-liquid50-one-hour-cycle1.json").read_text(encoding="utf-8"))
        universe = json.loads((ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json").read_text(encoding="utf-8"))
        pairs = [row["freqtrade_pair"] for row in universe["selected"]]
        self.assertEqual(config["exchange"]["pair_whitelist"], pairs)
        self.assertEqual(config["fee"], 0.00075)
        self.assertEqual(config["timeframe"], "1h")
        self.assertTrue(config["dry_run"])
        self.assertEqual(config["max_open_trades"], 5)


if __name__ == "__main__":
    unittest.main()
