"""Eight-hour leader momentum with a single-candle re-entry cooldown."""

from pandas import DataFrame

from ProfitMaxCrossSectionalShortHorizon import ProfitMaxCrossSectionalTopTwo8h


class _FastReentry(ProfitMaxCrossSectionalTopTwo8h):
    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 1},
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


class ProfitMaxCrossSectionalTopTwo8hFastReentry(_FastReentry):
    """Unfiltered fast re-entry candidate."""


class ProfitMaxCrossSectionalTopTwo8hFastReentryPositive(_FastReentry):
    """Fast re-entry candidate with positive absolute 30-day momentum."""

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
            "xsmom_top2_180_8h_fast_positive_long"
        )
        return dataframe
