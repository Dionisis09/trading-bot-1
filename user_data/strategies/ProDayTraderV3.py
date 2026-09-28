"""Deterministic 5m profitability challenger with causal multi-timeframe context."""

from __future__ import annotations

from pandas import DataFrame

from ProDayTraderV2 import ProDayTraderV2


class ProDayTraderV3(ProDayTraderV2):
    """T1 trend plus R1 flat-regime mean reversion, without an ML order gate."""

    startup_candle_count = 399

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # All inherited calculations use completed base/informative candles and
        # shifted channel/volume inputs.  No FreqAI output enters this cycle.
        return self._prepare_signal_frame(dataframe, metadata)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        type(self)._ensure_columns(
            frame,
            [
                "candidate_T1_long",
                "candidate_T1_short",
                "candidate_R1_long",
                "candidate_R1_short",
            ],
        )
        t1_long = frame["candidate_T1_long"].fillna(False).astype(bool)
        t1_short = frame["candidate_T1_short"].fillna(False).astype(bool)
        r1_long = frame["candidate_R1_long"].fillna(False).astype(bool)
        r1_short = frame["candidate_R1_short"].fillna(False).astype(bool)

        frame["enter_long"] = 0
        frame["enter_short"] = 0
        frame["enter_tag"] = ""
        frame.loc[t1_long, ["enter_long", "enter_tag"]] = (1, "T1_long")
        frame.loc[t1_short, ["enter_short", "enter_tag"]] = (1, "T1_short")
        frame.loc[r1_long, ["enter_long", "enter_tag"]] = (1, "R1_long")
        frame.loc[r1_short, ["enter_short", "enter_tag"]] = (1, "R1_short")
        return frame
