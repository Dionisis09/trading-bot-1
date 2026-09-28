from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProDayTraderV3 import ProDayTraderV3  # noqa: E402
from ProDayTraderV4 import ProDayTraderV4  # noqa: E402


class ProDayTraderV4Tests(unittest.TestCase):
    @staticmethod
    def candles(rows: int, rising: bool = True) -> pd.DataFrame:
        direction = 1.0 if rising else -1.0
        close = 100.0 + direction * np.arange(rows, dtype=float) * 0.1
        return pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=rows, freq="4h", tz="UTC"),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(rows, 100.0),
            }
        )

    def test_4h_regime_uses_ema20_ema50_and_excludes_ema200(self) -> None:
        result = ProDayTraderV4._informative_indicators(self.candles(100), "4h")
        self.assertIn("ema20", result)
        self.assertIn("ema50", result)
        self.assertNotIn("ema200", result)
        self.assertTrue(bool(result["trend_long"].iloc[-1]))
        self.assertFalse(bool(result["trend_short"].iloc[-1]))
        expected = (result["ema20"].iloc[-1] - result["ema50"].iloc[-1]) / result["atr14"].iloc[-1]
        self.assertAlmostEqual(result["trend_gap_atr"].iloc[-1], expected, places=12)

    def test_4h_regime_is_side_symmetric(self) -> None:
        result = ProDayTraderV4._informative_indicators(self.candles(100, rising=False), "4h")
        self.assertFalse(bool(result["trend_long"].iloc[-1]))
        self.assertTrue(bool(result["trend_short"].iloc[-1]))

    def test_non_4h_indicators_are_inherited_exactly(self) -> None:
        source = self.candles(100).assign(
            date=pd.date_range("2025-01-01", periods=100, freq="1h", tz="UTC")
        )
        expected = ProDayTraderV3._informative_indicators(source, "1h")
        actual = ProDayTraderV4._informative_indicators(source, "1h")
        pd.testing.assert_frame_equal(actual, expected)

    def test_live_feasible_startup_and_deterministic_config(self) -> None:
        self.assertEqual(ProDayTraderV4.startup_candle_count, 2399)
        config = json.loads(
            (ROOT / "user_data/config-pro-day-v4-cycle1-research.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["strategy"], "ProDayTraderV4")
        self.assertTrue(config["dry_run"])
        self.assertEqual(config["initial_state"], "stopped")
        self.assertNotIn("freqai", config)
        self.assertEqual(config["pro_day_v4_research"]["recursive_qualification_count"], 2399)
        self.assertFalse(config["pro_day_v4_research"]["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()
