"""Research-only 3.76x refinement of the qualified long swing sleeve."""

from pathlib import Path

from ProfitMaxCagr20V1 import ProfitMaxCagr20V1


class ProfitMaxCagr20V2(ProfitMaxCagr20V1):
    """Preserve the approximate 10% underlying stop at fixed 3.76x leverage."""

    fixed_research_leverage = 3.76
    stoploss = -0.376

    def _risk_policy_path(self) -> Path:
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        return user_data_dir / "risk_policy_profit_max_cagr20_v2.json"
