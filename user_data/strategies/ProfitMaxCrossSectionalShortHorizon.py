"""Frozen adjacent short holding horizons for 30-day leader momentum."""

from ProfitMaxCrossSectionalLong import _CrossSectionalTopTwoLong
from ProfitMaxCrossSectionalTopOne import _CrossSectionalTopOne


class ProfitMaxCrossSectionalTopOne8h(_CrossSectionalTopOne):
    hold_hours = 8


class ProfitMaxCrossSectionalTopOne4h(_CrossSectionalTopOne):
    hold_hours = 4


class ProfitMaxCrossSectionalTopTwo8h(_CrossSectionalTopTwoLong):
    momentum_candles = 180
    hold_hours = 8
    top_n = 2
