from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxIntradayMLV1 import ProfitMaxIntradayMLV1  # noqa: E402
from ProfitMaxIntradayMLV2 import ProfitMaxIntradayMLV2  # noqa: E402


class ProfitMaxIntradayMLV2Tests(unittest.TestCase):
    def test_model_schema_and_target_are_unchanged(self) -> None:
        self.assertEqual(ProfitMaxIntradayMLV2.FEATURE_COLUMNS, ProfitMaxIntradayMLV1.FEATURE_COLUMNS)
        self.assertEqual(ProfitMaxIntradayMLV2.target_column, ProfitMaxIntradayMLV1.target_column)
        self.assertEqual(ProfitMaxIntradayMLV2.target_horizon_candles, 16)
        self.assertEqual(ProfitMaxIntradayMLV2.target_roundtrip_fee, 0.0015)

    def test_fixed_threshold_is_fail_closed_and_veto_only(self) -> None:
        threshold = ProfitMaxIntradayMLV2.prediction_threshold
        frame = pd.DataFrame({
            "candidate_short": [True, True, True, True, False],
            "do_predict": [1, 1, 0, 1, 1],
            ProfitMaxIntradayMLV2.target_column: [threshold + 1e-7, threshold, 1.0, np.nan, 1.0],
        })
        result = ProfitMaxIntradayMLV2({}).populate_entry_trend(frame, {})
        self.assertEqual(result["enter_short"].tolist(), [1, 0, 0, 0, 0])
        self.assertEqual(result["enter_long"].sum(), 0)

    def test_config_locks_fee_threshold_and_model_isolation(self) -> None:
        config = json.loads((ROOT / "user_data/config-profit-max-intraday-ml-ensemble-cycle2.json").read_text())
        meta = config["profit_max_intraday_research"]
        self.assertEqual(meta["prediction_threshold"], ProfitMaxIntradayMLV2.prediction_threshold)
        self.assertEqual(meta["target_roundtrip_fee"], 0.0015)
        self.assertEqual(config["freqai"]["purge_old_models"], 0)
        self.assertEqual(config["freqai"]["identifier"], "profit-max-intraday-ml-ensemble-cycle2-20260817")
        self.assertFalse(meta["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()
