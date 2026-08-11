import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_report_artifact as daily


class DailyReportArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.reports = Path(self.temporary.name)
        (self.reports / "forward_monitor_latest.json").write_text(
            json.dumps(
                {
                    "snapshot_utc": "2026-01-02T04:00:00Z",
                    "alerting": {"webhook_delivery": {"status": "LOCAL_ONLY"}},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def base_dashboard() -> dict:
        cards = [
            {"id": name, "dataset": "overview", "sourceId": "source", "metrics": []}
            for name in (
                "forward_decision",
                "validated_days",
                "snapshot_coverage",
                "snapshot_freshness",
                "backup_freshness",
                "live_readiness",
                "execution_stress",
                "v1_closed",
                "v2r_closed",
                "v2r_net_profit",
                "v2r_drawdown",
            )
        ]
        tables = [
            {"id": name, "dataset": name, "sourceId": "source", "columns": []}
            for name in ("bot_comparison", "gate_status", "recent_alerts")
        ]
        return {
            "surface": "dashboard",
            "sources": [{"id": "source", "label": "Source", "path": "user_data/reports/source.json"}],
            "manifest": {"cards": cards, "tables": tables},
            "snapshot": {
                "generatedAt": "2026-01-02T04:00:00Z",
                "datasets": {
                    "overview": [
                        {
                            "decision_status": "Συλλογή δείγματος",
                            "live_trading_status": "Απενεργοποιημένο",
                            "qualification_status": "EVIDENCE_INCOMPLETE",
                            "validated_observation_days": 1.0,
                            "monitoring_days_target": 30.0,
                            "snapshot_coverage_pct": 100.0,
                            "v1_closed": 2,
                            "v1_closed_target": 30,
                            "v2r_closed": 3,
                            "v2r_closed_target": 30,
                            "v2r_net_profit": 1.5,
                            "v2r_drawdown_pct": 0.5,
                            "v2r_drawdown_limit": 10.0,
                            "execution_stress_status": "FAIL",
                        }
                    ],
                    "bot_compare": [],
                    "gates": [],
                    "alerts": [
                        {
                            "timestamp_utc": "2026-01-02T01:00:00Z",
                            "severity": "CRITICAL",
                        }
                    ],
                },
            },
        }

    def test_builds_answer_first_report_with_fail_closed_claims(self) -> None:
        with patch.object(daily, "build_dashboard_artifact", return_value=self.base_dashboard()):
            artifact = daily.build_artifact(self.reports)

        self.assertEqual(artifact["surface"], "report")
        self.assertEqual(artifact["manifest"]["surface"], "report")
        self.assertIn("## Executive Summary", artifact["manifest"]["blocks"][0]["body"])
        self.assertIn("Απενεργοποιημένο", artifact["manifest"]["blocks"][0]["body"])
        overview = artifact["snapshot"]["datasets"]["daily_overview"][0]
        self.assertEqual(overview["daily_alert_count"], 1)
        self.assertEqual(overview["daily_critical_alert_count"], 1)
        self.assertEqual(overview["alert_delivery_mode"], "LOCAL_ONLY")
        self.assertEqual(overview["last_alert_delivery_status"], "LOCAL_ONLY")
        self.assertEqual(len(artifact["manifest"]["charts"]), 1)
        progress = artifact["snapshot"]["datasets"]["qualification_progress"]
        self.assertEqual(len(progress), 6)
        self.assertEqual(
            sorted({row["series"] for row in progress}),
            ["Στόχος qualification", "Τρέχουσα πρόοδος"],
        )
        self.assertEqual(
            [row["value_pct"] for row in progress if row["series"] == "Στόχος qualification"],
            [100.0, 100.0, 100.0],
        )

    def test_writes_latest_artifact_and_daily_archive(self) -> None:
        output = self.reports / "dashboard" / "daily.json"
        archive_dir = self.reports / "daily"
        with patch.object(daily, "build_dashboard_artifact", return_value=self.base_dashboard()):
            artifact = daily.build_and_write(self.reports, output, archive_dir)

        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), artifact)
        archive = json.loads((archive_dir / "2026-01-02.json").read_text(encoding="utf-8"))
        self.assertEqual(archive["report_date_utc"], "2026-01-02")
        self.assertEqual(archive["kpis"]["v2r_closed"], 3)


if __name__ == "__main__":
    unittest.main()
