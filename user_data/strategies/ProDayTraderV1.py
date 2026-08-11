"""Frozen intraday research challenger with causal multi-timeframe evidence.

The exact rules and qualification gates are locked in
``docs/pro_day_trader_v1_locked_plan.md``.  Public derivatives and beta
order-flow inputs are deliberately shadow-only in this first version because
their point-in-time history does not cover the historical qualification window.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame, Series
import talib.abstract as ta

from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute
from ProfessionalRisk import ProfessionalRiskMixin


logger = logging.getLogger(__name__)


class ProDayTraderV1(ProfessionalRiskMixin, IStrategy):
    """Single frozen pro-style intraday candidate; not a live authorization."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 3199

    minimal_roi = {"0": 100.0}
    stoploss = -0.04
    trailing_stop = False
    use_custom_stoploss = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    informative_timeframes = ("15m", "1h", "4h")
    research_pairs = (
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "BNB/USDT:USDT",
    )
    btc_pair = "BTC/USDT:USDT"

    risk_per_trade_fraction = 0.0025
    maximum_single_trade_stake_fraction = 0.10
    minimum_sizing_stop_fraction = 0.0075
    maximum_sizing_stop_fraction = 0.03

    REJECTION_FLAGS = {
        1: "missing_or_nonfinite_data",
        2: "volatility_or_volume_gate",
        4: "market_regime_gate",
        8: "btc_context_gate",
        16: "price_location_gate",
        32: "market_structure_gate",
        64: "entry_trigger_gate",
        128: "participation_gate",
        256: "total_score_gate",
    }

    @property
    def protections(self) -> list[dict[str, Any]]:
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 3},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 144,
                "trade_limit": 3,
                "stop_duration_candles": 48,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 2016,
                "trade_limit": 10,
                "stop_duration_candles": 288,
                "max_allowed_drawdown": 0.08,
            },
        ]

    def informative_pairs(self) -> list[tuple[str, str]]:
        pairs = set(self.research_pairs)
        if self.dp is not None:
            try:
                pairs.update(self.dp.current_whitelist())
            except (AttributeError, TypeError):
                pass
        pairs.add(self.btc_pair)
        return sorted((pair, timeframe) for pair in pairs for timeframe in self.informative_timeframes)

    @staticmethod
    def _choppiness(dataframe: DataFrame, period: int = 14) -> Series:
        previous_close = dataframe["close"].shift(1)
        true_range = pd.concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - previous_close).abs(),
                (dataframe["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        range_high_low = (
            dataframe["high"].rolling(period, min_periods=period).max()
            - dataframe["low"].rolling(period, min_periods=period).min()
        )
        ratio = true_range.rolling(period, min_periods=period).sum() / range_high_low.replace(0, np.nan)
        return 100.0 * np.log10(ratio.where(ratio > 0)) / math.log10(period)

    @classmethod
    def _informative_indicators(cls, dataframe: DataFrame, timeframe: str) -> DataFrame:
        frame = dataframe.copy()
        if frame.empty:
            return frame
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["ema50"] = ta.EMA(frame, timeperiod=50)
        frame["ema200"] = ta.EMA(frame, timeperiod=200)
        frame["adx"] = ta.ADX(frame, timeperiod=14)
        frame["atr"] = ta.ATR(frame, timeperiod=14)
        frame["atr_pct"] = frame["atr"] / frame["close"].replace(0, np.nan)
        frame["chop"] = cls._choppiness(frame, 14)
        return frame

    @staticmethod
    def _anchored_vwap(dataframe: DataFrame, anchor: Series) -> Series:
        typical = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        cumulative_notional = (typical * dataframe["volume"]).groupby(anchor).cumsum()
        cumulative_volume = dataframe["volume"].groupby(anchor).cumsum()
        return cumulative_notional / cumulative_volume.where(cumulative_volume > 0)

    @staticmethod
    def _previous_period_levels(
        dataframe: DataFrame,
        key: Series,
        prefix: str,
    ) -> tuple[Series, Series]:
        levels = (
            dataframe.assign(_period_key=key)
            .groupby("_period_key", sort=True)
            .agg(period_high=("high", "max"), period_low=("low", "min"))
            .shift(1)
        )
        high = key.map(levels["period_high"]).rename(f"prev_{prefix}_high")
        low = key.map(levels["period_low"]).rename(f"prev_{prefix}_low")
        return high, low

    @classmethod
    def _main_indicators(cls, dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        frame["atr"] = ta.ATR(frame, timeperiod=14)
        frame["atr_pct"] = frame["atr"] / frame["close"].replace(0, np.nan)
        frame["adx"] = ta.ADX(frame, timeperiod=14)
        frame["rsi"] = ta.RSI(frame, timeperiod=14)

        previous_volume_median = frame["volume"].shift(1).rolling(48, min_periods=48).median()
        previous_volume_mean = frame["volume"].shift(1).rolling(12, min_periods=12).mean()
        frame["relative_volume_48"] = frame["volume"] / previous_volume_median.where(
            previous_volume_median > 0
        )
        frame["volume_expansion"] = frame["volume"] >= 1.20 * previous_volume_mean

        candle_range = (frame["high"] - frame["low"]).replace(0, np.nan)
        frame["candle_delta_proxy"] = (
            (frame["close"] - frame["open"]) / candle_range * frame["volume"]
        ).fillna(0.0)
        rolling_volume = frame["volume"].shift(1).rolling(48, min_periods=48).sum()
        frame["candle_delta_ratio"] = frame["candle_delta_proxy"] / rolling_volume.where(
            rolling_volume > 0
        )

        timestamps = pd.to_datetime(frame["date"], utc=True)
        day_key = timestamps.dt.floor("D")
        week_key = day_key - pd.to_timedelta(day_key.dt.weekday, unit="D")
        frame["session_vwap"] = cls._anchored_vwap(frame, day_key)
        frame["weekly_vwap"] = cls._anchored_vwap(frame, week_key)
        frame["prev_day_high"], frame["prev_day_low"] = cls._previous_period_levels(
            frame, day_key, "day"
        )
        frame["prev_week_high"], frame["prev_week_low"] = cls._previous_period_levels(
            frame, week_key, "week"
        )

        typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        window = 288
        volume_sum = frame["volume"].rolling(window, min_periods=window).sum()
        weighted_sum = (typical * frame["volume"]).rolling(window, min_periods=window).sum()
        weighted_square_sum = (
            typical.pow(2) * frame["volume"]
        ).rolling(window, min_periods=window).sum()
        frame["vp_poc"] = weighted_sum / volume_sum.where(volume_sum > 0)
        weighted_variance = (
            weighted_square_sum / volume_sum.where(volume_sum > 0) - frame["vp_poc"].pow(2)
        ).clip(lower=0.0)
        weighted_std = np.sqrt(weighted_variance)
        frame["vp_vah"] = frame["vp_poc"] + 1.15 * weighted_std
        frame["vp_val"] = frame["vp_poc"] - 1.15 * weighted_std

        frame["structure_recent_high"] = frame["high"].shift(1).rolling(12, min_periods=12).max()
        frame["structure_recent_low"] = frame["low"].shift(1).rolling(12, min_periods=12).min()
        frame["structure_prior_high"] = frame["high"].shift(13).rolling(12, min_periods=12).max()
        frame["structure_prior_low"] = frame["low"].shift(13).rolling(12, min_periods=12).min()

        frame["breakout_high_48"] = frame["high"].shift(2).rolling(48, min_periods=48).max()
        frame["breakout_low_48"] = frame["low"].shift(2).rolling(48, min_periods=48).min()
        frame["sweep_high_24"] = frame["high"].shift(1).rolling(24, min_periods=24).max()
        frame["sweep_low_24"] = frame["low"].shift(1).rolling(24, min_periods=24).min()
        return frame

    @staticmethod
    def _ensure_columns(dataframe: DataFrame, columns: list[str]) -> None:
        for column in columns:
            if column not in dataframe:
                dataframe[column] = np.nan

    def _merge_pair_timeframe(
        self,
        dataframe: DataFrame,
        pair: str,
        timeframe: str,
        suffix: str | None = None,
    ) -> DataFrame:
        if self.dp is None:
            return dataframe
        informative = self.dp.get_pair_dataframe(pair=pair, timeframe=timeframe)
        if informative is None or informative.empty:
            return dataframe
        informative = self._informative_indicators(informative, timeframe)
        if suffix is None:
            return merge_informative_pair(
                dataframe,
                informative,
                self.timeframe,
                timeframe,
                ffill=True,
            )
        return merge_informative_pair(
            dataframe,
            informative,
            self.timeframe,
            timeframe,
            ffill=True,
            append_timeframe=False,
            suffix=suffix,
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = self._main_indicators(dataframe)
        pair = metadata.get("pair", "")
        for timeframe in self.informative_timeframes:
            frame = self._merge_pair_timeframe(frame, pair, timeframe)
        frame = self._merge_pair_timeframe(frame, self.btc_pair, "4h", suffix="btc_4h")
        self._ensure_columns(
            frame,
            [
                "close_15m",
                "ema20_15m",
                "ema50_15m",
                "close_1h",
                "ema50_1h",
                "ema200_1h",
                "adx_1h",
                "atr_pct_1h",
                "chop_1h",
                "close_4h",
                "ema50_4h",
                "ema200_4h",
                "adx_4h",
                "close_btc_4h",
                "ema50_btc_4h",
                "ema200_btc_4h",
                "adx_btc_4h",
            ],
        )
        return frame

    @staticmethod
    def _near(price: Series, level: Series, distance: Series) -> Series:
        return level.notna() & distance.notna() & ((price - level).abs() <= distance)

    @classmethod
    def _score_frame(cls, dataframe: DataFrame, pair: str) -> DataFrame:
        frame = dataframe
        long_regime_4h = (frame["close_4h"] > frame["ema200_4h"]) & (
            frame["ema50_4h"] > frame["ema200_4h"]
        )
        long_regime_1h = (
            (frame["close_1h"] > frame["ema50_1h"])
            & (frame["ema50_1h"] > frame["ema200_1h"])
            & ((frame["adx_1h"] >= 18.0) | (frame["chop_1h"] <= 61.8))
        )
        short_regime_4h = (frame["close_4h"] < frame["ema200_4h"]) & (
            frame["ema50_4h"] < frame["ema200_4h"]
        )
        short_regime_1h = (
            (frame["close_1h"] < frame["ema50_1h"])
            & (frame["ema50_1h"] < frame["ema200_1h"])
            & (frame["adx_1h"] >= 20.0)
            & (frame["chop_1h"] <= 61.8)
        )
        frame["long_regime_score"] = long_regime_4h.astype(int) + long_regime_1h.astype(int)
        frame["short_regime_score"] = short_regime_4h.astype(int) + short_regime_1h.astype(int)

        if pair == cls.btc_pair:
            frame["long_btc_context_ok"] = True
            frame["short_btc_context_ok"] = True
        else:
            frame["long_btc_context_ok"] = (
                (frame["close_btc_4h"] >= 0.99 * frame["ema200_btc_4h"])
                & (frame["ema50_btc_4h"] >= 0.995 * frame["ema200_btc_4h"])
            )
            frame["short_btc_context_ok"] = (
                (frame["close_btc_4h"] <= 1.01 * frame["ema200_btc_4h"])
                & (frame["ema50_btc_4h"] <= 1.005 * frame["ema200_btc_4h"])
            )

        anchor_near = cls._near(frame["close"], frame["session_vwap"], 0.75 * frame["atr"]) | cls._near(
            frame["close"], frame["weekly_vwap"], frame["atr"]
        )
        inside_value = (frame["close"] >= frame["vp_val"]) & (frame["close"] <= frame["vp_vah"])
        important_near = inside_value.copy()
        for column in (
            "vp_val",
            "vp_vah",
            "prev_day_high",
            "prev_day_low",
            "prev_week_high",
            "prev_week_low",
        ):
            important_near |= cls._near(frame["close"], frame[column], frame["atr"])
        frame["long_location_score"] = anchor_near.astype(int) + important_near.astype(int)
        frame["short_location_score"] = frame["long_location_score"]

        hh = frame["structure_recent_high"] > frame["structure_prior_high"]
        hl = frame["structure_recent_low"] > frame["structure_prior_low"]
        lh = frame["structure_recent_high"] < frame["structure_prior_high"]
        ll = frame["structure_recent_low"] < frame["structure_prior_low"]
        frame["long_structure_score"] = hh.astype(int) + hl.astype(int)
        frame["short_structure_score"] = lh.astype(int) + ll.astype(int)

        body = (frame["close"] - frame["open"]).abs()
        candle_range = (frame["high"] - frame["low"]).replace(0, np.nan)
        close_position = (frame["close"] - frame["low"]) / candle_range
        displacement = body / frame["atr"].replace(0, np.nan) >= 0.45
        long_displacement = displacement & (close_position >= 0.65) & (frame["close"] > frame["open"])
        short_displacement = displacement & (close_position <= 0.35) & (frame["close"] < frame["open"])

        long_pullback = (
            (
                ((frame["low"] <= 1.0015 * frame["ema20_15m"]) & (frame["close"] > frame["ema20_15m"]))
                | ((frame["low"] <= 1.0015 * frame["session_vwap"]) & (frame["close"] > frame["session_vwap"]))
            )
            & (frame["close"] > frame["high"].shift(1))
        )
        short_pullback = (
            (
                ((frame["high"] >= 0.9985 * frame["ema20_15m"]) & (frame["close"] < frame["ema20_15m"]))
                | ((frame["high"] >= 0.9985 * frame["session_vwap"]) & (frame["close"] < frame["session_vwap"]))
            )
            & (frame["close"] < frame["low"].shift(1))
        )

        long_breakout_retest = (
            (frame["close"].shift(1) > 1.0005 * frame["breakout_high_48"])
            & (frame["low"] <= 1.0020 * frame["breakout_high_48"])
            & (frame["close"] > frame["breakout_high_48"])
        )
        short_breakout_retest = (
            (frame["close"].shift(1) < 0.9995 * frame["breakout_low_48"])
            & (frame["high"] >= 0.9980 * frame["breakout_low_48"])
            & (frame["close"] < frame["breakout_low_48"])
        )

        lower_wick = np.minimum(frame["open"], frame["close"]) - frame["low"]
        upper_wick = frame["high"] - np.maximum(frame["open"], frame["close"])
        long_sweep = (
            (frame["low"] < frame["sweep_low_24"])
            & (frame["close"] > frame["sweep_low_24"])
            & (lower_wick >= 1.25 * body)
        )
        short_sweep = (
            (frame["high"] > frame["sweep_high_24"])
            & (frame["close"] < frame["sweep_high_24"])
            & (upper_wick >= 1.25 * body)
        )

        frame["long_setup"] = np.select(
            [long_sweep, long_breakout_retest, long_pullback],
            ["liquidity_sweep", "breakout_retest", "trend_pullback"],
            default="",
        )
        frame["short_setup"] = np.select(
            [short_sweep, short_breakout_retest, short_pullback],
            ["liquidity_sweep", "breakout_retest", "trend_pullback"],
            default="",
        )
        frame["long_trigger_score"] = long_displacement.astype(int) + (frame["long_setup"] != "").astype(int)
        frame["short_trigger_score"] = short_displacement.astype(int) + (frame["short_setup"] != "").astype(int)

        relative_volume_ok = frame["relative_volume_48"] >= 1.15
        long_flow_ok = frame["volume_expansion"].fillna(False) | (frame["candle_delta_ratio"] >= 0.10)
        short_flow_ok = frame["volume_expansion"].fillna(False) | (frame["candle_delta_ratio"] <= -0.10)
        frame["long_participation_score"] = relative_volume_ok.astype(int) + long_flow_ok.astype(int)
        frame["short_participation_score"] = relative_volume_ok.astype(int) + short_flow_ok.astype(int)

        frame["long_total_score"] = (
            frame["long_regime_score"]
            + frame["long_location_score"]
            + frame["long_structure_score"]
            + frame["long_trigger_score"]
            + frame["long_participation_score"]
        )
        frame["short_total_score"] = (
            frame["short_regime_score"]
            + frame["short_location_score"]
            + frame["short_structure_score"]
            + frame["short_trigger_score"]
            + frame["short_participation_score"]
        )

        required_columns = [
            "atr",
            "atr_pct",
            "close_15m",
            "ema20_15m",
            "ema50_15m",
            "close_1h",
            "ema50_1h",
            "ema200_1h",
            "adx_1h",
            "atr_pct_1h",
            "chop_1h",
            "close_4h",
            "ema50_4h",
            "ema200_4h",
            "session_vwap",
            "weekly_vwap",
            "vp_poc",
            "vp_vah",
            "vp_val",
        ]
        if pair != cls.btc_pair:
            required_columns.extend(["close_btc_4h", "ema50_btc_4h", "ema200_btc_4h"])
        numeric = frame[required_columns].apply(pd.to_numeric, errors="coerce")
        frame["required_data_ok"] = numeric.notna().all(axis=1) & np.isfinite(numeric).all(axis=1)
        frame["volatility_volume_ok"] = (
            (frame["volume"] > 0)
            & frame["atr_pct"].between(0.0005, 0.025, inclusive="both")
            & frame["atr_pct_1h"].between(0.001, 0.08, inclusive="both")
        )
        return frame

    @staticmethod
    def _rejection_mask(
        frame: DataFrame,
        *,
        side: str,
        minimum_regime: int,
        minimum_total: int,
    ) -> Series:
        mask = pd.Series(0, index=frame.index, dtype="int64")
        checks = [
            (~frame["required_data_ok"], 1),
            (~frame["volatility_volume_ok"], 2),
            (frame[f"{side}_regime_score"] < minimum_regime, 4),
            (~frame[f"{side}_btc_context_ok"].fillna(False), 8),
            (frame[f"{side}_location_score"] < 1, 16),
            (frame[f"{side}_structure_score"] < 1, 32),
            (frame[f"{side}_trigger_score"] < 2, 64),
            (frame[f"{side}_participation_score"] < 1, 128),
            (frame[f"{side}_total_score"] < minimum_total, 256),
        ]
        for failed, flag in checks:
            mask = mask | failed.fillna(True).astype("int64") * flag
        return mask

    @classmethod
    def explain_rejection(cls, mask: int) -> list[str]:
        if mask == 0:
            return ["accepted"]
        return [reason for flag, reason in cls.REJECTION_FLAGS.items() if int(mask) & flag]

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = self._score_frame(dataframe, metadata.get("pair", ""))
        frame["long_rejection_mask"] = self._rejection_mask(
            frame,
            side="long",
            minimum_regime=1,
            minimum_total=7,
        )
        frame["short_rejection_mask"] = self._rejection_mask(
            frame,
            side="short",
            minimum_regime=2,
            minimum_total=8,
        )
        long_entry = frame["long_rejection_mask"] == 0
        short_entry = (frame["short_rejection_mask"] == 0) & ~long_entry

        long_tag = (
            frame["long_setup"].astype(str)
            + "_long_r"
            + frame["long_regime_score"].astype(str)
            + "l"
            + frame["long_location_score"].astype(str)
            + "s"
            + frame["long_structure_score"].astype(str)
            + "t"
            + frame["long_trigger_score"].astype(str)
            + "p"
            + frame["long_participation_score"].astype(str)
            + "_total"
            + frame["long_total_score"].astype(str)
        )
        short_tag = (
            frame["short_setup"].astype(str)
            + "_short_r"
            + frame["short_regime_score"].astype(str)
            + "l"
            + frame["short_location_score"].astype(str)
            + "s"
            + frame["short_structure_score"].astype(str)
            + "t"
            + frame["short_trigger_score"].astype(str)
            + "p"
            + frame["short_participation_score"].astype(str)
            + "_total"
            + frame["short_total_score"].astype(str)
        )
        frame.loc[long_entry, "enter_long"] = 1
        frame.loc[long_entry, "enter_tag"] = long_tag[long_entry]
        frame.loc[short_entry, "enter_short"] = 1
        frame.loc[short_entry, "enter_tag"] = short_tag[short_entry]
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_structure_failure = (
            dataframe["structure_recent_low"] < dataframe["structure_prior_low"]
        )
        short_structure_failure = (
            dataframe["structure_recent_high"] > dataframe["structure_prior_high"]
        )
        long_exit = (
            (dataframe["close"] < dataframe["ema50_15m"])
            & long_structure_failure
            & (dataframe["volume"] > 0)
        )
        short_exit = (
            (dataframe["close"] > dataframe["ema50_15m"])
            & short_structure_failure
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (1, "long_15m_ema50_and_ll")
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (1, "short_15m_ema50_and_hh")
        return dataframe

    def _latest_analyzed(self, pair: str) -> Series | None:
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
            if dataframe is None or dataframe.empty:
                return None
            return dataframe.iloc[-1]
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        try:
            latest = self._latest_analyzed(pair)
            if latest is None:
                return 0.0
            atr_pct = float(latest["atr_pct"])
            wallet = float(self.wallets.get_total_stake_amount())
            values = (atr_pct, wallet, proposed_stake, max_stake, current_rate)
            if any(not math.isfinite(value) or value <= 0 for value in values):
                return 0.0
            stop_distance = min(
                self.maximum_sizing_stop_fraction,
                max(self.minimum_sizing_stop_fraction, 2.0 * atr_pct),
            )
            risk_sized = wallet * self.risk_per_trade_fraction / stop_distance
            exposure_cap = wallet * self.maximum_single_trade_stake_fraction
            safe_stake = min(proposed_stake, max_stake, risk_sized, exposure_cap)
            if not math.isfinite(safe_stake) or safe_stake <= 0:
                return 0.0
            if min_stake is not None and safe_stake < float(min_stake):
                return 0.0
            return safe_stake
        except Exception as exc:
            logger.error("ProDay stake sizing failed closed for %s: %s", pair, exc)
            return 0.0

    def custom_stoploss(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs: Any,
    ) -> float | None:
        latest = self._latest_analyzed(pair)
        if latest is None or not math.isfinite(current_rate) or current_rate <= 0:
            return None
        try:
            atr = float(latest["atr"])
            if not math.isfinite(atr) or atr <= 0:
                return None
            is_short = bool(getattr(trade, "is_short", False))
            leverage = float(getattr(trade, "leverage", 1.0) or 1.0)
            if is_short:
                structure = float(latest["structure_recent_high"])
                candidate = max(structure + 0.25 * atr, current_rate + 1.75 * atr)
                distance = (candidate - current_rate) / current_rate
                stop_rate = current_rate * (
                    1.0 + min(self.maximum_sizing_stop_fraction, max(self.minimum_sizing_stop_fraction, distance))
                )
            else:
                structure = float(latest["structure_recent_low"])
                candidate = min(structure - 0.25 * atr, current_rate - 1.75 * atr)
                distance = (current_rate - candidate) / current_rate
                stop_rate = current_rate * (
                    1.0 - min(self.maximum_sizing_stop_fraction, max(self.minimum_sizing_stop_fraction, distance))
                )
            dynamic = stoploss_from_absolute(stop_rate, current_rate, is_short=is_short, leverage=leverage)

            profit_protection: float | None = None
            if current_profit >= 0.025:
                protected_rate = current_rate * (1.008 if is_short else 0.992)
                profit_protection = stoploss_from_absolute(
                    protected_rate, current_rate, is_short=is_short, leverage=leverage
                )
            elif current_profit >= 0.015:
                protected_rate = current_rate * (1.006 if is_short else 0.994)
                profit_protection = stoploss_from_absolute(
                    protected_rate, current_rate, is_short=is_short, leverage=leverage
                )
            elif current_profit >= 0.008:
                open_rate = float(getattr(trade, "open_rate"))
                protected_rate = open_rate * (0.999 if is_short else 1.001)
                profit_protection = stoploss_from_absolute(
                    protected_rate, current_rate, is_short=is_short, leverage=leverage
                )
            valid = [value for value in (dynamic, profit_protection) if value is not None and math.isfinite(value)]
            return min(valid) if valid else None
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def custom_exit(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | None:
        opened = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if not isinstance(opened, datetime):
            return None
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        now = current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
        age_minutes = (now.astimezone(timezone.utc) - opened.astimezone(timezone.utc)).total_seconds() / 60.0
        if age_minutes >= 720.0:
            return "time_stop_720m"
        if age_minutes >= 180.0 and current_profit <= 0.0:
            return "stale_loser_180m"
        return None

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        return 1.0
