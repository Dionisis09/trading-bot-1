"""Pre-declared, offline-only cost-robust variants of DualTrendFuturesV2R.

These classes are research candidates.  They are intentionally kept outside
the active dry-run configuration so a backtest cannot silently change the
forward comparison that is already collecting data.
"""

from pandas import DataFrame

from technical import qtpylib

from DualTrendFuturesRisk import AtrExposureRiskMixin
from DualTrendFuturesV2 import DualTrendFuturesV2


class CostRobustResearchBase(AtrExposureRiskMixin, DualTrendFuturesV2):
    """V2R with a small set of fixed, direction-symmetric entry filters."""

    research_roc_threshold = 0.0
    research_ema_separation = 0.0
    research_min_atr_pct = 0.005
    research_breakout_period = 30

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        if self.research_breakout_period != 30:
            period = self.research_breakout_period
            dataframe["research_entry_high"] = dataframe["high"].rolling(period).max().shift(1)
            dataframe["research_entry_low"] = dataframe["low"].rolling(period).min().shift(1)
        else:
            dataframe["research_entry_high"] = dataframe["entry_high"]
            dataframe["research_entry_low"] = dataframe["entry_low"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close_1d = dataframe["close_1d"]
        long_ema_separation = (dataframe["ema20_1d"] - dataframe["ema50_1d"]) / close_1d
        short_ema_separation = (dataframe["ema50_1d"] - dataframe["ema20_1d"]) / close_1d
        common = (
            (dataframe["adx"] > 20.0)
            & (dataframe["atr_pct"] > self.research_min_atr_pct)
            & (dataframe["atr_pct"] < 0.12)
            & (dataframe["volume"] > 0)
        )
        long_condition = (
            common
            & (dataframe["long_confluence_score"] >= 3)
            & (dataframe["close_1d"] > dataframe["ema200_1d"])
            & (dataframe["ema20_1d"] > dataframe["ema50_1d"])
            & (dataframe["ema50_1d"] > dataframe["ema200_1d"])
            & (dataframe["roc63_1d"] > self.research_roc_threshold)
            & (long_ema_separation >= self.research_ema_separation)
            & (dataframe["rsi"] > 52.0)
            & (dataframe["rsi"] < 82.0)
            & qtpylib.crossed_above(dataframe["close"], dataframe["research_entry_high"])
        )
        short_condition = (
            common
            & (dataframe["short_confluence_score"] >= 3)
            & (dataframe["close_1d"] < dataframe["ema200_1d"])
            & (dataframe["ema20_1d"] < dataframe["ema50_1d"])
            & (dataframe["ema50_1d"] < dataframe["ema200_1d"])
            & (dataframe["roc63_1d"] < -self.research_roc_threshold)
            & (short_ema_separation >= self.research_ema_separation)
            & (dataframe["rsi"] > 18.0)
            & (dataframe["rsi"] < 48.0)
            & qtpylib.crossed_below(dataframe["close"], dataframe["research_entry_low"])
        )
        tag = (
            f"cost_research_roc{self.research_roc_threshold:g}_"
            f"ema{self.research_ema_separation:g}_atr{self.research_min_atr_pct:g}_"
            f"breakout{self.research_breakout_period}"
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = 1, f"long_{tag}"
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = 1, f"short_{tag}"
        return dataframe


class CostRobustRoc5(CostRobustResearchBase):
    research_roc_threshold = 5.0


class CostRobustRoc10(CostRobustResearchBase):
    research_roc_threshold = 10.0


class CostRobustEma1(CostRobustResearchBase):
    research_ema_separation = 0.01


class CostRobustAtr1(CostRobustResearchBase):
    research_min_atr_pct = 0.01


class CostRobustBreakout50(CostRobustResearchBase):
    research_breakout_period = 50


class CostRobustRoc5Ema1(CostRobustResearchBase):
    research_roc_threshold = 5.0
    research_ema_separation = 0.01
