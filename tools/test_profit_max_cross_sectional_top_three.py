import json
import sys
import unittest
from pathlib import Path

from freqtrade.enums import CandleType


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data/strategies"
if str(STRATEGIES) not in sys.path:
    sys.path.insert(0, str(STRATEGIES))

from ProfitMaxCrossSectionalTopThree import ProfitMaxCrossSectionalTopThree8h  # noqa: E402


class TopThreeTests(unittest.TestCase):
    def test_exact_strategy_and_risk_contract(self):
        strategy = ProfitMaxCrossSectionalTopThree8h({"candle_type_def": CandleType.FUTURES})
        self.assertEqual((strategy.top_n, strategy.momentum_candles, strategy.hold_hours), (3, 180, 8))
        self.assertFalse(strategy.can_short)
        risk = json.loads((ROOT / "user_data/risk_policy_cross_sectional_3.json").read_text(encoding="utf-8"))
        self.assertEqual(risk["limits"]["maximum_open_trades"], 3)
        self.assertEqual(risk["limits"]["maximum_total_open_stake_pct"], 20.0)
        self.assertFalse(risk["live_launch"]["authorized"])


if __name__ == "__main__":
    unittest.main()
