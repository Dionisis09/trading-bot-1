"""One-hour descendants of the historically profitable V2 trend architecture."""

from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy, informative
from technical import qtpylib


class ProSwingBase1h(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 999
    minimal_roi = {"0": 100.0}
    stoploss = -0.06
    trailing_stop = False
    use_custom_stoploss = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    order_types = {"entry": "limit", "exit": "limit", "stoploss": "market", "stoploss_on_exchange": False}
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    entry_window = 30
    exit_window = 10
    confluence_minimum = 3
    adx_minimum = 20.0

    @informative("4h")
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["roc63"] = ta.ROC(dataframe, timeperiod=63)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        quote_volume = dataframe["close"] * dataframe["volume"]
        dataframe["relative_quote_volume_10"] = quote_volume / quote_volume.shift(1).rolling(10).mean()
        volume_sum = dataframe["volume"].rolling(20).sum()
        dataframe["vwma20"] = (dataframe["close"] * dataframe["volume"]).rolling(20).sum() / volume_sum.where(volume_sum > 0)
        dataframe["sma20"] = ta.SMA(dataframe, timeperiod=20)
        dataframe["entry_high"] = dataframe["high"].rolling(self.entry_window).max().shift(1)
        dataframe["entry_low"] = dataframe["low"].rolling(self.entry_window).min().shift(1)
        dataframe["exit_high"] = dataframe["high"].rolling(self.exit_window).max().shift(1)
        dataframe["exit_low"] = dataframe["low"].rolling(self.exit_window).min().shift(1)
        dataframe["long_score"] = (
            (dataframe["plus_di"] > dataframe["minus_di"]).astype(int)
            + ((dataframe["adx"] >= 25) & (dataframe["adx"] > dataframe["adx"].shift(1))).astype(int)
            + (dataframe["relative_quote_volume_10"] >= 1.10).astype(int)
            + ((dataframe["close"] > dataframe["vwma20"]) & (dataframe["vwma20"] > dataframe["sma20"])).astype(int)
        )
        dataframe["short_score"] = (
            (dataframe["minus_di"] > dataframe["plus_di"]).astype(int)
            + ((dataframe["adx"] >= 25) & (dataframe["adx"] > dataframe["adx"].shift(1))).astype(int)
            + (dataframe["relative_quote_volume_10"] >= 1.10).astype(int)
            + ((dataframe["close"] < dataframe["vwma20"]) & (dataframe["vwma20"] < dataframe["sma20"])).astype(int)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common = (dataframe["adx"] > self.adx_minimum) & (dataframe["atr_pct"] > 0.002) & (dataframe["atr_pct"] < 0.08) & (dataframe["volume"] > 0)
        long = common & (dataframe["long_score"] >= self.confluence_minimum) & (dataframe["close_4h"] > dataframe["ema200_4h"]) & (dataframe["ema20_4h"] > dataframe["ema50_4h"]) & (dataframe["ema50_4h"] > dataframe["ema200_4h"]) & (dataframe["roc63_4h"] > 0) & (dataframe["rsi"] > 52) & (dataframe["rsi"] < 82) & qtpylib.crossed_above(dataframe["close"], dataframe["entry_high"])
        short = common & (dataframe["short_score"] >= self.confluence_minimum) & (dataframe["close_4h"] < dataframe["ema200_4h"]) & (dataframe["ema20_4h"] < dataframe["ema50_4h"]) & (dataframe["ema50_4h"] < dataframe["ema200_4h"]) & (dataframe["roc63_4h"] < 0) & (dataframe["rsi"] > 18) & (dataframe["rsi"] < 48) & qtpylib.crossed_below(dataframe["close"], dataframe["entry_low"])
        dataframe.loc[long, ["enter_long", "enter_tag"]] = (1, "swing_breakout_long")
        dataframe.loc[short, ["enter_short", "enter_tag"]] = (1, "swing_breakout_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_invalid = qtpylib.crossed_below(dataframe["close"], dataframe["vwma20"]) & (dataframe["minus_di"] > dataframe["plus_di"])
        short_invalid = qtpylib.crossed_above(dataframe["close"], dataframe["vwma20"]) & (dataframe["plus_di"] > dataframe["minus_di"])
        long = (qtpylib.crossed_below(dataframe["close"], dataframe["exit_low"]) | (dataframe["close_4h"] < dataframe["ema20_4h"]) | long_invalid) & (dataframe["volume"] > 0)
        short = (qtpylib.crossed_above(dataframe["close"], dataframe["exit_high"]) | (dataframe["close_4h"] > dataframe["ema20_4h"]) | short_invalid) & (dataframe["volume"] > 0)
        dataframe.loc[long, ["exit_long", "exit_tag"]] = (1, "swing_long_invalidation")
        dataframe.loc[short, ["exit_short", "exit_tag"]] = (1, "swing_short_invalidation")
        return dataframe

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        return 1.0


class ProSwingCore1h(ProSwingBase1h):
    pass


class ProSwingSlow1h(ProSwingBase1h):
    entry_window = 55
    exit_window = 20


class ProSwingSelective1h(ProSwingBase1h):
    confluence_minimum = 4


class ProSwingStrongTrend1h(ProSwingBase1h):
    adx_minimum = 25.0

