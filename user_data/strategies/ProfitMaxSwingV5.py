"""Fixed Cycle 5 asymmetric-short challengers to DualTrendFuturesV2R."""

from pandas import DataFrame

from DualTrendFuturesRisk import DualTrendFuturesV2R


class _HalfShortStakeMixin:
    short_stake_multiplier = 0.50

    def custom_stake_amount(self, *args, side: str, **kwargs) -> float:
        stake = super().custom_stake_amount(*args, side=side, **kwargs)
        return stake * self.short_stake_multiplier if side == "short" else stake


class _DecliningDailyEmaShortMixin:
    daily_ema_slope_base_candles = 42  # seven completed days on a 4h base

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        had_short = dataframe["enter_short"].fillna(0).eq(1)
        declining = dataframe["ema200_1d"].lt(
            dataframe["ema200_1d"].shift(self.daily_ema_slope_base_candles)
        )
        blocked = had_short & ~declining.fillna(False)
        dataframe.loc[blocked, "enter_short"] = 0
        dataframe.loc[blocked & dataframe["enter_tag"].astype("string").str.contains(
            "bear", case=False, na=False
        ), "enter_tag"] = None
        return dataframe


class ProfitMaxV5Asymmetric50(_HalfShortStakeMixin, DualTrendFuturesV2R):
    """Unchanged signals with half-sized short exposure."""


class ProfitMaxV5SelectiveShort(_DecliningDailyEmaShortMixin, DualTrendFuturesV2R):
    """Full-sized shorts only in a persistently declining daily regime."""


class ProfitMaxV5Balanced(
    _HalfShortStakeMixin,
    _DecliningDailyEmaShortMixin,
    DualTrendFuturesV2R,
):
    """Declining-daily-regime shorts with half-sized exposure."""


class ProfitMaxV5LongOnly(DualTrendFuturesV2R):
    """Diagnostic ceiling which deliberately abandons short-side coverage."""

    can_short = False

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        had_short = dataframe["enter_short"].fillna(0).eq(1)
        dataframe.loc[had_short, "enter_short"] = 0
        dataframe.loc[had_short & dataframe["enter_tag"].astype("string").str.contains(
            "bear", case=False, na=False
        ), "enter_tag"] = None
        return dataframe
