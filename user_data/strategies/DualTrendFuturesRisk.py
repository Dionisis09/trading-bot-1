"""Locked ATR/exposure overlay applied to V1 and V2 for matched-risk testing."""

from datetime import datetime
import math

from DualTrendFuturesV1 import DualTrendFuturesV1
from DualTrendFuturesV2 import DualTrendFuturesV2


class AtrExposureRiskMixin:
    """Reduce proposed stake using a fixed exposure and ATR-volatility budget."""

    risk_exposure_fraction = 0.65
    target_atr_pct = 0.03
    minimum_volatility_scalar = 0.50
    maximum_volatility_scalar = 1.00

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        conservative_stake = (
            proposed_stake
            * self.risk_exposure_fraction
            * self.minimum_volatility_scalar
        )

        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(
                pair=pair,
                timeframe=self.timeframe,
            )
            atr_pct = float(dataframe.iloc[-1]["atr_pct"])
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return conservative_stake

        if not math.isfinite(atr_pct) or atr_pct <= 0:
            return conservative_stake

        volatility_scalar = self.target_atr_pct / atr_pct
        volatility_scalar = max(
            self.minimum_volatility_scalar,
            min(self.maximum_volatility_scalar, volatility_scalar),
        )
        return proposed_stake * self.risk_exposure_fraction * volatility_scalar


class DualTrendFuturesV1R(AtrExposureRiskMixin, DualTrendFuturesV1):
    """V1 signals with the locked matched-risk overlay (control)."""


class DualTrendFuturesV2R(AtrExposureRiskMixin, DualTrendFuturesV2):
    """V2 signals with the locked matched-risk overlay (challenger)."""
