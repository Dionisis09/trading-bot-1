from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from ProDayTraderV1 import ProDayTraderV1  # noqa: E402


class Wallets:
    def __init__(self, total: float) -> None:
        self.total = total

    def get_total_stake_amount(self) -> float:
        return self.total


class StakeHarness:
    risk_per_trade_fraction = ProDayTraderV1.risk_per_trade_fraction
    maximum_single_trade_stake_fraction = ProDayTraderV1.maximum_single_trade_stake_fraction
    minimum_sizing_stop_fraction = ProDayTraderV1.minimum_sizing_stop_fraction
    maximum_sizing_stop_fraction = ProDayTraderV1.maximum_sizing_stop_fraction

    def __init__(self, atr_pct: float | None, wallet: float = 1000.0) -> None:
        self.atr_pct = atr_pct
        self.wallets = Wallets(wallet)

    def _latest_analyzed(self, pair: str):
        if self.atr_pct is None:
            return None
        return pd.Series({"atr_pct": self.atr_pct})


class ProDayTraderTests(unittest.TestCase):
    @staticmethod
    def candles(rows: int) -> pd.DataFrame:
        index = np.arange(rows, dtype=float)
        mid = 100.0 + 0.01 * index + np.sin(index / 17.0)
        opened = mid + 0.05 * np.sin(index / 5.0)
        closed = mid + 0.05 * np.cos(index / 7.0)
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC"),
                "open": opened,
                "high": np.maximum(opened, closed) + 0.30,
                "low": np.minimum(opened, closed) - 0.30,
                "close": closed,
                "volume": 100.0 + (index % 11),
            }
        )

    def test_main_features_are_prefix_stable_and_previous_levels_are_shifted(self) -> None:
        full = ProDayTraderV1._main_indicators(self.candles(1200))
        prefix = ProDayTraderV1._main_indicators(self.candles(900))
        columns = [
            "atr",
            "relative_volume_48",
            "session_vwap",
            "weekly_vwap",
            "prev_day_high",
            "prev_day_low",
            "vp_poc",
            "structure_recent_high",
            "breakout_high_48",
        ]
        pd.testing.assert_frame_equal(
            prefix[columns],
            full.iloc[:900][columns].reset_index(drop=True),
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
        second_day = prefix[prefix["date"].dt.floor("D") == pd.Timestamp("2026-01-02", tz="UTC")]
        first_day = prefix[prefix["date"].dt.floor("D") == pd.Timestamp("2026-01-01", tz="UTC")]
        self.assertTrue((second_day["prev_day_high"] == first_day["high"].max()).all())
        self.assertTrue((second_day["prev_day_low"] == first_day["low"].min()).all())

    def test_rejection_mask_and_explanation_fail_independent_categories(self) -> None:
        frame = pd.DataFrame(
            {
                "required_data_ok": [True, False],
                "volatility_volume_ok": [True, True],
                "long_regime_score": [1, 2],
                "long_btc_context_ok": [True, True],
                "long_location_score": [1, 2],
                "long_structure_score": [1, 2],
                "long_trigger_score": [2, 2],
                "long_participation_score": [1, 2],
                "long_total_score": [7, 10],
            }
        )
        mask = ProDayTraderV1._rejection_mask(
            frame,
            side="long",
            minimum_regime=1,
            minimum_total=7,
        )
        self.assertEqual(mask.tolist(), [0, 1])
        self.assertEqual(ProDayTraderV1.explain_rejection(0), ["accepted"])
        self.assertEqual(
            ProDayTraderV1.explain_rejection(1 | 64),
            ["missing_or_nonfinite_data", "entry_trigger_gate"],
        )

    def test_atr_risk_sizing_caps_each_position_at_ten_percent_wallet(self) -> None:
        harness = StakeHarness(atr_pct=0.01)
        stake = ProDayTraderV1.custom_stake_amount(
            harness,
            "BTC/USDT:USDT",
            datetime.now(timezone.utc),
            50_000.0,
            200.0,
            5.0,
            500.0,
            1.0,
            "trend_pullback_long",
            "long",
        )
        self.assertEqual(stake, 100.0)
        rejected = ProDayTraderV1.custom_stake_amount(
            harness,
            "BTC/USDT:USDT",
            datetime.now(timezone.utc),
            50_000.0,
            200.0,
            110.0,
            500.0,
            1.0,
            "trend_pullback_long",
            "long",
        )
        self.assertEqual(rejected, 0.0)

    def test_stake_sizing_fails_closed_when_atr_is_missing(self) -> None:
        harness = StakeHarness(atr_pct=None)
        value = ProDayTraderV1.custom_stake_amount(
            harness,
            "BTC/USDT:USDT",
            datetime.now(timezone.utc),
            50_000.0,
            200.0,
            5.0,
            500.0,
            1.0,
            None,
            "long",
        )
        self.assertEqual(value, 0.0)

    def test_time_stops_are_fixed_and_leverage_is_one(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        losing_trade = type("Trade", (), {"open_date_utc": now - timedelta(minutes=181)})()
        old_trade = type("Trade", (), {"open_date_utc": now - timedelta(minutes=721)})()
        self.assertEqual(
            ProDayTraderV1.custom_exit(object(), "BTC/USDT:USDT", losing_trade, now, 1.0, -0.001),
            "stale_loser_180m",
        )
        self.assertEqual(
            ProDayTraderV1.custom_exit(object(), "BTC/USDT:USDT", old_trade, now, 1.0, 0.05),
            "time_stop_720m",
        )
        self.assertEqual(
            ProDayTraderV1.leverage(
                object(), "BTC/USDT:USDT", now, 1.0, 20.0, 125.0, None, "long"
            ),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
