"""Pre-declared V4 daily-momentum trend portfolio variants.

The fixed hypothesis, trial budget, and gates are documented in
``docs/strategy_v4_research_plan.md``.
"""

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, informative
from technical import qtpylib


class MajorTrendV4A(IStrategy):
    """Aligned daily trend with 63-day momentum and 30/15 channels."""

    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "4h"
    process_only_new_candles = True
    startup_candle_count = 800

    momentum_period = 63
    entry_period = 30
    exit_period = 15

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
        dataframe["roc126"] = ta.ROC(dataframe, timeperiod=126)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["volume_median_12"] = dataframe["volume"].rolling(12).median()
        dataframe["entry_channel"] = (
            dataframe["high"].rolling(self.entry_period).max().shift(1)
        )
        dataframe["exit_channel"] = (
            dataframe["low"].rolling(self.exit_period).min().shift(1)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        momentum = dataframe[f"roc{self.momentum_period}_1d"]
        conditions = (
            (dataframe["close_1d"] > dataframe["ema200_1d"])
            & (dataframe["ema20_1d"] > dataframe["ema50_1d"])
            & (dataframe["ema50_1d"] > dataframe["ema200_1d"])
            & (momentum > 0.0)
            & qtpylib.crossed_above(dataframe["close"], dataframe["entry_channel"])
            & (dataframe["adx"] > 18.0)
            & (dataframe["rsi"] > 52.0)
            & (dataframe["rsi"] < 82.0)
            & (dataframe["atr_pct"] > 0.005)
            & (dataframe["atr_pct"] < 0.12)
            & (dataframe["volume"] > dataframe["volume_median_12"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[conditions, ["enter_long", "enter_tag"]] = (
            1,
            f"momentum_{self.momentum_period}_breakout_{self.entry_period}",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = (
            qtpylib.crossed_below(dataframe["close"], dataframe["exit_channel"])
            | (dataframe["close_1d"] < dataframe["ema20_1d"])
        ) & (dataframe["volume"] > 0)
        dataframe.loc[conditions, ["exit_long", "exit_tag"]] = (
            1,
            f"channel_{self.exit_period}_or_daily_momentum_failure",
        )
        return dataframe


class MajorTrendV4B(MajorTrendV4A):
    """Faster 10-candle exit with the 63-day momentum filter."""

    exit_period = 10


class MajorTrendV4C(MajorTrendV4A):
    """Longer 126-day positive momentum requirement."""

    momentum_period = 126


class MajorTrendV4D(MajorTrendV4A):
    """Slower 42/21 channels with the 63-day momentum filter."""

    entry_period = 42
    exit_period = 21
