"""Capital-scaled, frequency-agnostic CAGR challenger.

The class deliberately inherits the frozen ProfitMaxV5Asymmetric50 trading logic
unchanged. Cycle 1 changes only the externally configured stake allocation.
"""

from ProfitMaxSwingV5 import ProfitMaxV5Asymmetric50


class ProfitMaxCagr15V1(ProfitMaxV5Asymmetric50):
    """Frozen V5 signals with Cycle 1 risk allocation supplied by config."""

