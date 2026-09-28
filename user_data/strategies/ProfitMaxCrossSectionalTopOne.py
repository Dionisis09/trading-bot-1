"""Frozen single-leader 30-day momentum holding-period candidates."""

from ProfitMaxCrossSectionalLong import _CrossSectionalTopTwoLong


class _CrossSectionalTopOne(_CrossSectionalTopTwoLong):
    top_n = 1
    momentum_candles = 180


class ProfitMaxCrossSectionalTopOne24h(_CrossSectionalTopOne):
    hold_hours = 24


class ProfitMaxCrossSectionalTopOne16h(_CrossSectionalTopOne):
    hold_hours = 16


class ProfitMaxCrossSectionalTopOne12h(_CrossSectionalTopOne):
    hold_hours = 12
