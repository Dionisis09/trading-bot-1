"""Cycle-2 short-breakdown exit/risk hypotheses, frozen before PnL."""

from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from ProfitMaxIntradayV1 import ProfitMaxIntradayBase15m


class _Cycle2Base(ProfitMaxIntradayBase15m):
    @staticmethod
    def _short_entry(frame: DataFrame) -> pd.Series:
        _, short = ProfitMaxIntradayBase15m._breakout_masks(frame)
        return short

    @staticmethod
    def _fast_exits(frame: DataFrame, allow_long: bool = False) -> DataFrame:
        frame["exit_long"] = (
            ((frame["close"].shift(1) >= frame["ema20"].shift(1)) & (frame["close"] < frame["ema20"]))
            | (frame["ema20_1h"] <= frame["ema50_1h"])
        ).fillna(False).astype("int8") if allow_long else 0
        frame["exit_short"] = (
            ((frame["close"].shift(1) <= frame["ema20"].shift(1)) & (frame["close"] > frame["ema20"]))
            | (frame["ema20_1h"] >= frame["ema50_1h"])
        ).fillna(False).astype("int8")
        frame["exit_tag"] = "intraday_fast_invalidation"
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._fast_exits(dataframe.copy())


class ProfitMaxIntradayShortTight15m(_Cycle2Base):
    can_short = True
    stoploss = -0.012
    minimal_roi = {"0": 0.018, "240": 0.009, "720": 0.003, "1440": 0.0}

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        short = self._short_entry(frame)
        frame.loc[short, ["enter_short", "enter_tag"]] = (1, "cycle2_short_breakout")
        return frame


class ProfitMaxIntradayShortBase15m(ProfitMaxIntradayShortTight15m):
    stoploss = -0.018
    minimal_roi = {"0": 0.024, "240": 0.012, "720": 0.005, "1440": 0.0}


class ProfitMaxIntradayAsymmetric15m(_Cycle2Base):
    can_short = True
    stoploss = -0.015
    minimal_roi = {"0": 0.020, "240": 0.010, "720": 0.004, "1440": 0.0}

    @classmethod
    def _strong_long(cls, frame: DataFrame) -> pd.Series:
        regime_long, _ = cls._shared_regime(frame)
        volume = pd.to_numeric(frame["volume"], errors="coerce") > 1.5 * pd.to_numeric(
            frame["volume_median_prev20"], errors="coerce"
        )
        return (
            regime_long
            & (frame["ema_gap_atr_4h"] >= 0.70)
            & (frame["close"] >= frame["channel_high_prev32"] + 0.15 * frame["atr14"])
            & volume
        ).fillna(False)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy(); self._initialize_entries(frame)
        long = self._strong_long(frame)
        short = self._short_entry(frame) & ~long
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "cycle2_strong_long")
        frame.loc[short, ["enter_short", "enter_tag"]] = (1, "cycle2_short_breakout")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._fast_exits(dataframe.copy(), allow_long=True)
