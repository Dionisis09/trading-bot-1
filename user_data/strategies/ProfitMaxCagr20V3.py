"""Research-only V3 swing adapter with a 3.78x fixed leverage contract."""

from pathlib import Path

from ProfitMaxCagr20V2 import ProfitMaxCagr20V2


class ProfitMaxCagr20V3(ProfitMaxCagr20V2):
    fixed_research_leverage = 3.78
    stoploss = -0.378

    def _risk_policy_path(self) -> Path:
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        return user_data_dir / "risk_policy_profit_max_cagr20_v3.json"
