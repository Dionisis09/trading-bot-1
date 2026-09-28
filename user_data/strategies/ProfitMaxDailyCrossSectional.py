"""Twice-daily causal cross-sectional leader with a BTC 30-day risk gate."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade

from ProfitMaxCrossSectional import _CrossSectionalBase


class ProfitMaxDailyCrossSectional(_CrossSectionalBase):
    can_short = False
    momentum_candles = 42
    btc_gate_candles = 180
    hold_hours = 8
    startup_candle_count = 190
    signal_hours_utc = (8, 20)

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
        cache["btc_bull"] = (btc / btc.shift(self.btc_gate_candles) - 1.0) > 0
        for pair in pairs:
            cache[f"rank::{pair}"] = ordinal[pair]
        self._rank_cache = cache
        return cache

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ready = (
            (dataframe["volume"] > 0)
            & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
            & dataframe["btc_bull"].fillna(False)
            & dataframe["date"].dt.hour.isin(self.signal_hours_utc)
        )
        strongest = dataframe["cross_rank"] == dataframe["rank_count"]
        dataframe.loc[ready & strongest, ["enter_long", "enter_tag"]] = (
            1,
            "daily_xsmom7_btc30_long",
        )
        dataframe["enter_short"] = 0
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        if current_time - trade.open_date_utc >= timedelta(hours=self.hold_hours):
            return "fixed_8h_exit"
        return None

