"""Locked 15m intraday family targeting one to two portfolio trades per day."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from pandas import DataFrame

from ProTournament15m import ProTournamentBase15m


class ProfitMaxIntradayBase15m(ProTournamentBase15m):
    """Shared causal indicators, risk and exact signal masks for Cycle 1."""

    startup_candle_count = 1599
    research_pairs = (
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "BNB/USDT:USDT",
        "XRP/USDT:USDT",
        "ADA/USDT:USDT",
        "DOGE/USDT:USDT",
    )
    stoploss = -0.018
    minimal_roi = {"0": 0.024, "240": 0.012, "720": 0.005, "1440": 0.0}

    @property
    def protections(self) -> list[dict]:
        return [{"method": "CooldownPeriod", "stop_duration_candles": 4}]

    @staticmethod
    def _shared_regime(frame: DataFrame) -> tuple[pd.Series, pd.Series]:
        long = (
            frame["trend_long_4h"].fillna(False).astype(bool)
            & (frame["ema_gap_atr_4h"] >= 0.35)
            & (frame["ema20_1h"] > frame["ema50_1h"])
            & (frame["momentum24_1h"] > 0.0)
            & (frame["adx14_1h"] >= 22.0)
        )
        short = (
            frame["trend_short_4h"].fillna(False).astype(bool)
            & (frame["ema_gap_atr_4h"] <= -0.35)
            & (frame["ema20_1h"] < frame["ema50_1h"])
            & (frame["momentum24_1h"] < 0.0)
            & (frame["adx14_1h"] >= 22.0)
        )
        return long, short

    @classmethod
    def _reclaim_masks(cls, frame: DataFrame) -> tuple[pd.Series, pd.Series]:
        regime_long, regime_short = cls._shared_regime(frame)
        volume = pd.to_numeric(frame["volume"], errors="coerce") > (
            0.9 * pd.to_numeric(frame["volume_median_prev20"], errors="coerce")
        )
        long = (
            regime_long
            & (frame["close"].shift(1) <= frame["ema20"].shift(1))
            & (frame["close"] > frame["ema20"])
            & (frame["rsi14"].shift(1) <= 45.0)
            & (frame["rsi14"] > 45.0)
            & volume
        )
        short = (
            regime_short
            & (frame["close"].shift(1) >= frame["ema20"].shift(1))
            & (frame["close"] < frame["ema20"])
            & (frame["rsi14"].shift(1) >= 55.0)
            & (frame["rsi14"] < 55.0)
            & volume
        )
        return long.fillna(False), short.fillna(False)

    @classmethod
    def _breakout_masks(cls, frame: DataFrame) -> tuple[pd.Series, pd.Series]:
        regime_long, regime_short = cls._shared_regime(frame)
        volume = pd.to_numeric(frame["volume"], errors="coerce") > (
            1.25 * pd.to_numeric(frame["volume_median_prev20"], errors="coerce")
        )
        adx_expanding = frame["adx14_1h"] > frame["adx14_1h"].shift(4)
        long = regime_long & (frame["close"] > frame["channel_high_prev32"]) & adx_expanding & volume
        short = regime_short & (frame["close"] < frame["channel_low_prev32"]) & adx_expanding & volume
        return long.fillna(False), short.fillna(False)

    @staticmethod
    def _common_exits(frame: DataFrame) -> DataFrame:
        long = (
            ((frame["ema20"].shift(1) >= frame["ema50"].shift(1)) & (frame["ema20"] < frame["ema50"]))
            | (frame["ema20_1h"] <= frame["ema50_1h"])
        )
        short = (
            ((frame["ema20"].shift(1) <= frame["ema50"].shift(1)) & (frame["ema20"] > frame["ema50"]))
            | (frame["ema20_1h"] >= frame["ema50_1h"])
        )
        return ProfitMaxIntradayBase15m._initialize_exits(frame, long, short, "intraday_regime_loss")

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._common_exits(dataframe.copy())

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


class ProfitMaxIntradayReclaim15m(ProfitMaxIntradayBase15m):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        self._initialize_entries(frame)
        long, short = self._reclaim_masks(frame)
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "intraday_reclaim_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "intraday_reclaim_short")
        return frame


class ProfitMaxIntradayBreakout15m(ProfitMaxIntradayBase15m):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        self._initialize_entries(frame)
        long, short = self._breakout_masks(frame)
        frame.loc[long, ["enter_long", "enter_tag"]] = (1, "intraday_breakout_long")
        frame.loc[short & ~long, ["enter_short", "enter_tag"]] = (1, "intraday_breakout_short")
        return frame


class ProfitMaxIntradayHybrid15m(ProfitMaxIntradayBase15m):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        self._initialize_entries(frame)
        reclaim_long, reclaim_short = self._reclaim_masks(frame)
        breakout_long, breakout_short = self._breakout_masks(frame)
        long = reclaim_long | breakout_long
        short = (reclaim_short | breakout_short) & ~long
        frame.loc[reclaim_long & ~breakout_long, ["enter_long", "enter_tag"]] = (
            1,
            "intraday_reclaim_long",
        )
        frame.loc[breakout_long, ["enter_long", "enter_tag"]] = (1, "intraday_breakout_long")
        frame.loc[reclaim_short & ~breakout_short & ~long, ["enter_short", "enter_tag"]] = (
            1,
            "intraday_reclaim_short",
        )
        frame.loc[breakout_short & ~long, ["enter_short", "enter_tag"]] = (
            1,
            "intraday_breakout_short",
        )
        return frame
