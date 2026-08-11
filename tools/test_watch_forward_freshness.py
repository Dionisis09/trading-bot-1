import argparse
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import watch_forward_freshness as watchdog


class FreshnessEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

    def test_fresh_snapshot_has_no_alert(self) -> None:
        result, alerts, state = watchdog.evaluate_freshness(
            (self.now - timedelta(hours=4)).isoformat(), self.now, 18_000, {}
        )
        self.assertEqual(result["status"], "FRESH")
        self.assertFalse(result["stale"])
        self.assertEqual(alerts, [])
        self.assertFalse(state["stale"])

    def test_stale_transition_is_deduplicated_and_recovers(self) -> None:
        stale_time = (self.now - timedelta(hours=6)).isoformat()
        first, first_alerts, stale_state = watchdog.evaluate_freshness(
            stale_time, self.now, 18_000, {}
        )
        _, repeated_alerts, _ = watchdog.evaluate_freshness(
            stale_time, self.now, 18_000, stale_state
        )
        recovered, recovery_alerts, _ = watchdog.evaluate_freshness(
            (self.now - timedelta(minutes=1)).isoformat(), self.now, 18_000, stale_state
        )
        self.assertEqual(first["status"], "STALE")
        self.assertEqual(first_alerts[0]["event_type"], "STALE_MONITOR")
        self.assertEqual(repeated_alerts, [])
        self.assertEqual(recovered["status"], "FRESH")
        self.assertEqual(recovery_alerts[0]["event_type"], "STALE_MONITOR_RECOVERED")

    def test_missing_and_future_snapshot_fail_closed(self) -> None:
        missing, missing_alerts, _ = watchdog.evaluate_freshness(None, self.now, 18_000, {})
        future, future_alerts, _ = watchdog.evaluate_freshness(
            (self.now + timedelta(minutes=2)).isoformat(), self.now, 18_000, {}
        )
        self.assertEqual(missing["status"], "UNAVAILABLE")
        self.assertTrue(missing_alerts)
        self.assertEqual(future["status"], "CLOCK_SKEW")
        self.assertTrue(future_alerts)


class DeadmanHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

    def test_disabled_and_stale_heartbeat_do_not_make_network_requests(self) -> None:
        with patch.object(watchdog.urllib.request, "urlopen") as mocked:
            disabled = watchdog.send_deadman_heartbeat(
                None, snapshot_fresh=True, timeout_seconds=1.0
            )
            suppressed = watchdog.send_deadman_heartbeat(
                "https://heartbeat.invalid/secret-token",
                snapshot_fresh=False,
                timeout_seconds=1.0,
            )
        self.assertEqual(disabled["status"], "DISABLED")
        self.assertEqual(suppressed["status"], "SUPPRESSED_STALE")
        mocked.assert_not_called()

    def test_rejects_non_https_url_without_exposing_it(self) -> None:
        secret_url = "http://heartbeat.invalid/private-secret"
        result = watchdog.send_deadman_heartbeat(
            secret_url, snapshot_fresh=True, timeout_seconds=1.0
        )
        self.assertEqual(result["status"], "INVALID_URL")
        self.assertNotIn("private-secret", json.dumps(result))

    def test_successful_https_heartbeat_returns_only_delivery_metadata(self) -> None:
        secret_url = "https://heartbeat.invalid/private-secret"
        with patch.object(watchdog.urllib.request, "urlopen") as mocked:
            mocked.return_value.__enter__.return_value.status = 204
            result = watchdog.send_deadman_heartbeat(
                secret_url, snapshot_fresh=True, timeout_seconds=1.0
            )
        self.assertEqual(result, {"status": "DELIVERED", "http_status": 204})
        self.assertNotIn("private-secret", json.dumps(result))

    def test_delivery_failure_is_deduplicated_and_recovery_is_emitted(self) -> None:
        failed = {"status": "NETWORK_ERROR"}
        first_alerts, is_failed = watchdog.evaluate_heartbeat_alerts(
            failed, self.now, {}
        )
        repeated_alerts, _ = watchdog.evaluate_heartbeat_alerts(
            failed, self.now, {"heartbeat_failed": True}
        )
        recovered_alerts, recovered_failed = watchdog.evaluate_heartbeat_alerts(
            {"status": "DELIVERED", "http_status": 200},
            self.now,
            {"heartbeat_failed": True},
        )
        self.assertTrue(is_failed)
        self.assertEqual(first_alerts[0]["event_type"], "DEADMAN_HEARTBEAT_FAILED")
        self.assertEqual(repeated_alerts, [])
        self.assertFalse(recovered_failed)
        self.assertEqual(
            recovered_alerts[0]["event_type"], "DEADMAN_HEARTBEAT_RECOVERED"
        )


class FreshnessIntegrationTests(unittest.TestCase):
    def test_check_once_writes_state_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports = root / "reports"
            reports.mkdir()
            now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
            (reports / "forward_monitor_latest.json").write_text(
                json.dumps({"snapshot_utc": now.isoformat()}), encoding="utf-8"
            )
            args = argparse.Namespace(
                reports_dir=str(reports),
                dashboard_output=str(root / "dashboard" / "artifact.json"),
                stale_seconds=18_000,
                timeout_seconds=1.0,
            )
            with patch.dict("os.environ", {}, clear=True):
                result = watchdog.check_once(args, now=now)
            latest = json.loads(
                (reports / "forward_watchdog_latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "FRESH")
            self.assertEqual(result["deadman_heartbeat"]["status"], "DISABLED")
            self.assertEqual(latest["status"], "FRESH")
            self.assertEqual(latest["deadman_heartbeat"]["status"], "DISABLED")
            self.assertTrue((reports / "forward_watchdog_state.json").exists())
            # The dashboard fixture is intentionally incomplete; watchdog evidence
            # must still be persisted even when dashboard regeneration cannot run.
            self.assertEqual(result["dashboard_artifact_status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
