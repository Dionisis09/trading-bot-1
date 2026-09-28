"""Minimal V5 alpha refinement after V4 missed severe CAGR by 0.078 points."""

from pathlib import Path

from ProfitMaxCagr20V4 import ProfitMaxCagr20V4


class ProfitMaxCagr20V5(ProfitMaxCagr20V4):
    fixed_research_leverage = 3.66
    stoploss = -0.366

    def _risk_policy_path(self) -> Path:
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        return user_data_dir / "risk_policy_profit_max_cagr20_v5.json"
