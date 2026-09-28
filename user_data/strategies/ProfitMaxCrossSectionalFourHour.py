"""Frozen top-two 30-day leader candidates with a four-hour hold."""

from datetime import datetime, timedelta

from pandas import DataFrame

from freqtrade.persistence import Trade

from ProfitMaxCrossSectionalLong import _CrossSectionalTopTwoLong


class _TopTwoFourHour(_CrossSectionalTopTwoLong):
    momentum_candles = 180
    hold_hours = 4
    top_n = 2

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        if current_time - trade.open_date_utc >= timedelta(hours=4):
            return "fixed_4h_rebalance"
        return None


class ProfitMaxCrossSectionalTopTwo4h(_TopTwoFourHour):
    """Unfiltered top-two 30-day leaders."""


class ProfitMaxCrossSectionalTopTwo4hPositive(_TopTwoFourHour):
    """Top-two leaders only when their own 30-day return is positive."""

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["absolute_momentum_30d"] = dataframe["close"] / dataframe["close"].shift(
            self.momentum_candles
        ) - 1.0
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        admitted = dataframe["absolute_momentum_30d"].gt(0).fillna(False)
        blocked = dataframe["enter_long"].fillna(0).eq(1) & ~admitted
        dataframe.loc[blocked, "enter_long"] = 0
        dataframe.loc[blocked, "enter_tag"] = None
        dataframe.loc[dataframe["enter_long"].fillna(0).eq(1), "enter_tag"] = (
            "xsmom_top2_180_4h_positive_long"
        )
        return dataframe
