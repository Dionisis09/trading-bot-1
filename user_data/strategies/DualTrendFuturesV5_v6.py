"""V5 candidate: small exposure tuning to attempt to improve over V2R.

This file defines a minimal variant on `DualTrendFuturesV2R` that tweaks the
ATR exposure parameters. Keep changes small so we can iterate quickly.
"""

from DualTrendFuturesRisk import AtrExposureRiskMixin
from DualTrendFuturesV2 import DualTrendFuturesV2


class DualTrendFuturesV5_v6(AtrExposureRiskMixin, DualTrendFuturesV2):
    """V5: tuned exposure parameters aiming to beat V2R."""

    # slightly adjust exposure to be modestly more selective than V2R
    risk_exposure_fraction = 0.7
    # target a slightly lower ATR budget to avoid oversized stakes in quiet markets
    target_atr_pct = 0.026
    # allow a bit wider scaling range to adapt to volatility regimes
    minimum_volatility_scalar = 0.45
    maximum_volatility_scalar = 1.08
