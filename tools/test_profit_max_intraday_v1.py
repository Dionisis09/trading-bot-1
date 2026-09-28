from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxIntradayV1 import (  # noqa: E402
    ProfitMaxIntradayBreakout15m,
    ProfitMaxIntradayHybrid15m,
    ProfitMaxIntradayReclaim15m,
)


def signal_frame(rows: int = 6) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trend_long_4h": [True] * rows,
            "trend_short_4h": [False] * rows,
            "ema_gap_atr_4h": [0.5] * rows,
            "ema20_1h": [102.0] * rows,
            "ema50_1h": [100.0] * rows,
            "momentum24_1h": [0.02] * rows,
            "adx14_1h": [23.0] * (rows - 1) + [25.0],
            "volume": [120.0] * rows,
            "volume_median_prev20": [100.0] * rows,
            "close": [101.0] * rows,
            "ema20": [100.0] * rows,
            "ema50": [99.0] * rows,
            "rsi14": [46.0] * rows,
            "channel_high_prev32": [100.0] * rows,
            "channel_low_prev32": [90.0] * rows,
        }
    )
    frame.loc[rows - 2, ["close", "rsi14"]] = [99.0, 44.0]
    frame.loc[rows - 1, "volume"] = 130.0
    return frame


class ProfitMaxIntradayTests(unittest.TestCase):
    def test_exact_family_and_fixed_risk_contract(self) -> None:
        candidates = [
            ProfitMaxIntradayReclaim15m,
            ProfitMaxIntradayBreakout15m,
            ProfitMaxIntradayHybrid15m,
        ]
        for candidate in candidates:
            self.assertEqual(candidate.timeframe, "15m")
            self.assertEqual(candidate.stoploss, -0.018)
            self.assertEqual(candidate.minimal_roi, {"0": 0.024, "240": 0.012, "720": 0.005, "1440": 0.0})
            self.assertEqual(len(candidate.research_pairs), 6)
            strategy = candidate(config={})
            self.assertEqual(strategy.protections, [{"method": "CooldownPeriod", "stop_duration_candles": 4}])
            self.assertEqual(
                strategy.leverage("BTC/USDT:USDT", datetime.now(timezone.utc), 1.0, 5.0, 125.0, None, "long"),
                1.0,
            )

    def test_reclaim_long_is_causal_and_tagged(self) -> None:
        strategy = ProfitMaxIntradayReclaim15m(config={})
        result = strategy.populate_entry_trend(signal_frame(), {"pair": "BTC/USDT:USDT"})
        self.assertEqual(int(result.iloc[-1]["enter_long"]), 1)
        self.assertEqual(int(result.iloc[-1]["enter_short"]), 0)
        self.assertEqual(result.iloc[-1]["enter_tag"], "intraday_reclaim_long")

    def test_reclaim_short_is_exact_mirror(self) -> None:
        frame = signal_frame()
        frame["trend_long_4h"] = False
        frame["trend_short_4h"] = True
        frame["ema_gap_atr_4h"] = -0.5
        frame["ema20_1h"] = 98.0
        frame["ema50_1h"] = 100.0
        frame["momentum24_1h"] = -0.02
        frame["ema20"] = 100.0
        frame["ema50"] = 101.0
        frame.loc[len(frame) - 2, ["close", "rsi14"]] = [101.0, 56.0]
        frame.loc[len(frame) - 1, ["close", "rsi14"]] = [99.0, 54.0]
        result = ProfitMaxIntradayReclaim15m(config={}).populate_entry_trend(frame, {})
        self.assertEqual(int(result.iloc[-1]["enter_short"]), 1)
        self.assertEqual(result.iloc[-1]["enter_tag"], "intraday_reclaim_short")

    def test_breakout_requires_expanding_completed_hour_adx(self) -> None:
        frame = signal_frame()
        result = ProfitMaxIntradayBreakout15m(config={}).populate_entry_trend(frame, {})
        self.assertEqual(int(result.iloc[-1]["enter_long"]), 1)
        frame.loc[len(frame) - 1, "adx14_1h"] = 22.0
        blocked = ProfitMaxIntradayBreakout15m(config={}).populate_entry_trend(frame, {})
        self.assertEqual(int(blocked.iloc[-1]["enter_long"]), 0)

    def test_hybrid_preserves_breakout_priority_tag(self) -> None:
        result = ProfitMaxIntradayHybrid15m(config={}).populate_entry_trend(signal_frame(), {})
        self.assertEqual(int(result.iloc[-1]["enter_long"]), 1)
        self.assertEqual(result.iloc[-1]["enter_tag"], "intraday_breakout_long")

    def test_config_locks_frequency_and_safety(self) -> None:
        config = json.loads((ROOT / "user_data/config-profit-max-intraday-cycle1.json").read_text(encoding="utf-8"))
        metadata = config["profit_max_intraday_research"]
        self.assertTrue(config["dry_run"])
        self.assertEqual(config["trading_mode"], "futures")
        self.assertEqual(config["margin_mode"], "isolated")
        self.assertEqual(config["max_open_trades"], 3)
        self.assertEqual(config["stake_amount"], 75)
        self.assertEqual(config["fee"], 0.00075)
        self.assertEqual(len(config["exchange"]["pair_whitelist"]), 6)
        self.assertEqual(config["exchange"]["key"], "")
        self.assertEqual(config["exchange"]["secret"], "")
        self.assertEqual(metadata["target_trades_per_day_min"], 1.0)
        self.assertEqual(metadata["target_trades_per_day_max"], 2.0)
        self.assertFalse(metadata["live_trading_authorized"])

    def test_source_uses_prior_channels_and_hourly_adx_lag(self) -> None:
        child = (ROOT / "user_data/strategies/ProfitMaxIntradayV1.py").read_text(encoding="utf-8")
        parent = (ROOT / "user_data/strategies/ProTournament15m.py").read_text(encoding="utf-8")
        self.assertIn('frame["adx14_1h"].shift(4)', child)
        self.assertIn('frame["high"].shift(1).rolling(32', parent)
        self.assertIn('frame["volume"].shift(1)', parent.replace('volume.shift(1)', 'frame["volume"].shift(1)'))


if __name__ == "__main__":
    unittest.main()
