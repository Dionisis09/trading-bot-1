"""Locked profitability-first V2 research strategy.

This strategy implements the single candidate frozen in
``docs/pro_day_trader_v2_locked_plan.md``.  Deterministic T1/R1 signals are the
only source of trade direction.  FreqAI's LightGBM regressor is a fail-closed
veto: it may reject a candidate but can never create or reverse one.
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


class ProDayTraderV2(ProfessionalRiskMixin, IStrategy):
    """Research-only hybrid strategy; it does not authorize live trading."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 399

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

    target_column = "&-candidate_net_log_return"
    target_horizon_candles = 12
    target_cost_hurdle = 0.0026

    risk_per_trade_fraction = 0.0025
    maximum_single_trade_stake_fraction = 0.10
    minimum_sizing_stop_fraction = 0.0075
    maximum_sizing_stop_fraction = 0.03
    atr_sizing_multiple = 1.5

    # These are the only model inputs.  The expand hooks deliberately add no
    # features, preventing FreqAI's timeframe/correlation machinery from
    # multiplying the locked schema.
    FEATURE_COLUMNS = (
        "%-ret_5m_1",
        "%-ret_5m_3",
        "%-ret_5m_12",
        "%-ema_gap_atr_15m",
        "%-momentum_1h_24",
        "%-adx_1h_14",
        "%-trend_gap_atr_4h",
        "%-channel_position_15m_20",
        "%-z48_5m",
        "%-atr_close_5m_14",
        "%-realized_vol_5m_24h",
        "%-log_volume_vs_median_5m_20",
        "%-btc_momentum_1h_24",
        "%-btc_trend_gap_atr_4h",
        "%-btc_realized_vol_5m_24h",
        "%-pair_minus_btc_momentum_1h_24",
        "%-setup_T1",
        "%-setup_R1",
        "%-candidate_side",
    )

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
        return sorted(
            (pair, informative_timeframe)
            for pair in pairs
            for informative_timeframe in self.informative_timeframes
        )

    @staticmethod
    def _finite_divide(numerator: Series, denominator: Series) -> Series:
        denominator = pd.to_numeric(denominator, errors="coerce").replace(0.0, np.nan)
        result = pd.to_numeric(numerator, errors="coerce") / denominator
        return result.where(np.isfinite(result))

    @classmethod
    def _base_indicators(cls, dataframe: DataFrame) -> DataFrame:
        """Compute causal 5m indicators used by candidates and locked features."""

        frame = dataframe.copy()
        close = pd.to_numeric(frame["close"], errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        log_close = np.log(close.where(close > 0.0))
        frame["ret_1"] = log_close.diff(1)
        frame["ret_3"] = log_close.diff(3)
        frame["ret_12"] = log_close.diff(12)
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["atr"] = ta.ATR(frame, timeperiod=14)
        frame["atr_pct"] = cls._finite_divide(frame["atr"], close)

        typical_price = (
            pd.to_numeric(frame["high"], errors="coerce")
            + pd.to_numeric(frame["low"], errors="coerce")
            + close
        ) / 3.0
        rolling_volume = volume.rolling(48, min_periods=48).sum()
        frame["vwap48"] = cls._finite_divide(
            (typical_price * volume).rolling(48, min_periods=48).sum(),
            rolling_volume,
        )
        # Population standard deviation is frozen here to make z48 identical
        # across pandas/runtime versions.
        frame["close_std48"] = close.rolling(48, min_periods=48).std(ddof=0)
        frame["z48"] = cls._finite_divide(close - frame["vwap48"], frame["close_std48"])

        frame["volume_median_prev20"] = volume.shift(1).rolling(20, min_periods=20).median()
        volume_ratio = cls._finite_divide(volume, frame["volume_median_prev20"])
        frame["log_volume_vs_median20"] = np.log(volume_ratio.where(volume_ratio > 0.0))
        # 24h realized volatility over 288 completed 5m returns.
        frame["realized_vol_24h"] = np.sqrt(
            frame["ret_1"].pow(2).rolling(288, min_periods=288).sum()
        )
        frame["r1_exit_long"] = (frame["z48"].shift(1) < 0.0) & (frame["z48"] >= 0.0)
        frame["r1_exit_short"] = (frame["z48"].shift(1) > 0.0) & (frame["z48"] <= 0.0)
        return frame

    @classmethod
    def _informative_indicators(cls, dataframe: DataFrame, informative_timeframe: str) -> DataFrame:
        """Compute indicators on their native, completed informative candles."""

        frame = dataframe.copy()
        if frame.empty:
            return frame
        if informative_timeframe == "15m":
            frame["ema20"] = ta.EMA(frame, timeperiod=20)
            frame["ema50"] = ta.EMA(frame, timeperiod=50)
            frame["atr14"] = ta.ATR(frame, timeperiod=14)
            frame["ema_gap_atr"] = cls._finite_divide(
                frame["ema20"] - frame["ema50"], frame["atr14"]
            )
            frame["channel_high_prev20"] = (
                frame["high"].shift(1).rolling(20, min_periods=20).max()
            )
            frame["channel_low_prev20"] = (
                frame["low"].shift(1).rolling(20, min_periods=20).min()
            )
            frame["channel_position_prev20"] = cls._finite_divide(
                frame["close"] - frame["channel_low_prev20"],
                frame["channel_high_prev20"] - frame["channel_low_prev20"],
            )
            frame["t1_exit_long"] = (frame["ema20"].shift(1) >= frame["ema50"].shift(1)) & (
                frame["ema20"] < frame["ema50"]
            )
            frame["t1_exit_short"] = (frame["ema20"].shift(1) <= frame["ema50"].shift(1)) & (
                frame["ema20"] > frame["ema50"]
            )
            columns = [
                "date",
                "ema20",
                "ema50",
                "atr14",
                "ema_gap_atr",
                "channel_high_prev20",
                "channel_low_prev20",
                "channel_position_prev20",
                "t1_exit_long",
                "t1_exit_short",
            ]
        elif informative_timeframe == "1h":
            close = pd.to_numeric(frame["close"], errors="coerce")
            frame["momentum24"] = np.log(
                cls._finite_divide(close, close.shift(24)).where(lambda value: value > 0.0)
            )
            frame["adx14"] = ta.ADX(frame, timeperiod=14)
            columns = ["date", "momentum24", "adx14"]
        elif informative_timeframe == "4h":
            frame["ema50"] = ta.EMA(frame, timeperiod=50)
            frame["ema200"] = ta.EMA(frame, timeperiod=200)
            frame["atr14"] = ta.ATR(frame, timeperiod=14)
            frame["trend_gap_atr"] = cls._finite_divide(
                frame["ema50"] - frame["ema200"], frame["atr14"]
            )
            frame["trend_long"] = (frame["ema50"] > frame["ema200"]) & (
                frame["ema50"] > frame["ema50"].shift(3)
            )
            frame["trend_short"] = (frame["ema50"] < frame["ema200"]) & (
                frame["ema50"] < frame["ema50"].shift(3)
            )
            columns = [
                "date",
                "ema50",
                "ema200",
                "atr14",
                "trend_gap_atr",
                "trend_long",
                "trend_short",
            ]
        else:
            raise ValueError(f"unsupported informative timeframe: {informative_timeframe}")
        return frame[columns]

    @classmethod
    def _causal_merge(
        cls,
        dataframe: DataFrame,
        informative: DataFrame,
        informative_timeframe: str,
        *,
        suffix: str | None = None,
    ) -> DataFrame:
        """Merge an informative frame only at its real close boundary."""

        if suffix is None:
            return merge_informative_pair(
                dataframe,
                informative,
                cls.timeframe,
                informative_timeframe,
                ffill=True,
            )
        return merge_informative_pair(
            dataframe,
            informative,
            cls.timeframe,
            informative_timeframe,
            ffill=True,
            append_timeframe=False,
            suffix=suffix,
        )

    def _pair_dataframe(self, pair: str, informative_timeframe: str) -> DataFrame | None:
        if self.dp is None:
            return None
        try:
            dataframe = self.dp.get_pair_dataframe(pair=pair, timeframe=informative_timeframe)
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        if dataframe is None or dataframe.empty:
            return None
        return dataframe

    def _merge_market_context(self, dataframe: DataFrame, pair: str) -> DataFrame:
        frame = dataframe
        for informative_timeframe in self.informative_timeframes:
            informative = self._pair_dataframe(pair, informative_timeframe)
            if informative is not None:
                prepared = self._informative_indicators(informative, informative_timeframe)
                frame = self._causal_merge(frame, prepared, informative_timeframe)

        if pair == self.btc_pair:
            frame["btc_momentum24_1h"] = frame.get("momentum24_1h", np.nan)
            frame["btc_trend_gap_atr_4h"] = frame.get("trend_gap_atr_4h", np.nan)
            frame["btc_realized_vol_24h"] = frame.get("realized_vol_24h", np.nan)
            return frame

        btc_1h = self._pair_dataframe(self.btc_pair, "1h")
        if btc_1h is not None:
            prepared = self._informative_indicators(btc_1h, "1h")
            frame = self._causal_merge(frame, prepared, "1h", suffix="btc_1h")
            frame["btc_momentum24_1h"] = frame["momentum24_btc_1h"]
        btc_4h = self._pair_dataframe(self.btc_pair, "4h")
        if btc_4h is not None:
            prepared = self._informative_indicators(btc_4h, "4h")
            frame = self._causal_merge(frame, prepared, "4h", suffix="btc_4h")
            frame["btc_trend_gap_atr_4h"] = frame["trend_gap_atr_btc_4h"]
        btc_5m = self._pair_dataframe(self.btc_pair, self.timeframe)
        if btc_5m is not None:
            prepared = self._base_indicators(btc_5m)[["date", "realized_vol_24h"]].rename(
                columns={"realized_vol_24h": "btc_realized_vol_24h"}
            )
            frame = frame.merge(prepared, on="date", how="left", sort=False, validate="one_to_one")
        return frame

    @staticmethod
    def _ensure_columns(dataframe: DataFrame, columns: tuple[str, ...] | list[str]) -> None:
        for column in columns:
            if column not in dataframe:
                dataframe[column] = np.nan

    @classmethod
    def _candidate_masks(cls, dataframe: DataFrame) -> DataFrame:
        """Add frozen T1/R1 candidates and a single deterministic side/setup."""

        frame = dataframe.copy()
        cls._ensure_columns(
            frame,
            [
                "trend_long_4h",
                "trend_short_4h",
                "momentum24_1h",
                "adx14_1h",
                "ema20_15m",
                "ema50_15m",
                "ema20",
                "volume_median_prev20",
                "z48",
            ],
        )
        volume_ok = (
            pd.to_numeric(frame["volume"], errors="coerce")
            > pd.to_numeric(frame["volume_median_prev20"], errors="coerce")
        )
        raw_t1_long = (
            frame["trend_long_4h"].fillna(False).astype(bool)
            & (frame["momentum24_1h"] > 0.0)
            & (frame["adx14_1h"] >= 18.0)
            & (frame["ema20_15m"] > frame["ema50_15m"])
            & (frame["close"] > frame["ema20"])
            & (frame["close"].shift(1) <= frame["ema20"].shift(1))
            & volume_ok
        )
        raw_t1_short = (
            frame["trend_short_4h"].fillna(False).astype(bool)
            & (frame["momentum24_1h"] < 0.0)
            & (frame["adx14_1h"] >= 18.0)
            & (frame["ema20_15m"] < frame["ema50_15m"])
            & (frame["close"] < frame["ema20"])
            & (frame["close"].shift(1) >= frame["ema20"].shift(1))
            & volume_ok
        )

        # The flat gate excludes either active 4h T1 direction.
        flat = (
            (frame["adx14_1h"] < 20.0)
            & ~frame["trend_long_4h"].fillna(False).astype(bool)
            & ~frame["trend_short_4h"].fillna(False).astype(bool)
        )
        raw_r1_long = (
            flat
            & (frame["z48"].shift(1) < -2.0)
            & (frame["z48"] >= -2.0)
            & (frame["close"] > frame["open"])
            & volume_ok
        )
        raw_r1_short = (
            flat
            & (frame["z48"].shift(1) > 2.0)
            & (frame["z48"] <= 2.0)
            & (frame["close"] < frame["open"])
            & volume_ok
        )

        # T1 wins any numerical overlap.  Long is the final deterministic
        # tie-break for an otherwise impossible same-setup, two-side overlap.
        frame["candidate_T1_long"] = raw_t1_long.fillna(False)
        frame["candidate_T1_short"] = raw_t1_short.fillna(False) & ~frame["candidate_T1_long"]
        any_t1 = frame["candidate_T1_long"] | frame["candidate_T1_short"]
        frame["candidate_R1_long"] = raw_r1_long.fillna(False) & ~any_t1
        frame["candidate_R1_short"] = (
            raw_r1_short.fillna(False) & ~any_t1 & ~frame["candidate_R1_long"]
        )
        frame["setup_T1"] = any_t1.astype("int8")
        frame["setup_R1"] = (
            frame["candidate_R1_long"] | frame["candidate_R1_short"]
        ).astype("int8")
        frame["candidate_side"] = np.select(
            [
                frame["candidate_T1_long"] | frame["candidate_R1_long"],
                frame["candidate_T1_short"] | frame["candidate_R1_short"],
            ],
            [1.0, -1.0],
            default=0.0,
        )
        frame["candidate_setup"] = np.select(
            [frame["setup_T1"] == 1, frame["setup_R1"] == 1],
            ["T1", "R1"],
            default="",
        )
        return frame

    def _prepare_signal_frame(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if "candidate_side" in dataframe and "btc_realized_vol_24h" in dataframe:
            return dataframe.copy()
        pair = metadata.get("pair", "")
        frame = self._base_indicators(dataframe)
        frame = self._merge_market_context(frame, pair)
        self._ensure_columns(
            frame,
            [
                "ema20_15m",
                "ema50_15m",
                "ema_gap_atr_15m",
                "channel_position_prev20_15m",
                "t1_exit_long_15m",
                "t1_exit_short_15m",
                "momentum24_1h",
                "adx14_1h",
                "trend_gap_atr_4h",
                "trend_long_4h",
                "trend_short_4h",
                "btc_momentum24_1h",
                "btc_trend_gap_atr_4h",
                "btc_realized_vol_24h",
            ],
        )
        return self._candidate_masks(frame)

    # Intentionally empty: all 19 locked features are defined once in the
    # standard hook, so FreqAI does not create a cartesian feature expansion.
    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs: Any
    ) -> DataFrame:
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs: Any
    ) -> DataFrame:
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs: Any
    ) -> DataFrame:
        frame = self._prepare_signal_frame(dataframe, metadata)
        frame["%-ret_5m_1"] = frame["ret_1"]
        frame["%-ret_5m_3"] = frame["ret_3"]
        frame["%-ret_5m_12"] = frame["ret_12"]
        frame["%-ema_gap_atr_15m"] = frame["ema_gap_atr_15m"]
        frame["%-momentum_1h_24"] = frame["momentum24_1h"]
        frame["%-adx_1h_14"] = frame["adx14_1h"]
        frame["%-trend_gap_atr_4h"] = frame["trend_gap_atr_4h"]
        frame["%-channel_position_15m_20"] = frame["channel_position_prev20_15m"]
        frame["%-z48_5m"] = frame["z48"]
        frame["%-atr_close_5m_14"] = frame["atr_pct"]
        frame["%-realized_vol_5m_24h"] = frame["realized_vol_24h"]
        frame["%-log_volume_vs_median_5m_20"] = frame["log_volume_vs_median20"]
        frame["%-btc_momentum_1h_24"] = frame["btc_momentum24_1h"]
        frame["%-btc_trend_gap_atr_4h"] = frame["btc_trend_gap_atr_4h"]
        frame["%-btc_realized_vol_5m_24h"] = frame["btc_realized_vol_24h"]
        frame["%-pair_minus_btc_momentum_1h_24"] = (
            frame["momentum24_1h"] - frame["btc_momentum24_1h"]
        )
        frame["%-setup_T1"] = frame["setup_T1"].astype(float)
        frame["%-setup_R1"] = frame["setup_R1"].astype(float)
        frame["%-candidate_side"] = frame["candidate_side"].astype(float)
        return frame

    @classmethod
    def _candidate_target(cls, dataframe: DataFrame) -> Series:
        """Target uses executable opens t+1 and t+13, only on candidates."""

        side = pd.to_numeric(dataframe["candidate_side"], errors="coerce")
        entry_open = pd.to_numeric(dataframe["open"], errors="coerce").shift(-1)
        exit_open = pd.to_numeric(dataframe["open"], errors="coerce").shift(
            -(cls.target_horizon_candles + 1)
        )
        gross = side * np.log(cls._finite_divide(exit_open, entry_open).where(lambda value: value > 0))
        target = gross - cls.target_cost_hurdle
        return target.where(side.isin([-1.0, 1.0]) & np.isfinite(target))

    def set_freqai_targets(
        self, dataframe: DataFrame, metadata: dict, **kwargs: Any
    ) -> DataFrame:
        frame = self._prepare_signal_frame(dataframe, metadata)
        frame[self.target_column] = self._candidate_target(frame)
        return frame

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        prepared = self._prepare_signal_frame(dataframe, metadata)
        freqai = getattr(self, "freqai", None)
        if freqai is None:
            # Unit/discovery contexts without FreqAI must remain fail-closed.
            prepared[self.target_column] = np.nan
            prepared["do_predict"] = 0
            return prepared
        result = freqai.start(prepared, metadata, self)
        # FreqAI removes '%' features, but deterministic columns must remain for
        # entry attribution and setup-specific exits.
        for column in prepared.columns:
            if column not in result.columns:
                result[column] = prepared[column]
        self._ensure_columns(result, [self.target_column, "do_predict"])
        return result

    @classmethod
    def _prediction_gate(cls, dataframe: DataFrame) -> Series:
        if cls.target_column not in dataframe or "do_predict" not in dataframe:
            return pd.Series(False, index=dataframe.index, dtype=bool)
        prediction = pd.to_numeric(dataframe[cls.target_column], errors="coerce")
        do_predict = pd.to_numeric(dataframe["do_predict"], errors="coerce")
        return (do_predict == 1) & np.isfinite(prediction) & (prediction > 0.0)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        type(self)._ensure_columns(
            frame,
            [
                "candidate_T1_long",
                "candidate_T1_short",
                "candidate_R1_long",
                "candidate_R1_short",
            ],
        )
        prediction_ok = type(self)._prediction_gate(frame)
        t1_long = frame["candidate_T1_long"].fillna(False).astype(bool) & prediction_ok
        t1_short = frame["candidate_T1_short"].fillna(False).astype(bool) & prediction_ok
        r1_long = frame["candidate_R1_long"].fillna(False).astype(bool) & prediction_ok
        r1_short = frame["candidate_R1_short"].fillna(False).astype(bool) & prediction_ok

        frame["enter_long"] = 0
        frame["enter_short"] = 0
        frame["enter_tag"] = ""
        frame.loc[t1_long, ["enter_long", "enter_tag"]] = (1, "T1_long")
        frame.loc[t1_short, ["enter_short", "enter_tag"]] = (1, "T1_short")
        frame.loc[r1_long, ["enter_long", "enter_tag"]] = (1, "R1_long")
        frame.loc[r1_short, ["enter_short", "enter_tag"]] = (1, "R1_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Setup-specific exits require the trade's deterministic entry tag and
        # are therefore implemented in custom_exit().
        frame = dataframe.copy()
        frame["exit_long"] = 0
        frame["exit_short"] = 0
        return frame

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
            values = (atr_pct, wallet, proposed_stake, max_stake, current_rate, leverage)
            if any(not math.isfinite(value) or value <= 0.0 for value in values):
                return 0.0
            sizing_stop_distance = min(
                self.maximum_sizing_stop_fraction,
                max(
                    self.minimum_sizing_stop_fraction,
                    self.atr_sizing_multiple * atr_pct,
                ),
            )
            risk_sized = wallet * self.risk_per_trade_fraction / sizing_stop_distance
            exposure_cap = wallet * self.maximum_single_trade_stake_fraction
            safe_stake = min(proposed_stake, max_stake, exposure_cap, risk_sized)
            if not math.isfinite(safe_stake) or safe_stake <= 0.0:
                return 0.0
            if min_stake is not None:
                minimum = float(min_stake)
                if not math.isfinite(minimum) or minimum <= 0.0 or minimum > safe_stake:
                    return 0.0
            return safe_stake
        except Exception as exc:
            logger.error("ProDayTraderV2 stake sizing failed closed for %s: %s", pair, exc)
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
        """Apply only the frozen profit protection; static -4% stays active."""

        try:
            if not math.isfinite(current_rate) or current_rate <= 0.0:
                return None
            is_short = bool(getattr(trade, "is_short", False))
            leverage = float(getattr(trade, "leverage", 1.0) or 1.0)
            if not math.isfinite(leverage) or leverage <= 0.0:
                return None
            if current_profit >= 0.025:
                protected_rate = current_rate * (1.008 if is_short else 0.992)
            elif current_profit >= 0.015:
                protected_rate = current_rate * (1.006 if is_short else 0.994)
            elif current_profit >= 0.008:
                open_rate = float(getattr(trade, "open_rate"))
                if not math.isfinite(open_rate) or open_rate <= 0.0:
                    return None
                protected_rate = open_rate * (0.999 if is_short else 1.001)
            else:
                return None
            value = stoploss_from_absolute(
                protected_rate,
                current_rate,
                is_short=is_short,
                leverage=leverage,
            )
            return value if value is not None and math.isfinite(value) else None
        except (AttributeError, TypeError, ValueError, OverflowError):
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
        age_minutes = (
            now.astimezone(timezone.utc) - opened.astimezone(timezone.utc)
        ).total_seconds() / 60.0
        if age_minutes >= 720.0:
            return "time_stop_720m"
        if age_minutes >= 180.0 and current_profit < 0.0:
            return "stale_loser_180m"

        tag = str(getattr(trade, "enter_tag", "") or "")
        latest = self._latest_analyzed(pair)
        if tag.startswith("R1_"):
            if latest is not None:
                is_short = bool(getattr(trade, "is_short", False))
                signal = "r1_exit_short" if is_short else "r1_exit_long"
                value = latest.get(signal, False)
                if pd.notna(value) and bool(value):
                    return "R1_z48_zero_cross"
            if age_minutes >= 60.0:
                return "R1_time_exit_60m"
        elif tag.startswith("T1_") and latest is not None:
            is_short = bool(getattr(trade, "is_short", False))
            signal = "t1_exit_short_15m" if is_short else "t1_exit_long_15m"
            value = latest.get(signal, False)
            if pd.notna(value) and bool(value):
                return "T1_15m_ema_cross"
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
