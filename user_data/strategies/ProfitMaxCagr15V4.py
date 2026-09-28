"""Cycle 4 adapter so the existing guard measures leveraged margin correctly."""

from datetime import datetime
from typing import Any

from ProfitMaxCagr15V3 import ProfitMaxCagr15V3


class ProfitMaxCagr15V4(ProfitMaxCagr15V3):
    """Cycle 3 candidate with leverage supplied to the inherited risk guard."""

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> bool:
        kwargs["leverage"] = self.fixed_research_leverage
        return super().confirm_trade_entry(
            pair=pair,
            order_type=order_type,
            amount=amount,
            rate=rate,
            time_in_force=time_in_force,
            current_time=current_time,
            entry_tag=entry_tag,
            side=side,
            **kwargs,
        )

