"""Conservative matched-risk variant of DualTrendFuturesV2R.

This strategy keeps the same entry and exit signal logic as DualTrendFuturesV2R,
while applying a slightly more disciplined ATR-based exposure profile.
No new signal rules, exits, leverage, or stoploss behavior are introduced.
"""

from DualTrendFuturesRisk import DualTrendFuturesV2R


class DualTrendFuturesV4R(DualTrendFuturesV2R):
    """V2R signals with a conservative ATR exposure profile."""

    # Retain the same core signals and risk protections as V2R.
    # This is intentionally a sizing variant only.
    risk_exposure_fraction = 0.60
    target_atr_pct = 0.025
    minimum_volatility_scalar = 0.60
    maximum_volatility_scalar = 0.90

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """Use the inherited ATR exposure sizing with narrower volatility bounds."""
        return super().custom_stake_amount(
            pair=pair,
            current_time=current_time,
            current_rate=current_rate,
            proposed_stake=proposed_stake,
            min_stake=min_stake,
            max_stake=max_stake,
            leverage=leverage,
            entry_tag=entry_tag,
            side=side,
            **kwargs,
        )
