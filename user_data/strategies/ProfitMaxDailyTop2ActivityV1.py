"""Twice-daily causal cross-sectional activity sleeve using the top two ranks."""

from pandas import DataFrame

from ProfitMaxDailyCrossSectionalAuditV2 import ProfitMaxDailyCrossStop20AuditV2


class ProfitMaxDailyTop2ActivityV1(ProfitMaxDailyCrossStop20AuditV2):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ready = (
            (dataframe["volume"] > 0)
            & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
            & dataframe["btc_bull"].fillna(False)
            & dataframe["date"].dt.hour.isin(self.signal_hours_utc)
        )
        top_two = dataframe["cross_rank"] >= (dataframe["rank_count"] - 1)
        dataframe.loc[ready & top_two, ["enter_long", "enter_tag"]] = (
            1,
            "daily_top2_xsmom7_btc30_long",
        )
        dataframe["enter_short"] = 0
        return dataframe
