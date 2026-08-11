import csv
import json
import tempfile
import unittest
from pathlib import Path

import build_pro_day_report_artifact as report


class ProDayReportArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.docs = self.workspace / "docs"
        self.reports = self.workspace / "user_data" / "reports" / "pro_day"
        self.docs.mkdir(parents=True)
        self.reports.mkdir(parents=True)
        self.plan = self.docs / "pro_day_trader_v1_locked_plan.md"
        self.plan.write_text("# Frozen plan\n\nDATA_BLOCKED before PnL.\n", encoding="utf-8")

        self.data_quality = self.reports / "data_quality.json"
        self.data_quality.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "candidate": "ProDayTraderV1",
                    "status": "DATA_BLOCKED",
                    "decision": "DATA_BLOCKED",
                    "pnl_evaluated": False,
                    "live_trading_authorized": False,
                    "generated_at_utc": "2026-08-11T12:36:46Z",
                    "expected_pairs": ["BTC/USDT:USDT"],
                    "expected_timeframes": ["5m", "15m", "1h", "4h"],
                    "intended_grain": "native futures candles",
                    "windows": {
                        "splits": [
                            {"name": "TRAIN", "start_utc": "2021-01-01T00:00:00Z", "end_utc": "2024-01-01T00:00:00Z"},
                            {"name": "VALIDATION", "start_utc": "2024-01-01T00:00:00Z", "end_utc": "2026-01-01T00:00:00Z"},
                            {"name": "CURRENT_PARTIAL", "start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-08-01T00:00:00Z"},
                        ]
                    },
                    "thresholds": {
                        "minimum_coverage_pct": 99.95,
                        "maximum_undocumented_gap_candles": 3,
                        "maximum_mismatch_days_pct": 0.2,
                        "reconciliation_absolute_tolerance": 1e-8,
                        "reconciliation_relative_tolerance": 1e-9,
                    },
                    "failures": [
                        {
                            "code": "TIMEFRAME_RECONCILIATION_FAILED",
                            "severity": "CRITICAL",
                            "split": "TRAIN",
                            "pair": "BTC/USDT:USDT",
                            "timeframe": "15m",
                            "detail": "mismatch_days_pct=1.0",
                        },
                        {
                            "code": "TIMEFRAME_RECONCILIATION_FAILED",
                            "severity": "CRITICAL",
                            "split": "VALIDATION",
                            "pair": "BTC/USDT:USDT",
                            "timeframe": "15m",
                            "detail": "mismatch_days_pct=1.0",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.files_csv = self.reports / "data_quality_files.csv"
        self._write_csv(
            self.files_csv,
            [
                {
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "5m",
                    "filename": "BTC-5m.feather",
                    "rows": "100",
                    "first_utc": "2021-01-01T00:00:00Z",
                    "last_utc": "2026-07-31T23:55:00Z",
                    "download_window_coverage_pct": "100.0",
                    "duplicate_timestamps": "0",
                    "null_ohlcv_cells": "0",
                    "invalid_ohlc_rows": "0",
                    "status": "PASS",
                }
            ],
        )
        self.splits_csv = self.reports / "data_quality_splits.csv"
        self._write_csv(
            self.splits_csv,
            [
                {
                    "split": split,
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "5m",
                    "expected_candles": "10",
                    "observed_candles": "10",
                    "missing_candles": "0",
                    "coverage_pct": "100.0",
                    "undocumented_gaps_over_limit": "0",
                    "status": "PASS",
                }
                for split in ("TRAIN", "VALIDATION", "CURRENT_PARTIAL")
            ],
        )
        self.reconciliation_csv = self.reports / "data_quality_reconciliation.csv"
        self._write_csv(
            self.reconciliation_csv,
            [
                {
                    "split": "TRAIN",
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "15m",
                    "compared_days": "10",
                    "mismatch_days": "1",
                    "mismatch_days_pct": "10.0",
                    "maximum_mismatch_days_pct": "0.2",
                    "status": "FAIL",
                },
                {
                    "split": "VALIDATION",
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "15m",
                    "compared_days": "10",
                    "mismatch_days": "1",
                    "mismatch_days_pct": "10.0",
                    "maximum_mismatch_days_pct": "0.2",
                    "status": "FAIL",
                },
                {
                    "split": "CURRENT_PARTIAL",
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "15m",
                    "compared_days": "10",
                    "mismatch_days": "0",
                    "mismatch_days_pct": "0.0",
                    "maximum_mismatch_days_pct": "0.2",
                    "status": "PASS",
                },
            ],
        )
        self.reconciliation_daily_csv = self.reports / "data_quality_reconciliation_daily.csv"
        self._write_csv(
            self.reconciliation_daily_csv,
            [
                {
                    "split": "TRAIN",
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "15m",
                    "date_utc": "2021-01-01T00:00:00Z",
                    "complete_5m_bins": "96",
                    "missing_native_bins": "0",
                    "duplicate_native_bins": "0",
                    "mismatched_bins": "1",
                    "mismatch_fields": "volume",
                    "status": "FAIL",
                },
                {
                    "split": "CURRENT_PARTIAL",
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "15m",
                    "date_utc": "2026-01-01T00:00:00Z",
                    "complete_5m_bins": "96",
                    "missing_native_bins": "0",
                    "duplicate_native_bins": "0",
                    "mismatched_bins": "0",
                    "mismatch_fields": "",
                    "status": "PASS",
                },
            ],
        )
        self.gaps_csv = self.reports / "data_quality_gaps.csv"
        self._write_csv(
            self.gaps_csv,
            [],
            fields=(
                "split",
                "pair",
                "timeframe",
                "gap_start_utc",
                "gap_end_utc",
                "missing_candles",
                "documented",
                "over_limit",
                "status",
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_csv(path: Path, rows: list[dict], fields: tuple[str, ...] | None = None) -> None:
        fields = fields or tuple(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _build(self, **overrides):
        kwargs = {
            "workspace": self.workspace,
            "locked_plan_path": self.plan,
            "data_quality_path": self.data_quality,
            "files_csv_path": self.files_csv,
            "splits_csv_path": self.splits_csv,
            "reconciliation_csv_path": self.reconciliation_csv,
            "reconciliation_daily_csv_path": self.reconciliation_daily_csv,
            "gaps_csv_path": self.gaps_csv,
        }
        kwargs.update(overrides)
        return report.build_artifact(**kwargs)

    def test_builds_answer_first_blocked_technical_report(self) -> None:
        artifact, _ = self._build()

        self.assertEqual(artifact["surface"], "report")
        self.assertEqual(artifact["manifest"]["surface"], "report")
        self.assertEqual(artifact["manifest"]["title"], "Τεχνικός Έλεγχος ProDayTraderV1")
        self.assertEqual(artifact["manifest"]["blocks"][0]["body"], "# Τεχνικός Έλεγχος ProDayTraderV1")
        self.assertIn("## Τεχνικό συμπέρασμα", artifact["manifest"]["blocks"][1]["body"])
        self.assertIn("qualification PnL είναι `NOT_RUN`", artifact["manifest"]["blocks"][1]["body"])
        self.assertEqual(artifact["snapshot"]["status"], "blocked")
        self.assertEqual(artifact["snapshot"]["accessIssues"][0]["id"], "pnl_not_run")
        self.assertIn("PnL NOT_RUN", artifact["snapshot"]["accessIssues"][0]["message"])

    def test_chart_is_single_series_with_explicit_zero_categories(self) -> None:
        artifact, notes = self._build()
        chart = artifact["manifest"]["charts"][0]
        rows = artifact["snapshot"]["datasets"]["reconciliation_status_counts"]

        self.assertEqual(chart["type"], "bar")
        self.assertNotIn("color", chart["encodings"])
        self.assertNotIn("series", chart)
        self.assertEqual(chart["settings"]["groupMode"], "single")
        self.assertEqual(chart["comparisonContext"]["baseline"], "0 checks")
        self.assertEqual(len(rows), 6)
        counts = {row["category"]: row["check_count"] for row in rows}
        self.assertEqual(counts["TRAIN · PASS"], 0)
        self.assertEqual(counts["TRAIN · FAIL"], 1)
        self.assertEqual(counts["VALIDATION · PASS"], 0)
        self.assertEqual(counts["VALIDATION · FAIL"], 1)
        self.assertEqual(counts["CURRENT_PARTIAL · PASS"], 1)
        self.assertEqual(counts["CURRENT_PARTIAL · FAIL"], 0)
        self.assertTrue(notes["chart_map"][0]["zero_baseline"])
        self.assertIn("no color", notes["chart_map"][0]["palette_policy"].lower())

    def test_preserves_exact_audit_rows_and_bounded_daily_failures(self) -> None:
        artifact, notes = self._build()
        datasets = artifact["snapshot"]["datasets"]

        self.assertEqual(len(datasets["file_checks"]), 1)
        self.assertEqual(len(datasets["split_checks"]), 3)
        self.assertEqual(len(datasets["reconciliation_checks"]), 3)
        self.assertEqual(len(datasets["reconciliation_daily_failures"]), 1)
        self.assertEqual(datasets["reconciliation_daily_failures"][0]["status"], "FAIL")
        self.assertEqual(len(datasets["failure_register"]), 2)
        self.assertEqual(datasets["gap_checks"], [])
        self.assertEqual(datasets["audit_summary"][0]["failed_daily_check_rows"], 1)
        self.assertEqual(datasets["audit_summary"][0]["failed_daily_distinct_utc_dates"], 1)
        self.assertIn("2 daily rows", notes["source_notes"]["daily_detail"])
        self.assertIn("all 1 FAIL day-check rows across 1 distinct UTC dates", notes["source_notes"]["daily_detail"])

    def test_all_native_evidence_has_safe_resolvable_source_metadata(self) -> None:
        artifact, _ = self._build()
        source_ids = {source["id"] for source in artifact["manifest"]["sources"]}
        self.assertEqual(artifact["sources"], artifact["manifest"]["sources"])
        for source in artifact["sources"]:
            path = source["path"]
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)
            self.assertTrue(source["query"]["tables_used"])
            self.assertEqual(source["query"]["engine"], "sqlite3")
            self.assertEqual(source["query"]["sql"], "SELECT * FROM report_rows")
        for chart in artifact["manifest"]["charts"]:
            self.assertIn(chart["sourceId"], source_ids)
        for table in artifact["manifest"]["tables"]:
            self.assertIn(table["sourceId"], source_ids)

    def test_block_references_are_validator_compatible(self) -> None:
        artifact, _ = self._build()
        manifest = artifact["manifest"]
        chart_ids = {item["id"] for item in manifest["charts"]}
        table_ids = {item["id"] for item in manifest["tables"]}
        source_ids = {item["id"] for item in manifest["sources"]}
        block_ids = [item["id"] for item in manifest["blocks"]]
        self.assertEqual(len(block_ids), len(set(block_ids)))
        for block in manifest["blocks"]:
            if block["type"] == "chart":
                self.assertIn(block["chartId"], chart_ids)
            if block["type"] == "table":
                self.assertIn(block["tableId"], table_ids)
            if "sourceId" in block:
                self.assertIn(block["sourceId"], source_ids)
        for table in manifest["tables"]:
            if "defaultSort" in table:
                fields = {column["field"] for column in table["columns"]}
                self.assertIn(table["defaultSort"]["field"], fields)

    def test_optional_evidence_is_included_without_schema_invention(self) -> None:
        final = self.reports / "final_decision.json"
        final.write_text(
            json.dumps(
                {
                    "decision": "KEEP_OFFLINE_RESEARCH",
                    "live_trading_authorized": False,
                    "nested": {"lossless_long_scalar": "x" * 9001},
                    "gates": [
                        {
                            "section": "train",
                            "gate": "trades",
                            "passed": False,
                            "actual": 10,
                            "requirement": ">= 180",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        orderflow = self.reports / "orderflow_compatibility.json"
        orderflow.write_text(json.dumps({"status": "LOCAL_ONLY", "peak_mb": 64}), encoding="utf-8")
        deployment = self.reports / "deployment_evidence.json"
        deployment.write_text(
            json.dumps({"collector": "HEALTHY", "existing_services_unchanged": True}),
            encoding="utf-8",
        )
        archive_security = self.reports / "archive_security_audit.json"
        archive_security.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "archive_count": 91,
                    "zip_integrity_pass_count": 91,
                    "config_redaction_pass_count": 91,
                    "failure_count": 0,
                    "pro_day_zip_count": 0,
                }
            ),
            encoding="utf-8",
        )

        artifact, notes = self._build(
            final_decision_path=final,
            orderflow_path=orderflow,
            deployment_evidence_path=deployment,
            archive_security_audit_path=archive_security,
        )

        datasets = artifact["snapshot"]["datasets"]
        self.assertIn("final_decision_fields", datasets)
        self.assertIn("final_gate_results", datasets)
        self.assertIn("orderflow_fields", datasets)
        self.assertIn("deployment_fields", datasets)
        self.assertIn("archive_security_fields", datasets)
        optional_rows = (
            datasets["final_decision_fields"]
            + datasets["orderflow_fields"]
            + datasets["deployment_fields"]
            + datasets["archive_security_fields"]
        )
        self.assertTrue(optional_rows)
        self.assertLess(max(len(cell) for row in optional_rows for cell in row.values()), 4000)
        long_scalar_chunks = [
            row["value"]
            for row in datasets["final_decision_fields"]
            if row["field"].startswith("nested.lossless_long_scalar [part ")
        ]
        self.assertEqual("".join(long_scalar_chunks), "x" * 9001)
        source_ids = {source["id"] for source in artifact["sources"]}
        self.assertTrue(
            {
                "final_decision_json",
                "orderflow_json",
                "deployment_json",
                "archive_security_json",
            }
            <= source_ids
        )
        self.assertEqual(notes["source_notes"]["optional_final_decision"], "included")
        self.assertEqual(notes["source_notes"]["optional_archive_security"], "included")
        # Data quality still blocks PnL even if an inconsistent optional decision file is supplied.
        self.assertEqual(artifact["snapshot"]["status"], "blocked")

    def test_atomic_writes_produce_artifact_and_supporting_notes(self) -> None:
        output = self.reports / "report_artifact.json"
        supporting = self.reports / "report_supporting_notes.json"
        artifact, notes = report.build_and_write(
            output_path=output,
            supporting_notes_path=supporting,
            workspace=self.workspace,
            locked_plan_path=self.plan,
            data_quality_path=self.data_quality,
            files_csv_path=self.files_csv,
            splits_csv_path=self.splits_csv,
            reconciliation_csv_path=self.reconciliation_csv,
            reconciliation_daily_csv_path=self.reconciliation_daily_csv,
            gaps_csv_path=self.gaps_csv,
        )

        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), artifact)
        self.assertEqual(json.loads(supporting.read_text(encoding="utf-8")), notes)
        self.assertEqual(list(self.reports.glob("*.tmp")), [])

    def test_rejects_sources_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            outside_path = Path(outside) / "final_decision.json"
            outside_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(report.ReportBuildError):
                self._build(final_decision_path=outside_path)


if __name__ == "__main__":
    unittest.main()
