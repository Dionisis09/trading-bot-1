from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxIntradayV2 import (  # noqa: E402
    ProfitMaxIntradayAsymmetric15m,
    ProfitMaxIntradayShortBase15m,
    ProfitMaxIntradayShortTight15m,
)


class ProfitMaxIntradayV2Tests(unittest.TestCase):
    def test_exact_three_candidates_and_fixed_risk(self) -> None:
        self.assertEqual(ProfitMaxIntradayShortTight15m.stoploss, -0.012)
        self.assertEqual(ProfitMaxIntradayShortBase15m.stoploss, -0.018)
        self.assertEqual(ProfitMaxIntradayAsymmetric15m.stoploss, -0.015)
        for candidate in (
            ProfitMaxIntradayShortTight15m,
            ProfitMaxIntradayShortBase15m,
            ProfitMaxIntradayAsymmetric15m,
        ):
            self.assertEqual(candidate.timeframe, "15m")
            self.assertEqual(len(candidate.research_pairs), 6)

    def test_short_candidates_do_not_create_long_entries(self) -> None:
        source = (ROOT / "user_data/strategies/ProfitMaxIntradayV2.py").read_text(encoding="utf-8")
        tight = source.split("class ProfitMaxIntradayShortTight15m", 1)[1].split(
            "class ProfitMaxIntradayShortBase15m", 1
        )[0]
        self.assertNotIn('enter_long"] =', tight)
        self.assertIn('enter_short", "enter_tag"]', tight)

    def test_asymmetric_strength_is_not_train_derived(self) -> None:
        source = (ROOT / "user_data/strategies/ProfitMaxIntradayV2.py").read_text(encoding="utf-8")
        self.assertIn('frame["ema_gap_atr_4h"] >= 0.70', source)
        self.assertIn('0.15 * frame["atr14"]', source)
        self.assertIn('1.5 * pd.to_numeric', source)


if __name__ == "__main__":
    unittest.main()
