"""Fixed causal cross-sectional reversal sleeves."""

from pandas import DataFrame
from ProfitMaxCrossSectional import _CrossSectionalBase


class _Reversal8hBase(_CrossSectionalBase):
    momentum_candles = 180
    hold_hours = 8
    selected_ranks = 2


class ProfitMaxCrossReversalLong8h(_Reversal8hBase):
    can_short = False

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ready = (dataframe["volume"] > 0) & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
        dataframe.loc[ready & (dataframe["cross_rank"] <= self.selected_ranks), ["enter_long", "enter_tag"]] = (1, "xsrev_bottom2_30d_8h_long")
        dataframe["enter_short"] = 0
        return dataframe


class ProfitMaxCrossReversalShort8h(_Reversal8hBase):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ready = (dataframe["volume"] > 0) & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
        dataframe.loc[ready & (dataframe["cross_rank"] > dataframe["rank_count"] - self.selected_ranks), ["enter_short", "enter_tag"]] = (1, "xsrev_top2_30d_8h_short")
        dataframe["enter_long"] = 0
        return dataframe
