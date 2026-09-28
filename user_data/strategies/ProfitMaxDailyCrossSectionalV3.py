"""Frozen base-plus-breadth-bonus daily cross-sectional candidate."""

from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from ProfitMaxDailyCrossSectionalV2 import ProfitMaxDailyCrossStop20


class ProfitMaxDailyCrossBreadthBonus(ProfitMaxDailyCrossStop20):
    signal_hours_utc = (8, 12, 20)
    bonus_signal_hour_utc = 12
    breadth_minimum = 0.70

    @property
    def protections(self):
        return []

    def _build_rank_cache(self) -> DataFrame:
        if self._rank_cache is not None:
            return self._rank_cache
        pairs = list(self.dp.current_whitelist())
        series = {}
        for pair in pairs:
            raw = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            current = raw.loc[:, ["date", "close"]].copy()
            current["date"] = pd.to_datetime(current["date"], utc=True)
            series[pair] = current.drop_duplicates("date").set_index("date")["close"].astype(float)
        closes = pd.concat(series, axis=1, sort=True).sort_index()
        momentum = closes / closes.shift(self.momentum_candles) - 1.0
        counts = momentum.notna().sum(axis=1)
        ordinal = momentum.rank(axis=1, method="first", ascending=True, na_option="keep")
        btc = closes["BTC/USDT:USDT"]
        cache = pd.DataFrame(index=closes.index)
        cache["rank_count"] = counts
        cache["breadth"] = (momentum > 0).sum(axis=1) / counts.replace(0, pd.NA)
        cache["btc_bull"] = (btc / btc.shift(self.btc_gate_candles) - 1.0) > 0
        for pair in pairs:
            cache[f"rank::{pair}"] = ordinal[pair]
        self._rank_cache = cache
        return cache

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        cache = self._build_rank_cache()
        breadth = cache.loc[:, ["breadth"]]
        merged = dataframe.copy()
        merged["date"] = pd.to_datetime(merged["date"], utc=True)
        return merged.merge(
            breadth.reset_index().rename(columns={"index": "date"}),
            on="date",
            how="left",
            validate="one_to_one",
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        hour = dataframe["date"].dt.hour
        scheduled = hour.isin((8, 20)) | (
            (hour == self.bonus_signal_hour_utc) & (dataframe["breadth"] >= self.breadth_minimum)
        )
        ready = (
            (dataframe["volume"] > 0)
            & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
            & dataframe["btc_bull"].fillna(False)
            & scheduled
        )
        strongest = dataframe["cross_rank"] == dataframe["rank_count"]
        dataframe.loc[ready & strongest, ["enter_long", "enter_tag"]] = (
            1,
            "daily_xsmom7_btc30_breadth_bonus",
        )
        dataframe["enter_short"] = 0
        return dataframe

