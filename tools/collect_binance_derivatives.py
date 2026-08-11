#!/usr/bin/env python3
"""Collect public Binance USD-M derivatives context without credentials.

The collector is intentionally isolated from Freqtrade strategies and runtime
configuration.  It stores point-in-time shadow data only.  Binance exposes at
most the latest 30 days through these endpoints, so the first run paginates
that window and later runs overlap/upsert the newest observations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 1
COLLECTOR_NAME = "binance_usdm_public_derivatives"
API_SCHEME = "https"
API_HOST = "fapi.binance.com"
BASE_URL = f"{API_SCHEME}://{API_HOST}"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
PERIODS = ("5m", "15m", "1h", "4h")
PERIOD_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14_400}

PAGE_LIMIT = 500
RETENTION_DAYS = 30
RETENTION_MILLISECONDS = RETENTION_DAYS * 24 * 60 * 60 * 1000
INCREMENTAL_OVERLAP_PERIODS = 2
MAX_FUTURE_SKEW_MILLISECONDS = 60_000
FRESHNESS_GRACE_SECONDS = 900
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

MANIFEST_FILENAME = "manifest.json"
STATUS_FILENAME = "status.json"


class CollectorError(RuntimeError):
    """Base exception for a safe, user-facing collector failure."""


class ValidationError(CollectorError):
    """Raised when remote or stored data fails strict validation."""


class NetworkError(CollectorError):
    """Raised when an HTTPS request cannot be completed safely."""


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    path: str
    api_fields: tuple[str, ...]
    csv_fields: tuple[str, ...]
    numeric_field_map: tuple[tuple[str, str], ...]
    includes_symbol: bool


OPEN_INTEREST = EndpointSpec(
    name="open_interest",
    path="/futures/data/openInterestHist",
    api_fields=(
        "symbol",
        "sumOpenInterest",
        "sumOpenInterestValue",
        "CMCCirculatingSupply",
        "timestamp",
    ),
    csv_fields=(
        "timestamp_utc",
        "timestamp_ms",
        "symbol",
        "period",
        "sum_open_interest",
        "sum_open_interest_value",
        "cmc_circulating_supply",
    ),
    numeric_field_map=(
        ("sumOpenInterest", "sum_open_interest"),
        ("sumOpenInterestValue", "sum_open_interest_value"),
        ("CMCCirculatingSupply", "cmc_circulating_supply"),
    ),
    includes_symbol=True,
)

TAKER_BUY_SELL = EndpointSpec(
    name="taker_buy_sell",
    path="/futures/data/takerlongshortRatio",
    api_fields=("buySellRatio", "buyVol", "sellVol", "timestamp"),
    csv_fields=(
        "timestamp_utc",
        "timestamp_ms",
        "symbol",
        "period",
        "buy_sell_ratio",
        "buy_volume",
        "sell_volume",
    ),
    numeric_field_map=(
        ("buySellRatio", "buy_sell_ratio"),
        ("buyVol", "buy_volume"),
        ("sellVol", "sell_volume"),
    ),
    includes_symbol=False,
)

ENDPOINTS = (OPEN_INTEREST, TAKER_BUY_SELL)
ENDPOINT_BY_NAME = {spec.name: spec for spec in ENDPOINTS}
ALLOWED_ENDPOINT_PATHS = frozenset(spec.path for spec in ENDPOINTS)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def datetime_to_ms(value: datetime) -> int:
    return int(require_utc(value).timestamp() * 1000)


def iso_utc_ms(timestamp_ms: int) -> str:
    try:
        value = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValidationError("timestamp_ms is outside the supported UTC range") from exc
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso_utc_ms(value: Any) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError("UTC timestamp must use canonical Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValidationError("UTC timestamp is invalid") from exc
    timestamp_ms = datetime_to_ms(parsed)
    if iso_utc_ms(timestamp_ms) != value:
        raise ValidationError("UTC timestamp is not canonical millisecond UTC")
    return timestamp_ms


def dataset_filename(spec: EndpointSpec, symbol: str, period: str) -> str:
    if symbol not in SYMBOLS or period not in PERIODS or spec not in ENDPOINTS:
        raise ValidationError("dataset identity is outside the locked allowlist")
    return f"{spec.name}_{symbol}_{period}.csv"


def dataset_id(spec: EndpointSpec, symbol: str, period: str) -> str:
    return f"{spec.name}:{symbol}:{period}"


def freshness_limit_seconds(period: str) -> int:
    try:
        return 2 * PERIOD_SECONDS[period] + FRESHNESS_GRACE_SECONDS
    except KeyError as exc:
        raise ValidationError("unsupported period") from exc


def build_url(path: str, params: dict[str, Any]) -> str:
    """Build and re-validate an allowlisted public HTTPS URL."""
    if path not in ALLOWED_ENDPOINT_PATHS:
        raise ValidationError("endpoint path is outside the locked allowlist")
    allowed_params = {"symbol", "period", "limit", "startTime", "endTime"}
    if set(params) != allowed_params:
        raise ValidationError("query parameter schema is not the locked public schema")
    if params.get("symbol") not in SYMBOLS or params.get("period") not in PERIODS:
        raise ValidationError("query identity is outside the locked allowlist")
    if params.get("limit") != PAGE_LIMIT:
        raise ValidationError("Binance derivatives page limit must remain 500")
    for name in ("startTime", "endTime"):
        value = params.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValidationError(f"{name} must be a positive integer")
    if params["startTime"] > params["endTime"]:
        raise ValidationError("startTime cannot be after endTime")

    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{path}?{query}"
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != API_SCHEME
        or parsed.hostname != API_HOST
        or parsed.netloc != API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValidationError("constructed URL is not the exact Binance HTTPS host")
    return url


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON response contains a duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValidationError(f"JSON response contains non-finite constant {value}")


def _decode_json(payload: bytes) -> Any:
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_json_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValidationError("response is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError("response is not valid JSON") from exc


def _is_retryable_http_status(status: int) -> bool:
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
    """GET one public page with bounded retries and no credential headers."""
    if timeout_seconds <= 0 or retries < 0 or backoff_seconds < 0:
        raise ValidationError("network retry settings are invalid")
    url = build_url(path, params)
    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "pro-day-trader-derivatives-collector/1.0",
        },
        method="GET",
    )

    for attempt in range(retries + 1):
        try:
            with open_url(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    if attempt < retries and _is_retryable_http_status(status):
                        delay = backoff_seconds * (2**attempt)
                        if delay > 0:
                            sleep_fn(delay)
                        continue
                    raise NetworkError(f"unexpected HTTP status {status}")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValidationError("response exceeds the bounded payload size")
            return _decode_json(payload)
        except urllib.error.HTTPError as exc:
            retryable = _is_retryable_http_status(int(exc.code))
            if attempt >= retries or not retryable:
                raise NetworkError(f"Binance HTTPS request failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise NetworkError(
                    f"Binance HTTPS request failed after {retries + 1} attempt(s)"
                ) from exc
        except NetworkError:
            raise

        delay = backoff_seconds * (2**attempt)
        if delay > 0:
            sleep_fn(delay)

    raise AssertionError("unreachable retry state")


def _canonical_nonnegative_decimal(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(f"{field} must be a non-empty decimal string")
    if len(value) > 128:
        raise ValidationError(f"{field} exceeds the numeric schema bound")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{field} is not a decimal number") from exc
    if not number.is_finite():
        raise ValidationError(f"{field} must be finite")
    if number < 0:
        raise ValidationError(f"{field} must be non-negative")
    if number and abs(number.adjusted()) > 50:
        raise ValidationError(f"{field} exceeds the numeric schema bound")
    if number == 0:
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _parse_timestamp_ms(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("timestamp_ms must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        result = int(value)
    else:
        raise ValidationError("timestamp_ms must be an integer")
    if result <= 0:
        raise ValidationError("timestamp_ms must be positive")
    iso_utc_ms(result)
    return result


def validate_rows(
    spec: EndpointSpec,
    symbol: str,
    period: str,
    rows: Iterable[dict[str, Any]],
    *,
    now_ms: int,
    require_nonempty: bool = True,
) -> list[dict[str, Any]]:
    """Validate and canonicalize the on-disk CSV schema."""
    if spec not in ENDPOINTS or symbol not in SYMBOLS or period not in PERIODS:
        raise ValidationError("dataset identity is outside the locked allowlist")
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    expected_fields = set(spec.csv_fields)
    numeric_csv_fields = tuple(csv_name for _, csv_name in spec.numeric_field_map)

    for position, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise ValidationError(
                f"{dataset_id(spec, symbol, period)} row {position} has invalid CSV schema"
            )
        timestamp_ms = _parse_timestamp_ms(row["timestamp_ms"])
        if timestamp_ms > now_ms + MAX_FUTURE_SKEW_MILLISECONDS:
            raise ValidationError(
                f"{dataset_id(spec, symbol, period)} contains a future timestamp"
            )
        if timestamp_ms in seen:
            raise ValidationError(
                f"{dataset_id(spec, symbol, period)} contains a duplicate timestamp"
            )
        seen.add(timestamp_ms)
        expected_utc = iso_utc_ms(timestamp_ms)
        if row["timestamp_utc"] != expected_utc:
            raise ValidationError(
                f"{dataset_id(spec, symbol, period)} has inconsistent UTC timestamp"
            )
        if row["symbol"] != symbol or row["period"] != period:
            raise ValidationError(
                f"{dataset_id(spec, symbol, period)} has inconsistent identity fields"
            )
        canonical: dict[str, Any] = {
            "timestamp_utc": expected_utc,
            "timestamp_ms": timestamp_ms,
            "symbol": symbol,
            "period": period,
        }
        for field in numeric_csv_fields:
            canonical[field] = _canonical_nonnegative_decimal(row[field], field)
        normalized.append(canonical)

    if require_nonempty and not normalized:
        raise ValidationError(f"{dataset_id(spec, symbol, period)} is empty")
    normalized.sort(key=lambda row: row["timestamp_ms"])
    return normalized


def parse_api_payload(
    spec: EndpointSpec,
    symbol: str,
    period: str,
    payload: Any,
    *,
    now_ms: int,
) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValidationError("Binance response must be a JSON array")
    if len(payload) > PAGE_LIMIT:
        raise ValidationError("Binance response exceeds the requested 500-row page")
    api_fields = set(spec.api_fields)
    canonical_rows: list[dict[str, Any]] = []
    for position, raw in enumerate(payload):
        if not isinstance(raw, dict) or set(raw) != api_fields:
            raise ValidationError(f"API row {position} has an unexpected schema")
        if spec.includes_symbol and raw["symbol"] != symbol:
            raise ValidationError(f"API row {position} has an unexpected symbol")
        timestamp_ms = _parse_timestamp_ms(raw["timestamp"])
        row: dict[str, Any] = {
            "timestamp_utc": iso_utc_ms(timestamp_ms),
            "timestamp_ms": timestamp_ms,
            "symbol": symbol,
            "period": period,
        }
        for api_name, csv_name in spec.numeric_field_map:
            row[csv_name] = _canonical_nonnegative_decimal(raw[api_name], api_name)
        canonical_rows.append(row)
    return validate_rows(
        spec,
        symbol,
        period,
        canonical_rows,
        now_ms=now_ms,
        require_nonempty=False,
    )


def fetch_series(
    spec: EndpointSpec,
    symbol: str,
    period: str,
    *,
    start_ms: int,
    end_ms: int,
    now_ms: int,
    timeout_seconds: float,
    retries: int,
    backoff_seconds: float,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Fetch one series using bounded backward pagination at 500 rows/page.

    These Binance endpoints return the newest ``limit`` rows inside a wide
    start/end range.  Therefore a 30-day bootstrap must move ``endTime``
    backwards; moving ``startTime`` forwards would repeatedly revisit the
    newest page and silently lose the older part of the retention window.
    """
    if start_ms <= 0 or end_ms <= 0 or start_ms > end_ms:
        raise ValidationError("invalid pagination time range")
    period_ms = PERIOD_SECONDS[period] * 1000
    estimated_pages = math.ceil((end_ms - start_ms + 1) / period_ms / PAGE_LIMIT)
    max_pages = max(3, estimated_pages + 5)
    cursor_end = end_ms
    collected: dict[int, dict[str, Any]] = {}

    for _ in range(max_pages):
        params = {
            "symbol": symbol,
            "period": period,
            "limit": PAGE_LIMIT,
            "startTime": start_ms,
            "endTime": cursor_end,
        }
        payload = request_json(
            spec.path,
            params,
            timeout_seconds=timeout_seconds,
            retries=retries,
            backoff_seconds=backoff_seconds,
            opener=opener,
            sleep_fn=sleep_fn,
        )
        rows = parse_api_payload(spec, symbol, period, payload, now_ms=now_ms)
        if not rows:
            break
        page_min = rows[0]["timestamp_ms"]
        page_max = rows[-1]["timestamp_ms"]
        # Binance may align a boundary to the surrounding period.  Accept at
        # most one period of alignment drift, then keep only the exact locked
        # request window.  Larger drift is a schema/semantics failure.
        if (
            page_min < start_ms - period_ms
            or page_max > cursor_end + period_ms
            or page_max > end_ms + MAX_FUTURE_SKEW_MILLISECONDS
        ):
            raise ValidationError("Binance page falls outside the requested time range")
        for row in rows:
            timestamp_ms = row["timestamp_ms"]
            if timestamp_ms < start_ms or timestamp_ms > end_ms:
                continue
            if timestamp_ms in collected:
                raise ValidationError("Binance pagination returned a duplicate timestamp")
            collected[timestamp_ms] = row
        if len(payload) < PAGE_LIMIT or page_min <= start_ms:
            break
        next_cursor_end = page_min - 1
        if next_cursor_end >= cursor_end:
            raise ValidationError("Binance pagination did not advance")
        cursor_end = next_cursor_end
    else:
        raise ValidationError("Binance pagination exceeded its bounded page count")

    if not collected:
        raise ValidationError(f"{dataset_id(spec, symbol, period)} returned no data")
    return validate_rows(
        spec,
        symbol,
        period,
        collected.values(),
        now_ms=now_ms,
    )


def read_csv_dataset(
    path: Path,
    spec: EndpointSpec,
    symbol: str,
    period: str,
    *,
    now_ms: int,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ValidationError(f"dataset path is not a regular file: {path.name}")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != spec.csv_fields:
                raise ValidationError(f"{path.name} has an unexpected CSV header")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationError(f"cannot read validated CSV dataset {path.name}") from exc
    return validate_rows(spec, symbol, period, rows, now_ms=now_ms)


def merge_rows(
    spec: EndpointSpec,
    symbol: str,
    period: str,
    existing: Iterable[dict[str, Any]],
    incoming: Iterable[dict[str, Any]],
    *,
    now_ms: int,
) -> list[dict[str, Any]]:
    merged = {row["timestamp_ms"]: row for row in existing}
    for row in incoming:
        merged[row["timestamp_ms"]] = row
    return validate_rows(spec, symbol, period, merged.values(), now_ms=now_ms)


def render_csv(spec: EndpointSpec, rows: Iterable[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=spec.csv_fields,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("cannot serialize collector metadata safely") from exc
    return (rendered + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably replace one file without exposing a partially written CSV/JSON."""
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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValidationError(f"cannot hash dataset {path.name}") from exc
    return digest.hexdigest()


def summarize_dataset(
    spec: EndpointSpec,
    symbol: str,
    period: str,
    rows: list[dict[str, Any]],
    *,
    now_ms: int,
    csv_sha256: str,
) -> dict[str, Any]:
    minimum_ms = rows[0]["timestamp_ms"]
    maximum_ms = rows[-1]["timestamp_ms"]
    age_seconds = max(0.0, (now_ms - maximum_ms) / 1000)
    freshness_limit = freshness_limit_seconds(period)
    return {
        "dataset_id": dataset_id(spec, symbol, period),
        "endpoint": spec.path,
        "file": dataset_filename(spec, symbol, period),
        "sha256": csv_sha256,
        "row_count": len(rows),
        "min_timestamp_ms": minimum_ms,
        "min_timestamp_utc": iso_utc_ms(minimum_ms),
        "max_timestamp_ms": maximum_ms,
        "max_timestamp_utc": iso_utc_ms(maximum_ms),
        "freshness_age_seconds": round(age_seconds, 3),
        "freshness_limit_seconds": freshness_limit,
        "fresh": age_seconds <= freshness_limit,
    }


def _safe_load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read metadata file {path.name}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"metadata file {path.name} is not a JSON object")
    return value


def collect_once(
    output_dir: Path | str,
    *,
    now: datetime | None = None,
    timeout_seconds: float = 15.0,
    retries: int = 4,
    backoff_seconds: float = 1.0,
    opener: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch, validate, stage, and atomically upsert all 24 locked datasets."""
    observed_at = require_utc(now or utc_now())
    now_ms = datetime_to_ms(observed_at)
    output_path = Path(output_dir)
    staged_csv: list[tuple[Path, bytes, str]] = []
    summaries: list[dict[str, Any]] = []

    # Nothing is committed until every remote page and every merged dataset has
    # passed validation.  Incoming rows replace matching timestamps (upsert),
    # while observations older than Binance's rolling window remain preserved.
    for spec in ENDPOINTS:
        for symbol in SYMBOLS:
            for period in PERIODS:
                path = output_path / dataset_filename(spec, symbol, period)
                existing = read_csv_dataset(
                    path, spec, symbol, period, now_ms=now_ms
                )
                retention_start = now_ms - RETENTION_MILLISECONDS
                if existing:
                    overlap_ms = (
                        INCREMENTAL_OVERLAP_PERIODS * PERIOD_SECONDS[period] * 1000
                    )
                    start_ms = max(
                        retention_start, existing[-1]["timestamp_ms"] - overlap_ms
                    )
                else:
                    start_ms = retention_start
                incoming = fetch_series(
                    spec,
                    symbol,
                    period,
                    start_ms=start_ms,
                    end_ms=now_ms,
                    now_ms=now_ms,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    backoff_seconds=backoff_seconds,
                    opener=opener,
                    sleep_fn=sleep_fn,
                )
                merged = merge_rows(
                    spec,
                    symbol,
                    period,
                    existing,
                    incoming,
                    now_ms=now_ms,
                )
                csv_payload = render_csv(spec, merged)
                csv_hash = sha256_bytes(csv_payload)
                staged_csv.append((path, csv_payload, csv_hash))
                summaries.append(
                    summarize_dataset(
                        spec,
                        symbol,
                        period,
                        merged,
                        now_ms=now_ms,
                        csv_sha256=csv_hash,
                    )
                )

    expected_dataset_count = len(ENDPOINTS) * len(SYMBOLS) * len(PERIODS)
    if len(summaries) != expected_dataset_count:
        raise ValidationError("locked dataset matrix is incomplete")
    stale = [item["dataset_id"] for item in summaries if not item["fresh"]]
    if stale:
        raise ValidationError(
            f"freshness validation failed for {len(stale)} locked dataset(s)"
        )

    minimum_ms = min(item["min_timestamp_ms"] for item in summaries)
    maximum_ms = max(item["max_timestamp_ms"] for item in summaries)
    generated_utc = iso_utc_ms(now_ms)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collector": COLLECTOR_NAME,
        "generated_utc": generated_utc,
        "credential_mode": "PUBLIC_NO_CREDENTIALS",
        "api_scheme": API_SCHEME,
        "api_host": API_HOST,
        "base_url": BASE_URL,
        "endpoints": [spec.path for spec in ENDPOINTS],
        "symbols": list(SYMBOLS),
        "periods": list(PERIODS),
        "initial_retention_days": RETENTION_DAYS,
        "page_limit": PAGE_LIMIT,
        "dataset_count": len(summaries),
        "total_row_count": sum(item["row_count"] for item in summaries),
        "min_timestamp_ms": minimum_ms,
        "min_timestamp_utc": iso_utc_ms(minimum_ms),
        "max_timestamp_ms": maximum_ms,
        "max_timestamp_utc": iso_utc_ms(maximum_ms),
        "all_fresh": True,
        "datasets": summaries,
    }

    # Each file replacement is atomic.  The manifest is committed only after
    # every CSV hash has been re-read and verified, and status is committed last.
    for path, payload, expected_hash in staged_csv:
        atomic_write_bytes(path, payload)
        if sha256_file(path) != expected_hash:
            raise ValidationError(f"post-write hash mismatch for {path.name}")
    manifest_payload = canonical_json_bytes(manifest)
    manifest_path = output_path / MANIFEST_FILENAME
    atomic_write_bytes(manifest_path, manifest_payload)
    manifest_hash = sha256_bytes(manifest_payload)
    if sha256_file(manifest_path) != manifest_hash:
        raise ValidationError("post-write manifest hash mismatch")

    status: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collector": COLLECTOR_NAME,
        "status": "READY",
        "healthy": True,
        "checked_utc": generated_utc,
        "last_success_utc": generated_utc,
        "credential_mode": "PUBLIC_NO_CREDENTIALS",
        "api_host": API_HOST,
        "manifest_file": MANIFEST_FILENAME,
        "manifest_sha256": manifest_hash,
        "dataset_count": manifest["dataset_count"],
        "total_row_count": manifest["total_row_count"],
        "min_timestamp_utc": manifest["min_timestamp_utc"],
        "max_timestamp_utc": manifest["max_timestamp_utc"],
        "all_fresh": True,
    }
    atomic_write_bytes(output_path / STATUS_FILENAME, canonical_json_bytes(status))
    return status


def record_failure_status(
    output_dir: Path | str,
    error: BaseException,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = require_utc(now or utc_now())
    output_path = Path(output_dir)
    previous: dict[str, Any] = {}
    status_path = output_path / STATUS_FILENAME
    if status_path.exists():
        try:
            previous = _safe_load_json_object(status_path)
        except ValidationError:
            previous = {}
    message = " ".join(str(error).split())[:500] or type(error).__name__
    status: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collector": COLLECTOR_NAME,
        "status": "ERROR",
        "healthy": False,
        "checked_utc": iso_utc_ms(datetime_to_ms(observed_at)),
        "last_success_utc": previous.get("last_success_utc"),
        "credential_mode": "PUBLIC_NO_CREDENTIALS",
        "api_host": API_HOST,
        "manifest_file": MANIFEST_FILENAME,
        "manifest_sha256": previous.get("manifest_sha256"),
        "dataset_count": previous.get("dataset_count"),
        "total_row_count": previous.get("total_row_count"),
        "min_timestamp_utc": previous.get("min_timestamp_utc"),
        "max_timestamp_utc": previous.get("max_timestamp_utc"),
        "all_fresh": False,
        "error_type": type(error).__name__,
        "error_message": message,
    }
    atomic_write_bytes(status_path, canonical_json_bytes(status))
    return status


def _require_manifest_scalar(
    manifest: dict[str, Any], key: str, expected: Any
) -> None:
    if manifest.get(key) != expected:
        raise ValidationError(f"manifest field {key} does not match the locked schema")


def healthcheck(
    output_dir: Path | str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Validate status, manifest, every CSV hash/schema, and live freshness."""
    observed_at = require_utc(now or utc_now())
    now_ms = datetime_to_ms(observed_at)
    checked_utc = iso_utc_ms(now_ms)
    output_path = Path(output_dir)
    try:
        status_path = output_path / STATUS_FILENAME
        manifest_path = output_path / MANIFEST_FILENAME
        status = _safe_load_json_object(status_path)
        if status.get("status") != "READY" or status.get("healthy") is not True:
            raise ValidationError("collector status is not READY")
        _require_manifest_scalar(status, "schema_version", SCHEMA_VERSION)
        _require_manifest_scalar(status, "collector", COLLECTOR_NAME)
        _require_manifest_scalar(status, "credential_mode", "PUBLIC_NO_CREDENTIALS")
        _require_manifest_scalar(status, "api_host", API_HOST)
        _require_manifest_scalar(status, "manifest_file", MANIFEST_FILENAME)
        if status.get("all_fresh") is not True:
            raise ValidationError("collector status freshness is not READY")
        manifest_payload = manifest_path.read_bytes()
        if sha256_bytes(manifest_payload) != status.get("manifest_sha256"):
            raise ValidationError("manifest hash does not match status")
        manifest = _safe_load_json_object(manifest_path)
        _require_manifest_scalar(manifest, "schema_version", SCHEMA_VERSION)
        _require_manifest_scalar(manifest, "collector", COLLECTOR_NAME)
        _require_manifest_scalar(manifest, "credential_mode", "PUBLIC_NO_CREDENTIALS")
        _require_manifest_scalar(manifest, "api_scheme", API_SCHEME)
        _require_manifest_scalar(manifest, "api_host", API_HOST)
        _require_manifest_scalar(manifest, "base_url", BASE_URL)
        _require_manifest_scalar(
            manifest, "endpoints", [spec.path for spec in ENDPOINTS]
        )
        _require_manifest_scalar(manifest, "symbols", list(SYMBOLS))
        _require_manifest_scalar(manifest, "periods", list(PERIODS))
        _require_manifest_scalar(manifest, "page_limit", PAGE_LIMIT)
        _require_manifest_scalar(manifest, "initial_retention_days", RETENTION_DAYS)
        expected_count = len(ENDPOINTS) * len(SYMBOLS) * len(PERIODS)
        _require_manifest_scalar(manifest, "dataset_count", expected_count)
        generated_ms = parse_iso_utc_ms(manifest.get("generated_utc"))
        if generated_ms > now_ms + MAX_FUTURE_SKEW_MILLISECONDS:
            raise ValidationError("manifest generation timestamp is in the future")

        entries = manifest.get("datasets")
        if not isinstance(entries, list) or len(entries) != expected_count:
            raise ValidationError("manifest dataset matrix is incomplete")
        entries_by_id: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("dataset_id"), str):
                raise ValidationError("manifest contains an invalid dataset entry")
            identifier = entry["dataset_id"]
            if identifier in entries_by_id:
                raise ValidationError("manifest contains a duplicate dataset entry")
            entries_by_id[identifier] = entry

        total_rows = 0
        all_minimums: list[int] = []
        all_maximums: list[int] = []
        maximum_age = 0.0
        for spec in ENDPOINTS:
            for symbol in SYMBOLS:
                for period in PERIODS:
                    identifier = dataset_id(spec, symbol, period)
                    entry = entries_by_id.get(identifier)
                    if entry is None:
                        raise ValidationError(f"manifest is missing {identifier}")
                    expected_file = dataset_filename(spec, symbol, period)
                    if entry.get("file") != expected_file or entry.get("endpoint") != spec.path:
                        raise ValidationError(f"manifest identity mismatch for {identifier}")
                    relative = Path(expected_file)
                    if relative.is_absolute() or relative.name != str(relative):
                        raise ValidationError("manifest dataset path is unsafe")
                    csv_path = output_path / relative
                    actual_hash = sha256_file(csv_path)
                    if actual_hash != entry.get("sha256"):
                        raise ValidationError(f"CSV hash mismatch for {identifier}")
                    rows = read_csv_dataset(
                        csv_path, spec, symbol, period, now_ms=now_ms
                    )
                    minimum_ms = rows[0]["timestamp_ms"]
                    maximum_ms = rows[-1]["timestamp_ms"]
                    age_seconds = max(0.0, (now_ms - maximum_ms) / 1000)
                    freshness_limit = freshness_limit_seconds(period)
                    if age_seconds > freshness_limit:
                        raise ValidationError(f"dataset is stale: {identifier}")
                    recorded_age = entry.get("freshness_age_seconds")
                    generated_age = max(0.0, (generated_ms - maximum_ms) / 1000)
                    if (
                        isinstance(recorded_age, bool)
                        or not isinstance(recorded_age, (int, float))
                        or not math.isfinite(recorded_age)
                        or abs(float(recorded_age) - round(generated_age, 3)) > 0.001
                        or entry.get("freshness_limit_seconds") != freshness_limit
                        or entry.get("fresh") is not True
                    ):
                        raise ValidationError(f"manifest freshness mismatch for {identifier}")
                    if (
                        entry.get("row_count") != len(rows)
                        or entry.get("min_timestamp_ms") != minimum_ms
                        or entry.get("min_timestamp_utc") != iso_utc_ms(minimum_ms)
                        or entry.get("max_timestamp_ms") != maximum_ms
                        or entry.get("max_timestamp_utc") != iso_utc_ms(maximum_ms)
                    ):
                        raise ValidationError(f"manifest counts/timestamps mismatch for {identifier}")
                    total_rows += len(rows)
                    all_minimums.append(minimum_ms)
                    all_maximums.append(maximum_ms)
                    maximum_age = max(maximum_age, age_seconds)

        if set(entries_by_id) != {
            dataset_id(spec, symbol, period)
            for spec in ENDPOINTS
            for symbol in SYMBOLS
            for period in PERIODS
        }:
            raise ValidationError("manifest contains an unexpected dataset entry")
        if (
            manifest.get("total_row_count") != total_rows
            or manifest.get("min_timestamp_ms") != min(all_minimums)
            or manifest.get("max_timestamp_ms") != max(all_maximums)
            or manifest.get("min_timestamp_utc") != iso_utc_ms(min(all_minimums))
            or manifest.get("max_timestamp_utc") != iso_utc_ms(max(all_maximums))
            or manifest.get("all_fresh") is not True
        ):
            raise ValidationError("manifest aggregate metadata mismatch")
        if (
            status.get("dataset_count") != expected_count
            or status.get("total_row_count") != total_rows
            or status.get("min_timestamp_utc") != iso_utc_ms(min(all_minimums))
            or status.get("max_timestamp_utc") != iso_utc_ms(max(all_maximums))
        ):
            raise ValidationError("collector status aggregate metadata mismatch")
        return {
            "schema_version": SCHEMA_VERSION,
            "collector": COLLECTOR_NAME,
            "status": "HEALTHY",
            "healthy": True,
            "checked_utc": checked_utc,
            "dataset_count": expected_count,
            "total_row_count": total_rows,
            "maximum_freshness_age_seconds": round(maximum_age, 3),
            "manifest_sha256": status["manifest_sha256"],
        }
    except (CollectorError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "collector": COLLECTOR_NAME,
            "status": "UNHEALTHY",
            "healthy": False,
            "checked_utc": checked_utc,
            "error_type": type(exc).__name__,
            "error_message": (" ".join(str(exc).split())[:500] or type(exc).__name__),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true", help="collect one complete validated snapshot"
    )
    mode.add_argument(
        "--healthcheck",
        action="store_true",
        help="validate local status/manifest/CSVs without network access",
    )
    parser.add_argument(
        "--output-dir", default="user_data/data/binance/derivatives"
    )
    parser.add_argument("--loop-seconds", type=float, default=300.0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--backoff-seconds", type=float, default=1.0)
    return parser


def _print_json(value: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        file=stream,
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        args.loop_seconds <= 0
        or args.timeout_seconds <= 0
        or args.retries < 0
        or args.backoff_seconds < 0
    ):
        raise SystemExit("collector intervals and retry settings must be valid")
    output_dir = Path(args.output_dir)
    if args.healthcheck:
        result = healthcheck(output_dir)
        _print_json(result, stream=sys.stdout if result["healthy"] else sys.stderr)
        return 0 if result["healthy"] else 1

    while True:
        try:
            result = collect_once(
                output_dir,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                backoff_seconds=args.backoff_seconds,
            )
            _print_json(result)
            exit_code = 0
        except Exception as exc:
            try:
                status = record_failure_status(output_dir, exc)
            except Exception as status_exc:
                status = {
                    "schema_version": SCHEMA_VERSION,
                    "collector": COLLECTOR_NAME,
                    "status": "ERROR",
                    "healthy": False,
                    "error_type": type(exc).__name__,
                    "error_message": "collector failed and status persistence failed",
                    "status_error_type": type(status_exc).__name__,
                }
            _print_json(status, stream=sys.stderr)
            exit_code = 2
        if args.once:
            return exit_code
        try:
            time.sleep(args.loop_seconds)
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
