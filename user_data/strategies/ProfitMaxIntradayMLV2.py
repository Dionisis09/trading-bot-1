"""Frequency-preserving causal FreqAI veto, frozen for ML ensemble Cycle 2."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from ProfitMaxIntradayMLV1 import ProfitMaxIntradayMLV1


class ProfitMaxIntradayMLV2(ProfitMaxIntradayMLV1):
    """Reuse the frozen model and admit only deterministic candidates above a fixed score."""

    prediction_threshold = -0.0135255

    @classmethod
    def _prediction_gate(cls, dataframe: DataFrame) -> Series:
        if cls.target_column not in dataframe or "do_predict" not in dataframe:
            return pd.Series(False, index=dataframe.index, dtype=bool)
        prediction = pd.to_numeric(dataframe[cls.target_column], errors="coerce")
        allowed = pd.to_numeric(dataframe["do_predict"], errors="coerce") == 1
        return allowed & np.isfinite(prediction) & (prediction > cls.prediction_threshold)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        self._initialize_entries(frame)
        candidate = frame.get("candidate_short", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
        accepted = candidate & self._prediction_gate(frame)
        frame.loc[accepted, ["enter_short", "enter_tag"]] = (1, "ml_v2_frequency_veto_short")
        return frame
