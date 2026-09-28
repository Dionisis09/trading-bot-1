"""Qualified-signal swing sleeve for the locked ProfitMax20 V4 mix."""

from pathlib import Path

from ProfitMaxCagr20V3 import ProfitMaxCagr20V3


class ProfitMaxCagr20V4(ProfitMaxCagr20V3):
    fixed_research_leverage = 3.64
    stoploss = -0.364

    def _risk_policy_path(self) -> Path:
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        return user_data_dir / "risk_policy_profit_max_cagr20_v4.json"
