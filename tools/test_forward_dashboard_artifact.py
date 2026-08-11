import csv
import json
import tempfile
import unittest
from pathlib import Path

import forward_dashboard_artifact as dashboard


class DashboardArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.reports = Path(self.temp_dir.name)
        latest = {
            "snapshot_utc": "2026-01-02T00:00:00Z",
            "monitoring": {"elapsed_days": 1.0},
            "locked_thresholds": {
                "minimum_monitoring_days": 30.0,
                "minimum_closed_trades_per_bot": 30,
                "minimum_v2r_profit_factor": 1.2,
                "maximum_v2r_drawdown_pct_of_start_wallet": 10.0,
            },
            "bots": {
                "v1": self.bot("DualTrendFuturesV1", 2, 1.0, 1.1, 0.5),
                "v2r": self.bot("DualTrendFuturesV2R", 3, 2.0, 1.3, 0.4),
            },
        }
        decision = {
            "decision": "INSUFFICIENT_FORWARD_SAMPLE",
            "integrity_gates": [self.gate("integrity", "PASS", True, "true")],
            "sample_gates": [self.gate("days", "FAIL", 1.0, ">= 30")],
            "performance_gates": [],
        }
        (self.reports / "forward_monitor_latest.json").write_text(
            json.dumps(latest), encoding="utf-8"
        )
        (self.reports / "forward_monitor_decision.json").write_text(
            json.dumps(decision), encoding="utf-8"
        )
        with (self.reports / "forward_monitor_history.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "snapshot_utc",
                    "bot_key",
                    "closed_trades",
                    "open_trades",
                    "net_profit_abs",
                    "return_pct_of_start_wallet",
                    "profit_factor",
                    "max_drawdown_pct_of_start_wallet",
                    "return_to_drawdown",
                    "distinct_pairs",
                    "collection_status",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "snapshot_utc": "2026-01-02T00:00:00Z",
                    "bot_key": "v2r",
                    "closed_trades": 3,
                    "open_trades": 0,
                    "net_profit_abs": 2,
                    "return_pct_of_start_wallet": 0.2,
                    "profit_factor": 1.3,
                    "max_drawdown_pct_of_start_wallet": 0.4,
                    "return_to_drawdown": 0.5,
                    "distinct_pairs": 2,
                    "collection_status": "OK",
                }
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def bot(strategy: str, closed: int, net: float, pf: float, drawdown: float) -> dict:
        return {
            "strategy": strategy,
            "status": "OK",
            "runtime_validation": {"pass": True},
            "data_quality": {"pass": True},
            "metrics": {
                "closed_trades": closed,
                "open_trades": 0,
                "net_profit_abs": net,
                "return_pct_of_start_wallet": net / 10,
                "profit_factor": pf,
                "max_drawdown_pct_of_start_wallet": drawdown,
                "return_to_drawdown": 0.5,
                "distinct_pairs": 2,
            },
        }

    @staticmethod
    def gate(name: str, status: str, actual, requirement: str) -> dict:
        return {"name": name, "status": status, "actual": actual, "requirement": requirement}

    def test_builds_canonical_dashboard_with_bounded_sources(self) -> None:
        artifact = dashboard.build_artifact(self.reports)

        self.assertEqual(artifact["surface"], "dashboard")
        self.assertEqual(artifact["snapshot"]["status"], "ready")
        self.assertEqual(len(artifact["manifest"]["cards"]), 14)
        self.assertEqual(artifact["manifest"]["title"], "Κέντρο Ελέγχου Trading Bot")
        overview = artifact["snapshot"]["datasets"]["overview"][0]
        self.assertEqual(overview["validated_observation_days"], 1.0)
        self.assertEqual(overview["snapshot_coverage_pct"], 100.0)
        self.assertEqual(artifact["snapshot"]["datasets"]["history"][0]["bot"], "V2R")
        self.assertTrue(all(not source["path"].startswith("C:") for source in artifact["sources"]))
        self.assertFalse(any("password" in json.dumps(source).lower() for source in artifact["sources"]))

    def test_atomic_write_produces_same_payload(self) -> None:
        output = self.reports / "dashboard" / "artifact.json"

        artifact = dashboard.build_and_write(self.reports, output)
        written = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(written, artifact)

    def test_monitoring_error_still_builds_a_fail_closed_dashboard(self) -> None:
        latest = json.loads(
            (self.reports / "forward_monitor_latest.json").read_text(encoding="utf-8")
        )
        latest["bots"]["v2r"] = {
            "strategy": "DualTrendFuturesV2R",
            "status": "ERROR",
            "error": "temporary API startup failure",
        }
        (self.reports / "forward_monitor_latest.json").write_text(
            json.dumps(latest), encoding="utf-8"
        )
        decision = json.loads(
            (self.reports / "forward_monitor_decision.json").read_text(encoding="utf-8")
        )
        decision["decision"] = "MONITORING_ERROR"
        (self.reports / "forward_monitor_decision.json").write_text(
            json.dumps(decision), encoding="utf-8"
        )

        artifact = dashboard.build_artifact(self.reports)

        overview = artifact["snapshot"]["datasets"]["overview"][0]
        self.assertIsNone(overview["v2r_closed"])
        self.assertEqual(artifact["snapshot"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
