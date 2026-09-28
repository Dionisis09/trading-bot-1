from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxIntradayMLV1 import ProfitMaxIntradayMLV1  # noqa: E402


class ProfitMaxIntradayMLV1Tests(unittest.TestCase):
    def test_locked_schema_and_target(self) -> None:
        self.assertEqual(len(ProfitMaxIntradayMLV1.FEATURE_COLUMNS), 15)
        self.assertEqual(ProfitMaxIntradayMLV1.target_horizon_candles, 16)
        self.assertEqual(ProfitMaxIntradayMLV1.target_roundtrip_fee, 0.0015)

    def test_target_uses_next_and_seventeenth_open(self) -> None:
        opens = np.full(20, 100.0)
        opens[1] = 100.0
        opens[17] = 98.0
        frame = pd.DataFrame({"open": opens})
        target = ProfitMaxIntradayMLV1._target(frame)
        self.assertAlmostEqual(target.iloc[0], -np.log(0.98) - 0.0015, places=12)
        self.assertTrue(target.iloc[-17:].isna().all())

    def test_prediction_is_fail_closed_and_veto_only(self) -> None:
        frame = pd.DataFrame({
            "candidate_short": [True, True, True, False],
            "do_predict": [1, 1, 0, 1],
            ProfitMaxIntradayMLV1.target_column: [0.001, -0.001, 0.01, 0.01],
        })
        strategy = ProfitMaxIntradayMLV1({})
        result = strategy.populate_entry_trend(frame, {})
        self.assertEqual(result["enter_short"].tolist(), [1, 0, 0, 0])
        self.assertEqual(result["enter_long"].sum(), 0)


if __name__ == "__main__":
    unittest.main()
