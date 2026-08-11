import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import build_pro_day_v2_canonical_data as canonical


class ProDayV2CanonicalDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_dir = self.root / "user_data" / "data" / "binance" / "futures"
        self.output_dir = (
            self.root / "user_data" / "data" / "binance" / "pro_day_v2_canonical"
        )
        self.report_dir = self.root / "user_data" / "reports" / canonical.CYCLE_ID
        self.source_dir.mkdir(parents=True)
        self.policy = canonical.CanonicalPolicy(
            start=canonical.utc_timestamp("2026-01-01T00:00:00Z"),
            end=canonical.utc_timestamp("2026-01-03T00:00:00Z"),
            source_rows=576,
        )
        self.base_frames: dict[str, pd.DataFrame] = {}
        self._write_valid_inputs()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _base_frame(self, offset: float) -> pd.DataFrame:
        dates = pd.date_range(
            self.policy.start,
            self.policy.end,
            freq="5min",
            inclusive="left",
        )
        sequence = np.arange(len(dates), dtype=np.float64)
        opens = offset + sequence * 0.01
        closes = opens + np.where((sequence.astype(int) % 2) == 0, 0.004, -0.003)
        return pd.DataFrame(
            {
                "date": dates,
                "open": opens,
                "high": np.maximum(opens, closes) + 0.02,
                "low": np.minimum(opens, closes) - 0.02,
                "close": closes,
                "volume": 1.0 + (sequence % 7) * 0.1,
            }
        )

    def _funding_frame(self, offset: float) -> pd.DataFrame:
        dates = pd.date_range(
            self.policy.start,
            self.policy.end,
            freq="8h",
            inclusive="left",
        )
        rates = np.linspace(-0.0001, 0.0001, len(dates)) + offset * 1e-9
        zeros = np.zeros(len(dates), dtype=np.float64)
        return pd.DataFrame(
            {
                "date": dates,
                "open": rates,
                "high": zeros,
                "low": zeros,
                "close": zeros,
                "volume": zeros,
            }
        )

    def _mark_frame(self, offset: float) -> pd.DataFrame:
        dates = pd.date_range(
            self.policy.start,
            self.policy.end,
            freq="1h",
            inclusive="left",
        )
        sequence = np.arange(len(dates), dtype=np.float64)
        opens = offset + sequence * 0.1
        closes = opens + 0.02
        return pd.DataFrame(
            {
                "date": dates,
                "open": opens,
                "high": closes + 0.03,
                "low": opens - 0.03,
                "close": closes,
                "volume": np.zeros(len(dates), dtype=np.float64),
            }
        )

    def _write_valid_inputs(self) -> None:
        for index, pair in enumerate(canonical.PAIRS):
            offset = 100.0 + index * 100.0
            base = self._base_frame(offset)
            self.base_frames[pair] = base.copy()
            base.to_feather(self.source_dir / canonical.data_filename(pair, "5m"))
            self._funding_frame(offset).to_feather(
                self.source_dir / canonical.auxiliary_filename(pair, "funding_rate")
            )
            self._mark_frame(offset).to_feather(
                self.source_dir / canonical.auxiliary_filename(pair, "mark")
            )

    def _run(self, *, write_outputs: bool = True) -> dict:
        return canonical.run_pipeline(
            project_root=self.root,
            source_dir=self.source_dir,
            output_dir=self.output_dir,
            report_dir=self.report_dir,
            policy=self.policy,
            write_outputs=write_outputs,
        )

    def test_valid_snapshot_is_exact_deterministic_atomic_and_fully_lineaged(self) -> None:
        # A malformed native informative file exists, but must never be an input.
        pd.DataFrame({"forbidden_native": [1]}).to_feather(
            self.source_dir / canonical.data_filename(canonical.PAIRS[0], "15m")
        )

        result = self._run()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["decision"], "READY_FOR_PRE_PNL_TECHNICAL_GATES")
        self.assertFalse(result["pnl_evaluated"])
        self.assertEqual(result["summary"]["source_files_passed"], 3)
        self.assertEqual(result["summary"]["canonical_files_passed"], 12)
        self.assertEqual(result["summary"]["auxiliary_files_passed"], 6)
        self.assertEqual(result["summary"]["roundtrip_checks_passed"], 9)
        self.assertEqual(len(result["lineage"]), 9)
        self.assertEqual(len(result["auxiliary_lineage"]), 6)
        self.assertTrue(all(row["exact_all_rows"] for row in result["roundtrip_reconstruction"]))
        self.assertTrue(all(row["partial_bins"] == 0 for row in result["roundtrip_reconstruction"]))
        self.assertEqual(
            {path.name for path in self.output_dir.iterdir()},
            canonical._expected_output_names(),
        )

        pair = canonical.PAIRS[0]
        source_path = self.source_dir / canonical.data_filename(pair, "5m")
        copied_path = self.output_dir / canonical.data_filename(pair, "5m")
        self.assertEqual(canonical.sha256_file(source_path), canonical.sha256_file(copied_path))
        derived = pd.read_feather(self.output_dir / canonical.data_filename(pair, "15m"))
        source = self.base_frames[pair]
        self.assertEqual(len(derived), 192)
        self.assertEqual(derived.loc[0, "open"], source.loc[0, "open"])
        self.assertEqual(derived.loc[0, "high"], source.loc[:2, "high"].max())
        self.assertEqual(derived.loc[0, "low"], source.loc[:2, "low"].min())
        self.assertEqual(derived.loc[0, "close"], source.loc[2, "close"])
        self.assertEqual(derived.loc[0, "volume"], source.loc[:2, "volume"].sum())

        for auxiliary in result["auxiliary_canonical_files"]:
            self.assertTrue(auxiliary["byte_exact_source_copy"])
            self.assertFalse(auxiliary["entry_or_ml_feature"])
        exclusion = result["native_timeframe_exclusion"]
        self.assertEqual(exclusion["native_ohlcv_15m_1h_4h_files_read"], [])
        self.assertFalse(exclusion["auxiliary_files_are_entry_or_ml_features"])

        report_path = self.report_dir / canonical.REPORT_NAME
        checksum_path = self.report_dir / canonical.REPORT_CHECKSUM_NAME
        first_report_bytes = report_path.read_bytes()
        recorded_hash = checksum_path.read_text(encoding="ascii").split()[0]
        self.assertEqual(recorded_hash, hashlib.sha256(first_report_bytes).hexdigest())
        stored = json.loads(first_report_bytes)
        integrity = stored.pop("report_integrity")
        self.assertEqual(
            integrity["canonical_payload_sha256"],
            hashlib.sha256(canonical.canonical_json_bytes(stored)).hexdigest(),
        )
        self.assertEqual(
            result["code_hashes"]["generator_source"]["sha256"],
            result["code_hashes"]["audit_source"]["sha256"],
        )

        second = self._run()
        self.assertEqual(second["status"], "PASS")
        self.assertEqual(report_path.read_bytes(), first_report_bytes)
        self.assertFalse(any(self.output_dir.parent.glob(f".{self.output_dir.name}.stage-*")))

    def test_missing_duplicate_nonfinite_and_invalid_ohlc_fail_before_publish(self) -> None:
        pair = canonical.PAIRS[0]
        path = self.source_dir / canonical.data_filename(pair, "5m")
        damaged = self.base_frames[pair].copy()
        damaged = pd.concat([damaged.drop(index=20), damaged.iloc[[10]]], ignore_index=True)
        damaged.loc[30, "volume"] = np.inf
        damaged.loc[40, "high"] = damaged.loc[40, "open"] - 1.0
        damaged.to_feather(path)

        result = self._run()

        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertFalse(self.output_dir.exists())
        source_record = next(row for row in result["source_files"] if row["pair"] == pair)
        self.assertGreater(source_record["missing_expected_timestamps"], 0)
        self.assertGreater(source_record["duplicate_timestamp_rows"], 0)
        self.assertEqual(source_record["nonfinite_ohlcv_cells"], 1)
        self.assertEqual(source_record["invalid_ohlc_rows"], 1)
        self.assertTrue((self.report_dir / canonical.REPORT_NAME).is_file())

    def test_auxiliary_gap_fails_closed_and_is_not_imputed(self) -> None:
        pair = canonical.PAIRS[1]
        path = self.source_dir / canonical.auxiliary_filename(pair, "funding_rate")
        frame = pd.read_feather(path).drop(index=2).reset_index(drop=True)
        frame.to_feather(path)

        result = self._run()

        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertFalse(self.output_dir.exists())
        record = next(
            row
            for row in result["auxiliary_source_files"]
            if row["pair"] == pair and row["kind"] == "funding_rate"
        )
        self.assertEqual(record["locked_window_missing_timestamps"], 1)
        self.assertEqual(record["locked_window_row_count_delta"], 1)

    def test_existing_snapshot_with_extra_native_ohlcv_is_never_overwritten(self) -> None:
        first = self._run()
        self.assertEqual(first["status"], "PASS")
        extra = self.output_dir / f"{canonical.PAIR_STEMS[canonical.PAIRS[0]]}-1d-futures.feather"
        pd.DataFrame({"forbidden_native": [1]}).to_feather(extra)
        original_5m_hash = canonical.sha256_file(
            self.output_dir / canonical.data_filename(canonical.PAIRS[0], "5m")
        )

        with self.assertRaisesRegex(canonical.PipelineError, "immutable canonical output conflict"):
            self._run()

        self.assertTrue(extra.exists())
        self.assertEqual(
            canonical.sha256_file(
                self.output_dir / canonical.data_filename(canonical.PAIRS[0], "5m")
            ),
            original_5m_hash,
        )
        self.assertFalse(any(self.output_dir.parent.glob(f".{self.output_dir.name}.stage-*")))


if __name__ == "__main__":
    unittest.main()
