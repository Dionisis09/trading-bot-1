from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from ProDayTraderV2 import ProDayTraderV2  # noqa: E402
from ProDayTraderV3 import ProDayTraderV3  # noqa: E402


class ProDayTraderV3Tests(unittest.TestCase):
    def test_direct_entries_cover_both_setups_and_sides_without_ml_columns(self) -> None:
        frame = pd.DataFrame(
            {
                "candidate_T1_long": [True, False, False, False, False],
                "candidate_T1_short": [False, True, False, False, False],
                "candidate_R1_long": [False, False, True, False, False],
                "candidate_R1_short": [False, False, False, True, False],
            }
        )
        strategy = object.__new__(ProDayTraderV3)
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(
            result["enter_tag"].tolist(),
            ["T1_long", "T1_short", "R1_long", "R1_short", ""],
        )
        self.assertEqual(result["enter_long"].tolist(), [1, 0, 1, 0, 0])
        self.assertEqual(result["enter_short"].tolist(), [0, 1, 0, 1, 0])
        self.assertNotIn("do_predict", result)
        self.assertNotIn(ProDayTraderV2.target_column, result)

    def test_missing_candidate_columns_fail_closed(self) -> None:
        strategy = object.__new__(ProDayTraderV3)
        result = strategy.populate_entry_trend(pd.DataFrame(index=range(3)), {})
        self.assertEqual(result["enter_long"].tolist(), [0, 0, 0])
        self.assertEqual(result["enter_short"].tolist(), [0, 0, 0])
        self.assertEqual(result["enter_tag"].tolist(), ["", "", ""])

    def test_populate_indicators_never_starts_freqai(self) -> None:
        strategy = object.__new__(ProDayTraderV3)
        expected = pd.DataFrame({"sentinel": [1.0]})
        calls: list[tuple[pd.DataFrame, dict]] = []

        def prepare(frame: pd.DataFrame, metadata: dict) -> pd.DataFrame:
            calls.append((frame, metadata))
            return expected

        strategy._prepare_signal_frame = prepare
        strategy.freqai = type(
            "ForbiddenFreqAI",
            (),
            {"start": staticmethod(lambda *args, **kwargs: self.fail("FreqAI was invoked"))},
        )()
        source = pd.DataFrame({"close": [100.0]})
        self.assertIs(strategy.populate_indicators(source, {"pair": "BTC/USDT:USDT"}), expected)
        self.assertEqual(len(calls), 1)

    def test_config_is_deterministic_and_research_only(self) -> None:
        config = json.loads(
            (ROOT / "user_data" / "config-pro-day-v3-cycle1-research.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["strategy"], "ProDayTraderV3")
        self.assertTrue(config["dry_run"])
        self.assertEqual(config["initial_state"], "stopped")
        self.assertEqual(config["timeframe"], "5m")
        self.assertEqual(config["trading_mode"], "futures")
        self.assertEqual(config["margin_mode"], "isolated")
        self.assertEqual(config["max_open_trades"], 2)
        self.assertEqual(config["fee"], 0.0005)
        self.assertNotIn("freqai", config)
        self.assertNotIn("freqaimodel", config)
        self.assertFalse(config["pro_day_v3_research"]["ml_order_gate"])
        self.assertFalse(config["pro_day_v3_research"]["live_trading_authorized"])
        self.assertEqual(
            config["exchange"]["pair_whitelist"],
            list(ProDayTraderV3.research_pairs),
        )

    def test_inherits_risk_limits_and_one_x_leverage(self) -> None:
        self.assertEqual(ProDayTraderV3.startup_candle_count, 399)
        self.assertEqual(ProDayTraderV3.risk_per_trade_fraction, 0.0025)
        self.assertEqual(ProDayTraderV3.stoploss, -0.04)
        self.assertIs(ProDayTraderV3.custom_stake_amount, ProDayTraderV2.custom_stake_amount)
        self.assertIs(ProDayTraderV3.custom_exit, ProDayTraderV2.custom_exit)
        self.assertEqual(
            ProDayTraderV3.leverage(
                object(),
                "BTC/USDT:USDT",
                datetime.now(timezone.utc),
                50_000.0,
                20.0,
                125.0,
                None,
                "long",
            ),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
