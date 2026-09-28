"""Fixed 2.5x, long-only CAGR15 Cycle 3 research candidate."""

from datetime import datetime

from ProfitMaxCagr15V2 import ProfitMaxCagr15V2


class ProfitMaxCagr15V3(ProfitMaxCagr15V2):
    """Cycle 2 logic with fixed research-only leverage."""

    fixed_research_leverage = 2.5

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
        return min(self.fixed_research_leverage, float(max_leverage))

