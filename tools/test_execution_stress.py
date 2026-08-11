import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import validate_execution_stress as stress


class ExecutionStressTests(unittest.TestCase):
    def make_fixture(self, root: Path, *, weak: bool = False) -> tuple[Path, Path]:
        backtests = root / "backtests"
        backtests.mkdir()
        summary = root / "summary.csv"
        rows = []
        for split in stress.DEFAULT_SPLITS:
            archive_name = f"{split}.zip"
            trades = [
                {
                    "amount": 1.0,
                    "open_rate": 100.0,
                    "close_rate": 101.0,
                    "profit_abs": 5.0 if not weak else 0.05,
                    "funding_fees": 0.0,
                    "close_date": "2026-01-01T00:00:00Z",
                },
                {
                    "amount": 1.0,
                    "open_rate": 100.0,
                    "close_rate": 99.0,
                    "profit_abs": -1.0,
                    "funding_fees": 0.0,
                    "close_date": "2026-01-02T00:00:00Z",
                },
            ]
            payload = {"strategy": {"DualTrendFuturesV2R": {"trades": trades}}}
            with zipfile.ZipFile(backtests / archive_name, "w") as bundle:
                bundle.writestr(f"{split}.json", json.dumps(payload))
            rows.append(
                {
                    "artifact": archive_name,
                    "strategy": "DualTrendFuturesV2R",
                    "split": split,
                    "profit_abs_usdt": sum(item["profit_abs"] for item in trades),
                }
            )
        with summary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return summary, backtests

    def test_reconciles_and_passes_resilient_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary, backtests = self.make_fixture(Path(temporary))
            report = stress.build_report(summary, backtests)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["results"]), len(stress.DEFAULT_SPLITS) * 2)

    def test_fails_when_adverse_costs_remove_the_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary, backtests = self.make_fixture(Path(temporary), weak=True)
            report = stress.build_report(summary, backtests)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(item["status"] == "FAIL" for item in report["gates"]))


if __name__ == "__main__":
    unittest.main()
