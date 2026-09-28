"""Cycle 2 execution correction for the frozen cross-swing ensemble."""

from datetime import datetime

from freqtrade.persistence import Trade

from ProfitMaxEnsembleCrossSwing import ProfitMaxEnsembleCrossSwingV1


class ProfitMaxEnsembleCrossSwingV2(ProfitMaxEnsembleCrossSwingV1):
    """Enable callbacks while isolating swing exit signals from 8h leader trades."""

    use_exit_signal = True

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
        if tag.startswith("xsmom_") and exit_reason == "exit_signal":
            return False
        return True
