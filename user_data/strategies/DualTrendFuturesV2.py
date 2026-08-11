"""Locked pro-style confluence challenger to DualTrendFuturesV1."""

from datetime import datetime

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, informative
from technical import qtpylib
from ProfessionalRisk import ProfessionalRiskMixin


class DualTrendFuturesV2(ProfessionalRiskMixin, IStrategy):
    """Daily trend/breakout strategy with fixed 4h confluence scoring."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "4h"
    process_only_new_candles = True
    startup_candle_count = 800

    minimal_roi = {"0": 100.0}
    stoploss = -0.10
    trailing_stop = False

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 42,
                "trade_limit": 3,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 180,
                "trade_limit": 10,
                "stop_duration_candles": 18,
                "max_allowed_drawdown": 0.15,
            },
        ]

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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
        previous_quote_volume_mean = quote_volume.shift(1).rolling(10).mean()
        dataframe["relative_quote_volume_10"] = quote_volume / previous_quote_volume_mean

        volume_sum_20 = dataframe["volume"].rolling(20).sum()
        dataframe["vwma20"] = (
            (dataframe["close"] * dataframe["volume"]).rolling(20).sum()
            / volume_sum_20.where(volume_sum_20 > 0)
        )
        dataframe["sma20"] = ta.SMA(dataframe, timeperiod=20)

        dataframe["entry_high"] = dataframe["high"].rolling(30).max().shift(1)
        dataframe["entry_low"] = dataframe["low"].rolling(30).min().shift(1)
        dataframe["exit_high"] = dataframe["high"].rolling(10).max().shift(1)
        dataframe["exit_low"] = dataframe["low"].rolling(10).min().shift(1)

        dataframe["long_confluence_score"] = (
            (dataframe["plus_di"] > dataframe["minus_di"]).astype(int)
            + ((dataframe["adx"] >= 25.0) & (dataframe["adx"] > dataframe["adx"].shift(1))).astype(int)
            + (dataframe["relative_quote_volume_10"] >= 1.10).astype(int)
            + ((dataframe["close"] > dataframe["vwma20"]) & (dataframe["vwma20"] > dataframe["sma20"])).astype(int)
        )
        dataframe["short_confluence_score"] = (
            (dataframe["minus_di"] > dataframe["plus_di"]).astype(int)
            + ((dataframe["adx"] >= 25.0) & (dataframe["adx"] > dataframe["adx"].shift(1))).astype(int)
            + (dataframe["relative_quote_volume_10"] >= 1.10).astype(int)
            + ((dataframe["close"] < dataframe["vwma20"]) & (dataframe["vwma20"] < dataframe["sma20"])).astype(int)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common = (
            (dataframe["adx"] > 20.0)
            & (dataframe["atr_pct"] > 0.005)
            & (dataframe["atr_pct"] < 0.12)
            & (dataframe["volume"] > 0)
        )
        long_condition = (
            common
            & (dataframe["long_confluence_score"] >= 3)
            & (dataframe["close_1d"] > dataframe["ema200_1d"])
            & (dataframe["ema20_1d"] > dataframe["ema50_1d"])
            & (dataframe["ema50_1d"] > dataframe["ema200_1d"])
            & (dataframe["roc63_1d"] > 0.0)
            & (dataframe["rsi"] > 52.0)
            & (dataframe["rsi"] < 82.0)
            & qtpylib.crossed_above(dataframe["close"], dataframe["entry_high"])
        )
        short_condition = (
            common
            & (dataframe["short_confluence_score"] >= 3)
            & (dataframe["close_1d"] < dataframe["ema200_1d"])
            & (dataframe["ema20_1d"] < dataframe["ema50_1d"])
            & (dataframe["ema50_1d"] < dataframe["ema200_1d"])
            & (dataframe["roc63_1d"] < 0.0)
            & (dataframe["rsi"] > 18.0)
            & (dataframe["rsi"] < 48.0)
            & qtpylib.crossed_below(dataframe["close"], dataframe["entry_low"])
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "daily_bull_breakout_30_confluence_3of4",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "daily_bear_breakdown_30_confluence_3of4",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_invalidation = (
            qtpylib.crossed_below(dataframe["close"], dataframe["vwma20"])
            & (dataframe["minus_di"] > dataframe["plus_di"])
        )
        short_invalidation = (
            qtpylib.crossed_above(dataframe["close"], dataframe["vwma20"])
            & (dataframe["plus_di"] > dataframe["minus_di"])
        )
        long_exit = (
            qtpylib.crossed_below(dataframe["close"], dataframe["exit_low"])
            | (dataframe["close_1d"] < dataframe["ema20_1d"])
            | long_invalidation
        ) & (dataframe["volume"] > 0)
        short_exit = (
            qtpylib.crossed_above(dataframe["close"], dataframe["exit_high"])
            | (dataframe["close_1d"] > dataframe["ema20_1d"])
            | short_invalidation
        ) & (dataframe["volume"] > 0)
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (
            1,
            "long_channel_daily_or_confluence_failure",
        )
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (
            1,
            "short_channel_daily_or_confluence_failure",
        )
        return dataframe

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return 1.0
