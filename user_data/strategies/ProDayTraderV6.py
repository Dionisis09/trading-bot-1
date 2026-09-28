"""Trend-only 5m challenger with setup-specific causal exits."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pandas import DataFrame

from ProDayTraderV5 import ProDayTraderV5


class ProDayTraderV6(ProDayTraderV5):
    """Keep the T1 trend engine isolated from mean-reversion exit semantics."""

    startup_candle_count = 2399

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        type(self)._ensure_columns(frame, ["candidate_T1_long", "candidate_T1_short"])
        long_signal = frame["candidate_T1_long"].fillna(False).astype(bool)
        short_signal = frame["candidate_T1_short"].fillna(False).astype(bool)
        frame["enter_long"] = 0
        frame["enter_short"] = 0
        frame["enter_tag"] = ""
        frame.loc[long_signal, ["enter_long", "enter_tag"]] = (1, "T1_long")
        frame.loc[short_signal & ~long_signal, ["enter_short", "enter_tag"]] = (1, "T1_short")
        return frame

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        type(self)._ensure_columns(frame, ["t1_exit_long_15m", "t1_exit_short_15m"])
        frame["exit_long"] = frame["t1_exit_long_15m"].fillna(False).astype(bool).astype("int8")
        frame["exit_short"] = frame["t1_exit_short_15m"].fillna(False).astype(bool).astype("int8")
        frame["exit_tag"] = "T1_15m_ema_cross"
        return frame

    def custom_exit(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | None:
        """Use only a 12-hour fail-safe; setup exits remain vectorized and causal."""

        opened = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if not isinstance(opened, datetime):
            return None
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        now = current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
        age_minutes = (now.astimezone(timezone.utc) - opened.astimezone(timezone.utc)).total_seconds() / 60.0
        return "T1_time_stop_720m" if age_minutes >= 720.0 else None

