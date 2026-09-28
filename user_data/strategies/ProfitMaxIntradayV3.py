"""Cycle-3 fee-aware exit repair candidates, frozen before PnL."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freqtrade.strategy import stoploss_from_open

from ProfitMaxIntradayV2 import ProfitMaxIntradayShortBase15m


class ProfitMaxIntradayShortProfitOnly15m(ProfitMaxIntradayShortBase15m):
    exit_profit_only = True
    exit_profit_offset = 0.0015


class _BreakEvenMixin:
    use_custom_stoploss = True

    def custom_stoploss(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs: Any,
    ) -> float | None:
        if after_fill or current_profit < 0.01:
            return None
        return stoploss_from_open(
            0.0025,
            current_profit,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )


class ProfitMaxIntradayShortBreakEven15m(_BreakEvenMixin, ProfitMaxIntradayShortBase15m):
    pass


class ProfitMaxIntradayShortProfitOnlyBreakEven15m(
    _BreakEvenMixin,
    ProfitMaxIntradayShortProfitOnly15m,
):
    pass
