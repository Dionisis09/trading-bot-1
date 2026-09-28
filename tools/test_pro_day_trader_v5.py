from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProDayTraderV5 import ProDayTraderV5  # noqa: E402


class Wallets:
    @staticmethod
    def get_total_stake_amount() -> float:
        return 1000.0


class ProDayTraderV5Tests(unittest.TestCase):
    def test_vectorized_exits_are_symmetric_and_fail_closed(self) -> None:
        frame = pd.DataFrame(
            {
                "r1_exit_long": [True, False, False],
                "r1_exit_short": [False, True, False],
                "t1_exit_long_15m": [False, False, True],
                "t1_exit_short_15m": [False, False, True],
            }
        )
        strategy = object.__new__(ProDayTraderV5)
        result = strategy.populate_exit_trend(frame, {})
        self.assertEqual(result["exit_long"].tolist(), [1, 0, 1])
        self.assertEqual(result["exit_short"].tolist(), [0, 1, 1])
        empty = strategy.populate_exit_trend(pd.DataFrame(index=range(2)), {})
        self.assertEqual(empty["exit_long"].tolist(), [0, 0])
        self.assertEqual(empty["exit_short"].tolist(), [0, 0])

    def test_fixed_risk_sizing_uses_no_analyzed_dataframe(self) -> None:
        strategy = object.__new__(ProDayTraderV5)
        strategy.wallets = Wallets()
        strategy.dp = type("Forbidden", (), {"get_analyzed_dataframe": lambda *args: self.fail("dp read")})()
        stake = strategy.custom_stake_amount(
            "BTC/USDT:USDT", datetime.now(timezone.utc), 50_000.0,
            100.0, 5.0, 500.0, 1.0, "T1_long", "long",
        )
        self.assertEqual(stake, 62.5)
        self.assertEqual(
            strategy.custom_stake_amount(
                "BTC/USDT:USDT", datetime.now(timezone.utc), 50_000.0,
                100.0, 70.0, 500.0, 1.0, "T1_long", "long",
            ),
            0.0,
        )

    def test_custom_exit_uses_only_time_profit_and_tag(self) -> None:
        strategy = object.__new__(ProDayTraderV5)
        strategy.dp = type("Forbidden", (), {"get_analyzed_dataframe": lambda *args: self.fail("dp read")})()
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        trade = type("Trade", (), {"open_date_utc": now - timedelta(minutes=60), "enter_tag": "R1_long"})()
        self.assertEqual(strategy.custom_exit("BTC/USDT:USDT", trade, now, 100.0, 0.01), "R1_time_exit_60m")
        loser = type("Trade", (), {"open_date_utc": now - timedelta(minutes=180), "enter_tag": "T1_long"})()
        self.assertEqual(strategy.custom_exit("BTC/USDT:USDT", loser, now, 100.0, -0.01), "stale_loser_180m")

    def test_config_is_stopped_deterministic_and_one_x(self) -> None:
        config = json.loads((ROOT / "user_data/config-pro-day-v5-cycle1-research.json").read_text(encoding="utf-8"))
        self.assertEqual(config["strategy"], "ProDayTraderV5")
        self.assertTrue(config["dry_run"])
        self.assertEqual(config["initial_state"], "stopped")
        self.assertNotIn("freqai", config)
        self.assertEqual(config["pro_day_v5_research"]["leverage"], 1)
        self.assertFalse(config["pro_day_v5_research"]["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()
