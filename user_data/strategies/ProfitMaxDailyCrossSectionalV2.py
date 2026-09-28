"""Bounded stop robustness candidates for the frozen daily-cross alpha."""

from __future__ import annotations

from ProfitMaxDailyCrossSectional import ProfitMaxDailyCrossSectional


class _ProfitMaxDailyCrossV2Base(ProfitMaxDailyCrossSectional):
    @property
    def protections(self):
        return [{"method": "CooldownPeriod", "stop_duration_candles": 1}]


class ProfitMaxDailyCrossStop12(_ProfitMaxDailyCrossV2Base):
    stoploss = -0.12


class ProfitMaxDailyCrossStop16(_ProfitMaxDailyCrossV2Base):
    stoploss = -0.16


class ProfitMaxDailyCrossStop20(_ProfitMaxDailyCrossV2Base):
    stoploss = -0.20

