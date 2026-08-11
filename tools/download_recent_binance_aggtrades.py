#!/usr/bin/env python3
"""Download a bounded public Binance USD-M aggregate-trades window.

This is a credential-free local order-flow fallback for a small BTC benchmark.
It does not alter Freqtrade configuration and does not run a backtest.  Output
uses Freqtrade 2026.7's exact DEFAULT_TRADES_COLUMNS Feather schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import numbers
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd


SCHEMA_VERSION = 1
COLLECTOR_NAME = "binance_usdm_recent_aggtrades"
API_SCHEME = "https"
API_HOST = "fapi.binance.com"
BASE_URL = f"{API_SCHEME}://{API_HOST}"
SERVER_TIME_PATH = "/fapi/v1/time"
AGGTRADES_PATH = "/fapi/v1/aggTrades"

SYMBOL = "BTCUSDT"
FREQTRADE_PAIR = "BTC/USDT:USDT"
DEFAULT_TRADES_COLUMNS = [
    "timestamp",
    "id",
    "type",
    "side",
    "price",
    "amount",
    "cost",
]
TRADES_DTYPES = {
    "timestamp": "int64",
    "id": "str",
    "type": "str",
    "side": "str",
    "price": "float64",
    "amount": "float64",
    "cost": "float64",
}

DEFAULT_WINDOW_MINUTES = 60
MIN_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 90
DEFAULT_HEALTH_MAX_AGE_MINUTES = 120
PAGE_LIMIT = 1000
INITIAL_PROBE_MILLISECONDS = 60_000
MAX_ID_PAGES = 200
MAX_PROBE_REQUESTS = 500
MAX_FUTURE_SKEW_MILLISECONDS = 1_000
MAX_COLLECTION_SERVER_ADVANCE_MILLISECONDS = 10 * 60 * 1000
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

DEFAULT_DATA_DIR = Path("user_data/data/binance/futures")
FEATHER_FILENAME = "BTC_USDT_USDT-trades.feather"
MANIFEST_FILENAME = "BTC_USDT_USDT-trades.manifest.json"

MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "collector",
        "credential_mode",
        "api_scheme",
        "api_host",
        "server_time_endpoint",
        "aggregate_trades_endpoint",
        "symbol",
        "freqtrade_pair",
        "window_minutes",
        "window_start_ms",
        "window_start_utc",
        "window_end_ms",
        "window_end_utc",
        "generated_utc",
        "output_file",
        "sha256",
        "columns",
        "dtypes",
        "row_count",
        "incoming_row_count",
        "min_timestamp_ms",
        "min_timestamp_utc",
        "max_timestamp_ms",
        "max_timestamp_utc",
        "min_aggregate_id",
        "max_aggregate_id",
        "side_semantics",
        "status",
    }
)

REQUIRED_AGGTRADE_FIELDS = frozenset({"a", "p", "q", "f", "l", "T", "m"})
# Binance added normal quantity (excluding RPI trades) to the documented
# response.  It is validated when present but is not part of Freqtrade's schema.
OPTIONAL_AGGTRADE_FIELDS = frozenset({"nq"})


class DownloadError(RuntimeError):
    """Base exception for a fail-closed downloader error."""


class ValidationError(DownloadError):
    """Remote or local data violated a locked invariant."""


class NetworkError(DownloadError):
    """A bounded public HTTPS request failed."""


def iso_utc_ms(timestamp_ms: int) -> str:
    try:
        value = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError) as exc:
        raise ValidationError("timestamp is outside the supported UTC range") from exc
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def output_paths(data_dir: Path | str) -> tuple[Path, Path]:
    root = Path(data_dir)
    return root / FEATHER_FILENAME, root / MANIFEST_FILENAME


def build_url(path: str, params: dict[str, Any]) -> str:
    if path == SERVER_TIME_PATH:
        if params:
            raise ValidationError("server-time endpoint does not accept query parameters")
    elif path == AGGTRADES_PATH:
        keys = set(params)
        time_keys = {"symbol", "startTime", "endTime", "limit"}
        id_keys = {"symbol", "fromId", "limit"}
        if keys not in (time_keys, id_keys):
            raise ValidationError("aggregate-trades query schema is not allowlisted")
        if params.get("symbol") != SYMBOL or params.get("limit") != PAGE_LIMIT:
            raise ValidationError("aggregate-trades identity/limit is not locked")
        if keys == time_keys:
            start_ms = params["startTime"]
            end_ms = params["endTime"]
            if (
                not _is_plain_int(start_ms)
                or not _is_plain_int(end_ms)
                or start_ms <= 0
                or start_ms > end_ms
                or end_ms - start_ms >= 60 * 60 * 1000
            ):
                raise ValidationError("aggregate-trades time window is invalid")
        else:
            from_id = params["fromId"]
            if not _is_plain_int(from_id) or from_id < 0:
                raise ValidationError("fromId must be a non-negative integer")
    else:
        raise ValidationError("endpoint is outside the public allowlist")

    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != API_SCHEME
        or parsed.hostname != API_HOST
        or parsed.netloc != API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValidationError("URL is not the exact Binance public HTTPS host")
    return url


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON response contains a duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValidationError(f"JSON response contains non-finite constant {value}")


def decode_json(payload: bytes) -> Any:
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_json_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValidationError("response is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError("response is not valid JSON") from exc


def _retryable_http_status(status: int) -> bool:
    return status in {408, 418, 425, 429} or 500 <= status <= 599


def request_json(
    path: str,
    params: dict[str, Any],
    *,
    timeout_seconds: float,
    retries: int,
    backoff_seconds: float,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Any:
    if timeout_seconds <= 0 or retries < 0 or backoff_seconds < 0:
        raise ValidationError("network retry settings are invalid")
    request = urllib.request.Request(
        build_url(path, params),
        headers={
            "Accept": "application/json",
            "User-Agent": "pro-day-trader-aggtrades/1.0",
        },
        method="GET",
    )
    open_url = opener or urllib.request.urlopen
    for attempt in range(retries + 1):
        try:
            with open_url(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    if attempt < retries and _retryable_http_status(status):
                        delay = backoff_seconds * (2**attempt)
                        if delay:
                            sleep_fn(delay)
                        continue
                    raise NetworkError(f"unexpected HTTP status {status}")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValidationError("response exceeds the bounded payload size")
            return decode_json(payload)
        except urllib.error.HTTPError as exc:
            if attempt >= retries or not _retryable_http_status(int(exc.code)):
                raise NetworkError(f"Binance HTTPS request failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise NetworkError(
                    f"Binance HTTPS request failed after {retries + 1} attempt(s)"
                ) from exc

        delay = backoff_seconds * (2**attempt)
        if delay:
            sleep_fn(delay)
    raise AssertionError("unreachable retry state")


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def get_server_time_ms(
    *,
    timeout_seconds: float,
    retries: int,
    backoff_seconds: float,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    payload = request_json(
        SERVER_TIME_PATH,
        {},
        timeout_seconds=timeout_seconds,
        retries=retries,
        backoff_seconds=backoff_seconds,
        opener=opener,
        sleep_fn=sleep_fn,
    )
    if not isinstance(payload, dict) or set(payload) != {"serverTime"}:
        raise ValidationError("Binance server-time response has an unexpected schema")
    value = payload["serverTime"]
    if not _is_plain_int(value) or value <= 0:
        raise ValidationError("Binance serverTime must be a positive integer")
    iso_utc_ms(int(value))
    return int(value)


def _positive_decimal(value: Any, field: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128:
        raise ValidationError(f"{field} must be a bounded decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{field} is not a decimal number") from exc
    if not number.is_finite() or (number < 0 if allow_zero else number <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValidationError(f"{field} must be finite and {qualifier}")
    if number and abs(number.adjusted()) > 50:
        raise ValidationError(f"{field} exceeds the numeric schema bound")
    return number


def parse_aggtrade_payload(
    payload: Any,
    *,
    server_time_ms: int,
    lower_timestamp_ms: int | None = None,
    upper_timestamp_ms: int | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValidationError("aggregate-trades response must be a JSON array")
    if len(payload) > PAGE_LIMIT:
        raise ValidationError("aggregate-trades response exceeds the 1000-row limit")

    rows: list[dict[str, Any]] = []
    previous_id: int | None = None
    previous_timestamp: int | None = None
    for position, raw in enumerate(payload):
        fields = set(raw) if isinstance(raw, dict) else set()
        if (
            not isinstance(raw, dict)
            or not REQUIRED_AGGTRADE_FIELDS.issubset(fields)
            or not fields.issubset(REQUIRED_AGGTRADE_FIELDS | OPTIONAL_AGGTRADE_FIELDS)
        ):
            raise ValidationError(f"aggregate-trade row {position} has invalid schema")
        aggregate_id = raw["a"]
        first_trade_id = raw["f"]
        last_trade_id = raw["l"]
        timestamp_ms = raw["T"]
        if (
            not _is_plain_int(aggregate_id)
            or not _is_plain_int(first_trade_id)
            or not _is_plain_int(last_trade_id)
            or not _is_plain_int(timestamp_ms)
            or aggregate_id < 0
            or first_trade_id < 0
            or last_trade_id < first_trade_id
            or timestamp_ms <= 0
        ):
            raise ValidationError(f"aggregate-trade row {position} has invalid IDs/timestamp")
        aggregate_id = int(aggregate_id)
        timestamp_ms = int(timestamp_ms)
        if timestamp_ms > server_time_ms + MAX_FUTURE_SKEW_MILLISECONDS:
            raise ValidationError("aggregate-trades response contains a future timestamp")
        if lower_timestamp_ms is not None and timestamp_ms < lower_timestamp_ms:
            raise ValidationError("aggregate-trades response precedes the requested window")
        if upper_timestamp_ms is not None and timestamp_ms > upper_timestamp_ms:
            raise ValidationError("aggregate-trades response exceeds the requested window")
        if previous_id is not None and aggregate_id != previous_id + 1:
            raise ValidationError("aggregate-trade IDs are not contiguous and increasing")
        if previous_timestamp is not None and timestamp_ms < previous_timestamp:
            raise ValidationError("aggregate-trade timestamps are not monotonic")
        previous_id = aggregate_id
        previous_timestamp = timestamp_ms
        if not isinstance(raw["m"], bool):
            raise ValidationError("aggregate-trade maker flag must be boolean")
        price_decimal = _positive_decimal(raw["p"], "price")
        amount_decimal = _positive_decimal(raw["q"], "amount")
        if "nq" in raw:
            _positive_decimal(raw["nq"], "normal quantity", allow_zero=True)
        cost_decimal = price_decimal * amount_decimal
        price = float(price_decimal)
        amount = float(amount_decimal)
        cost = float(cost_decimal)
        if not all(math.isfinite(value) and value > 0 for value in (price, amount, cost)):
            raise ValidationError("aggregate-trade numeric conversion is not finite/positive")
        rows.append(
            {
                "timestamp": timestamp_ms,
                "id": str(aggregate_id),
                # CCXT returns no order type for aggTrades; Freqtrade casts
                # that None through TRADES_DTYPES['type'] == 'str'.
                "type": "None",
                # m=True means the buyer was maker, therefore the taker sold.
                "side": "sell" if raw["m"] else "buy",
                "price": price,
                "amount": amount,
                "cost": cost,
            }
        )
    return rows


def find_first_aggregate_id(
    *,
    start_ms: int,
    end_ms: int,
    server_time_ms: int,
    timeout_seconds: float,
    retries: int,
    backoff_seconds: float,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Find the first complete aggTrade ID without accepting a truncated seed page."""
    cursor = start_ms
    probe_span = INITIAL_PROBE_MILLISECONDS
    for _ in range(MAX_PROBE_REQUESTS):
        if cursor > end_ms:
            break
        probe_end = min(cursor + probe_span - 1, end_ms)
        payload = request_json(
            AGGTRADES_PATH,
            {
                "symbol": SYMBOL,
                "startTime": cursor,
                "endTime": probe_end,
                "limit": PAGE_LIMIT,
            },
            timeout_seconds=timeout_seconds,
            retries=retries,
            backoff_seconds=backoff_seconds,
            opener=opener,
            sleep_fn=sleep_fn,
        )
        rows = parse_aggtrade_payload(
            payload,
            server_time_ms=server_time_ms,
            lower_timestamp_ms=cursor,
            upper_timestamp_ms=probe_end,
        )
        if len(payload) == PAGE_LIMIT:
            if probe_span <= 1:
                raise ValidationError("seed interval is truncated even at 1 millisecond")
            probe_span = max(1, probe_span // 2)
            continue
        if rows:
            return int(rows[0]["id"])
        cursor = probe_end + 1
        probe_span = INITIAL_PROBE_MILLISECONDS
    raise ValidationError("no complete aggregate-trades seed exists in the requested window")


def fetch_recent_window(
    *,
    start_ms: int,
    end_ms: int,
    server_time_ms: int,
    timeout_seconds: float,
    retries: int,
    backoff_seconds: float,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    if start_ms <= 0 or start_ms >= end_ms or end_ms > server_time_ms:
        raise ValidationError("requested aggregate-trades window is invalid")
    first_id = find_first_aggregate_id(
        start_ms=start_ms,
        end_ms=end_ms,
        server_time_ms=server_time_ms,
        timeout_seconds=timeout_seconds,
        retries=retries,
        backoff_seconds=backoff_seconds,
        opener=opener,
        sleep_fn=sleep_fn,
    )
    from_id = first_id
    collected: list[dict[str, Any]] = []
    max_observed_timestamp = 0
    for _ in range(MAX_ID_PAGES):
        payload = request_json(
            AGGTRADES_PATH,
            {"symbol": SYMBOL, "fromId": from_id, "limit": PAGE_LIMIT},
            timeout_seconds=timeout_seconds,
            retries=retries,
            backoff_seconds=backoff_seconds,
            opener=opener,
            sleep_fn=sleep_fn,
        )
        # The initial server time remains the immutable requested window end,
        # but Binance keeps producing trades while ID pagination runs.  Permit
        # only a small bounded provisional advance here; every observed row is
        # checked against a freshly fetched server time before acceptance.
        rows = parse_aggtrade_payload(
            payload,
            server_time_ms=(
                server_time_ms + MAX_COLLECTION_SERVER_ADVANCE_MILLISECONDS
            ),
        )
        if not rows:
            break
        max_observed_timestamp = max(
            max_observed_timestamp, int(rows[-1]["timestamp"])
        )
        page_first_id = int(rows[0]["id"])
        page_last_id = int(rows[-1]["id"])
        if page_first_id != from_id:
            raise ValidationError("fromId pagination did not start at the requested ID")
        crossed_end = False
        for row in rows:
            timestamp_ms = int(row["timestamp"])
            if timestamp_ms < start_ms:
                raise ValidationError("ID pagination moved before the requested window")
            if timestamp_ms > end_ms:
                crossed_end = True
                break
            collected.append(row)
        if crossed_end or len(payload) < PAGE_LIMIT:
            break
        next_from_id = page_last_id + 1
        if next_from_id <= from_id:
            raise ValidationError("fromId pagination did not advance")
        from_id = next_from_id
    else:
        raise ValidationError("aggregate-trades pagination exceeded its bounded page count")
    if not collected:
        raise ValidationError("aggregate-trades window contains no validated trades")
    final_server_time_ms = get_server_time_ms(
        timeout_seconds=timeout_seconds,
        retries=retries,
        backoff_seconds=backoff_seconds,
        opener=opener,
        sleep_fn=sleep_fn,
    )
    if (
        final_server_time_ms < server_time_ms - MAX_FUTURE_SKEW_MILLISECONDS
        or final_server_time_ms
        > server_time_ms + MAX_COLLECTION_SERVER_ADVANCE_MILLISECONDS
    ):
        raise ValidationError("Binance server time changed outside the bounded collection window")
    if max_observed_timestamp > final_server_time_ms + MAX_FUTURE_SKEW_MILLISECONDS:
        raise ValidationError("aggregate-trades response contains a future timestamp")
    return validate_trade_frame(pd.DataFrame(collected, columns=DEFAULT_TRADES_COLUMNS))


def validate_trade_frame(frame: pd.DataFrame, *, require_nonempty: bool = True) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or list(frame.columns) != DEFAULT_TRADES_COLUMNS:
        raise ValidationError("Feather trade schema does not match DEFAULT_TRADES_COLUMNS")
    if require_nonempty and frame.empty:
        raise ValidationError("trade frame is empty")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for position, row in enumerate(frame.to_dict(orient="records")):
        timestamp = row["timestamp"]
        if not _is_plain_int(timestamp) or int(timestamp) <= 0:
            raise ValidationError(f"trade row {position} has invalid timestamp")
        identifier_raw = row["id"]
        if _is_plain_int(identifier_raw):
            identifier = int(identifier_raw)
        elif (
            isinstance(identifier_raw, str)
            and identifier_raw.isascii()
            and identifier_raw.isdigit()
        ):
            identifier = int(identifier_raw)
        else:
            raise ValidationError(f"trade row {position} has invalid aggregate ID")
        if identifier < 0 or identifier in seen_ids:
            raise ValidationError("trade frame contains duplicate/invalid aggregate IDs")
        seen_ids.add(identifier)
        trade_type = row["type"]
        if trade_type is None:
            trade_type = "None"
        if trade_type != "None" or row["side"] not in {"buy", "sell"}:
            raise ValidationError(f"trade row {position} has invalid type/side")
        numeric_values: list[float] = []
        for field in ("price", "amount", "cost"):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ValidationError(f"trade row {position} has invalid {field}")
            numeric = float(value)
            if not math.isfinite(numeric) or numeric <= 0:
                raise ValidationError(f"trade row {position} has non-finite {field}")
            numeric_values.append(numeric)
        price, amount, cost = numeric_values
        if not math.isclose(cost, price * amount, rel_tol=1e-12, abs_tol=1e-12):
            raise ValidationError(f"trade row {position} has inconsistent cost")
        normalized.append(
            {
                "timestamp": int(timestamp),
                "id": str(identifier),
                "type": "None",
                "side": row["side"],
                "price": price,
                "amount": amount,
                "cost": cost,
                "_numeric_id": identifier,
            }
        )

    if not normalized:
        result = pd.DataFrame(columns=DEFAULT_TRADES_COLUMNS)
        return result.astype(TRADES_DTYPES)
    normalized.sort(key=lambda row: row["_numeric_id"])
    previous_id: int | None = None
    previous_timestamp: int | None = None
    for row in normalized:
        identifier = row["_numeric_id"]
        timestamp = row["timestamp"]
        if previous_id is not None and identifier != previous_id + 1:
            raise ValidationError("stored aggregate-trade IDs are not contiguous")
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValidationError("stored aggregate-trade timestamps are not monotonic")
        previous_id = identifier
        previous_timestamp = timestamp
        del row["_numeric_id"]
    return pd.DataFrame(normalized, columns=DEFAULT_TRADES_COLUMNS).astype(TRADES_DTYPES)


def read_existing_feather(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=DEFAULT_TRADES_COLUMNS).astype(TRADES_DTYPES)
    if not path.is_file():
        raise ValidationError("trade Feather path is not a regular file")
    try:
        frame = pd.read_feather(path)
    except Exception as exc:
        raise ValidationError("existing trade Feather cannot be read") from exc
    return validate_trade_frame(frame)


def merge_trade_frames(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        return validate_trade_frame(incoming)
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "id"], keep="last")
    return validate_trade_frame(combined)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValidationError(f"cannot hash {path.name}") from exc
    return digest.hexdigest()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_feather(path: Path, frame: pd.DataFrame) -> str:
    """Validate a staged Freqtrade-compatible Feather before atomic replace."""
    canonical = validate_trade_frame(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        canonical.to_feather(temporary_path, compression="lz4", compression_level=9)
        with temporary_path.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        staged = pd.read_feather(temporary_path)
        staged = validate_trade_frame(staged)
        if not staged.equals(canonical):
            raise ValidationError("staged Feather round-trip changed validated trades")
        expected_hash = sha256_file(temporary_path)
        os.replace(temporary_path, path)
        if sha256_file(path) != expected_hash:
            raise ValidationError("post-write Feather hash mismatch")
        return expected_hash
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("manifest is not safely serializable") from exc
    return (text + "\n").encode("utf-8")


def collect_once(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    timeout_seconds: float = 15.0,
    retries: int = 4,
    backoff_seconds: float = 1.0,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if (
        not _is_plain_int(window_minutes)
        or not MIN_WINDOW_MINUTES <= int(window_minutes) <= MAX_WINDOW_MINUTES
    ):
        raise ValidationError("window_minutes must remain between 60 and 90")
    server_time_ms = get_server_time_ms(
        timeout_seconds=timeout_seconds,
        retries=retries,
        backoff_seconds=backoff_seconds,
        opener=opener,
        sleep_fn=sleep_fn,
    )
    start_ms = server_time_ms - int(window_minutes) * 60 * 1000
    incoming = fetch_recent_window(
        start_ms=start_ms,
        end_ms=server_time_ms,
        server_time_ms=server_time_ms,
        timeout_seconds=timeout_seconds,
        retries=retries,
        backoff_seconds=backoff_seconds,
        opener=opener,
        sleep_fn=sleep_fn,
    )
    feather_path, manifest_path = output_paths(data_dir)
    existing = read_existing_feather(feather_path)
    merged = merge_trade_frames(existing, incoming)
    if int(merged.iloc[-1]["timestamp"]) > server_time_ms + MAX_FUTURE_SKEW_MILLISECONDS:
        raise ValidationError("merged Feather contains a future timestamp")

    feather_hash = atomic_write_feather(feather_path, merged)
    min_timestamp = int(merged.iloc[0]["timestamp"])
    max_timestamp = int(merged.iloc[-1]["timestamp"])
    min_id = int(merged.iloc[0]["id"])
    max_id = int(merged.iloc[-1]["id"])
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collector": COLLECTOR_NAME,
        "credential_mode": "PUBLIC_NO_CREDENTIALS",
        "api_scheme": API_SCHEME,
        "api_host": API_HOST,
        "server_time_endpoint": SERVER_TIME_PATH,
        "aggregate_trades_endpoint": AGGTRADES_PATH,
        "symbol": SYMBOL,
        "freqtrade_pair": FREQTRADE_PAIR,
        "window_minutes": int(window_minutes),
        "window_start_ms": start_ms,
        "window_start_utc": iso_utc_ms(start_ms),
        "window_end_ms": server_time_ms,
        "window_end_utc": iso_utc_ms(server_time_ms),
        "generated_utc": iso_utc_ms(server_time_ms),
        "output_file": FEATHER_FILENAME,
        "sha256": feather_hash,
        "columns": DEFAULT_TRADES_COLUMNS,
        "dtypes": TRADES_DTYPES,
        "row_count": len(merged),
        "incoming_row_count": len(incoming),
        "min_timestamp_ms": min_timestamp,
        "min_timestamp_utc": iso_utc_ms(min_timestamp),
        "max_timestamp_ms": max_timestamp,
        "max_timestamp_utc": iso_utc_ms(max_timestamp),
        "min_aggregate_id": min_id,
        "max_aggregate_id": max_id,
        "side_semantics": "taker: m=true -> sell, m=false -> buy",
        "status": "READY",
    }
    atomic_write_bytes(manifest_path, canonical_json_bytes(manifest))
    return manifest


def healthcheck(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    now_ms: int | None = None,
    max_age_minutes: int = DEFAULT_HEALTH_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    """Offline integrity/freshness check for the Feather and its manifest."""
    observed_ms = (
        int(datetime.now(timezone.utc).timestamp() * 1000)
        if now_ms is None
        else now_ms
    )
    checked_utc = iso_utc_ms(observed_ms) if _is_plain_int(observed_ms) else None
    try:
        if (
            not _is_plain_int(observed_ms)
            or observed_ms <= 0
            or not _is_plain_int(max_age_minutes)
            or max_age_minutes <= 0
        ):
            raise ValidationError("healthcheck clock/age settings are invalid")
        feather_path, manifest_path = output_paths(data_dir)
        try:
            manifest_payload = manifest_path.read_bytes()
        except OSError as exc:
            raise ValidationError("aggregate-trades manifest is unavailable") from exc
        manifest = decode_json(manifest_payload)
        if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
            raise ValidationError("aggregate-trades manifest schema is invalid")
        locked_scalars = {
            "schema_version": SCHEMA_VERSION,
            "collector": COLLECTOR_NAME,
            "credential_mode": "PUBLIC_NO_CREDENTIALS",
            "api_scheme": API_SCHEME,
            "api_host": API_HOST,
            "server_time_endpoint": SERVER_TIME_PATH,
            "aggregate_trades_endpoint": AGGTRADES_PATH,
            "symbol": SYMBOL,
            "freqtrade_pair": FREQTRADE_PAIR,
            "output_file": FEATHER_FILENAME,
            "columns": DEFAULT_TRADES_COLUMNS,
            "dtypes": TRADES_DTYPES,
            "side_semantics": "taker: m=true -> sell, m=false -> buy",
            "status": "READY",
        }
        for key, expected in locked_scalars.items():
            if manifest.get(key) != expected:
                raise ValidationError(f"manifest field {key} violates the locked schema")
        window_minutes = manifest["window_minutes"]
        start_ms = manifest["window_start_ms"]
        end_ms = manifest["window_end_ms"]
        if (
            not _is_plain_int(window_minutes)
            or not MIN_WINDOW_MINUTES <= window_minutes <= MAX_WINDOW_MINUTES
            or not _is_plain_int(start_ms)
            or not _is_plain_int(end_ms)
            or start_ms <= 0
            or end_ms - start_ms != window_minutes * 60 * 1000
            or end_ms > observed_ms + MAX_FUTURE_SKEW_MILLISECONDS
        ):
            raise ValidationError("manifest collection window is invalid")
        if (
            manifest["window_start_utc"] != iso_utc_ms(start_ms)
            or manifest["window_end_utc"] != iso_utc_ms(end_ms)
            or manifest["generated_utc"] != iso_utc_ms(end_ms)
        ):
            raise ValidationError("manifest UTC fields are inconsistent")
        age_minutes = max(0.0, (observed_ms - end_ms) / 60_000)
        if age_minutes > max_age_minutes:
            raise ValidationError("aggregate-trades artifact is stale")
        sha256 = manifest["sha256"]
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or sha256_file(feather_path) != sha256
        ):
            raise ValidationError("Feather SHA256 does not match the manifest")
        frame = read_existing_feather(feather_path)
        row_count = manifest["row_count"]
        incoming_count = manifest["incoming_row_count"]
        if (
            not _is_plain_int(row_count)
            or not _is_plain_int(incoming_count)
            or row_count != len(frame)
            or incoming_count <= 0
            or incoming_count > row_count
        ):
            raise ValidationError("manifest trade counts are inconsistent")
        min_timestamp = int(frame.iloc[0]["timestamp"])
        max_timestamp = int(frame.iloc[-1]["timestamp"])
        min_id = int(frame.iloc[0]["id"])
        max_id = int(frame.iloc[-1]["id"])
        if (
            manifest["min_timestamp_ms"] != min_timestamp
            or manifest["min_timestamp_utc"] != iso_utc_ms(min_timestamp)
            or manifest["max_timestamp_ms"] != max_timestamp
            or manifest["max_timestamp_utc"] != iso_utc_ms(max_timestamp)
            or manifest["min_aggregate_id"] != min_id
            or manifest["max_aggregate_id"] != max_id
            or max_timestamp > end_ms + MAX_FUTURE_SKEW_MILLISECONDS
        ):
            raise ValidationError("manifest trade bounds are inconsistent")
        return {
            "schema_version": SCHEMA_VERSION,
            "collector": COLLECTOR_NAME,
            "status": "HEALTHY",
            "healthy": True,
            "checked_utc": checked_utc,
            "artifact_age_minutes": round(age_minutes, 3),
            "row_count": len(frame),
            "min_timestamp_utc": iso_utc_ms(min_timestamp),
            "max_timestamp_utc": iso_utc_ms(max_timestamp),
            "min_aggregate_id": min_id,
            "max_aggregate_id": max_id,
            "sha256": sha256,
        }
    except Exception as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "collector": COLLECTOR_NAME,
            "status": "UNHEALTHY",
            "healthy": False,
            "checked_utc": checked_utc,
            "error_type": type(exc).__name__,
            "error_message": " ".join(str(exc).split())[:500],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="validate local Feather/manifest without any network request",
    )
    parser.add_argument("--symbol", choices=[SYMBOL], default=SYMBOL)
    parser.add_argument("--window-minutes", type=int, default=DEFAULT_WINDOW_MINUTES)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--backoff-seconds", type=float, default=1.0)
    parser.add_argument(
        "--health-max-age-minutes",
        type=int,
        default=DEFAULT_HEALTH_MAX_AGE_MINUTES,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        not MIN_WINDOW_MINUTES <= args.window_minutes <= MAX_WINDOW_MINUTES
        or args.timeout_seconds <= 0
        or args.retries < 0
        or args.backoff_seconds < 0
        or args.health_max_age_minutes <= 0
    ):
        raise SystemExit("window and retry settings are outside the bounded policy")
    if args.healthcheck:
        result = healthcheck(
            args.data_dir, max_age_minutes=args.health_max_age_minutes
        )
        print(
            json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
            file=sys.stdout if result["healthy"] else sys.stderr,
            flush=True,
        )
        return 0 if result["healthy"] else 1
    try:
        manifest = collect_once(
            args.data_dir,
            window_minutes=args.window_minutes,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            backoff_seconds=args.backoff_seconds,
        )
        print(
            json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
            flush=True,
        )
        return 0
    except Exception as exc:
        error = {
            "schema_version": SCHEMA_VERSION,
            "collector": COLLECTOR_NAME,
            "status": "ERROR",
            "credential_mode": "PUBLIC_NO_CREDENTIALS",
            "api_host": API_HOST,
            "error_type": type(exc).__name__,
            "error_message": " ".join(str(exc).split())[:500],
        }
        print(
            json.dumps(error, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
