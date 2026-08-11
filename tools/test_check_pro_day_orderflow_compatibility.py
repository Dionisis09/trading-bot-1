import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from freqtrade.data.converter.orderflow import populate_dataframe_with_trades

import check_pro_day_orderflow_compatibility as checker


def synthetic_trades(bucket_count: int = 14) -> pd.DataFrame:
    start = pd.Timestamp("2026-08-11T10:00:00Z")
    rows = []
    for bucket in range(bucket_count):
        bucket_start = start + pd.Timedelta(minutes=5 * bucket)
        for offset, side, amount in ((10, "buy", 2.0), (20, "sell", 0.5)):
            timestamp = int((bucket_start + pd.Timedelta(seconds=offset)).timestamp() * 1000)
            price = 100.0 + bucket
            rows.append(
                {
                    "timestamp": timestamp,
                    "id": str(bucket * 2 + offset),
                    "type": "None",
                    "side": side,
                    "price": price,
                    "amount": amount,
                    "cost": price * amount,
                }
            )
    return pd.DataFrame(rows, columns=checker.DEFAULT_TRADES_COLUMNS).astype(
        {
            "timestamp": "int64",
            "id": "str",
            "type": "str",
            "side": "str",
            "price": "float64",
            "amount": "float64",
            "cost": "float64",
        }
    )


def valid_config() -> dict:
    return {
        "timeframe": "5m",
        "orderflow": {
            "cache_size": 12,
            "max_candles": 12,
            "scale": 10.0,
            "stacked_imbalance_range": 3,
            "imbalance_volume": 1.0,
            "imbalance_ratio": 3.0,
        },
    }


class OrderflowCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input_path = self.root / "BTC_USDT_USDT-trades.feather"
        self.config_path = self.root / "config.json"
        self.report_path = self.root / "reports" / "orderflow_compatibility.json"
        synthetic_trades().to_feather(self.input_path)
        self.config_path.write_text(json.dumps(valid_config()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_selects_only_latest_twelve_utc_five_minute_buckets(self):
        selected, candles, metrics = checker.load_latest_trade_buckets(
            self.input_path,
            maximum_buckets=12,
        )

        self.assertEqual(len(candles), 12)
        self.assertEqual(len(selected), 24)
        self.assertEqual(metrics["input_rows"], 28)
        self.assertGreaterEqual(metrics["total_record_batches"], 1)
        self.assertLessEqual(
            metrics["tail_record_batches_scanned"],
            metrics["total_record_batches"],
        )
        self.assertEqual(metrics["tail_rows_materialized"], 24)
        self.assertEqual(checker.utc_iso(candles.iloc[0]["date"]), "2026-08-11T10:10:00Z")
        self.assertEqual(checker.utc_iso(candles.iloc[-1]["date"]), "2026-08-11T11:05:00Z")
        self.assertEqual(list(candles.columns), ["date"])
        self.assertTrue((selected["date"] >= candles.iloc[0]["date"]).all())

    def test_real_freqtrade_orderflow_passes_on_synthetic_data_and_writes_atomic_report(self):
        result = checker.run_compatibility_check(
            input_path=self.input_path,
            config_path=self.config_path,
            report_path=self.report_path,
            peak_rss_function=lambda: 123456,
        )

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["pnl_computed"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["backtest_run"])
        self.assertEqual(result["inputs"]["selected_bucket_count"], 12)
        self.assertEqual(result["inputs"]["selected_rows"], 24)
        self.assertEqual(result["results"]["populated_candles"], 12)
        self.assertEqual(result["results"]["total_trades"], 24)
        self.assertTrue(all(item["pass"] for item in result["checks"].values()))
        self.assertEqual(json.loads(self.report_path.read_text(encoding="utf-8"))["status"], "PASS")
        self.assertEqual(list(self.report_path.parent.glob("*.tmp")), [])

    def test_mock_wrapper_observes_minimal_candles_and_bounded_trades(self):
        observed = {}

        def observing_populate(cache, config, candles, trades):
            observed["columns"] = list(candles.columns)
            observed["buckets"] = len(candles)
            observed["trades"] = len(trades)
            observed["max_candles"] = config["orderflow"]["max_candles"]
            return populate_dataframe_with_trades(cache, config, candles, trades)

        with patch.object(
            checker.pd,
            "read_feather",
            side_effect=AssertionError("full Feather materialization is forbidden"),
        ):
            result = checker.run_compatibility_check(
                input_path=self.input_path,
                config_path=self.config_path,
                report_path=self.report_path,
                populate_function=observing_populate,
                peak_rss_function=lambda: 1,
            )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(observed, {
            "columns": ["date"],
            "buckets": 12,
            "trades": 24,
            "max_candles": 12,
        })

    def test_side_mismatch_fails_closed(self):
        def corrupt_delta(cache, config, candles, trades):
            output, grouped = populate_dataframe_with_trades(cache, config, candles, trades)
            output.loc[output.index[0], "delta"] += 1.0
            return output, grouped

        result = checker.run_compatibility_check(
            input_path=self.input_path,
            config_path=self.config_path,
            report_path=self.report_path,
            populate_function=corrupt_delta,
            peak_rss_function=lambda: 1,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["side_consistency"]["pass"])
        self.assertEqual(json.loads(self.report_path.read_text(encoding="utf-8"))["status"], "FAIL")

    def test_invalid_trade_schema_is_rejected(self):
        pd.DataFrame({"timestamp": [1]}).to_feather(self.input_path)
        with self.assertRaisesRegex(checker.CompatibilityError, "columns"):
            checker.run_compatibility_check(
                input_path=self.input_path,
                config_path=self.config_path,
                report_path=self.report_path,
                peak_rss_function=lambda: 1,
            )

    def test_more_than_twelve_requested_buckets_is_rejected(self):
        with self.assertRaisesRegex(checker.CompatibilityError, "cannot exceed 12"):
            checker.run_compatibility_check(
                input_path=self.input_path,
                config_path=self.config_path,
                report_path=self.report_path,
                maximum_buckets=13,
                peak_rss_function=lambda: 1,
            )

    def test_cli_missing_input_writes_failure_report_and_returns_two(self):
        missing = self.root / "missing.feather"
        exit_code = checker.main(
            [
                "--input",
                str(missing),
                "--config",
                str(self.config_path),
                "--report",
                str(self.report_path),
            ]
        )

        self.assertEqual(exit_code, 2)
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["pnl_computed"])
        self.assertEqual(report["error"]["type"], "CompatibilityError")


if __name__ == "__main__":
    unittest.main()
