"""Final frozen top-three 30-day leader candidate."""

from ProfitMaxCrossSectionalLong import _CrossSectionalTopTwoLong


class ProfitMaxCrossSectionalTopThree8h(_CrossSectionalTopTwoLong):
    momentum_candles = 180
    hold_hours = 8
    top_n = 3
