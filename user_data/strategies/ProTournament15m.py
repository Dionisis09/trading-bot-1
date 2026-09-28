"""Fixed 15m strategy-family tournament for profitability research."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair


class ProTournamentBase15m(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    startup_candle_count = 799
    process_only_new_candles = True
    minimal_roi = {"0": 100.0}
    stoploss = -0.03
    trailing_stop = False
    use_custom_stoploss = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    order_types = {
        "entry": "limit", "exit": "limit", "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    research_pairs = ("BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT")

    @property
    def protections(self) -> list[dict[str, Any]]:
        return [{"method": "CooldownPeriod", "stop_duration_candles": 1}]

    def informative_pairs(self) -> list[tuple[str, str]]:
        pairs = set(self.research_pairs)
        if self.dp is not None:
            try:
                pairs.update(self.dp.current_whitelist())
            except (AttributeError, TypeError):
                pass
        return sorted((pair, tf) for pair in pairs for tf in ("1h", "4h"))

    @staticmethod
    def _finite_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        denominator = pd.to_numeric(denominator, errors="coerce").replace(0.0, np.nan)
        value = pd.to_numeric(numerator, errors="coerce") / denominator
        return value.where(np.isfinite(value))

    @classmethod
    def _base_indicators(cls, dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        close = pd.to_numeric(frame["close"], errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["ema50"] = ta.EMA(frame, timeperiod=50)
        frame["atr14"] = ta.ATR(frame, timeperiod=14)
        frame["adx14"] = ta.ADX(frame, timeperiod=14)
        frame["rsi14"] = ta.RSI(frame, timeperiod=14)
        frame["channel_high_prev20"] = frame["high"].shift(1).rolling(20, min_periods=20).max()
        frame["channel_low_prev20"] = frame["low"].shift(1).rolling(20, min_periods=20).min()
        frame["channel_high_prev32"] = frame["high"].shift(1).rolling(32, min_periods=32).max()
        frame["channel_low_prev32"] = frame["low"].shift(1).rolling(32, min_periods=32).min()
        frame["volume_median_prev20"] = volume.shift(1).rolling(20, min_periods=20).median()
        typical = (frame["high"] + frame["low"] + close) / 3.0
        volume48 = volume.rolling(48, min_periods=48).sum()
        frame["vwap48"] = cls._finite_divide((typical * volume).rolling(48, min_periods=48).sum(), volume48)
        frame["z48"] = cls._finite_divide(close - frame["vwap48"], close.rolling(48, min_periods=48).std(ddof=0))
        mid = close.rolling(20, min_periods=20).mean()
        std = close.rolling(20, min_periods=20).std(ddof=0)
        frame["bb_width"] = cls._finite_divide(4.0 * std, mid)
        frame["bb_width_q30_prev96"] = frame["bb_width"].shift(1).rolling(96, min_periods=96).quantile(0.30)
        return frame

    @classmethod
    def _informative(cls, dataframe: DataFrame, timeframe: str) -> DataFrame:
        frame = dataframe.copy()
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["ema50"] = ta.EMA(frame, timeperiod=50)
        frame["atr14"] = ta.ATR(frame, timeperiod=14)
        if timeframe == "1h":
            frame["adx14"] = ta.ADX(frame, timeperiod=14)
            frame["momentum24"] = np.log(cls._finite_divide(frame["close"], frame["close"].shift(24)))
            frame["ema_gap_atr"] = cls._finite_divide(frame["ema20"] - frame["ema50"], frame["atr14"])
            return frame[["date", "ema20", "ema50", "atr14", "adx14", "momentum24", "ema_gap_atr"]]
        frame["trend_long"] = (frame["ema20"] > frame["ema50"]) & (frame["ema50"] > frame["ema50"].shift(3))
        frame["trend_short"] = (frame["ema20"] < frame["ema50"]) & (frame["ema50"] < frame["ema50"].shift(3))
        frame["ema_gap_atr"] = cls._finite_divide(frame["ema20"] - frame["ema50"], frame["atr14"])
        return frame[["date", "ema20", "ema50", "atr14", "trend_long", "trend_short", "ema_gap_atr"]]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = self._base_indicators(dataframe)
        pair = metadata.get("pair", "")
        if self.dp is None or not pair:
            return frame
        for tf in ("1h", "4h"):
            informative = self.dp.get_pair_dataframe(pair=pair, timeframe=tf)
            if informative is not None and not informative.empty:
                frame = merge_informative_pair(frame, self._informative(informative, tf), self.timeframe, tf, ffill=True)
        return frame

    @staticmethod
    def _volume_ok(frame: DataFrame, multiplier: float = 1.0) -> pd.Series:
        return pd.to_numeric(frame["volume"], errors="coerce") > multiplier * pd.to_numeric(
            frame["volume_median_prev20"], errors="coerce"
        )

    @staticmethod
    def _initialize_entries(frame: DataFrame) -> None:
        frame["enter_long"] = 0
        frame["enter_short"] = 0
        frame["enter_tag"] = ""

    @staticmethod
    def _initialize_exits(frame: DataFrame, long_mask: pd.Series, short_mask: pd.Series, tag: str) -> DataFrame:
        frame["exit_long"] = long_mask.fillna(False).astype("int8")
        frame["exit_short"] = short_mask.fillna(False).astype("int8")
        frame["exit_tag"] = tag
        return frame


class ProTrendBreakout15m(ProTournamentBase15m):
    stoploss = -0.03

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        volume = self._volume_ok(frame)
        long = frame["trend_long_4h"].fillna(False) & (frame["ema20_1h"] > frame["ema50_1h"]) & (frame["adx14_1h"] >= 20) & (frame["close"] > frame["channel_high_prev20"]) & volume
        short = frame["trend_short_4h"].fillna(False) & (frame["ema20_1h"] < frame["ema50_1h"]) & (frame["adx14_1h"] >= 20) & (frame["close"] < frame["channel_low_prev20"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "breakout_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "breakout_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = (dataframe["close"].shift(1) >= dataframe["ema20"].shift(1)) & (dataframe["close"] < dataframe["ema20"])
        short = (dataframe["close"].shift(1) <= dataframe["ema20"].shift(1)) & (dataframe["close"] > dataframe["ema20"])
        return self._initialize_exits(dataframe.copy(), long, short, "ema20_recross")


class ProTrendPullback15m(ProTournamentBase15m):
    stoploss = -0.025

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        volume = self._volume_ok(frame, 0.8)
        long = frame["trend_long_4h"].fillna(False) & (frame["momentum24_1h"] > 0) & (frame["adx14_1h"] >= 18) & (frame["ema20"] > frame["ema50"]) & (frame["close"].shift(1) <= frame["ema20"].shift(1)) & (frame["close"] > frame["ema20"]) & volume
        short = frame["trend_short_4h"].fillna(False) & (frame["momentum24_1h"] < 0) & (frame["adx14_1h"] >= 18) & (frame["ema20"] < frame["ema50"]) & (frame["close"].shift(1) >= frame["ema20"].shift(1)) & (frame["close"] < frame["ema20"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "pullback_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "pullback_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = (dataframe["ema20"].shift(1) >= dataframe["ema50"].shift(1)) & (dataframe["ema20"] < dataframe["ema50"])
        short = (dataframe["ema20"].shift(1) <= dataframe["ema50"].shift(1)) & (dataframe["ema20"] > dataframe["ema50"])
        return self._initialize_exits(dataframe.copy(), long, short, "ema20_ema50_cross")


class ProMomentumCross15m(ProTournamentBase15m):
    stoploss = -0.03

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        volume = self._volume_ok(frame)
        long = frame["trend_long_4h"].fillna(False) & (frame["momentum24_1h"] > 0) & (frame["adx14_1h"] >= 20) & (frame["ema20"].shift(1) <= frame["ema50"].shift(1)) & (frame["ema20"] > frame["ema50"]) & volume
        short = frame["trend_short_4h"].fillna(False) & (frame["momentum24_1h"] < 0) & (frame["adx14_1h"] >= 20) & (frame["ema20"].shift(1) >= frame["ema50"].shift(1)) & (frame["ema20"] < frame["ema50"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "momentum_cross_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "momentum_cross_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = dataframe["close"] < dataframe["ema50"]
        short = dataframe["close"] > dataframe["ema50"]
        return self._initialize_exits(dataframe.copy(), long, short, "close_beyond_ema50")


class ProVolatilityBreakout15m(ProTournamentBase15m):
    stoploss = -0.03

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        squeeze = frame["bb_width"].shift(1) <= frame["bb_width_q30_prev96"]
        expanding = frame["bb_width"] > frame["bb_width"].shift(1)
        volume = self._volume_ok(frame, 1.2)
        long = squeeze & expanding & frame["trend_long_4h"].fillna(False) & (frame["close"] > frame["channel_high_prev32"]) & volume
        short = squeeze & expanding & frame["trend_short_4h"].fillna(False) & (frame["close"] < frame["channel_low_prev32"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "vol_breakout_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "vol_breakout_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = dataframe["close"] < dataframe["ema20"]
        short = dataframe["close"] > dataframe["ema20"]
        return self._initialize_exits(dataframe.copy(), long, short, "vol_breakout_ema20")


class ProMeanReversion15m(ProTournamentBase15m):
    stoploss = -0.02

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        flat = (frame["adx14_1h"] < 18) & (frame["ema_gap_atr_1h"].abs() < 0.5)
        volume = self._volume_ok(frame, 0.7)
        long = flat & (frame["z48"].shift(1) < -2.2) & (frame["z48"] >= -2.2) & (frame["rsi14"] < 40) & volume
        short = flat & (frame["z48"].shift(1) > 2.2) & (frame["z48"] <= 2.2) & (frame["rsi14"] > 60) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "mean_reversion_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "mean_reversion_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = (dataframe["z48"] >= 0) | (dataframe["rsi14"] >= 55)
        short = (dataframe["z48"] <= 0) | (dataframe["rsi14"] <= 45)
        return self._initialize_exits(dataframe.copy(), long, short, "mean_reversion_center")

