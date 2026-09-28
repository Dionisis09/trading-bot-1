"""Frozen 1h pullback/breakout candidates for portfolio-frequency research."""

from datetime import datetime

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, informative
from technical import qtpylib

from DualTrendFuturesRisk import AtrExposureRiskMixin
from ProfessionalRisk import ProfessionalRiskMixin


class _ProfitMaxOneHourBase(AtrExposureRiskMixin, ProfessionalRiskMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 800
    minimal_roi = {"0": 100.0}
    stoploss = -0.04
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    setup_mode = "hybrid"

    order_types = {"entry": "limit", "exit": "limit", "stoploss": "market", "stoploss_on_exchange": False}
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 8},
            {"method": "StoplossGuard", "lookback_period_candles": 168, "trade_limit": 3,
             "stop_duration_candles": 48, "only_per_pair": False},
            {"method": "MaxDrawdown", "lookback_period_candles": 720, "trade_limit": 10,
             "stop_duration_candles": 72, "max_allowed_drawdown": 0.15},
        ]

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["roc20"] = ta.ROC(dataframe, timeperiod=20)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        previous_volume = dataframe["volume"].shift(1).rolling(20).median()
        dataframe["relative_volume_20"] = dataframe["volume"] / previous_volume.where(previous_volume > 0)
        dataframe["prior_high_24"] = dataframe["high"].rolling(24).max().shift(1)
        dataframe["prior_low_24"] = dataframe["low"].rolling(24).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common = (
            (dataframe["volume"] > 0)
            & (dataframe["adx"] >= 18.0)
            & (dataframe["atr_pct"] >= 0.0025)
            & (dataframe["atr_pct"] <= 0.08)
        )
        long_regime = common & (dataframe["close_1d"] > dataframe["ema200_1d"]) & (dataframe["roc20_1d"] > 0)
        short_regime = common & (dataframe["close_1d"] < dataframe["ema200_1d"]) & (dataframe["roc20_1d"] < 0)
        long_trend = (dataframe["ema20"] > dataframe["ema50"]) & (dataframe["plus_di"] > dataframe["minus_di"])
        short_trend = (dataframe["ema20"] < dataframe["ema50"]) & (dataframe["minus_di"] > dataframe["plus_di"])
        pullback_long = (
            long_regime & long_trend & (dataframe["relative_volume_20"] >= 0.80)
            & (dataframe["rsi"] > 48.0) & (dataframe["rsi"] < 72.0)
            & qtpylib.crossed_above(dataframe["close"], dataframe["ema20"])
        )
        pullback_short = (
            short_regime & short_trend & (dataframe["relative_volume_20"] >= 0.80)
            & (dataframe["rsi"] > 28.0) & (dataframe["rsi"] < 52.0)
            & qtpylib.crossed_below(dataframe["close"], dataframe["ema20"])
        )
        breakout_long = (
            long_regime & long_trend & (dataframe["relative_volume_20"] >= 1.00) & (dataframe["rsi"] < 78.0)
            & qtpylib.crossed_above(dataframe["close"], dataframe["prior_high_24"])
        )
        breakout_short = (
            short_regime & short_trend & (dataframe["relative_volume_20"] >= 1.00) & (dataframe["rsi"] > 22.0)
            & qtpylib.crossed_below(dataframe["close"], dataframe["prior_low_24"])
        )
        if self.setup_mode in ("pullback", "hybrid"):
            dataframe.loc[pullback_long, ["enter_long", "enter_tag"]] = (1, "pullback_long")
            dataframe.loc[pullback_short, ["enter_short", "enter_tag"]] = (1, "pullback_short")
        if self.setup_mode in ("breakout", "hybrid"):
            dataframe.loc[breakout_long, ["enter_long", "enter_tag"]] = (1, "breakout_long")
            dataframe.loc[breakout_short, ["enter_short", "enter_tag"]] = (1, "breakout_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_exit = qtpylib.crossed_below(dataframe["close"], dataframe["ema50"]) & (dataframe["minus_di"] > dataframe["plus_di"])
        short_exit = qtpylib.crossed_above(dataframe["close"], dataframe["ema50"]) & (dataframe["plus_di"] > dataframe["minus_di"])
        dataframe.loc[long_exit & (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (1, "ema50_di_failure")
        dataframe.loc[short_exit & (dataframe["volume"] > 0), ["exit_short", "exit_tag"]] = (1, "ema50_di_failure")
        return dataframe

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        return 1.0


class ProfitMaxOneHourPullback(_ProfitMaxOneHourBase):
    setup_mode = "pullback"


class ProfitMaxOneHourBreakout(_ProfitMaxOneHourBase):
    setup_mode = "breakout"


class ProfitMaxOneHourHybrid(_ProfitMaxOneHourBase):
    setup_mode = "hybrid"
