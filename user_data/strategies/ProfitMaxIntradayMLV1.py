"""Causal FreqAI veto over the fixed ProfitMax short-breakdown stream."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from ProfitMaxIntradayV2 import ProfitMaxIntradayShortBase15m


class ProfitMaxIntradayMLV1(ProfitMaxIntradayShortBase15m):
    target_column = "&-short_net_log_return_4h"
    target_horizon_candles = 16
    target_roundtrip_fee = 0.0015
    FEATURE_COLUMNS = (
        "%-ret_15m_1",
        "%-ret_15m_4",
        "%-ret_15m_16",
        "%-ema_gap_atr_15m",
        "%-channel_position_prev32",
        "%-breakdown_distance_atr",
        "%-rsi14_15m",
        "%-adx14_15m",
        "%-log_volume_vs_prev20_median",
        "%-atr_close_15m",
        "%-realized_vol_24h",
        "%-ema_gap_atr_1h",
        "%-adx14_1h",
        "%-momentum24_1h",
        "%-ema_gap_atr_4h",
    )

    @classmethod
    def _prepare_ml_frame(cls, dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        close = pd.to_numeric(frame["close"], errors="coerce")
        log_close = np.log(close.where(close > 0.0))
        frame["ml_ret_1"] = log_close.diff(1)
        frame["ml_ret_4"] = log_close.diff(4)
        frame["ml_ret_16"] = log_close.diff(16)
        frame["ml_ema_gap_atr"] = cls._finite_divide(frame["ema20"] - frame["ema50"], frame["atr14"])
        frame["ml_channel_position"] = cls._finite_divide(
            close - frame["channel_low_prev32"],
            frame["channel_high_prev32"] - frame["channel_low_prev32"],
        )
        frame["ml_breakdown_distance_atr"] = cls._finite_divide(frame["channel_low_prev32"] - close, frame["atr14"])
        frame["ml_volume_log_ratio"] = np.log(
            cls._finite_divide(frame["volume"], frame["volume_median_prev20"]).where(lambda value: value > 0.0)
        )
        frame["ml_atr_close"] = cls._finite_divide(frame["atr14"], close)
        frame["ml_realized_vol_24h"] = np.sqrt(frame["ml_ret_1"].pow(2).rolling(96, min_periods=96).sum())
        frame["candidate_short"] = cls._short_entry(frame).fillna(False)
        return frame

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs: Any) -> DataFrame:
        return dataframe

    def feature_engineering_expand_basic(self, dataframe: DataFrame, metadata: dict, **kwargs: Any) -> DataFrame:
        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict, **kwargs: Any) -> DataFrame:
        frame = self._prepare_ml_frame(dataframe)
        frame["%-ret_15m_1"] = frame["ml_ret_1"]
        frame["%-ret_15m_4"] = frame["ml_ret_4"]
        frame["%-ret_15m_16"] = frame["ml_ret_16"]
        frame["%-ema_gap_atr_15m"] = frame["ml_ema_gap_atr"]
        frame["%-channel_position_prev32"] = frame["ml_channel_position"]
        frame["%-breakdown_distance_atr"] = frame["ml_breakdown_distance_atr"]
        frame["%-rsi14_15m"] = frame["rsi14"]
        frame["%-adx14_15m"] = frame["adx14"]
        frame["%-log_volume_vs_prev20_median"] = frame["ml_volume_log_ratio"]
        frame["%-atr_close_15m"] = frame["ml_atr_close"]
        frame["%-realized_vol_24h"] = frame["ml_realized_vol_24h"]
        frame["%-ema_gap_atr_1h"] = frame["ema_gap_atr_1h"]
        frame["%-adx14_1h"] = frame["adx14_1h"]
        frame["%-momentum24_1h"] = frame["momentum24_1h"]
        frame["%-ema_gap_atr_4h"] = frame["ema_gap_atr_4h"]
        return frame

    @classmethod
    def _target(cls, dataframe: DataFrame) -> Series:
        entry = pd.to_numeric(dataframe["open"], errors="coerce").shift(-1)
        exit_rate = pd.to_numeric(dataframe["open"], errors="coerce").shift(-(cls.target_horizon_candles + 1))
        ratio = cls._finite_divide(exit_rate, entry)
        return -np.log(ratio.where(ratio > 0.0)) - cls.target_roundtrip_fee

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs: Any) -> DataFrame:
        frame = self._prepare_ml_frame(dataframe)
        frame[self.target_column] = self._target(frame)
        return frame

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        prepared = self._prepare_ml_frame(super().populate_indicators(dataframe, metadata))
        freqai = getattr(self, "freqai", None)
        if freqai is None:
            prepared[self.target_column] = np.nan
            prepared["do_predict"] = 0
            return prepared
        result = freqai.start(prepared, metadata, self)
        for column in prepared.columns:
            if column not in result:
                result[column] = prepared[column]
        if self.target_column not in result:
            result[self.target_column] = np.nan
        if "do_predict" not in result:
            result["do_predict"] = 0
        return result

    @classmethod
    def _prediction_gate(cls, dataframe: DataFrame) -> Series:
        if cls.target_column not in dataframe or "do_predict" not in dataframe:
            return pd.Series(False, index=dataframe.index, dtype=bool)
        prediction = pd.to_numeric(dataframe[cls.target_column], errors="coerce")
        allowed = pd.to_numeric(dataframe["do_predict"], errors="coerce") == 1
        return allowed & np.isfinite(prediction) & (prediction > 0.0)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        self._initialize_entries(frame)
        candidate = frame.get("candidate_short", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
        accepted = candidate & self._prediction_gate(frame)
        frame.loc[accepted, ["enter_short", "enter_tag"]] = (1, "ml_veto_short_breakout")
        return frame
