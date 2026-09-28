"""Research-only 3.5x version of the qualified long swing sleeve."""

from pathlib import Path

from ProfitMaxCagr15V5 import ProfitMaxCagr15V5


class ProfitMaxCagr20V1(ProfitMaxCagr15V5):
    """Keep the underlying 10% price stop while testing fixed 3.5x leverage."""

    fixed_research_leverage = 3.5
    stoploss = -0.35

    def _risk_policy_path(self) -> Path:
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        return user_data_dir / "risk_policy_profit_max_cagr20_v1.json"
