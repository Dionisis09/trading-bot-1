import json
import io
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parent))
import download_recent_binance_aggtrades as downloader  # noqa: E402


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


def agg_row(identifier, timestamp, *, maker=False, price="100.5", amount="2", nq=True):
    row = {
        "a": identifier,
        "p": price,
        "q": amount,
        "f": identifier * 10,
        "l": identifier * 10 + 1,
        "T": timestamp,
        "m": maker,
    }
    if nq:
        row["nq"] = amount
    return row


def trade_frame(rows):
    return downloader.validate_trade_frame(
        pd.DataFrame(rows, columns=downloader.DEFAULT_TRADES_COLUMNS)
    )


def trade_row(identifier, timestamp, *, side="buy", price=100.5, amount=2.0):
    return {
        "timestamp": timestamp,
        "id": str(identifier),
        "type": "None",
        "side": side,
        "price": price,
        "amount": amount,
        "cost": price * amount,
    }


class LockedPublicEndpointTests(unittest.TestCase):
    def test_locked_host_endpoints_schema_and_default_path(self):
        self.assertEqual(downloader.BASE_URL, "https://fapi.binance.com")
        self.assertEqual(downloader.SERVER_TIME_PATH, "/fapi/v1/time")
        self.assertEqual(downloader.AGGTRADES_PATH, "/fapi/v1/aggTrades")
        self.assertEqual(downloader.SYMBOL, "BTCUSDT")
        self.assertEqual(
            downloader.DEFAULT_TRADES_COLUMNS,
            ["timestamp", "id", "type", "side", "price", "amount", "cost"],
        )
        feather, manifest = downloader.output_paths(downloader.DEFAULT_DATA_DIR)
        self.assertEqual(
            feather.as_posix(),
            "user_data/data/binance/futures/BTC_USDT_USDT-trades.feather",
        )
        self.assertEqual(manifest.name, "BTC_USDT_USDT-trades.manifest.json")

    def test_time_and_id_urls_have_exact_query_allowlists(self):
        time_url = downloader.build_url(downloader.SERVER_TIME_PATH, {})
        self.assertEqual(time_url, "https://fapi.binance.com/fapi/v1/time")
        window_url = downloader.build_url(
            downloader.AGGTRADES_PATH,
            {
                "symbol": "BTCUSDT",
                "startTime": 1_700_000_000_000,
                "endTime": 1_700_000_059_999,
                "limit": 1000,
            },
        )
        id_url = downloader.build_url(
            downloader.AGGTRADES_PATH,
            {"symbol": "BTCUSDT", "fromId": 123, "limit": 1000},
        )
        for url in (window_url, id_url):
            parsed = urllib.parse.urlsplit(url)
            query = urllib.parse.parse_qs(parsed.query)
            self.assertEqual(parsed.scheme, "https")
            self.assertEqual(parsed.netloc, "fapi.binance.com")
            self.assertEqual(parsed.path, "/fapi/v1/aggTrades")
            self.assertNotIn("signature", query)
            self.assertNotIn("apiKey", query)
            self.assertNotIn("recvWindow", query)

    def test_url_rejects_wrong_endpoint_symbol_limit_and_mixed_pagination(self):
        with self.assertRaises(downloader.ValidationError):
            downloader.build_url("/fapi/v1/account", {})
        with self.assertRaises(downloader.ValidationError):
            downloader.build_url(
                downloader.AGGTRADES_PATH,
                {"symbol": "ETHUSDT", "fromId": 1, "limit": 1000},
            )
        with self.assertRaises(downloader.ValidationError):
            downloader.build_url(
                downloader.AGGTRADES_PATH,
                {"symbol": "BTCUSDT", "fromId": 1, "limit": 999},
            )
        with self.assertRaises(downloader.ValidationError):
            downloader.build_url(
                downloader.AGGTRADES_PATH,
                {
                    "symbol": "BTCUSDT",
                    "fromId": 1,
                    "startTime": 2,
                    "endTime": 3,
                    "limit": 1000,
                },
            )

    def test_cli_default_is_bounded_to_one_hour_btc(self):
        args = downloader.build_parser().parse_args([])
        self.assertEqual(args.symbol, "BTCUSDT")
        self.assertEqual(args.window_minutes, 60)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                downloader.build_parser().parse_args(["--symbol", "ETHUSDT"])


class NetworkAndServerTimeTests(unittest.TestCase):
    def test_server_time_is_strict_and_request_has_no_credentials(self):
        observed = []

        def fake_open(request, timeout):
            observed.append((request, timeout))
            return FakeResponse({"serverTime": 1_700_000_000_000})

        value = downloader.get_server_time_ms(
            timeout_seconds=2,
            retries=0,
            backoff_seconds=0,
            opener=fake_open,
        )
        self.assertEqual(value, 1_700_000_000_000)
        request = observed[0][0]
        self.assertEqual(request.full_url, "https://fapi.binance.com/fapi/v1/time")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(set(headers), {"accept", "user-agent"})

    def test_invalid_server_time_schema_fails_closed(self):
        for payload in (
            [],
            {},
            {"serverTime": "1700000000000"},
            {"serverTime": True},
            {"serverTime": 1, "extra": 2},
        ):
            with self.subTest(payload=payload):
                with patch.object(downloader, "request_json", return_value=payload):
                    with self.assertRaises(downloader.ValidationError):
                        downloader.get_server_time_ms(
                            timeout_seconds=1, retries=0, backoff_seconds=0
                        )

    def test_transient_network_error_retries_with_backoff(self):
        calls = []
        sleeps = []

        def fake_open(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.URLError("temporary")
            return FakeResponse({"serverTime": 1_700_000_000_000})

        payload = downloader.request_json(
            downloader.SERVER_TIME_PATH,
            {},
            timeout_seconds=1,
            retries=2,
            backoff_seconds=0.25,
            opener=fake_open,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(payload["serverTime"], 1_700_000_000_000)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.25])


class AggTradeSchemaTests(unittest.TestCase):
    def setUp(self):
        self.server_time = 1_700_000_100_000
        self.timestamp = self.server_time - 1_000

    def test_transform_matches_freqtrade_columns_and_taker_side(self):
        rows = downloader.parse_aggtrade_payload(
            [
                agg_row(10, self.timestamp, maker=False, price="100.5", amount="2"),
                agg_row(11, self.timestamp, maker=True, price="101", amount="0.5"),
            ],
            server_time_ms=self.server_time,
        )
        self.assertEqual(list(rows[0]), downloader.DEFAULT_TRADES_COLUMNS)
        self.assertEqual(rows[0]["id"], "10")
        self.assertEqual(rows[0]["type"], "None")
        self.assertEqual(rows[0]["side"], "buy")
        self.assertEqual(rows[1]["side"], "sell")
        self.assertEqual(rows[0]["cost"], 201.0)
        self.assertEqual(rows[1]["cost"], 50.5)

    def test_optional_normal_quantity_is_validated_but_not_stored(self):
        row = agg_row(10, self.timestamp, nq=False)
        parsed = downloader.parse_aggtrade_payload(
            [row], server_time_ms=self.server_time
        )
        self.assertNotIn("nq", parsed[0])
        row["nq"] = "NaN"
        with self.assertRaises(downloader.ValidationError):
            downloader.parse_aggtrade_payload([row], server_time_ms=self.server_time)

    def test_schema_ids_timestamps_maker_and_numerics_fail_closed(self):
        valid = agg_row(10, self.timestamp)
        invalid_rows = [
            {key: value for key, value in valid.items() if key != "a"},
            {**valid, "unexpected": 1},
            {**valid, "a": True},
            {**valid, "f": 20, "l": 19},
            {**valid, "T": self.server_time + 1_001},
            {**valid, "m": 1},
            {**valid, "p": "NaN"},
            {**valid, "p": "0"},
            {**valid, "q": "-1"},
        ]
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(downloader.ValidationError):
                    downloader.parse_aggtrade_payload(
                        [row], server_time_ms=self.server_time
                    )

    def test_noncontiguous_ids_and_reverse_timestamps_fail_closed(self):
        with self.assertRaisesRegex(downloader.ValidationError, "not contiguous"):
            downloader.parse_aggtrade_payload(
                [agg_row(10, self.timestamp), agg_row(12, self.timestamp + 1)],
                server_time_ms=self.server_time,
            )
        with self.assertRaisesRegex(downloader.ValidationError, "not monotonic"):
            downloader.parse_aggtrade_payload(
                [agg_row(10, self.timestamp), agg_row(11, self.timestamp - 1)],
                server_time_ms=self.server_time,
            )


class StrictPaginationTests(unittest.TestCase):
    def setUp(self):
        self.start = 1_700_000_000_000
        self.end = self.start + 100_000
        self.server_time = self.end

    def test_seed_probe_shrinks_when_1000_rows_would_be_truncated(self):
        observed = []
        full_page = [
            agg_row(identifier, self.start + 1)
            for identifier in range(1000, 2000)
        ]
        complete_page = [
            agg_row(2000, self.start + 1),
            agg_row(2001, self.start + 2),
        ]

        def fake_request(path, params, **_kwargs):
            observed.append((path, params.copy()))
            return full_page if len(observed) == 1 else complete_page

        with patch.object(downloader, "request_json", side_effect=fake_request):
            identifier = downloader.find_first_aggregate_id(
                start_ms=self.start,
                end_ms=self.end,
                server_time_ms=self.server_time,
                timeout_seconds=1,
                retries=0,
                backoff_seconds=0,
            )
        self.assertEqual(identifier, 2000)
        first_span = observed[0][1]["endTime"] - observed[0][1]["startTime"]
        second_span = observed[1][1]["endTime"] - observed[1][1]["startTime"]
        self.assertLess(second_span, first_span)
        self.assertEqual(observed[0][1]["limit"], 1000)

    def test_id_pagination_is_contiguous_and_stops_after_window_end(self):
        first_page = [
            agg_row(identifier, self.start + (identifier - 100))
            for identifier in range(100, 1100)
        ]
        second_page = [
            agg_row(1100, self.end - 1),
            agg_row(1101, self.end + 1),
        ]
        observed = []

        def fake_request(path, params, **_kwargs):
            observed.append(params.copy())
            return first_page if len(observed) == 1 else second_page

        with patch.object(downloader, "find_first_aggregate_id", return_value=100):
            with patch.object(downloader, "request_json", side_effect=fake_request):
                with patch.object(
                    downloader,
                    "get_server_time_ms",
                    return_value=self.server_time + 1,
                ):
                    frame = downloader.fetch_recent_window(
                        start_ms=self.start,
                        end_ms=self.end,
                        server_time_ms=self.server_time,
                        timeout_seconds=1,
                        retries=0,
                        backoff_seconds=0,
                    )
        self.assertEqual(len(frame), 1001)
        self.assertEqual(frame.iloc[0]["id"], "100")
        self.assertEqual(frame.iloc[-1]["id"], "1100")
        self.assertEqual(observed[0]["fromId"], 100)
        self.assertEqual(observed[1]["fromId"], 1100)

    def test_fresh_final_server_time_allows_market_to_advance_during_pagination(self):
        # Regression: a real 60m run took ~21 seconds.  The first trade beyond
        # the immutable window end is expected to be newer than the initial
        # serverTime, but must be no newer than a fresh final serverTime.
        page = [
            agg_row(100, self.end - 1),
            agg_row(101, self.end + 21_000),
        ]
        with patch.object(downloader, "find_first_aggregate_id", return_value=100):
            with patch.object(downloader, "request_json", return_value=page):
                with patch.object(
                    downloader,
                    "get_server_time_ms",
                    return_value=self.end + 22_000,
                ) as final_time:
                    frame = downloader.fetch_recent_window(
                        start_ms=self.start,
                        end_ms=self.end,
                        server_time_ms=self.end,
                        timeout_seconds=1,
                        retries=0,
                        backoff_seconds=0,
                    )
        self.assertEqual(frame["id"].tolist(), ["100"])
        final_time.assert_called_once()

    def test_final_server_time_advance_is_bounded(self):
        page = [agg_row(100, self.end - 1)]
        with patch.object(downloader, "find_first_aggregate_id", return_value=100):
            with patch.object(downloader, "request_json", return_value=page):
                with patch.object(
                    downloader,
                    "get_server_time_ms",
                    return_value=(
                        self.end
                        + downloader.MAX_COLLECTION_SERVER_ADVANCE_MILLISECONDS
                        + 1
                    ),
                ):
                    with self.assertRaisesRegex(
                        downloader.ValidationError, "bounded collection window"
                    ):
                        downloader.fetch_recent_window(
                            start_ms=self.start,
                            end_ms=self.end,
                            server_time_ms=self.end,
                            timeout_seconds=1,
                            retries=0,
                            backoff_seconds=0,
                        )

    def test_stale_final_server_time_rejects_observed_future_trade(self):
        page = [
            agg_row(100, self.end - 1),
            agg_row(101, self.end + 5_000),
        ]
        with patch.object(downloader, "find_first_aggregate_id", return_value=100):
            with patch.object(downloader, "request_json", return_value=page):
                with patch.object(
                    downloader, "get_server_time_ms", return_value=self.end
                ):
                    with self.assertRaisesRegex(
                        downloader.ValidationError, "future timestamp"
                    ):
                        downloader.fetch_recent_window(
                            start_ms=self.start,
                            end_ms=self.end,
                            server_time_ms=self.end,
                            timeout_seconds=1,
                            retries=0,
                            backoff_seconds=0,
                        )

    def test_wrong_first_id_fails_closed(self):
        with patch.object(downloader, "find_first_aggregate_id", return_value=100):
            with patch.object(
                downloader,
                "request_json",
                return_value=[agg_row(101, self.start + 1)],
            ):
                with self.assertRaisesRegex(downloader.ValidationError, "requested ID"):
                    downloader.fetch_recent_window(
                        start_ms=self.start,
                        end_ms=self.end,
                        server_time_ms=self.server_time,
                        timeout_seconds=1,
                        retries=0,
                        backoff_seconds=0,
                    )


class FeatherUpsertTests(unittest.TestCase):
    def setUp(self):
        self.server_time = 1_700_000_100_000

    def test_atomic_feather_upsert_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "futures"
            first = trade_frame(
                [
                    trade_row(10, self.server_time - 5_000),
                    trade_row(11, self.server_time - 4_000, side="sell"),
                ]
            )
            with patch.object(
                downloader, "get_server_time_ms", return_value=self.server_time
            ):
                with patch.object(
                    downloader, "fetch_recent_window", return_value=first
                ):
                    manifest = downloader.collect_once(data_dir)
            feather_path, manifest_path = downloader.output_paths(data_dir)
            stored = pd.read_feather(feather_path)
            self.assertEqual(list(stored.columns), downloader.DEFAULT_TRADES_COLUMNS)
            self.assertEqual(str(stored["timestamp"].dtype), "int64")
            self.assertEqual(str(stored["price"].dtype), "float64")
            self.assertEqual(manifest["row_count"], 2)
            self.assertEqual(manifest["incoming_row_count"], 2)
            self.assertEqual(manifest["sha256"], downloader.sha256_file(feather_path))
            disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(disk_manifest, manifest)
            with patch.object(
                downloader,
                "request_json",
                side_effect=AssertionError("healthcheck must remain offline"),
            ):
                health = downloader.healthcheck(
                    data_dir,
                    now_ms=self.server_time + 60_000,
                    max_age_minutes=120,
                )
            self.assertEqual(health["status"], "HEALTHY")
            self.assertEqual(health["row_count"], 2)

            second = trade_frame(
                [
                    trade_row(11, self.server_time - 4_000, side="sell"),
                    trade_row(12, self.server_time - 3_000),
                ]
            )
            with patch.object(
                downloader, "get_server_time_ms", return_value=self.server_time
            ):
                with patch.object(
                    downloader, "fetch_recent_window", return_value=second
                ):
                    updated_manifest = downloader.collect_once(data_dir)
            updated = pd.read_feather(feather_path)
            self.assertEqual(updated["id"].tolist(), ["10", "11", "12"])
            self.assertEqual(updated_manifest["row_count"], 3)
            self.assertEqual(updated_manifest["incoming_row_count"], 2)

    def test_healthcheck_detects_hash_tamper_and_staleness(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "futures"
            incoming = trade_frame(
                [
                    trade_row(10, self.server_time - 2_000),
                    trade_row(11, self.server_time - 1_000),
                ]
            )
            with patch.object(
                downloader, "get_server_time_ms", return_value=self.server_time
            ), patch.object(
                downloader, "fetch_recent_window", return_value=incoming
            ):
                downloader.collect_once(data_dir)
            stale = downloader.healthcheck(
                data_dir,
                now_ms=self.server_time + 121 * 60_000,
                max_age_minutes=120,
            )
            self.assertEqual(stale["status"], "UNHEALTHY")
            self.assertIn("stale", stale["error_message"])
            feather_path, _ = downloader.output_paths(data_dir)
            feather_path.write_bytes(feather_path.read_bytes() + b"tamper")
            tampered = downloader.healthcheck(
                data_dir,
                now_ms=self.server_time + 60_000,
                max_age_minutes=120,
            )
            self.assertEqual(tampered["status"], "UNHEALTHY")
            self.assertIn("SHA256", tampered["error_message"])

    def test_invalid_increment_fails_before_feather_or_manifest_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "futures"
            initial = trade_frame(
                [
                    trade_row(10, self.server_time - 5_000),
                    trade_row(11, self.server_time - 4_000),
                ]
            )
            with patch.object(
                downloader, "get_server_time_ms", return_value=self.server_time
            ), patch.object(
                downloader, "fetch_recent_window", return_value=initial
            ):
                downloader.collect_once(data_dir)
            feather_path, manifest_path = downloader.output_paths(data_dir)
            before_feather = feather_path.read_bytes()
            before_manifest = manifest_path.read_bytes()
            invalid_gap = trade_frame([trade_row(15, self.server_time - 1_000)])
            with patch.object(
                downloader, "get_server_time_ms", return_value=self.server_time
            ), patch.object(
                downloader, "fetch_recent_window", return_value=invalid_gap
            ):
                with self.assertRaisesRegex(downloader.ValidationError, "not contiguous"):
                    downloader.collect_once(data_dir)
            self.assertEqual(feather_path.read_bytes(), before_feather)
            self.assertEqual(manifest_path.read_bytes(), before_manifest)

    def test_duplicate_ids_nonfinite_values_and_bad_cost_fail_closed(self):
        valid = trade_row(10, self.server_time - 1_000)
        cases = [
            [valid, valid],
            [{**valid, "price": float("nan")}],
            [{**valid, "cost": 999.0}],
            [{**valid, "side": "maker"}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                with self.assertRaises(downloader.ValidationError):
                    downloader.validate_trade_frame(
                        pd.DataFrame(rows, columns=downloader.DEFAULT_TRADES_COLUMNS)
                    )

    def test_corrupt_existing_feather_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "futures"
            feather_path, manifest_path = downloader.output_paths(data_dir)
            feather_path.parent.mkdir(parents=True)
            pd.DataFrame({"wrong": [1]}).to_feather(feather_path)
            original = feather_path.read_bytes()
            incoming = trade_frame([trade_row(10, self.server_time - 1_000)])
            with patch.object(
                downloader, "get_server_time_ms", return_value=self.server_time
            ), patch.object(
                downloader, "fetch_recent_window", return_value=incoming
            ):
                with self.assertRaises(downloader.ValidationError):
                    downloader.collect_once(data_dir)
            self.assertEqual(feather_path.read_bytes(), original)
            self.assertFalse(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
