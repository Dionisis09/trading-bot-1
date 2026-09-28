"""Cycle 3 portfolio-capacity and protection-isolation ensemble candidates."""

from datetime import datetime

from freqtrade.persistence import Trade

from ProfitMaxEnsembleCrossSwing import ProfitMaxEnsembleCrossSwingV1


class _ProfitMaxEnsembleCrossSwingV3Base(ProfitMaxEnsembleCrossSwingV1):
    use_exit_signal = True
    cross_foreign_exit_reasons = frozenset(
        {
            "exit_signal",
            "long_channel_daily_or_confluence_failure",
            "short_channel_daily_or_confluence_failure",
        }
    )

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        tag = str(trade.enter_tag or "")
        if tag.startswith("xsmom_") and exit_reason in self.cross_foreign_exit_reasons:
            return False
        return True


class ProfitMaxEnsembleCrossSwingV3Global(_ProfitMaxEnsembleCrossSwingV3Base):
    """Four-slot ensemble retaining the original global protection contract."""


class ProfitMaxEnsembleCrossSwingV3PairGuard(_ProfitMaxEnsembleCrossSwingV3Base):
    """Four-slot ensemble with stop-loss bursts isolated by pair."""

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 42,
                "trade_limit": 3,
                "stop_duration_candles": 12,
                "only_per_pair": True,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 180,
                "trade_limit": 10,
                "stop_duration_candles": 18,
                "max_allowed_drawdown": 0.15,
            },
        ]
