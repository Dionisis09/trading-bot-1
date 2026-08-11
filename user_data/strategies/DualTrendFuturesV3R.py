"""Final locked V2R challenger using a confirmed-candle Chandelier exit."""

from pandas import DataFrame

from DualTrendFuturesRisk import DualTrendFuturesV2R
from technical import qtpylib


class DualTrendFuturesV3R(DualTrendFuturesV2R):
    """V2R entries and sizing with a 22-period, 3-ATR Chandelier exit."""

    chandelier_lookback = 22
    chandelier_atr_multiplier = 3.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        highest_high = dataframe["high"].rolling(self.chandelier_lookback).max()
        lowest_low = dataframe["low"].rolling(self.chandelier_lookback).min()
        dataframe["chandelier_long_exit"] = (
            highest_high - self.chandelier_atr_multiplier * dataframe["atr"]
        )
        dataframe["chandelier_short_exit"] = (
            lowest_low + self.chandelier_atr_multiplier * dataframe["atr"]
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_exit = (
            qtpylib.crossed_below(dataframe["close"], dataframe["chandelier_long_exit"])
            | (dataframe["close_1d"] < dataframe["ema20_1d"])
        ) & (dataframe["volume"] > 0)
        short_exit = (
            qtpylib.crossed_above(dataframe["close"], dataframe["chandelier_short_exit"])
            | (dataframe["close_1d"] > dataframe["ema20_1d"])
        ) & (dataframe["volume"] > 0)
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (
            1,
            "long_chandelier_22x3_or_daily_failure",
        )
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (
            1,
            "short_chandelier_22x3_or_daily_failure",
        )
        return dataframe
