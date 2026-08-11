import unittest

import build_live_readiness as readiness


def bot(allowed=True):
    return {
        "runtime": {"dry_run": True},
        "runtime_validation": {
            "checks": [{"name": "local_exchange_credentials_empty", "status": "PASS"}]
        },
        "account_risk": {"new_entries_allowed": allowed},
    }


class LiveReadinessTests(unittest.TestCase):
    def inputs(self):
        snapshot = {
            "snapshot_utc": "2026-08-10T00:00:00Z",
            "monitoring": {"continuity": {"pass": True, "status": "VALID"}},
            "bots": {"v1": bot(), "v2r": bot()},
        }
        decision = {
            "decision": "FORWARD_REVIEW_READY",
            "selected_candidate": "DualTrendFuturesV2R",
            "auto_promotion_enabled": False,
        }
        stress = {"status": "PASS"}
        policy = {"live_launch": {"authorized": False}}
        return snapshot, decision, stress, policy

    def test_ready_for_review_never_authorizes_live(self):
        report = readiness.build_readiness(*self.inputs())
        self.assertEqual(report["qualification_status"], "READY_FOR_HUMAN_REVIEW")
        self.assertFalse(report["live_trading_authorized"])
        self.assertFalse(report["automatic_live_launch_available"])

    def test_stress_failure_blocks_qualification(self):
        snapshot, decision, stress, policy = self.inputs()
        stress["status"] = "FAIL"
        report = readiness.build_readiness(snapshot, decision, stress, policy)
        self.assertEqual(report["qualification_status"], "EVIDENCE_INCOMPLETE")

    def test_credentials_present_is_a_safety_block(self):
        snapshot, decision, stress, policy = self.inputs()
        snapshot["bots"]["v2r"]["runtime_validation"]["checks"][0]["status"] = "FAIL"
        report = readiness.build_readiness(snapshot, decision, stress, policy)
        self.assertEqual(report["qualification_status"], "SAFETY_BLOCK")


if __name__ == "__main__":
    unittest.main()
