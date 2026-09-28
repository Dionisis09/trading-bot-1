"""BTC-regime-aware 15m momentum tournament."""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import merge_informative_pair
from ProTournament15m import ProTournamentBase15m


class ProRegimeBase15m(ProTournamentBase15m):
    startup_candle_count = 1599
    btc_pair = "BTC/USDT:USDT"

    @classmethod
    def _base_indicators(cls, dataframe: DataFrame) -> DataFrame:
        frame = super()._base_indicators(dataframe)
        frame["ema100"] = ta.EMA(frame, timeperiod=100)
        return frame

    @classmethod
    def _informative(cls, dataframe: DataFrame, timeframe: str) -> DataFrame:
        if timeframe != "1h":
            return super()._informative(dataframe, timeframe)
        frame = dataframe.copy()
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["ema50"] = ta.EMA(frame, timeperiod=50)
        frame["ema200"] = ta.EMA(frame, timeperiod=200)
        frame["atr14"] = ta.ATR(frame, timeperiod=14)
        frame["adx14"] = ta.ADX(frame, timeperiod=14)
        frame["momentum24"] = np.log(cls._finite_divide(frame["close"], frame["close"].shift(24)))
        frame["ema_gap_atr"] = cls._finite_divide(frame["ema20"] - frame["ema50"], frame["atr14"])
        frame["regime_long"] = (frame["ema50"] > frame["ema200"]) & (frame["ema200"] > frame["ema200"].shift(12))
        frame["regime_short"] = (frame["ema50"] < frame["ema200"]) & (frame["ema200"] < frame["ema200"].shift(12))
        return frame[["date", "ema20", "ema50", "ema200", "atr14", "adx14", "momentum24",
                      "ema_gap_atr", "regime_long", "regime_short"]]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = self._base_indicators(dataframe)
        pair = metadata.get("pair", "")
        if self.dp is None or not pair:
            return frame
        for tf in ("1h", "4h"):
            informative = self.dp.get_pair_dataframe(pair=pair, timeframe=tf)
            if informative is not None and not informative.empty:
                frame = merge_informative_pair(frame, self._informative(informative, tf), self.timeframe, tf, ffill=True)
        if pair == self.btc_pair:
            frame["btc_regime_long_1h"] = frame["regime_long_1h"]
            frame["btc_regime_short_1h"] = frame["regime_short_1h"]
            frame["btc_momentum24_1h"] = frame["momentum24_1h"]
        else:
            btc = self.dp.get_pair_dataframe(pair=self.btc_pair, timeframe="1h")
            if btc is not None and not btc.empty:
                frame = merge_informative_pair(
                    frame, self._informative(btc, "1h"), self.timeframe, "1h",
                    ffill=True, append_timeframe=False, suffix="btc_1h",
                )
                frame["btc_regime_long_1h"] = frame["regime_long_btc_1h"]
                frame["btc_regime_short_1h"] = frame["regime_short_btc_1h"]
                frame["btc_momentum24_1h"] = frame["momentum24_btc_1h"]
        frame["relative_momentum_1h"] = frame["momentum24_1h"] - frame["btc_momentum24_1h"]
        return frame

    @staticmethod
    def _regime_long(frame: DataFrame) -> pd.Series:
        return frame["btc_regime_long_1h"].fillna(False).astype(bool) & frame["trend_long_4h"].fillna(False).astype(bool)

    @staticmethod
    def _regime_short(frame: DataFrame) -> pd.Series:
        return frame["btc_regime_short_1h"].fillna(False).astype(bool) & frame["trend_short_4h"].fillna(False).astype(bool)


class ProRegimeMomentum15m(ProRegimeBase15m):
    stoploss = -0.025

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame); volume = self._volume_ok(frame)
        long = self._regime_long(frame) & (frame["momentum24_1h"] > 0) & (frame["adx14_1h"] >= 18) & (frame["ema20"].shift(1) <= frame["ema50"].shift(1)) & (frame["ema20"] > frame["ema50"]) & volume
        short = self._regime_short(frame) & (frame["momentum24_1h"] < 0) & (frame["adx14_1h"] >= 18) & (frame["ema20"].shift(1) >= frame["ema50"].shift(1)) & (frame["ema20"] < frame["ema50"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "regime_momentum_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "regime_momentum_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = (dataframe["close"] < dataframe["ema50"]) | dataframe["btc_regime_short_1h"].fillna(False)
        short = (dataframe["close"] > dataframe["ema50"]) | dataframe["btc_regime_long_1h"].fillna(False)
        return self._initialize_exits(dataframe.copy(), long, short, "regime_or_ema50")


class ProRegimeBreakout15m(ProRegimeBase15m):
    stoploss = -0.025

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame); volume = self._volume_ok(frame, 1.1)
        long = self._regime_long(frame) & (frame["adx14_1h"] >= 18) & (frame["close"] > frame["channel_high_prev32"]) & volume
        short = self._regime_short(frame) & (frame["adx14_1h"] >= 18) & (frame["close"] < frame["channel_low_prev32"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "regime_breakout_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "regime_breakout_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = (dataframe["close"] < dataframe["ema20"]) | dataframe["btc_regime_short_1h"].fillna(False)
        short = (dataframe["close"] > dataframe["ema20"]) | dataframe["btc_regime_long_1h"].fillna(False)
        return self._initialize_exits(dataframe.copy(), long, short, "regime_or_ema20")


class ProRegimePullback15m(ProRegimeBase15m):
    stoploss = -0.02

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame); volume = self._volume_ok(frame, 0.8)
        long = self._regime_long(frame) & (frame["momentum24_1h"] > 0) & (frame["ema20"] > frame["ema50"]) & (frame["close"].shift(1) <= frame["ema20"].shift(1)) & (frame["close"] > frame["ema20"]) & volume
        short = self._regime_short(frame) & (frame["momentum24_1h"] < 0) & (frame["ema20"] < frame["ema50"]) & (frame["close"].shift(1) >= frame["ema20"].shift(1)) & (frame["close"] < frame["ema20"]) & volume
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "regime_pullback_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "regime_pullback_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long = (dataframe["close"] < dataframe["ema50"]) | dataframe["btc_regime_short_1h"].fillna(False)
        short = (dataframe["close"] > dataframe["ema50"]) | dataframe["btc_regime_long_1h"].fillna(False)
        return self._initialize_exits(dataframe.copy(), long, short, "regime_or_ema50")


class ProRelativeMomentum15m(ProRegimeMomentum15m):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = super().populate_entry_trend(dataframe, metadata)
        pair = metadata.get("pair", "")
        if pair != self.btc_pair:
            frame.loc[frame["relative_momentum_1h"] <= 0, "enter_long"] = 0
            frame.loc[frame["relative_momentum_1h"] >= 0, "enter_short"] = 0
            frame.loc[(frame["enter_long"] == 0) & (frame["enter_short"] == 0), "enter_tag"] = ""
            frame.loc[frame["enter_long"] == 1, "enter_tag"] = "relative_momentum_long"
            frame.loc[frame["enter_short"] == 1, "enter_tag"] = "relative_momentum_short"
        return frame

