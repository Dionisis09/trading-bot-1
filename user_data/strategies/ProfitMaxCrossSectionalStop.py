"""Bounded stop-loss variants over the frozen top-two 30-day/8h momentum signal."""

from ProfitMaxCrossSectionalShortHorizon import ProfitMaxCrossSectionalTopTwo8h


class ProfitMaxCrossTopTwo8hStop2(ProfitMaxCrossSectionalTopTwo8h):
    stoploss = -0.02


class ProfitMaxCrossTopTwo8hStop4(ProfitMaxCrossSectionalTopTwo8h):
    stoploss = -0.04


class ProfitMaxCrossTopTwo8hStop6(ProfitMaxCrossSectionalTopTwo8h):
    stoploss = -0.06
