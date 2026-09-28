"""Deterministic 5m challenger with a live-feasible 4h EMA20/EMA50 regime."""

from __future__ import annotations

import talib.abstract as ta
from pandas import DataFrame

from ProDayTraderV3 import ProDayTraderV3


class ProDayTraderV4(ProDayTraderV3):
    """T1/R1 engine using a convergent 4h medium-term trend guard."""

    startup_candle_count = 2399

    @classmethod
    def _informative_indicators(
        cls, dataframe: DataFrame, informative_timeframe: str
    ) -> DataFrame:
        if informative_timeframe != "4h":
            return super()._informative_indicators(dataframe, informative_timeframe)

        frame = dataframe.copy()
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["ema50"] = ta.EMA(frame, timeperiod=50)
        frame["atr14"] = ta.ATR(frame, timeperiod=14)
        frame["trend_gap_atr"] = cls._finite_divide(
            frame["ema20"] - frame["ema50"], frame["atr14"]
        )
        frame["trend_long"] = (frame["ema20"] > frame["ema50"]) & (
            frame["ema50"] > frame["ema50"].shift(3)
        )
        frame["trend_short"] = (frame["ema20"] < frame["ema50"]) & (
            frame["ema50"] < frame["ema50"].shift(3)
        )
        return frame[
            [
                "date",
                "ema20",
                "ema50",
                "atr14",
                "trend_gap_atr",
                "trend_long",
                "trend_short",
            ]
        ]
