"""Frozen ensemble of qualified swing signals and 8h cross-sectional leaders."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from pandas import DataFrame
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import informative

from DualTrendFuturesV2 import DualTrendFuturesV2
from ProfitMaxCrossSectional import _CrossSectionalBase


class ProfitMaxEnsembleCrossSwingV1(_CrossSectionalBase):
    """Three-slot portfolio: two fast leaders plus one slow swing opportunity."""

    can_short = True
    momentum_candles = 180
    top_n = 2
    hold_hours = 8
    stoploss = -0.08
    use_exit_signal = False

    swing_pairs = frozenset(
        {
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "BNB/USDT:USDT",
            "XRP/USDT:USDT",
            "ADA/USDT:USDT",
            "DOGE/USDT:USDT",
        }
    )

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return DualTrendFuturesV2.populate_indicators_1d(self, dataframe, metadata)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = DualTrendFuturesV2.populate_indicators(self, dataframe, metadata)
        cache = self._build_rank_cache()
        rank_column = f"rank::{metadata['pair']}"
        rank = cache.loc[:, ["rank_count", "btc_bull", rank_column]].rename(
            columns={rank_column: "cross_rank"}
        )
        dataframe = dataframe.copy()
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True)
        return dataframe.merge(
            rank.reset_index().rename(columns={"index": "date"}),
            on="date",
            how="left",
            validate="one_to_one",
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = DualTrendFuturesV2.populate_entry_trend(self, dataframe, metadata)
        pair = metadata["pair"]
        if pair not in self.swing_pairs:
            dataframe["enter_long"] = 0
            dataframe["enter_short"] = 0
            dataframe["enter_tag"] = None

        swing_long = dataframe["enter_long"].fillna(0).eq(1)
        swing_short = dataframe["enter_short"].fillna(0).eq(1)
        swing_signal = swing_long | swing_short
        swing_tag = dataframe["enter_tag"].astype("string")
        dataframe.loc[swing_long, "enter_tag"] = "swing_" + swing_tag[swing_long]
        dataframe.loc[swing_short, "enter_tag"] = "swing_" + swing_tag[swing_short]

        ready = (dataframe["volume"] > 0) & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
        leader = dataframe["cross_rank"] > (dataframe["rank_count"] - self.top_n)
        cross_entry = ready & leader & ~swing_signal
        dataframe.loc[cross_entry, ["enter_long", "enter_tag"]] = (
            1,
            "xsmom_top2_180_8h_long",
        )
        dataframe.loc[cross_entry, "enter_short"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Preserve the swing exit calculation in the analyzed frame.  Global
        # exit signals are disabled so they cannot close cross-sectional trades.
        return DualTrendFuturesV2.populate_exit_trend(self, dataframe, metadata)

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        tag = str(trade.enter_tag or "")
        if tag.startswith("xsmom_"):
            if current_time - trade.open_date_utc >= timedelta(hours=self.hold_hours):
                return "xsmom_fixed_8h_rebalance"
            return None
        if not tag.startswith("swing_"):
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
            last = dataframe.iloc[-1]
            column = "exit_short" if trade.is_short else "exit_long"
            if int(last.get(column, 0) or 0) == 1:
                return "swing_" + str(last.get("exit_tag") or "signal_exit")
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
        return None

    def custom_stake_amount(self, *args, side: str, **kwargs) -> float:
        stake = super().custom_stake_amount(*args, side=side, **kwargs)
        return stake * 0.50 if side == "short" else stake

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return 1.0
