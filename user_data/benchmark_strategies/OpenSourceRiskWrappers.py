"""Risk-only wrappers for the pinned open-source benchmark strategies.

The read-only source checkout is mounted at /freqtrade/vendor.  These wrappers
change no strategy signal, ROI, stoploss, trailing, or hyperopt default.
"""

import sys

sys.path.insert(0, "/freqtrade/vendor")

from Bandtastic import Bandtastic  # noqa: E402
from Supertrend import Supertrend  # noqa: E402
from SwingHighToSky import SwingHighToSky  # noqa: E402


class CommonRiskOverlay:
    """Apply the project's common portfolio protections to a vendor strategy."""

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 24,
                "max_allowed_drawdown": 0.10,
            },
        ]


class BandtasticRisk(CommonRiskOverlay, Bandtastic):
    pass


class SwingHighToSkyRisk(CommonRiskOverlay, SwingHighToSky):
    pass


class SupertrendRisk(CommonRiskOverlay, Supertrend):
    pass

