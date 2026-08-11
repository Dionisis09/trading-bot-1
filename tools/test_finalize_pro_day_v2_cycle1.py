from __future__ import annotations

import copy
import unittest

import finalize_pro_day_v2_cycle1 as module


class ProDayV2Cycle1FinalizerTests(unittest.TestCase):
    def test_real_state_builds_pre_pnl_rejection(self):
        report = module.build_decision(generated_at="2026-08-11T00:00:00Z")
        self.assertEqual(report["decision"], "REJECT_PRO_DAY_TRADER_V2")
        self.assertEqual(report["performance"]["status"], "NOT_RUN_BY_LOCKED_TECHNICAL_GATE")
        self.assertFalse(report["performance"]["pnl_parsed"])
        self.assertFalse(report["live_trading_authorized"])

    def test_artifact_presence_would_fail_closed(self):
        manifest = module._load(module.ROOT / module.MANIFEST, "manifest")
        changed = copy.deepcopy(manifest)
        changed["artifacts"]["train"]["status"] = "READY"
        with self.assertRaisesRegex(module.FinalizationError, "train"):
            module.validate_frozen_state(changed)

    def test_manifest_cannot_claim_model_or_pnl_before_failure(self):
        manifest = module._load(module.ROOT / module.MANIFEST, "manifest")
        changed = copy.deepcopy(manifest)
        changed["pnl_parsed"] = True
        with self.assertRaisesRegex(module.FinalizationError, "pnl_parsed"):
            module.validate_frozen_state(changed)


if __name__ == "__main__":
    unittest.main()
