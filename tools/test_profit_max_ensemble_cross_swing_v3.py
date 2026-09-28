import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxEnsembleCrossSwingV3 import (  # noqa: E402
    ProfitMaxEnsembleCrossSwingV3Global,
    ProfitMaxEnsembleCrossSwingV3PairGuard,
)


class ProfitMaxEnsembleCrossSwingV3Tests(unittest.TestCase):
    def setUp(self):
        self.strategy = object.__new__(ProfitMaxEnsembleCrossSwingV3Global)
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def confirm(self, tag, reason):
        return self.strategy.confirm_trade_exit(
            "BTC/USDT:USDT", SimpleNamespace(enter_tag=tag), "limit", 1, 1, "GTC", reason, self.now
        )

    def test_cross_rejects_every_foreign_swing_exit_spelling(self):
        for reason in self.strategy.cross_foreign_exit_reasons:
            self.assertFalse(self.confirm("xsmom_top2_180_8h_long", reason))
        for reason in ("xsmom_fixed_8h_rebalance", "stop_loss", "force_exit", "emergency_exit"):
            self.assertTrue(self.confirm("xsmom_top2_180_8h_long", reason))

    def test_swing_accepts_signal_exit(self):
        self.assertTrue(self.confirm("swing_daily_bull", "long_channel_daily_or_confluence_failure"))
        self.assertTrue(self.confirm("swing_daily_bear", "short_channel_daily_or_confluence_failure"))

    def test_pair_guard_changes_only_stoploss_scope(self):
        global_strategy = object.__new__(ProfitMaxEnsembleCrossSwingV3Global)
        pair_strategy = object.__new__(ProfitMaxEnsembleCrossSwingV3PairGuard)
        self.assertFalse(global_strategy.protections[1]["only_per_pair"])
        self.assertTrue(pair_strategy.protections[1]["only_per_pair"])
        global_without_scope = [{k: v for k, v in item.items() if k != "only_per_pair"} for item in global_strategy.protections]
        pair_without_scope = [{k: v for k, v in item.items() if k != "only_per_pair"} for item in pair_strategy.protections]
        self.assertEqual(global_without_scope, pair_without_scope)


if __name__ == "__main__":
    unittest.main()
