"""Causal deterministic 5m challenger with vectorized exits and fixed-risk sizing."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pandas import DataFrame

from ProDayTraderV4 import ProDayTraderV4


class ProDayTraderV5(ProDayTraderV4):
    """V4 entries with callback-independent execution decisions."""

    startup_candle_count = 2399

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        type(self)._ensure_columns(
            frame,
            ["r1_exit_long", "r1_exit_short", "t1_exit_long_15m", "t1_exit_short_15m"],
        )
        frame["exit_long"] = (
            frame["r1_exit_long"].fillna(False).astype(bool)
            | frame["t1_exit_long_15m"].fillna(False).astype(bool)
        ).astype("int8")
        frame["exit_short"] = (
            frame["r1_exit_short"].fillna(False).astype(bool)
            | frame["t1_exit_short_15m"].fillna(False).astype(bool)
        ).astype("int8")
        frame["exit_tag"] = "causal_setup_exit"
        return frame

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        """Risk 0.25% of wallet against the frozen 4% emergency stop."""

        try:
            wallet = float(self.wallets.get_total_stake_amount())
            values = (wallet, proposed_stake, max_stake, current_rate, leverage)
            if any(not math.isfinite(value) or value <= 0.0 for value in values):
                return 0.0
            stop_fraction = abs(float(self.stoploss))
            risk_sized = wallet * self.risk_per_trade_fraction / stop_fraction
            exposure_cap = wallet * self.maximum_single_trade_stake_fraction
            stake = min(proposed_stake, max_stake, exposure_cap, risk_sized)
            if min_stake is not None:
                minimum = float(min_stake)
                if not math.isfinite(minimum) or minimum <= 0.0 or minimum > stake:
                    return 0.0
            return stake if math.isfinite(stake) and stake > 0.0 else 0.0
        except (AttributeError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            return 0.0

    def custom_exit(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | None:
        """Only causal time/profit exits remain in the callback path."""

        opened = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if not isinstance(opened, datetime):
            return None
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        now = current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
        age_minutes = (now.astimezone(timezone.utc) - opened.astimezone(timezone.utc)).total_seconds() / 60.0
        if age_minutes >= 720.0:
            return "time_stop_720m"
        if age_minutes >= 180.0 and current_profit < 0.0:
            return "stale_loser_180m"
        tag = str(getattr(trade, "enter_tag", "") or "")
        if tag.startswith("R1_") and age_minutes >= 60.0:
            return "R1_time_exit_60m"
        return None
