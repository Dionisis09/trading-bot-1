"""Audit-compatible daily cross rank using the frozen config whitelist."""

from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from ProfitMaxDailyCrossSectionalV2 import ProfitMaxDailyCrossStop20


class ProfitMaxDailyCrossStop20Audit(ProfitMaxDailyCrossStop20):
    def _build_rank_cache(self) -> DataFrame:
        if self._rank_cache is not None:
            return self._rank_cache
        pairs = list((self.config.get("exchange") or {}).get("pair_whitelist") or [])
        if len(pairs) != 50 or "BTC/USDT:USDT" not in pairs:
            raise ValueError("frozen 50-pair config whitelist is unavailable")
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

