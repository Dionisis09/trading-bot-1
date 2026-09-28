"""Causal cross-sectional momentum candidates over a frozen universe."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from pandas import DataFrame
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

from DualTrendFuturesRisk import AtrExposureRiskMixin
from ProfessionalRisk import ProfessionalRiskMixin


class _CrossSectionalBase(AtrExposureRiskMixin, ProfessionalRiskMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "4h"
    process_only_new_candles = True
    startup_candle_count = 1300
    minimal_roi = {"0": 100.0}
    stoploss = -0.08
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    momentum_candles = 42
    regime_gated = False
    hold_hours = 24
    minimum_ranked_pairs = 35
    _rank_cache: DataFrame | None = None

    order_types = {"entry": "limit", "exit": "limit", "stoploss": "market", "stoploss_on_exchange": False}
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {"method": "StoplossGuard", "lookback_period_candles": 42, "trade_limit": 3,
             "stop_duration_candles": 12, "only_per_pair": False},
            {"method": "MaxDrawdown", "lookback_period_candles": 180, "trade_limit": 10,
             "stop_duration_candles": 18, "max_allowed_drawdown": 0.15},
        ]

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
        closes = pd.concat(series, axis=1).sort_index()
        momentum = closes / closes.shift(self.momentum_candles) - 1.0
        counts = momentum.notna().sum(axis=1)
        ordinal = momentum.rank(axis=1, method="first", ascending=True, na_option="keep")
        btc = closes["BTC/USDT:USDT"]
        btc_ema_200d = btc.ewm(span=1200, adjust=False, min_periods=1200).mean()
        cache = pd.DataFrame(index=closes.index)
        cache["rank_count"] = counts
        cache["btc_bull"] = btc > btc_ema_200d
        for pair in pairs:
            cache[f"rank::{pair}"] = ordinal[pair]
        self._rank_cache = cache
        return cache

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        cache = self._build_rank_cache()
        rank = cache.loc[:, ["rank_count", "btc_bull", f"rank::{metadata['pair']}"]].rename(
            columns={f"rank::{metadata['pair']}": "cross_rank"}
        )
        merged = dataframe.copy()
        merged["date"] = pd.to_datetime(merged["date"], utc=True)
        merged = merged.merge(rank.reset_index().rename(columns={"index": "date"}), on="date", how="left", validate="one_to_one")
        return merged

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ready = (dataframe["volume"] > 0) & (dataframe["rank_count"] >= self.minimum_ranked_pairs)
        strongest = dataframe["cross_rank"] == dataframe["rank_count"]
        weakest = dataframe["cross_rank"] == 1.0
        if self.regime_gated:
            long = ready & strongest & dataframe["btc_bull"].fillna(False)
            short = ready & weakest & ~dataframe["btc_bull"].fillna(False)
        else:
            long = ready & strongest
            short = ready & weakest
        dataframe.loc[long, ["enter_long", "enter_tag"]] = (1, f"xsmom_{self.momentum_candles}_long")
        dataframe.loc[short, ["enter_short", "enter_tag"]] = (1, f"xsmom_{self.momentum_candles}_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs) -> str | None:
        opened = trade.open_date_utc
        if current_time - opened >= timedelta(hours=self.hold_hours):
            return "fixed_24h_rebalance"
        return None

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        return 1.0


class ProfitMaxCrossSectional7dNeutral(_CrossSectionalBase):
    momentum_candles = 42


class ProfitMaxCrossSectional30dNeutral(_CrossSectionalBase):
    momentum_candles = 180


class ProfitMaxCrossSectional7dRegime(_CrossSectionalBase):
    momentum_candles = 42
    regime_gated = True
