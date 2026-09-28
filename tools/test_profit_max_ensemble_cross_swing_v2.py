import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxEnsembleCrossSwingV2 import ProfitMaxEnsembleCrossSwingV2  # noqa: E402


class ProfitMaxEnsembleCrossSwingV2Tests(unittest.TestCase):
    def setUp(self):
        self.strategy = object.__new__(ProfitMaxEnsembleCrossSwingV2)
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def confirm(self, tag, reason):
        trade = SimpleNamespace(enter_tag=tag)
        return self.strategy.confirm_trade_exit(
            "BTC/USDT:USDT", trade, "limit", 1.0, 1.0, "GTC", reason, self.now
        )

    def test_callbacks_are_enabled(self):
        self.assertTrue(self.strategy.use_exit_signal)

    def test_cross_trade_rejects_only_foreign_swing_exit_signal(self):
        self.assertFalse(self.confirm("xsmom_top2_180_8h_long", "exit_signal"))
        self.assertTrue(self.confirm("xsmom_top2_180_8h_long", "xsmom_fixed_8h_rebalance"))
        self.assertTrue(self.confirm("xsmom_top2_180_8h_long", "stop_loss"))
        self.assertTrue(self.confirm("xsmom_top2_180_8h_long", "force_exit"))

    def test_swing_trade_accepts_its_signal_and_unknown_is_fail_safe_for_exit(self):
        self.assertTrue(self.confirm("swing_daily_bull", "exit_signal"))
        self.assertTrue(self.confirm(None, "emergency_exit"))


if __name__ == "__main__":
    unittest.main()
