"""Lookahead-compatible exact frozen-universe cross-sectional audit variant."""

from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from ProfitMaxDailyCrossSectionalAudit import ProfitMaxDailyCrossStop20Audit


class ProfitMaxDailyCrossStop20AuditV2(ProfitMaxDailyCrossStop20Audit):
    frozen_pairs = tuple(
        f"{symbol}/USDT:USDT"
        for symbol in "BTC ETH SOL ZEC XRP LINK BNB DOGE AVAX XMR ADA UNI NEAR AAVE FIL BCH LTC TRX DOT XLM CRV DASH ATOM ONT ETC BEL ALGO STORJ AXS BAT RUNE VET TRB IOTA ZEN THETA KAVA ZIL GRT SUSHI YFI SNX NEO COMP RLC XTZ EGLD ENJ QTUM 1INCH".split()
    )

    def _build_rank_cache(self) -> DataFrame:
        if self._rank_cache is not None:
            return self._rank_cache
        if len(self.frozen_pairs) != 50 or self.frozen_pairs[0] != "BTC/USDT:USDT":
            raise ValueError("embedded frozen universe contract failed")
        series = {}
        for pair in self.frozen_pairs:
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
        for pair in self.frozen_pairs:
            cache[f"rank::{pair}"] = ordinal[pair]
        self._rank_cache = cache
        return cache

