"""Cycle 5: preserve the 1x strategy's underlying stop distance at fixed 2.5x."""

from pathlib import Path

from ProfitMaxCagr15V4 import ProfitMaxCagr15V4


class ProfitMaxCagr15V5(ProfitMaxCagr15V4):
    """Long-only leveraged candidate under a dedicated fail-closed research policy."""

    stoploss = -0.25

    def _risk_policy_path(self) -> Path:
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        return user_data_dir / "risk_policy_profit_max_cagr15_cycle5.json"

