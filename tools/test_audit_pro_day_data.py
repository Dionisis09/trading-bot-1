import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import audit_pro_day_data as audit


class ProDayDataAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = self.root / "user_data" / "data" / "binance" / "futures"
        self.report_dir = self.root / "user_data" / "reports" / "pro_day"
        self.data_dir.mkdir(parents=True)
        self.policy = audit.AuditPolicy(
            download_start=audit.utc_timestamp("2026-01-01T00:00:00Z"),
            download_end=audit.utc_timestamp("2026-01-04T00:00:00Z"),
            splits=(
                (
                    "TRAIN",
                    audit.utc_timestamp("2026-01-01T00:00:00Z"),
                    audit.utc_timestamp("2026-01-02T00:00:00Z"),
                ),
                (
                    "VALIDATION",
                    audit.utc_timestamp("2026-01-02T00:00:00Z"),
                    audit.utc_timestamp("2026-01-03T00:00:00Z"),
                ),
                (
                    "CURRENT_PARTIAL",
                    audit.utc_timestamp("2026-01-03T00:00:00Z"),
                    audit.utc_timestamp("2026-01-04T00:00:00Z"),
                ),
            ),
        )
        self.frames: dict[tuple[str, str], pd.DataFrame] = {}
        self._write_valid_matrix()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _base_frame(self, offset: float) -> pd.DataFrame:
        dates = pd.date_range(
            self.policy.download_start,
            self.policy.download_end,
            freq="5min",
            inclusive="left",
        )
        price = offset + np.arange(len(dates), dtype=float) * 0.01
        return pd.DataFrame(
            {
                "date": dates,
                "open": price,
                "high": price + 0.01,
                "low": price - 0.01,
                "close": price + 0.002,
                "volume": 1.0 + (np.arange(len(dates)) % 7) * 0.1,
            }
        )

    @staticmethod
    def _aggregate(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        indexed = frame.set_index("date")
        frequency = pd.Timedelta(seconds=audit.TIMEFRAME_SECONDS[timeframe])
        result = indexed.resample(frequency, label="left", closed="left", origin="epoch").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        return result.reset_index()

    def _path(self, pair: str, timeframe: str) -> Path:
        return audit.data_path(self.data_dir, pair, timeframe)

    def _write(self, pair: str, timeframe: str, frame: pd.DataFrame) -> None:
        self.frames[(pair, timeframe)] = frame.copy()
        frame.reset_index(drop=True).to_feather(self._path(pair, timeframe))

    def _write_valid_matrix(self) -> None:
        for index, pair in enumerate(audit.PAIRS):
            base = self._base_frame(100.0 + index * 100.0)
            self._write(pair, "5m", base)
            for timeframe in audit.INFORMATIVE_TIMEFRAMES:
                self._write(pair, timeframe, self._aggregate(base, timeframe))

    def _run(self, *, write_output: bool = False) -> dict:
        return audit.run_audit(
            project_root=self.root,
            data_dir=self.data_dir,
            report_dir=self.report_dir,
            policy=self.policy,
            write_output=write_output,
        )

    def test_valid_exact_matrix_passes_and_writes_json_csv_hash_evidence(self) -> None:
        result = self._run(write_output=True)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["decision"], "READY_FOR_RESEARCH_FREEZE")
        self.assertFalse(result["pnl_evaluated"])
        self.assertEqual(len(result["data_files"]), 12)
        self.assertEqual(len(result["split_checks"]), 36)
        self.assertEqual(len(result["reconciliation_checks"]), 27)
        self.assertTrue(all(len(row["sha256"]) == 64 for row in result["data_files"]))
        self.assertTrue(all(row["coverage_pct"] == 100.0 for row in result["split_checks"]))
        self.assertTrue(all(row["status"] == "PASS" for row in result["reconciliation_checks"]))
        for name in (
            "data_quality.json",
            "data_quality_files.csv",
            "data_quality_splits.csv",
            "data_quality_gaps.csv",
            "data_quality_reconciliation.csv",
            "data_quality_reconciliation_daily.csv",
        ):
            self.assertTrue((self.report_dir / name).is_file(), name)
        stored = json.loads((self.report_dir / "data_quality.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "PASS")
        self.assertIn("json", stored["report_paths"])

    def test_duplicate_nonfinite_invalid_ohlc_and_large_gap_fail_closed(self) -> None:
        btc_base = self.frames[(audit.PAIRS[0], "5m")]
        damaged_base = pd.concat([btc_base.drop(index=range(20, 24)), btc_base.iloc[[10]]])
        self._write(audit.PAIRS[0], "5m", damaged_base)

        eth_15m = self.frames[(audit.PAIRS[1], "15m")]
        eth_15m.loc[3, "volume"] = np.inf
        self._write(audit.PAIRS[1], "15m", eth_15m)

        bnb_1h = self.frames[(audit.PAIRS[2], "1h")]
        bnb_1h.loc[2, "high"] = bnb_1h.loc[2, "open"] - 1.0
        self._write(audit.PAIRS[2], "1h", bnb_1h)

        result = self._run()

        self.assertEqual(result["status"], "DATA_BLOCKED")
        btc_file = next(
            row
            for row in result["data_files"]
            if row["pair"] == audit.PAIRS[0] and row["timeframe"] == "5m"
        )
        self.assertGreater(btc_file["duplicate_timestamps"], 0)
        eth_file = next(
            row
            for row in result["data_files"]
            if row["pair"] == audit.PAIRS[1] and row["timeframe"] == "15m"
        )
        self.assertEqual(eth_file["nonfinite_ohlcv_cells"], 1)
        bnb_file = next(
            row
            for row in result["data_files"]
            if row["pair"] == audit.PAIRS[2] and row["timeframe"] == "1h"
        )
        self.assertEqual(bnb_file["invalid_ohlc_rows"], 1)
        large_gaps = [row for row in result["gaps"] if row["over_limit"]]
        self.assertTrue(any(row["missing_candles"] == 4 for row in large_gaps))

    def test_native_timeframe_mismatch_is_reported_by_day(self) -> None:
        native = self.frames[(audit.PAIRS[0], "15m")]
        changed_at = pd.Timestamp("2026-01-02T03:00:00Z")
        row_index = native.index[native["date"] == changed_at][0]
        native.loc[row_index, "close"] += 0.001
        self._write(audit.PAIRS[0], "15m", native)

        result = self._run()

        self.assertEqual(result["status"], "DATA_BLOCKED")
        summary = next(
            row
            for row in result["reconciliation_checks"]
            if row["pair"] == audit.PAIRS[0]
            and row["timeframe"] == "15m"
            and row["split"] == "VALIDATION"
        )
        self.assertEqual(summary["mismatch_days"], 1)
        self.assertEqual(summary["status"], "FAIL")
        day = next(
            row
            for row in result["reconciliation_daily"]
            if row["pair"] == audit.PAIRS[0]
            and row["timeframe"] == "15m"
            and row["date_utc"] == "2026-01-02T00:00:00Z"
        )
        self.assertEqual(day["mismatched_bins"], 1)
        self.assertIn("close", day["mismatch_fields"])

    def test_missing_required_file_never_degrades_to_partial_universe(self) -> None:
        self._path(audit.PAIRS[2], "4h").unlink()

        result = self._run()

        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertEqual(result["summary"]["files_total"], 12)
        missing = [row for row in result["failures"] if row["code"] == "MISSING_REQUIRED_DATA_FILE"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["pair"], audit.PAIRS[2])


if __name__ == "__main__":
    unittest.main()
