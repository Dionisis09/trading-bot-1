from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProDayTraderV6 import ProDayTraderV6  # noqa: E402


class ProDayTraderV6Tests(unittest.TestCase):
    def test_only_t1_candidates_can_enter(self) -> None:
        frame = pd.DataFrame({
            "candidate_T1_long": [True, False, False],
            "candidate_T1_short": [False, True, False],
            "candidate_R1_long": [False, False, True],
        })
        result = object.__new__(ProDayTraderV6).populate_entry_trend(frame, {})
        self.assertEqual(result["enter_long"].tolist(), [1, 0, 0])
        self.assertEqual(result["enter_short"].tolist(), [0, 1, 0])
        self.assertEqual(result["enter_tag"].tolist(), ["T1_long", "T1_short", ""])

    def test_only_t1_exit_columns_control_positions(self) -> None:
        frame = pd.DataFrame({
            "t1_exit_long_15m": [True, False, False],
            "t1_exit_short_15m": [False, True, False],
            "r1_exit_long": [False, False, True],
            "r1_exit_short": [False, False, True],
        })
        result = object.__new__(ProDayTraderV6).populate_exit_trend(frame, {})
        self.assertEqual(result["exit_long"].tolist(), [1, 0, 0])
        self.assertEqual(result["exit_short"].tolist(), [0, 1, 0])

    def test_custom_exit_has_no_180_minute_loser_cut(self) -> None:
        strategy = object.__new__(ProDayTraderV6)
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        trade = type("Trade", (), {"open_date_utc": now - timedelta(minutes=180)})()
        self.assertIsNone(strategy.custom_exit("BTC/USDT:USDT", trade, now, 100.0, -0.02))
        old = type("Trade", (), {"open_date_utc": now - timedelta(minutes=720)})()
        self.assertEqual(strategy.custom_exit("BTC/USDT:USDT", old, now, 100.0, -0.02), "T1_time_stop_720m")

    def test_config_is_isolated_stopped_and_live_disabled(self) -> None:
        config = json.loads((ROOT / "user_data/config-pro-day-v6-cycle1-research.json").read_text(encoding="utf-8"))
        self.assertEqual(config["strategy"], "ProDayTraderV6")
        self.assertEqual(config["initial_state"], "stopped")
        self.assertTrue(config["dry_run"])
        self.assertFalse(config["pro_day_v6_research"]["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()

