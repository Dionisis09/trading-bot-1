from __future__ import annotations

import unittest

import finalize_pro_day_v2_cycle2 as finalizer


class Cycle2FinalizerTests(unittest.TestCase):
    def test_real_evidence_builds_terminal_no_pnl_rejection(self) -> None:
        report = finalizer.build(finalizer.ROOT)
        self.assertEqual(report["decision"], "REJECT_PRO_DAY_TRADER_V2")
        self.assertEqual(report["decision_stage"], "PRE_PNL_RECURSIVE_GATE")
        self.assertIs(report["performance"]["pnl_parsed"], False)
        self.assertEqual(report["performance"]["qualification_backtests"], 0)

    def test_active_bots_and_live_remain_unauthorized(self) -> None:
        report = finalizer.build(finalizer.ROOT)
        self.assertIs(report["active_v1_v2r_changed"], False)
        self.assertIs(report["live_trading_authorized"], False)
        self.assertIs(report["deployment_performed"], False)


if __name__ == "__main__":
    unittest.main()
