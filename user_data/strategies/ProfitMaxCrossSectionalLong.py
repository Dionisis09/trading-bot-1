"""Frozen top-two long momentum candidates derived from TRAIN attribution."""

from pandas import DataFrame

from ProfitMaxCrossSectional import _CrossSectionalBase


class _CrossSectionalTopTwoLong(_CrossSectionalBase):
    can_short = False
    top_n = 2

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ready = (dataframe["volume"] > 0) & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
        leader = dataframe["cross_rank"] > (dataframe["rank_count"] - self.top_n)
        dataframe.loc[ready & leader, ["enter_long", "enter_tag"]] = (
            1,
            f"xsmom_top{self.top_n}_{self.momentum_candles}_{self.hold_hours}h_long",
        )
        dataframe["enter_short"] = 0
        return dataframe


class ProfitMaxCrossSectionalLong30d48h(_CrossSectionalTopTwoLong):
    momentum_candles = 180
    hold_hours = 48


class ProfitMaxCrossSectionalLong60d48h(_CrossSectionalTopTwoLong):
    momentum_candles = 360
    hold_hours = 48


class ProfitMaxCrossSectionalLong30d36h(_CrossSectionalTopTwoLong):
    momentum_candles = 180
    hold_hours = 36
