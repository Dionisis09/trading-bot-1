from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from ProDayTraderV2 import ProDayTraderV2  # noqa: E402


class Wallets:
    def __init__(self, total: float) -> None:
        self.total = total

    def get_total_stake_amount(self) -> float:
        return self.total


class StakeHarness:
    risk_per_trade_fraction = ProDayTraderV2.risk_per_trade_fraction
    maximum_single_trade_stake_fraction = ProDayTraderV2.maximum_single_trade_stake_fraction
    minimum_sizing_stop_fraction = ProDayTraderV2.minimum_sizing_stop_fraction
    maximum_sizing_stop_fraction = ProDayTraderV2.maximum_sizing_stop_fraction
    atr_sizing_multiple = ProDayTraderV2.atr_sizing_multiple

    def __init__(self, atr_pct: float | None, wallet: float = 1000.0) -> None:
        self.atr_pct = atr_pct
        self.wallets = Wallets(wallet)

    def _latest_analyzed(self, pair: str):
        if self.atr_pct is None:
            return None
        return pd.Series({"atr_pct": self.atr_pct})


class ProDayTraderV2Tests(unittest.TestCase):
    @staticmethod
    def candles(rows: int, frequency: str = "5min") -> pd.DataFrame:
        index = np.arange(rows, dtype=float)
        mid = 100.0 + 0.02 * index + np.sin(index / 13.0)
        opened = mid + 0.04 * np.sin(index / 5.0)
        closed = mid + 0.04 * np.cos(index / 7.0)
        return pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=rows, freq=frequency, tz="UTC"),
                "open": opened,
                "high": np.maximum(opened, closed) + 0.30,
                "low": np.minimum(opened, closed) - 0.30,
                "close": closed,
                "volume": 100.0 + (index % 11),
            }
        )

    def test_informative_value_is_unavailable_until_real_close(self) -> None:
        base = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=13, freq="5min", tz="UTC"),
                "close": np.arange(13, dtype=float),
            }
        )
        informative = pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-01-01T00:00:00Z")],
                "known": [42.0],
            }
        )
        merged = ProDayTraderV2._causal_merge(base, informative, "1h")
        self.assertTrue(merged.loc[:10, "known_1h"].isna().all())
        self.assertEqual(merged.loc[11, "known_1h"], 42.0)
        self.assertEqual(merged.loc[12, "known_1h"], 42.0)

    def test_previous_15m_channel_excludes_current_candle(self) -> None:
        candles = self.candles(24, "15min")
        candles.loc[:19, "high"] = np.arange(20, dtype=float) + 100.0
        candles.loc[:19, "low"] = np.arange(20, dtype=float) + 50.0
        candles.loc[20, ["high", "low", "close"]] = [9999.0, 1.0, 5000.0]
        result = ProDayTraderV2._informative_indicators(candles, "15m")
        self.assertEqual(result.loc[20, "channel_high_prev20"], 119.0)
        self.assertEqual(result.loc[20, "channel_low_prev20"], 50.0)

    @staticmethod
    def candidate_frame() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [100.0] * 8,
                "high": [101.0] * 8,
                "low": [99.0] * 8,
                "close": [99.0, 101.0, 101.0, 99.0, 99.0, 101.0, 101.0, 99.0],
                "volume": [200.0] * 8,
                "volume_median_prev20": [100.0] * 8,
                "ema20": [100.0] * 8,
                "ema20_15m": [110.0, 110.0, 90.0, 90.0, 100.0, 100.0, 100.0, 100.0],
                "ema50_15m": [100.0] * 8,
                "trend_long_4h": [True, True, False, False, False, False, False, False],
                "trend_short_4h": [False, False, True, True, False, False, False, False],
                "momentum24_1h": [0.1, 0.1, -0.1, -0.1, 0.0, 0.0, 0.0, 0.0],
                "adx14_1h": [25.0, 25.0, 25.0, 25.0, 10.0, 10.0, 10.0, 10.0],
                "z48": [0.0, 0.0, 0.0, 0.0, -2.5, -1.5, 2.5, 1.5],
            }
        )

    def test_candidate_sides_are_symmetric_and_t1_has_priority(self) -> None:
        result = ProDayTraderV2._candidate_masks(self.candidate_frame())
        self.assertTrue(result.loc[1, "candidate_T1_long"])
        self.assertEqual(result.loc[1, "candidate_side"], 1.0)
        self.assertTrue(result.loc[3, "candidate_T1_short"])
        self.assertEqual(result.loc[3, "candidate_side"], -1.0)
        self.assertTrue(result.loc[5, "candidate_R1_long"])
        self.assertEqual(result.loc[5, "candidate_side"], 1.0)
        self.assertTrue(result.loc[7, "candidate_R1_short"])
        self.assertEqual(result.loc[7, "candidate_side"], -1.0)
        self.assertFalse(
            (result[["candidate_T1_long", "candidate_T1_short", "candidate_R1_long", "candidate_R1_short"]].sum(axis=1) > 1).any()
        )

    def test_target_uses_t_plus_1_and_t_plus_13_and_deducts_26_bps(self) -> None:
        opens = np.full(16, 100.0)
        opens[1] = 100.0
        opens[13] = 110.0
        frame = pd.DataFrame(
            {
                "open": opens,
                "candidate_side": [1.0, 0.0] + [0.0] * 14,
            }
        )
        target = ProDayTraderV2._candidate_target(frame)
        self.assertAlmostEqual(target.iloc[0], np.log(110.0 / 100.0) - 0.0026, places=15)
        self.assertTrue(target.iloc[1:].isna().all())

        # Altering open[t] is irrelevant; the executable entry remains open[t+1].
        changed_t = frame.copy()
        changed_t.loc[0, "open"] = 1.0
        self.assertEqual(
            ProDayTraderV2._candidate_target(changed_t).iloc[0],
            target.iloc[0],
        )
        changed_entry = frame.copy()
        changed_entry.loc[1, "open"] = 200.0
        self.assertNotEqual(
            ProDayTraderV2._candidate_target(changed_entry).iloc[0],
            target.iloc[0],
        )

        short_opens = np.full(16, 100.0)
        short_opens[13] = 90.0
        short_frame = pd.DataFrame(
            {
                "open": short_opens,
                "candidate_side": [-1.0] + [0.0] * 15,
            }
        )
        self.assertAlmostEqual(
            ProDayTraderV2._candidate_target(short_frame).iloc[0],
            -np.log(90.0 / 100.0) - 0.0026,
            places=15,
        )

    def test_noncandidate_labels_are_nan_even_with_future_prices(self) -> None:
        frame = pd.DataFrame(
            {
                "open": np.linspace(100.0, 120.0, 20),
                "candidate_side": np.zeros(20),
            }
        )
        self.assertTrue(ProDayTraderV2._candidate_target(frame).isna().all())

    def test_prediction_veto_fails_closed_and_never_creates_a_side(self) -> None:
        frame = pd.DataFrame(
            {
                "candidate_T1_long": [True, True, False, False, False],
                "candidate_T1_short": [False] * 5,
                "candidate_R1_long": [False] * 5,
                "candidate_R1_short": [False, False, True, True, False],
                "do_predict": [1, 0, 1, 1, 1],
                ProDayTraderV2.target_column: [0.01, 0.01, np.nan, -0.01, 1.0],
            }
        )
        strategy = object.__new__(ProDayTraderV2)
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(result["enter_long"].tolist(), [1, 0, 0, 0, 0])
        self.assertEqual(result["enter_short"].tolist(), [0, 0, 0, 0, 0])
        self.assertEqual(result.loc[0, "enter_tag"], "T1_long")
        self.assertEqual(result.loc[4, "enter_tag"], "")

    def test_deterministic_tags_cover_each_setup_and_side(self) -> None:
        frame = pd.DataFrame(
            {
                "candidate_T1_long": [True, False, False, False],
                "candidate_T1_short": [False, True, False, False],
                "candidate_R1_long": [False, False, True, False],
                "candidate_R1_short": [False, False, False, True],
                "do_predict": [1, 1, 1, 1],
                ProDayTraderV2.target_column: [0.01, 0.01, 0.01, 0.01],
            }
        )
        strategy = object.__new__(ProDayTraderV2)
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(result["enter_tag"].tolist(), ["T1_long", "T1_short", "R1_long", "R1_short"])
        self.assertEqual(result["enter_long"].tolist(), [1, 0, 1, 0])
        self.assertEqual(result["enter_short"].tolist(), [0, 1, 0, 1])

    def test_safe_stake_and_one_x_leverage(self) -> None:
        harness = StakeHarness(atr_pct=0.01)
        stake = ProDayTraderV2.custom_stake_amount(
            harness,
            "BTC/USDT:USDT",
            datetime.now(timezone.utc),
            50_000.0,
            200.0,
            5.0,
            500.0,
            1.0,
            "T1_long",
            "long",
        )
        self.assertEqual(stake, 100.0)
        rejected = ProDayTraderV2.custom_stake_amount(
            harness,
            "BTC/USDT:USDT",
            datetime.now(timezone.utc),
            50_000.0,
            200.0,
            110.0,
            500.0,
            1.0,
            "T1_long",
            "long",
        )
        self.assertEqual(rejected, 0.0)
        self.assertEqual(
            ProDayTraderV2.leverage(
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

    def test_setup_specific_and_safety_exits(self) -> None:
        strategy = object.__new__(ProDayTraderV2)
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

        strategy._latest_analyzed = lambda pair: pd.Series(
            {
                "r1_exit_long": True,
                "r1_exit_short": False,
                "t1_exit_long_15m": True,
                "t1_exit_short_15m": False,
            }
        )
        r1 = type(
            "Trade",
            (),
            {
                "open_date_utc": now - pd.Timedelta(minutes=55),
                "enter_tag": "R1_long",
                "is_short": False,
            },
        )()
        t1 = type(
            "Trade",
            (),
            {
                "open_date_utc": now - pd.Timedelta(minutes=55),
                "enter_tag": "T1_long",
                "is_short": False,
            },
        )()
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", r1, now, 100.0, 0.01),
            "R1_z48_zero_cross",
        )
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", t1, now, 100.0, 0.01),
            "T1_15m_ema_cross",
        )

        strategy._latest_analyzed = lambda pair: pd.Series(dtype=float)
        r1_old = type(
            "Trade",
            (),
            {
                "open_date_utc": now - pd.Timedelta(minutes=61),
                "enter_tag": "R1_short",
                "is_short": True,
            },
        )()
        loser = type(
            "Trade",
            (),
            {
                "open_date_utc": now - pd.Timedelta(minutes=181),
                "enter_tag": "T1_long",
                "is_short": False,
            },
        )()
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", r1_old, now, 100.0, 0.01),
            "R1_time_exit_60m",
        )
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", loser, now, 100.0, -0.01),
            "stale_loser_180m",
        )

    def test_config_freezes_exact_model_and_no_expansion(self) -> None:
        config = json.loads(
            (ROOT / "user_data" / "config-pro-day-v2-research.json").read_text(encoding="utf-8")
        )
        self.assertTrue(config["dry_run"])
        self.assertEqual(config["trading_mode"], "futures")
        self.assertEqual(config["margin_mode"], "isolated")
        self.assertEqual(config["freqaimodel"], "LightGBMRegressor")
        self.assertEqual(config["freqai"]["train_period_days"], 365)
        self.assertEqual(config["freqai"]["backtest_period_days"], 30)
        self.assertEqual(config["freqai"]["feature_parameters"]["include_shifted_candles"], 0)
        self.assertEqual(config["freqai"]["data_split_parameters"]["test_size"], 0)
        self.assertEqual(config["freqai"]["model_training_parameters"]["n_estimators"], 200)
        self.assertFalse(config["pro_day_v2_research"]["automatic_feature_expansion"])
        self.assertEqual(
            config["datadir"],
            "user_data/data/binance/pro_day_v2_canonical",
        )
        self.assertEqual(
            config["exchange"]["pair_whitelist"],
            list(ProDayTraderV2.research_pairs),
        )
        self.assertEqual(
            config["freqai"]["model_training_parameters"],
            {
                "n_estimators": 200,
                "learning_rate": 0.03,
                "num_leaves": 15,
                "max_depth": 4,
                "min_child_samples": 200,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "n_jobs": 2,
                "deterministic": True,
                "force_col_wise": True,
                "random_state": 20260811,
                "random_seed": 20260811,
                "data_random_seed": 20260811,
                "feature_fraction_seed": 20260811,
                "bagging_seed": 20260811,
            },
        )

    def test_real_datakitchen_raw_and_prepared_feature_paths_match(self) -> None:
        """Exercise FreqAI's real use_strategy_to_populate_indicators path.

        Background training and backtest prediction hand DataKitchen raw base
        dataframes, not the frame prepared in populate_indicators().  The
        standard hook must therefore reproduce the exact same 19 inputs.
        """

        # The pinned standard image intentionally omits FreqAI-only datasieve.
        # Stub only that unused pipeline dependency while exercising the real
        # 2026.7 DataKitchen feature-population implementation.
        try:
            from datasieve.pipeline import Pipeline as _Pipeline  # noqa: F401
        except ModuleNotFoundError:
            datasieve_module = types.ModuleType("datasieve")
            pipeline_module = types.ModuleType("datasieve.pipeline")

            class Pipeline:
                def __init__(self, *args, **kwargs) -> None:
                    pass

            pipeline_module.Pipeline = Pipeline
            sys.modules["datasieve"] = datasieve_module
            sys.modules["datasieve.pipeline"] = pipeline_module

        from freqtrade.freqai.data_kitchen import FreqaiDataKitchen

        config = json.loads(
            (ROOT / "user_data" / "config-pro-day-v2-research.json").read_text(encoding="utf-8")
        )
        config["user_data_dir"] = str(ROOT / "user_data")
        config["timerange"] = "20250101-20250801"
        strategy = ProDayTraderV2(config)

        base_5m = self.candles(2400, "5min")
        frames = {
            (ProDayTraderV2.btc_pair, "5m"): base_5m,
            (ProDayTraderV2.btc_pair, "15m"): self.candles(800, "15min"),
            (ProDayTraderV2.btc_pair, "1h"): self.candles(400, "1h"),
            (ProDayTraderV2.btc_pair, "4h"): self.candles(260, "4h"),
            ("ETH/USDT:USDT", "5m"): base_5m.assign(
                open=base_5m["open"] * 0.8,
                high=base_5m["high"] * 0.8,
                low=base_5m["low"] * 0.8,
                close=base_5m["close"] * 0.8,
            ),
            ("ETH/USDT:USDT", "15m"): self.candles(800, "15min"),
            ("ETH/USDT:USDT", "1h"): self.candles(400, "1h"),
            ("ETH/USDT:USDT", "4h"): self.candles(260, "4h"),
        }

        class DataProvider:
            @staticmethod
            def current_whitelist():
                return [ProDayTraderV2.btc_pair, "ETH/USDT:USDT"]

            @staticmethod
            def get_pair_dataframe(pair: str, timeframe: str):
                return frames[(pair, timeframe)].copy()

        strategy.dp = DataProvider()
        compare_columns = list(ProDayTraderV2.FEATURE_COLUMNS) + [
            "candidate_T1_long",
            "candidate_T1_short",
            "candidate_R1_long",
            "candidate_R1_short",
            "candidate_side",
        ]
        for pair in (ProDayTraderV2.btc_pair, "ETH/USDT:USDT"):
            raw = frames[(pair, "5m")].copy()
            prepared = strategy._prepare_signal_frame(raw, {"pair": pair})
            prepared_features = strategy.feature_engineering_standard(prepared, {"pair": pair})

            kitchen = FreqaiDataKitchen(config, live=True, pair=pair)
            through_kitchen = kitchen.use_strategy_to_populate_indicators(
                strategy,
                prediction_dataframe=raw,
                pair=pair,
            )
            self.assertEqual(
                [column for column in through_kitchen if column.startswith("%")],
                list(ProDayTraderV2.FEATURE_COLUMNS),
            )
            pd.testing.assert_frame_equal(
                through_kitchen[compare_columns].reset_index(drop=True),
                prepared_features[compare_columns].reset_index(drop=True),
                check_dtype=False,
                check_exact=False,
                rtol=1e-12,
                atol=1e-12,
            )


if __name__ == "__main__":
    unittest.main()
