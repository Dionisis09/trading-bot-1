"""Predeclared 1h channel horizons over the qualified daily-regime alpha."""

from pandas import DataFrame

from ProfitMaxSwingV5 import ProfitMaxV5Asymmetric50


class _OneHourChannelMixin:
    timeframe = "1h"
    entry_channel_hours = 30
    exit_channel_hours = 10

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 8},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 168,
                "trade_limit": 3,
                "stop_duration_candles": 48,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 720,
                "trade_limit": 10,
                "stop_duration_candles": 72,
                "max_allowed_drawdown": 0.15,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_high"] = dataframe["high"].rolling(self.entry_channel_hours).max().shift(1)
        dataframe["entry_low"] = dataframe["low"].rolling(self.entry_channel_hours).min().shift(1)
        dataframe["exit_high"] = dataframe["high"].rolling(self.exit_channel_hours).max().shift(1)
        dataframe["exit_low"] = dataframe["low"].rolling(self.exit_channel_hours).min().shift(1)
        return dataframe


class ProfitMaxLiquid50OneHour30(_OneHourChannelMixin, ProfitMaxV5Asymmetric50):
    """30h entry / 10h exit channel."""


class ProfitMaxLiquid50OneHour60(_OneHourChannelMixin, ProfitMaxV5Asymmetric50):
    """60h entry / 20h exit channel."""

    entry_channel_hours = 60
    exit_channel_hours = 20


class ProfitMaxLiquid50OneHour120(_OneHourChannelMixin, ProfitMaxV5Asymmetric50):
    """120h entry / 40h exit channel."""

    entry_channel_hours = 120
    exit_channel_hours = 40
