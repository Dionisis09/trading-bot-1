from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProRegimeTournament15m import (  # noqa: E402
    ProRegimeBreakout15m, ProRegimeMomentum15m, ProRegimePullback15m, ProRelativeMomentum15m,
)


class ProRegimeTournamentTests(unittest.TestCase):
    def test_four_candidates_are_callback_free_and_15m(self) -> None:
        candidates = [ProRegimeMomentum15m, ProRegimeBreakout15m, ProRegimePullback15m, ProRelativeMomentum15m]
        for candidate in candidates:
            self.assertEqual(candidate.timeframe, "15m")
            self.assertNotIn("custom_exit", candidate.__dict__)
            self.assertNotIn("custom_stoploss", candidate.__dict__)

    def test_btc_regime_uses_slow_ema_and_prior_slope(self) -> None:
        source = (ROOT / "user_data/strategies/ProRegimeTournament15m.py").read_text(encoding="utf-8")
        self.assertIn('timeperiod=200', source)
        self.assertIn('frame["ema200"].shift(12)', source)
        self.assertIn('suffix="btc_1h"', source)


if __name__ == "__main__":
    unittest.main()

