import csv
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_binance_derivatives as collector  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, _size=-1):
        return self.payload


def api_row(spec, symbol, timestamp_ms, value="1"):
    if spec is collector.OPEN_INTEREST:
        return {
            "symbol": symbol,
            "sumOpenInterest": value,
            "sumOpenInterestValue": str(int(value) * 10),
            "CMCCirculatingSupply": "1000.0000",
            "timestamp": timestamp_ms,
        }
    return {
        "buySellRatio": value,
        "buyVol": str(int(value) * 2),
        "sellVol": "2.0000",
        "timestamp": timestamp_ms,
    }


class LockedEndpointTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        self.now_ms = collector.datetime_to_ms(self.now)

    def test_locked_matrix_and_exact_public_https_endpoints(self):
        self.assertEqual(collector.BASE_URL, "https://fapi.binance.com")
        self.assertEqual(
            [spec.path for spec in collector.ENDPOINTS],
            [
                "/futures/data/openInterestHist",
                "/futures/data/takerlongshortRatio",
            ],
        )
        self.assertEqual(
            collector.SYMBOLS, ("BTCUSDT", "ETHUSDT", "BNBUSDT")
        )
        self.assertEqual(collector.PERIODS, ("5m", "15m", "1h", "4h"))

    def test_url_has_exact_host_limit_and_no_credential_parameters(self):
        params = {
            "symbol": "BTCUSDT",
            "period": "5m",
            "limit": 500,
            "startTime": self.now_ms - 1000,
            "endTime": self.now_ms,
        }
        url = collector.build_url(collector.OPEN_INTEREST.path, params)
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "fapi.binance.com")
        self.assertEqual(parsed.path, "/futures/data/openInterestHist")
        self.assertEqual(query["limit"], ["500"])
        self.assertNotIn("signature", query)
        self.assertNotIn("timestamp", query)
        self.assertNotIn("apiKey", query)

    def test_url_rejects_non_allowlisted_path_identity_and_limit(self):
        base = {
            "symbol": "BTCUSDT",
            "period": "5m",
            "limit": 500,
            "startTime": self.now_ms - 1000,
            "endTime": self.now_ms,
        }
        with self.assertRaises(collector.ValidationError):
            collector.build_url("/fapi/v1/account", base)
        with self.assertRaises(collector.ValidationError):
            collector.build_url(
                collector.OPEN_INTEREST.path, {**base, "symbol": "XRPUSDT"}
            )
        with self.assertRaises(collector.ValidationError):
            collector.build_url(collector.OPEN_INTEREST.path, {**base, "limit": 499})


class SchemaValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        self.now_ms = collector.datetime_to_ms(self.now)
        self.timestamp = self.now_ms - 300_000

    def test_open_interest_schema_is_canonical_utc_and_finite(self):
        rows = collector.parse_api_payload(
            collector.OPEN_INTEREST,
            "BTCUSDT",
            "5m",
            [api_row(collector.OPEN_INTEREST, "BTCUSDT", self.timestamp, "2")],
            now_ms=self.now_ms,
        )
        self.assertEqual(rows[0]["timestamp_utc"], "2026-08-11T11:55:00.000Z")
        self.assertEqual(rows[0]["sum_open_interest"], "2")
        self.assertEqual(rows[0]["sum_open_interest_value"], "20")
        self.assertEqual(rows[0]["cmc_circulating_supply"], "1000")

    def test_taker_schema_injects_locked_identity(self):
        rows = collector.parse_api_payload(
            collector.TAKER_BUY_SELL,
            "ETHUSDT",
            "15m",
            [api_row(collector.TAKER_BUY_SELL, "ETHUSDT", self.timestamp, "3")],
            now_ms=self.now_ms,
        )
        self.assertEqual(rows[0]["symbol"], "ETHUSDT")
        self.assertEqual(rows[0]["period"], "15m")
        self.assertEqual(rows[0]["buy_sell_ratio"], "3")

    def test_missing_extra_wrong_symbol_and_nonfinite_fields_fail_closed(self):
        valid = api_row(
            collector.OPEN_INTEREST, "BTCUSDT", self.timestamp, "1"
        )
        for invalid in (
            {key: value for key, value in valid.items() if key != "sumOpenInterest"},
            {**valid, "unexpected": "1"},
            {**valid, "symbol": "ETHUSDT"},
            {**valid, "sumOpenInterest": "NaN"},
            {**valid, "sumOpenInterest": "Infinity"},
            {**valid, "sumOpenInterest": "-1"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(collector.ValidationError):
                    collector.parse_api_payload(
                        collector.OPEN_INTEREST,
                        "BTCUSDT",
                        "5m",
                        [invalid],
                        now_ms=self.now_ms,
                    )

    def test_duplicate_and_future_timestamps_fail_closed(self):
        row = api_row(
            collector.TAKER_BUY_SELL, "BTCUSDT", self.timestamp, "1"
        )
        with self.assertRaisesRegex(collector.ValidationError, "duplicate"):
            collector.parse_api_payload(
                collector.TAKER_BUY_SELL,
                "BTCUSDT",
                "5m",
                [row, row],
                now_ms=self.now_ms,
            )
        future = api_row(
            collector.TAKER_BUY_SELL,
            "BTCUSDT",
            self.now_ms + collector.MAX_FUTURE_SKEW_MILLISECONDS + 1,
            "1",
        )
        with self.assertRaisesRegex(collector.ValidationError, "future"):
            collector.parse_api_payload(
                collector.TAKER_BUY_SELL,
                "BTCUSDT",
                "5m",
                [future],
                now_ms=self.now_ms,
            )

    def test_json_decoder_rejects_duplicate_keys_and_nonfinite_constants(self):
        with self.assertRaises(collector.ValidationError):
            collector._decode_json(b'{"x":1,"x":2}')
        with self.assertRaises(collector.ValidationError):
            collector._decode_json(b'[NaN]')

    def test_csv_duplicate_and_inconsistent_utc_fail_closed(self):
        row = collector.parse_api_payload(
            collector.TAKER_BUY_SELL,
            "BTCUSDT",
            "5m",
            [api_row(collector.TAKER_BUY_SELL, "BTCUSDT", self.timestamp)],
            now_ms=self.now_ms,
        )[0]
        with self.assertRaisesRegex(collector.ValidationError, "duplicate"):
            collector.validate_rows(
                collector.TAKER_BUY_SELL,
                "BTCUSDT",
                "5m",
                [row, row],
                now_ms=self.now_ms,
            )
        with self.assertRaisesRegex(collector.ValidationError, "inconsistent UTC"):
            collector.validate_rows(
                collector.TAKER_BUY_SELL,
                "BTCUSDT",
                "5m",
                [{**row, "timestamp_utc": "2026-08-11T00:00:00.000Z"}],
                now_ms=self.now_ms,
            )


class NetworkAndPaginationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        self.now_ms = collector.datetime_to_ms(self.now)

    def test_request_retries_with_exponential_backoff(self):
        calls = []
        sleeps = []

        def fake_open(request, timeout):
            calls.append((request, timeout))
            if len(calls) == 1:
                raise urllib.error.URLError("temporary")
            return FakeResponse([])

        result = collector.request_json(
            collector.OPEN_INTEREST.path,
            {
                "symbol": "BTCUSDT",
                "period": "5m",
                "limit": 500,
                "startTime": self.now_ms - 1000,
                "endTime": self.now_ms,
            },
            timeout_seconds=2.0,
            retries=2,
            backoff_seconds=0.25,
            opener=fake_open,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(result, [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.25])
        request = calls[-1][0]
        self.assertEqual(request.host, "fapi.binance.com")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(set(headers), {"accept", "user-agent"})

    def test_non_retryable_http_error_fails_immediately(self):
        calls = []

        def fake_open(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(
                request.full_url, 400, "bad request", {}, None
            )

        with self.assertRaises(collector.NetworkError):
            collector.request_json(
                collector.OPEN_INTEREST.path,
                {
                    "symbol": "BTCUSDT",
                    "period": "5m",
                    "limit": 500,
                    "startTime": self.now_ms - 1000,
                    "endTime": self.now_ms,
                },
                timeout_seconds=2,
                retries=4,
                backoff_seconds=0,
                opener=fake_open,
            )
        self.assertEqual(len(calls), 1)

    def test_initial_window_paginates_backward_with_max_500(self):
        period_ms = collector.PERIOD_SECONDS["5m"] * 1000
        start_ms = self.now_ms - 502 * period_ms
        timestamps = [start_ms + index * period_ms for index in range(502)]
        # The live endpoints return the newest 500 rows from a wide range.
        pages = [
            [
                api_row(collector.OPEN_INTEREST, "BTCUSDT", timestamp)
                for timestamp in timestamps[2:]
            ],
            [
                api_row(collector.OPEN_INTEREST, "BTCUSDT", timestamp)
                for timestamp in timestamps[:2]
            ],
        ]
        observed_params = []

        def fake_request(path, params, **_kwargs):
            self.assertEqual(path, "/futures/data/openInterestHist")
            observed_params.append(params.copy())
            return pages[len(observed_params) - 1]

        with patch.object(collector, "request_json", side_effect=fake_request):
            rows = collector.fetch_series(
                collector.OPEN_INTEREST,
                "BTCUSDT",
                "5m",
                start_ms=start_ms,
                end_ms=self.now_ms,
                now_ms=self.now_ms,
                timeout_seconds=1,
                retries=0,
                backoff_seconds=0,
            )
        self.assertEqual(len(rows), 502)
        self.assertEqual([item["limit"] for item in observed_params], [500, 500])
        self.assertEqual(observed_params[0]["startTime"], start_ms)
        self.assertEqual(
            observed_params[1]["startTime"], start_ms
        )
        self.assertEqual(
            observed_params[1]["endTime"], timestamps[2] - 1
        )


class AtomicUpsertAndHealthcheckTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        self.now_ms = collector.datetime_to_ms(self.now)

    def fake_fetch(self, value, calls=None):
        def implementation(
            spec,
            symbol,
            period,
            *,
            start_ms,
            end_ms,
            now_ms,
            **_kwargs,
        ):
            if calls is not None:
                calls.append((spec.name, symbol, period, start_ms, end_ms))
            timestamp = now_ms - collector.PERIOD_SECONDS[period] * 1000
            return collector.parse_api_payload(
                spec,
                symbol,
                period,
                [api_row(spec, symbol, timestamp, value)],
                now_ms=now_ms,
            )

        return implementation

    def test_initial_30_day_matrix_atomic_upsert_manifest_and_healthcheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "derivatives"
            first_calls = []
            with patch.object(
                collector, "fetch_series", side_effect=self.fake_fetch("1", first_calls)
            ):
                status = collector.collect_once(output, now=self.now)
            self.assertEqual(status["status"], "READY")
            self.assertEqual(len(first_calls), 24)
            expected_start = self.now_ms - collector.RETENTION_MILLISECONDS
            self.assertTrue(all(call[3] == expected_start for call in first_calls))

            manifest = json.loads(
                (output / collector.MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["dataset_count"], 24)
            self.assertTrue(manifest["all_fresh"])
            self.assertEqual(len(manifest["datasets"]), 24)
            for entry in manifest["datasets"]:
                dataset_path = output / entry["file"]
                self.assertEqual(collector.sha256_file(dataset_path), entry["sha256"])
                self.assertEqual(entry["row_count"], 1)

            check = collector.healthcheck(output, now=self.now)
            self.assertEqual(check["status"], "HEALTHY")
            self.assertEqual(check["dataset_count"], 24)

            second_calls = []
            with patch.object(
                collector, "fetch_series", side_effect=self.fake_fetch("2", second_calls)
            ):
                collector.collect_once(output, now=self.now)
            self.assertEqual(len(second_calls), 24)
            for _name, _symbol, period, start_ms, _end_ms in second_calls:
                latest = self.now_ms - collector.PERIOD_SECONDS[period] * 1000
                expected = latest - (
                    collector.INCREMENTAL_OVERLAP_PERIODS
                    * collector.PERIOD_SECONDS[period]
                    * 1000
                )
                self.assertEqual(start_ms, expected)

            path = output / collector.dataset_filename(
                collector.OPEN_INTEREST, "BTCUSDT", "5m"
            )
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sum_open_interest"], "2")
            self.assertEqual(collector.healthcheck(output, now=self.now)["status"], "HEALTHY")

    def test_validation_failure_before_commit_preserves_all_csvs_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "derivatives"
            with patch.object(
                collector, "fetch_series", side_effect=self.fake_fetch("1")
            ):
                collector.collect_once(output, now=self.now)
            before = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.suffix == ".csv" or path.name == collector.MANIFEST_FILENAME
            }
            call_count = 0
            valid_fetch = self.fake_fetch("2")

            def failing_fetch(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 12:
                    raise collector.ValidationError("synthetic schema failure")
                return valid_fetch(*args, **kwargs)

            with patch.object(collector, "fetch_series", side_effect=failing_fetch):
                with self.assertRaisesRegex(collector.ValidationError, "synthetic"):
                    collector.collect_once(output, now=self.now)
            after = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.suffix == ".csv" or path.name == collector.MANIFEST_FILENAME
            }
            self.assertEqual(after, before)

    def test_hash_tamper_staleness_and_error_status_are_unhealthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "derivatives"
            with patch.object(
                collector, "fetch_series", side_effect=self.fake_fetch("1")
            ):
                collector.collect_once(output, now=self.now)

            path = output / collector.dataset_filename(
                collector.TAKER_BUY_SELL, "ETHUSDT", "15m"
            )
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            tampered = collector.healthcheck(output, now=self.now)
            self.assertEqual(tampered["status"], "UNHEALTHY")
            self.assertIn("hash mismatch", tampered["error_message"])
            path.write_bytes(original)

            stale_time = self.now + timedelta(hours=9)
            stale = collector.healthcheck(output, now=stale_time)
            self.assertEqual(stale["status"], "UNHEALTHY")
            self.assertIn("stale", stale["error_message"])

            error_status = collector.record_failure_status(
                output,
                collector.NetworkError("network unavailable"),
                now=self.now + timedelta(minutes=1),
            )
            self.assertEqual(error_status["status"], "ERROR")
            self.assertEqual(error_status["last_success_utc"], "2026-08-11T12:00:00.000Z")
            self.assertEqual(
                collector.healthcheck(output, now=self.now)["status"], "UNHEALTHY"
            )

    def test_stale_candidate_fails_before_any_csv_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "derivatives"

            def stale_fetch(spec, symbol, period, *, now_ms, **_kwargs):
                timestamp = now_ms - 24 * 60 * 60 * 1000
                return collector.parse_api_payload(
                    spec,
                    symbol,
                    period,
                    [api_row(spec, symbol, timestamp)],
                    now_ms=now_ms,
                )

            with patch.object(collector, "fetch_series", side_effect=stale_fetch):
                with self.assertRaisesRegex(collector.ValidationError, "freshness"):
                    collector.collect_once(output, now=self.now)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
