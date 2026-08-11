#!/usr/bin/env python3
"""Deterministic, fail-closed evaluator for the locked ProDayTraderV1 cycle.

The evaluator never discovers artifacts by timestamp.  Every sanitized ZIP must
be supplied explicitly and must have a matching, hashed record in the frozen
manifest.  A post-run manifest record has this minimal shape::

    "artifacts": {
      "canonical": {
        "path": "user_data/backtest_results/proday-canonical.zip",
        "filename": "proday-canonical.zip",
        "sha256": "...", "sanitized": true,
        "members": {
          "result":   {"filename": "...json", "sha256": "..."},
          "config":   {"filename": "..._config.json", "sha256": "..."},
          "strategy": {"filename": "..._ProDayTraderV1.py", "sha256": "..."}
        }
      },
      "train": { ... }, "validation": { ... }, "current_partial": { ... }
    }

The original frozen file records may be under ``inputs`` or ``files``.  This
keeps the evaluator compatible with the immutable pre-PnL data-gate manifest,
while refusing to evaluate until a separately hashed artifact inventory exists.
No filesystem mtime or wall-clock timestamp enters the decision or output.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import re
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
STRATEGY = "ProDayTraderV1"
PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT")
TIMEFRAMES = ("5m", "15m", "1h", "4h")
ARTIFACT_LABELS = ("canonical", "train", "validation", "current_partial")
PERIODS = {
    "canonical": ("2021-01-01T00:00:00Z", "2026-08-01T00:00:00Z"),
    "train": ("2021-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
    "validation": ("2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    "current_partial": ("2026-01-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}
EXPECTED_TIMERANGES = {
    label: start[0:10].replace("-", "") + "-" + end[0:10].replace("-", "")
    for label, (start, end) in PERIODS.items()
}
SETUPS = ("trend_pullback", "breakout_retest", "liquidity_sweep")
REGIMES = ("bull", "bear", "sideways")
RECURSIVE_COUNTS = (199, 399, 799, 1599, 3199, 6399, 12799)
STARTUP_CANDLE_COUNT = 3199
PROFIT_TOLERANCE = 1e-6
PF_TOLERANCE = 1e-12
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1_000_000_000
MAX_JSON_MEMBER_BYTES = 200_000_000
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TAG_RE = re.compile(
    r"^(trend_pullback|breakout_retest|liquidity_sweep)_"
    r"(long|short)_r([0-2])l([0-2])s([0-2])t([0-2])p([0-2])_total(\d{1,2})$"
)
SENSITIVE_KEYS = {
    "api_key", "apikey", "jwt_secret_key", "key", "password", "secret",
    "secret_key", "token", "ws_token", "webhook_url",
}
REDACTION = "REDACTED"
STRESS_SCENARIOS: dict[str, dict[str, float]] = {
    "moderate": {
        "additional_fee_bps_per_side": 2.0,
        "slippage_bps_per_side": 5.0,
        "latency_bps_one_way": 2.0,
        "funding_multiplier": 1.5,
    },
    "severe": {
        "additional_fee_bps_per_side": 10.0,
        "slippage_bps_per_side": 15.0,
        "latency_bps_one_way": 5.0,
        "funding_multiplier": 3.0,
    },
}


class EvaluationError(RuntimeError):
    """A technical/source-integrity failure which must reject the candidate."""


@dataclass(frozen=True)
class Trade:
    pair: str
    open_time: datetime
    close_time: datetime
    profit_abs: float
    profit_ratio: float
    is_short: bool
    setup: str
    side: str
    tag: str
    amount: float
    open_rate: float
    close_rate: float
    funding_fees: float
    regime: str | None = None


@dataclass
class Artifact:
    label: str
    path: Path
    sha256: str
    result_member: str
    config_member: str
    strategy_member: str
    wallet_member: str | None
    result_sha256: str
    config_sha256: str
    strategy_sha256: str
    result: dict[str, Any]
    config: dict[str, Any]
    strategy_source: bytes
    wallet_bytes: bytes | None
    strategy_payload: dict[str, Any]
    trades: list[Trade]
    source_metrics: dict[str, Any]


def _reject_constant(value: str) -> None:
    raise EvaluationError(f"JSON contains forbidden non-finite constant {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def load_json_bytes(payload: bytes, label: str) -> Any:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationError(f"{label} is not UTF-8") from exc
    try:
        return json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except EvaluationError:
        raise
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"{label} is not valid JSON: {exc.msg}") from exc


def load_json(path: Path, label: str) -> Any:
    try:
        return load_json_bytes(path.read_bytes(), label)
    except OSError as exc:
        raise EvaluationError(f"Cannot read {label}: {path}") from exc


def finite_number(value: Any, field: str) -> float:
    """Accept only real JSON numbers, never bools, numeric strings, NaN or inf."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{field} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise EvaluationError(f"{field} must be finite")
    return number


def strict_integer(value: Any, field: str, *, minimum: int = 0) -> int:
    number = finite_number(value, field)
    if not number.is_integer() or number < minimum:
        raise EvaluationError(f"{field} must be an integer >= {minimum}")
    return int(number)


def parse_utc(value: Any, field: str) -> datetime:
    if isinstance(value, bool):
        raise EvaluationError(f"{field} must be an ISO timestamp or epoch number")
    if isinstance(value, (int, float)):
        stamp = finite_number(value, field)
        if stamp > 10_000_000_000:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise EvaluationError(f"{field} is outside the supported timestamp range") from exc
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{field} must be an ISO timestamp or epoch number")
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise EvaluationError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise EvaluationError(f"Cannot hash required file: {path}") from exc
    return digest.hexdigest()


def require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value.lower()):
        raise EvaluationError(f"{field} must be a 64-character SHA256")
    return value.lower()


def within_workspace(path: Path, workspace: Path, field: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise EvaluationError(f"{field} escapes the workspace") from exc
    return resolved


def resolve_record_path(record: Mapping[str, Any], workspace: Path, field: str) -> Path:
    raw = record.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluationError(f"{field}.path is required")
    path = Path(raw)
    if not path.is_absolute():
        path = workspace / path
    resolved = within_workspace(path, workspace, f"{field}.path")
    filename = record.get("filename")
    if filename is not None and (not isinstance(filename, str) or filename != resolved.name):
        raise EvaluationError(f"{field}.filename does not match its path")
    return resolved


def verify_file_record(record: Any, workspace: Path, field: str) -> Path:
    if not isinstance(record, Mapping):
        raise EvaluationError(f"{field} must be a file record")
    path = resolve_record_path(record, workspace, field)
    if not path.is_file():
        raise EvaluationError(f"{field} file is missing: {path}")
    expected = require_hash(record.get("sha256"), f"{field}.sha256")
    actual = sha256_file(path)
    if actual != expected:
        raise EvaluationError(f"{field} SHA256 mismatch")
    if "bytes" in record and strict_integer(record["bytes"], f"{field}.bytes") != path.stat().st_size:
        raise EvaluationError(f"{field} byte count mismatch")
    return path


def _input_records(manifest: Mapping[str, Any]) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for container_name in ("inputs", "files", "frozen_inputs"):
        container = manifest.get(container_name)
        if isinstance(container, Mapping):
            records.update(container)
    aliases = {
        "plan": ("plan", "research_plan"),
        "strategy": ("strategy",),
        "config": ("config", "research_config"),
        "risk_policy": ("risk_policy", "risk"),
        "data_quality": ("data_quality", "data_audit"),
    }
    normalized: dict[str, Any] = {}
    for target, names in aliases.items():
        for name in names:
            if name in records:
                normalized[target] = records[name]
                break
    return normalized


def verify_manifest_inputs(
    manifest: Mapping[str, Any], workspace: Path
) -> tuple[dict[str, Path], Path]:
    if str(manifest.get("schema_version")) != SCHEMA_VERSION:
        raise EvaluationError("Unsupported manifest schema_version")
    if manifest.get("status") != "RESEARCH_FROZEN":
        raise EvaluationError("Manifest status must be RESEARCH_FROZEN")
    candidate = manifest.get("candidate", manifest.get("strategy"))
    if candidate != STRATEGY:
        raise EvaluationError(f"Manifest candidate must be {STRATEGY}")
    if manifest.get("live_trading_authorized", False) is not False:
        raise EvaluationError("Manifest must not authorize live trading")

    records = _input_records(manifest)
    required = ("plan", "strategy", "config", "risk_policy", "data_quality")
    missing = [name for name in required if name not in records]
    if missing:
        raise EvaluationError("Manifest missing frozen input records: " + ", ".join(missing))
    paths = {
        name: verify_file_record(records[name], workspace, f"input.{name}")
        for name in required
    }
    audit = load_json(paths["data_quality"], "data quality audit")
    if not isinstance(audit, Mapping) or audit.get("status") != "PASS":
        raise EvaluationError("Frozen data quality audit is not PASS")

    data_files = manifest.get("data_files")
    if not isinstance(data_files, list):
        raise EvaluationError("Manifest data_files must be a list")
    expected = {(pair, timeframe) for pair in PAIRS for timeframe in TIMEFRAMES}
    seen: dict[tuple[str, str], Path] = {}
    for index, record in enumerate(data_files):
        if not isinstance(record, Mapping):
            raise EvaluationError(f"data_files[{index}] must be a file record")
        pair, timeframe = record.get("pair"), record.get("timeframe")
        key = (pair, timeframe)
        if key not in expected:
            raise EvaluationError(f"data_files[{index}] has an unlocked pair/timeframe")
        if key in seen:
            raise EvaluationError(f"Duplicate data file record for {pair} {timeframe}")
        seen[key] = verify_file_record(record, workspace, f"data_files[{index}]")
    if set(seen) != expected:
        missing_data = sorted(expected - set(seen))
        raise EvaluationError(f"Manifest does not contain the exact 12 data files: {missing_data}")
    return paths, seen[("BTC/USDT:USDT", "4h")]


def parse_explicit_artifacts(values: Sequence[str], workspace: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    aliases = {"current": "current_partial"}
    for value in values:
        if "=" not in value:
            raise EvaluationError("Each --artifact must be LABEL=PATH")
        raw_label, raw_path = value.split("=", 1)
        label = aliases.get(raw_label.strip(), raw_label.strip())
        if label not in ARTIFACT_LABELS:
            raise EvaluationError(f"Unknown artifact label {raw_label!r}")
        if label in result:
            raise EvaluationError(f"Duplicate explicit artifact label {label}")
        if not raw_path.strip():
            raise EvaluationError(f"Artifact {label} has an empty path")
        path = Path(raw_path.strip())
        if not path.is_absolute():
            path = workspace / path
        result[label] = within_workspace(path, workspace, f"artifact {label}")
    if set(result) != set(ARTIFACT_LABELS):
        missing = sorted(set(ARTIFACT_LABELS) - set(result))
        raise EvaluationError("Explicit artifacts missing: " + ", ".join(missing))
    return result


def _safe_member_names(bundle: zipfile.ZipFile, archive: Path) -> list[str]:
    names = [info.filename for info in bundle.infolist()]
    if len(names) != len(set(names)):
        raise EvaluationError(f"{archive.name} contains duplicate member names")
    total_size = 0
    for info in bundle.infolist():
        member = PurePosixPath(info.filename.replace("\\", "/"))
        if member.is_absolute() or ".." in member.parts:
            raise EvaluationError(f"{archive.name} contains an unsafe member path")
        if info.flag_bits & 0x1:
            raise EvaluationError(f"{archive.name} contains an encrypted member")
        total_size += info.file_size
    if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise EvaluationError(f"{archive.name} exceeds the uncompressed size limit")
    return names


def _member_spec(record: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    members = record.get("members")
    spec: Any = members.get(role) if isinstance(members, Mapping) else None
    if spec is None:
        spec = record.get(role)
    if not isinstance(spec, Mapping):
        raise EvaluationError(f"Artifact manifest is missing hashed {role} member record")
    return spec


def _verify_member(
    role: str,
    actual_name: str,
    payload: bytes,
    record: Mapping[str, Any],
) -> str:
    spec = _member_spec(record, role)
    expected_name = spec.get("filename", spec.get("name"))
    if not isinstance(expected_name, str) or expected_name != actual_name:
        raise EvaluationError(f"Artifact {role} member filename does not match manifest")
    expected_hash = require_hash(spec.get("sha256"), f"artifact.members.{role}.sha256")
    actual_hash = sha256_bytes(payload)
    if actual_hash != expected_hash:
        raise EvaluationError(f"Artifact {role} member SHA256 mismatch")
    if "bytes" in spec and strict_integer(spec["bytes"], f"artifact.members.{role}.bytes") != len(payload):
        raise EvaluationError(f"Artifact {role} member byte count mismatch")
    return actual_hash


def assert_sanitized(value: Any, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key.lower() in SENSITIVE_KEYS and item not in (None, "", REDACTION):
                raise EvaluationError(f"Sanitized config contains a non-redacted sensitive field at {child}")
            assert_sanitized(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_sanitized(item, f"{path}[{index}]")


def _semantic_subset(expected: Any, actual: Any, path: str = "config") -> None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise EvaluationError(f"Sanitized config mismatch at {path}")
        for key, value in expected.items():
            if key.lower() in SENSITIVE_KEYS or key in {"$schema", "config_files"}:
                continue
            if key not in actual:
                raise EvaluationError(f"Sanitized config is missing frozen field {path}.{key}")
            _semantic_subset(value, actual[key], f"{path}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise EvaluationError(f"Sanitized config mismatch at {path}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            _semantic_subset(left, right, f"{path}[{index}]")
        return
    if isinstance(expected, bool) or isinstance(actual, bool):
        equal = type(expected) is type(actual) and expected == actual
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        equal = math.isfinite(float(expected)) and math.isfinite(float(actual)) and float(expected) == float(actual)
    else:
        equal = type(expected) is type(actual) and expected == actual
    if not equal:
        raise EvaluationError(f"Sanitized config differs from frozen config at {path}")


def verify_locked_config(config: Mapping[str, Any], frozen_config: Mapping[str, Any]) -> None:
    assert_sanitized(config)
    _semantic_subset(frozen_config, config)
    requirements: tuple[tuple[str, Any], ...] = (
        ("dry_run", True),
        ("trading_mode", "futures"),
        ("margin_mode", "isolated"),
        ("stake_currency", "USDT"),
        ("max_open_trades", 2),
        ("timeframe", "5m"),
    )
    for key, expected in requirements:
        if config.get(key) != expected:
            raise EvaluationError(f"Sanitized config violates locked field {key}")
    fee = finite_number(config.get("fee"), "config.fee")
    if abs(fee - 0.0005) > 1e-15:
        raise EvaluationError("Sanitized config fee must be 5 bps per side")
    exchange = config.get("exchange")
    if not isinstance(exchange, Mapping) or exchange.get("name") != "binance":
        raise EvaluationError("Sanitized config exchange must be Binance")
    whitelist = exchange.get("pair_whitelist")
    if (
        not isinstance(whitelist, list)
        or len(whitelist) != len(PAIRS)
        or set(whitelist) != set(PAIRS)
    ):
        raise EvaluationError("Sanitized config pair whitelist must match the locked universe")


def _parse_timerange(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise EvaluationError(f"{field} must be a timerange string")
    match = re.fullmatch(r"(\d{8})-(\d{8})", value.strip())
    if not match:
        raise EvaluationError(f"{field} must use YYYYMMDD-YYYYMMDD")
    return value.strip()


def parse_trade(raw: Any, index: int) -> Trade:
    if not isinstance(raw, Mapping):
        raise EvaluationError(f"trade[{index}] must be an object")
    pair = raw.get("pair")
    if pair not in PAIRS:
        raise EvaluationError(f"trade[{index}].pair is outside the locked universe")
    is_short = raw.get("is_short")
    if not isinstance(is_short, bool):
        raise EvaluationError(f"trade[{index}].is_short must be boolean")
    if raw.get("is_open", False) is not False:
        raise EvaluationError(f"trade[{index}] is not closed")
    tag = raw.get("enter_tag")
    if not isinstance(tag, str):
        raise EvaluationError(f"trade[{index}].enter_tag must be a locked explanatory tag")
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise EvaluationError(f"trade[{index}].enter_tag does not match the locked schema")
    setup, side = match.group(1), match.group(2)
    expected_side = "short" if is_short else "long"
    if side != expected_side:
        raise EvaluationError(f"trade[{index}] tag side disagrees with is_short")
    scores = tuple(int(item) for item in match.groups()[2:7])
    total = int(match.group(8))
    if sum(scores) != total:
        raise EvaluationError(f"trade[{index}] tag component scores do not sum to total")
    regime, location, structure, trigger, participation = scores
    if trigger != 2 or location < 1 or structure < 1 or participation < 1:
        raise EvaluationError(f"trade[{index}] tag violates mandatory component gates")
    if side == "long" and (regime < 1 or total < 7):
        raise EvaluationError(f"trade[{index}] tag violates locked long threshold")
    if side == "short" and (regime != 2 or total < 8):
        raise EvaluationError(f"trade[{index}] tag violates locked short threshold")
    leverage = finite_number(raw.get("leverage"), f"trade[{index}].leverage")
    if abs(leverage - 1.0) > 1e-12:
        raise EvaluationError(f"trade[{index}] leverage is not locked at 1x")
    return Trade(
        pair=pair,
        open_time=parse_utc(raw.get("open_timestamp", raw.get("open_date")), f"trade[{index}].open_time"),
        close_time=parse_utc(raw.get("close_timestamp", raw.get("close_date")), f"trade[{index}].close_time"),
        profit_abs=finite_number(raw.get("profit_abs"), f"trade[{index}].profit_abs"),
        profit_ratio=finite_number(raw.get("profit_ratio"), f"trade[{index}].profit_ratio"),
        is_short=is_short,
        setup=setup,
        side=side,
        tag=tag,
        amount=abs(finite_number(raw.get("amount"), f"trade[{index}].amount")),
        open_rate=abs(finite_number(raw.get("open_rate"), f"trade[{index}].open_rate")),
        close_rate=abs(finite_number(raw.get("close_rate"), f"trade[{index}].close_rate")),
        funding_fees=finite_number(raw.get("funding_fees", 0.0), f"trade[{index}].funding_fees"),
    )


def profit_factor(profits: Iterable[float]) -> float | None:
    values = list(profits)
    gross_positive = math.fsum(value for value in values if value > 0)
    gross_loss = abs(math.fsum(value for value in values if value < 0))
    if gross_loss == 0:
        return None
    return gross_positive / gross_loss


def _assert_close(actual: float, expected: float, tolerance: float, field: str) -> None:
    if abs(actual - expected) > tolerance:
        raise EvaluationError(f"Source reconciliation failed for {field}")


def reconcile_source(payload: Mapping[str, Any], trades: Sequence[Trade], label: str) -> dict[str, Any]:
    profits = [trade.profit_abs for trade in trades]
    wins = sum(value > 0 for value in profits)
    losses = sum(value < 0 for value in profits)
    draws = sum(value == 0 for value in profits)
    longs = sum(not trade.is_short for trade in trades)
    shorts = sum(trade.is_short for trade in trades)
    expected_counts = {
        "total_trades": len(trades), "wins": wins, "losses": losses, "draws": draws,
        "trade_count_long": longs, "trade_count_short": shorts,
    }
    for key, expected in expected_counts.items():
        actual = strict_integer(payload.get(key), f"{label}.{key}")
        if actual != expected:
            raise EvaluationError(f"Source reconciliation failed for {label}.{key}")
    net = math.fsum(profits)
    stored_net = finite_number(payload.get("profit_total_abs"), f"{label}.profit_total_abs")
    _assert_close(net, stored_net, PROFIT_TOLERANCE, f"{label}.profit_total_abs")
    computed_pf = profit_factor(profits)
    stored_pf_raw = payload.get("profit_factor")
    if computed_pf is None:
        # Freqtrade serializes zero gross loss as 0.0, including all-winning and
        # empty samples.  Independently this is unbounded (wins) or undefined
        # (no positive PnL); neither is emitted as non-finite JSON.
        if stored_pf_raw != 0:
            raise EvaluationError(f"Source reconciliation failed for {label}.profit_factor")
        stored_pf = None
    else:
        stored_pf = finite_number(stored_pf_raw, f"{label}.profit_factor")
        _assert_close(computed_pf, stored_pf, PF_TOLERANCE, f"{label}.profit_factor")
    starting = finite_number(payload.get("starting_balance"), f"{label}.starting_balance")
    if starting <= 0:
        raise EvaluationError(f"{label}.starting_balance must be positive")
    stored_return = finite_number(payload.get("profit_total"), f"{label}.profit_total")
    _assert_close(net / starting, stored_return, PF_TOLERANCE, f"{label}.profit_total")
    source_dd_fraction = finite_number(
        payload.get("max_drawdown_account"), f"{label}.max_drawdown_account"
    )
    if not 0 <= source_dd_fraction <= 1:
        raise EvaluationError(f"{label}.max_drawdown_account must be in [0, 1]")

    per_pair: dict[str, list[Trade]] = {pair: [] for pair in PAIRS}
    for trade in trades:
        per_pair[trade.pair].append(trade)
    rows = payload.get("results_per_pair")
    if not isinstance(rows, list):
        raise EvaluationError(f"{label}.results_per_pair must be a list")
    row_map: dict[Any, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise EvaluationError(f"{label}.results_per_pair contains a non-object row")
        key = row.get("key")
        if key in row_map:
            raise EvaluationError(f"{label}.results_per_pair contains duplicate key {key!r}")
        row_map[key] = row
    for pair, pair_trades in per_pair.items():
        row = row_map.get(pair)
        if not isinstance(row, Mapping):
            raise EvaluationError(f"{label}.results_per_pair is missing {pair}")
        pair_profits = [trade.profit_abs for trade in pair_trades]
        counts = {
            "trades": len(pair_trades),
            "wins": sum(value > 0 for value in pair_profits),
            "losses": sum(value < 0 for value in pair_profits),
            "draws": sum(value == 0 for value in pair_profits),
        }
        for key, expected in counts.items():
            if strict_integer(row.get(key), f"{label}.{pair}.{key}") != expected:
                raise EvaluationError(f"Source pair reconciliation failed for {label}.{pair}.{key}")
        _assert_close(
            math.fsum(pair_profits),
            finite_number(row.get("profit_total_abs"), f"{label}.{pair}.profit_total_abs"),
            PROFIT_TOLERANCE,
            f"{label}.{pair}.profit_total_abs",
        )
        pair_pf = profit_factor(pair_profits)
        if pair_pf is None:
            if row.get("profit_factor") != 0:
                raise EvaluationError(f"Source pair PF reconciliation failed for {label}.{pair}")
        else:
            _assert_close(
                pair_pf,
                finite_number(row.get("profit_factor"), f"{label}.{pair}.profit_factor"),
                PF_TOLERANCE,
                f"{label}.{pair}.profit_factor",
            )

    for side, source_key in (("long", "profit_total_long_abs"), ("short", "profit_total_short_abs")):
        expected = math.fsum(trade.profit_abs for trade in trades if trade.side == side)
        actual = finite_number(payload.get(source_key), f"{label}.{source_key}")
        _assert_close(expected, actual, PROFIT_TOLERANCE, f"{label}.{source_key}")

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "longs": longs,
        "shorts": shorts,
        "net_profit_abs": net,
        "profit_factor": computed_pf,
        "profit_factor_unbounded": computed_pf is None and any(value > 0 for value in profits),
        "return_pct": stored_return * 100.0,
        "source_max_drawdown_account_pct": source_dd_fraction * 100.0,
        "starting_balance": starting,
        "rejected_signals": strict_integer(payload.get("rejected_signals", 0), f"{label}.rejected_signals"),
    }


def load_artifact(
    label: str,
    path: Path,
    record: Any,
    frozen_strategy_hash: str,
    frozen_config: Mapping[str, Any],
) -> Artifact:
    if not isinstance(record, Mapping):
        raise EvaluationError(f"Manifest artifact {label} must be a record")
    expected_path = record.get("path")
    expected_filename = record.get("filename")
    if not isinstance(expected_path, str) or not isinstance(expected_filename, str):
        raise EvaluationError(f"Manifest artifact {label} needs path and filename")
    if path.name != expected_filename:
        raise EvaluationError(f"Explicit artifact {label} filename does not match manifest")
    normalized_expected = expected_path.replace("\\", "/").lstrip("./")
    normalized_actual = path.as_posix()
    if not normalized_actual.endswith("/" + normalized_expected) and normalized_actual != normalized_expected:
        raise EvaluationError(f"Explicit artifact {label} path does not match manifest")
    if record.get("sanitized") is not True:
        raise EvaluationError(f"Manifest artifact {label} is not explicitly marked sanitized")
    status = record.get("status")
    if not isinstance(status, str) or not status.strip():
        raise EvaluationError(f"Manifest artifact {label} needs a completed status")
    normalized_status = status.strip().upper()
    if any(token in normalized_status for token in ("PLANNED", "PENDING", "NOT_RUN")):
        raise EvaluationError(f"Manifest artifact {label} is still {status}")
    if path.suffix.lower() != ".zip" or not path.is_file():
        raise EvaluationError(f"Explicit artifact {label} is not an existing ZIP")
    expected_zip_hash = require_hash(record.get("sha256"), f"artifacts.{label}.sha256")
    actual_zip_hash = sha256_file(path)
    if actual_zip_hash != expected_zip_hash:
        raise EvaluationError(f"Artifact {label} ZIP SHA256 mismatch")
    if "bytes" in record and strict_integer(record["bytes"], f"artifacts.{label}.bytes") != path.stat().st_size:
        raise EvaluationError(f"Artifact {label} ZIP byte count mismatch")
    try:
        with zipfile.ZipFile(path, "r") as bundle:
            names = _safe_member_names(bundle, path)
            bad = bundle.testzip()
            if bad is not None:
                raise EvaluationError(f"Artifact {label} failed ZIP integrity at a member")
            result_names = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            config_names = [name for name in names if name.endswith("_config.json")]
            source_names = [name for name in names if name.endswith(f"_{STRATEGY}.py")]
            wallet_names = [name for name in names if name.endswith(f"_{STRATEGY}_wallet.feather")]
            if len(result_names) != 1 or len(config_names) != 1 or len(source_names) != 1:
                raise EvaluationError(
                    f"Artifact {label} must contain exactly one result/config/{STRATEGY} source"
                )
            if len(wallet_names) > 1:
                raise EvaluationError(f"Artifact {label} has multiple strategy wallet members")
            for name in result_names + config_names + source_names:
                if bundle.getinfo(name).file_size > MAX_JSON_MEMBER_BYTES:
                    raise EvaluationError(f"Artifact {label} metadata/source member is too large")
            result_bytes = bundle.read(result_names[0])
            config_bytes = bundle.read(config_names[0])
            source_bytes = bundle.read(source_names[0])
            wallet_bytes = bundle.read(wallet_names[0]) if wallet_names else None
    except zipfile.BadZipFile as exc:
        raise EvaluationError(f"Artifact {label} is not a valid ZIP") from exc

    result_hash = _verify_member("result", result_names[0], result_bytes, record)
    config_hash = _verify_member("config", config_names[0], config_bytes, record)
    source_hash = _verify_member("strategy", source_names[0], source_bytes, record)
    if source_hash != frozen_strategy_hash:
        raise EvaluationError(f"Artifact {label} embedded strategy differs from frozen workspace source")
    result = load_json_bytes(result_bytes, f"artifact {label} result")
    config = load_json_bytes(config_bytes, f"artifact {label} config")
    if not isinstance(result, Mapping) or not isinstance(config, Mapping):
        raise EvaluationError(f"Artifact {label} result/config roots must be objects")
    verify_locked_config(config, frozen_config)
    strategies = result.get("strategy")
    if not isinstance(strategies, Mapping) or set(strategies) != {STRATEGY}:
        raise EvaluationError(f"Artifact {label} must contain only strategy {STRATEGY}")
    strategy_payload = strategies[STRATEGY]
    if not isinstance(strategy_payload, Mapping):
        raise EvaluationError(f"Artifact {label} strategy payload must be an object")
    if strategy_payload.get("strategy_name") != STRATEGY:
        raise EvaluationError(f"Artifact {label} source strategy_name mismatch")
    if _parse_timerange(strategy_payload.get("timerange"), f"{label}.timerange") != EXPECTED_TIMERANGES[label]:
        raise EvaluationError(f"Artifact {label} timerange does not match the locked period")
    for key, expected in (
        ("timeframe", "5m"), ("trading_mode", "futures"),
        ("margin_mode", "isolated"), ("max_open_trades", 2),
        ("enable_protections", True),
    ):
        if strategy_payload.get(key) != expected:
            raise EvaluationError(f"Artifact {label} result violates locked field {key}")
    pairlist = strategy_payload.get("pairlist")
    if (
        not isinstance(pairlist, list)
        or len(pairlist) != len(PAIRS)
        or set(pairlist) != set(PAIRS)
    ):
        raise EvaluationError(f"Artifact {label} result pairlist mismatch")
    raw_trades = strategy_payload.get("trades")
    if not isinstance(raw_trades, list):
        raise EvaluationError(f"Artifact {label} trades must be a list")
    trades = [parse_trade(raw, index) for index, raw in enumerate(raw_trades)]
    start = parse_utc(PERIODS[label][0], f"{label}.start")
    end = parse_utc(PERIODS[label][1], f"{label}.end")
    for index, trade in enumerate(trades):
        if not start <= trade.open_time < end:
            raise EvaluationError(f"Artifact {label} trade[{index}] opens outside locked period")
        if trade.close_time < trade.open_time:
            raise EvaluationError(f"Artifact {label} trade[{index}] closes before it opens")
    metrics = reconcile_source(strategy_payload, trades, label)
    return Artifact(
        label=label,
        path=path,
        sha256=actual_zip_hash,
        result_member=result_names[0],
        config_member=config_names[0],
        strategy_member=source_names[0],
        wallet_member=wallet_names[0] if wallet_names else None,
        result_sha256=result_hash,
        config_sha256=config_hash,
        strategy_sha256=source_hash,
        result=dict(result),
        config=dict(config),
        strategy_source=source_bytes,
        wallet_bytes=wallet_bytes,
        strategy_payload=dict(strategy_payload),
        trades=trades,
        source_metrics=metrics,
    )


def _read_feather(source: Path | bytes, label: str) -> Any:
    try:
        import pandas as pd
    except ImportError as exc:
        raise EvaluationError("pandas/pyarrow are required to read locked Feather evidence") from exc
    try:
        return pd.read_feather(io.BytesIO(source) if isinstance(source, bytes) else source)
    except Exception as exc:
        raise EvaluationError(f"Cannot read {label} Feather evidence") from exc


def _talib_ema(values: Sequence[float], period: int) -> list[float]:
    """TA-Lib compatible EMA seed (period SMA, then recursive EMA)."""
    result = [math.nan] * len(values)
    if len(values) < period:
        return result
    seed = math.fsum(values[:period]) / period
    result[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(values)):
        previous = (values[index] - previous) * alpha + previous
        result[index] = previous
    return result


def _talib_adx(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14) -> list[float]:
    """Wilder ADX with the same lookback/seed convention used by TA-Lib."""
    size = len(close)
    result = [math.nan] * size
    if size <= 2 * period - 1:
        return result
    true_range = [0.0] * size
    plus_dm = [0.0] * size
    minus_dm = [0.0] * size
    for index in range(1, size):
        up = high[index] - high[index - 1]
        down = low[index - 1] - low[index]
        plus_dm[index] = up if up > down and up > 0 else 0.0
        minus_dm[index] = down if down > up and down > 0 else 0.0
        true_range[index] = max(
            high[index] - low[index],
            abs(high[index] - close[index - 1]),
            abs(low[index] - close[index - 1]),
        )
    smoothed_tr = math.fsum(true_range[1 : period + 1])
    smoothed_plus = math.fsum(plus_dm[1 : period + 1])
    smoothed_minus = math.fsum(minus_dm[1 : period + 1])
    dx_values: list[float] = []
    for index in range(period, size):
        if index > period:
            smoothed_tr = smoothed_tr - smoothed_tr / period + true_range[index]
            smoothed_plus = smoothed_plus - smoothed_plus / period + plus_dm[index]
            smoothed_minus = smoothed_minus - smoothed_minus / period + minus_dm[index]
        if smoothed_tr == 0:
            dx = 0.0
        else:
            plus_di = 100.0 * smoothed_plus / smoothed_tr
            minus_di = 100.0 * smoothed_minus / smoothed_tr
            denominator = plus_di + minus_di
            dx = 0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator
        dx_values.append(dx)
        if len(dx_values) == period:
            result[index] = math.fsum(dx_values) / period
        elif len(dx_values) > period:
            previous = result[index - 1]
            result[index] = ((previous * (period - 1)) + dx) / period
    return result


def build_btc_regime_context(path: Path) -> tuple[list[datetime], list[str | None], dict[str, Any]]:
    frame = _read_feather(path, "BTC 4h")
    required = {"date", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise EvaluationError("BTC 4h Feather lacks date/high/low/close")
    try:
        import pandas as pd
        dates = pd.to_datetime(frame["date"], utc=True, errors="raise")
    except Exception as exc:
        raise EvaluationError("BTC 4h Feather contains invalid timestamps") from exc
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise EvaluationError("BTC 4h Feather timestamps must be unique and increasing")
    numeric = frame[["high", "low", "close"]].astype(float)
    if not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()):
        raise EvaluationError("BTC 4h Feather contains non-finite regime inputs")
    high = [float(value) for value in numeric["high"]]
    low = [float(value) for value in numeric["low"]]
    close = [float(value) for value in numeric["close"]]
    ema50 = _talib_ema(close, 50)
    ema200 = _talib_ema(close, 200)
    adx = _talib_adx(high, low, close, 14)
    available = [(item.to_pydatetime() + timedelta(hours=4)).astimezone(timezone.utc) for item in dates]
    regimes: list[str | None] = []
    for c, e50, e200, strength in zip(close, ema50, ema200, adx):
        values = (float(c), float(e50), float(e200), float(strength))
        if not all(math.isfinite(value) for value in values):
            regimes.append(None)
        elif c > e200 and e50 > e200 and strength >= 20:
            regimes.append("bull")
        elif c < e200 and e50 < e200 and strength >= 20:
            regimes.append("bear")
        else:
            regimes.append("sideways")
    counts = Counter(regime if regime is not None else "unavailable" for regime in regimes)
    return available, regimes, {"candles": len(regimes), "candle_regime_counts": dict(sorted(counts.items()))}


def assign_regimes(
    trades: Sequence[Trade], available: Sequence[datetime], regimes: Sequence[str | None]
) -> list[Trade]:
    assigned: list[Trade] = []
    for index, trade in enumerate(trades):
        position = bisect.bisect_right(available, trade.open_time) - 1
        if position < 0 or regimes[position] is None:
            raise EvaluationError(f"No closed, fully initialized BTC 4h regime exists for trade[{index}] entry")
        assigned.append(Trade(**{**trade.__dict__, "regime": regimes[position]}))
    return assigned


def regime_time_share(
    available: Sequence[datetime], regimes: Sequence[str | None], start: datetime, end: datetime
) -> dict[str, float]:
    seconds: Counter[str] = Counter()
    for index, left in enumerate(available):
        right = available[index + 1] if index + 1 < len(available) else end
        window_left, window_right = max(left, start), min(right, end)
        if window_right > window_left:
            key = regimes[index] if regimes[index] is not None else "unavailable"
            seconds[str(key)] += (window_right - window_left).total_seconds()
    total = (end - start).total_seconds()
    return {key: seconds.get(key, 0.0) / total for key in (*REGIMES, "unavailable")}


def wallet_series(wallet_bytes: bytes) -> list[tuple[datetime, float]]:
    frame = _read_feather(wallet_bytes, "canonical wallet")
    if not {"date", "total_quote"}.issubset(frame.columns):
        raise EvaluationError("Canonical wallet Feather lacks date/total_quote")
    try:
        import pandas as pd
        dates = pd.to_datetime(frame["date"], utc=True, errors="raise")
    except Exception as exc:
        raise EvaluationError("Canonical wallet Feather has invalid dates") from exc
    values: dict[datetime, float] = {}
    for date, raw in zip(dates, frame["total_quote"]):
        timestamp = date.to_pydatetime().astimezone(timezone.utc)
        value = finite_number(raw, "wallet.total_quote")
        if value <= 0:
            raise EvaluationError("Canonical wallet total_quote must be positive")
        if timestamp in values and values[timestamp] != value:
            raise EvaluationError("Canonical wallet has conflicting values at one timestamp")
        values[timestamp] = value
    ordered = sorted(values.items())
    if not ordered:
        raise EvaluationError("Canonical wallet Feather is empty")
    return ordered


def continuous_wallet_drawdown_pct(
    series: Sequence[tuple[datetime, float]], start: datetime, end: datetime
) -> float:
    peak: float | None = None
    maximum = 0.0
    found = False
    for timestamp, equity in series:
        if timestamp >= end:
            break
        peak = equity if peak is None else max(peak, equity)
        if timestamp >= start:
            found = True
            maximum = max(maximum, (peak - equity) / peak * 100.0)
    if not found:
        raise EvaluationError("Canonical wallet has no observations inside a required period")
    return maximum


def stress_profit(trade: Trade, scenario: Mapping[str, float]) -> float:
    entry_notional = trade.amount * trade.open_rate
    exit_notional = trade.amount * trade.close_rate
    bps = scenario["additional_fee_bps_per_side"] + scenario["slippage_bps_per_side"]
    round_trip_cost = bps / 10_000.0 * (entry_notional + exit_notional)
    latency_cost = scenario["latency_bps_one_way"] / 10_000.0 * entry_notional
    extra_funding = abs(trade.funding_fees) * (scenario["funding_multiplier"] - 1.0)
    return trade.profit_abs - round_trip_cost - latency_cost - extra_funding


def realized_drawdown_pct(profits: Sequence[tuple[datetime, float]], starting: float) -> float:
    equity = peak = starting
    maximum = 0.0
    for _, profit in sorted(profits, key=lambda item: item[0]):
        equity += profit
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak * 100.0)
    return maximum


def summarize_trades(
    scope: str,
    key: str,
    trades: Sequence[Trade],
    starting: float,
    *,
    scenario: str = "baseline",
    source_dd: float | None = None,
    wallet_dd: float | None = None,
) -> dict[str, Any]:
    if scenario == "baseline":
        profits = [trade.profit_abs for trade in trades]
    else:
        profits = [stress_profit(trade, STRESS_SCENARIOS[scenario]) for trade in trades]
    net = math.fsum(profits)
    pf = profit_factor(profits)
    pf_unbounded = pf is None and any(value > 0 for value in profits)
    realized = realized_drawdown_pct(
        [(trade.close_time, profit) for trade, profit in zip(trades, profits)], starting
    )
    official_dd = source_dd if source_dd is not None else wallet_dd
    return_dd = None if official_dd in (None, 0) else (net / starting * 100.0) / official_dd
    gross_positive = math.fsum(value for value in profits if value > 0)
    largest_win_contribution = (
        max((value for value in profits if value > 0), default=0.0) / gross_positive
        if gross_positive > 0 else None
    )
    return {
        "scope": scope,
        "key": key,
        "scenario": scenario,
        "trades": len(trades),
        "wins": sum(value > 0 for value in profits),
        "losses": sum(value < 0 for value in profits),
        "draws": sum(value == 0 for value in profits),
        "longs": sum(not trade.is_short for trade in trades),
        "shorts": sum(trade.is_short for trade in trades),
        "net_profit_abs": net,
        "return_pct": net / starting * 100.0,
        "profit_factor": pf,
        "profit_factor_unbounded": pf_unbounded,
        "source_max_drawdown_account_pct": source_dd,
        "continuous_wallet_drawdown_pct": wallet_dd,
        "realized_closed_trade_drawdown_pct": realized,
        "return_to_drawdown": return_dd,
        "largest_winning_trade_contribution": largest_win_contribution,
    }


def _period_trades(trades: Sequence[Trade], start: datetime, end: datetime) -> list[Trade]:
    return [trade for trade in trades if start <= trade.close_time < end]


def _quarter_bounds(year: int, quarter: int) -> tuple[datetime, datetime]:
    month = 1 + (quarter - 1) * 3
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if quarter == 4 else datetime(year, month + 3, 1, tzinfo=timezone.utc)
    return start, end


def build_metrics(
    artifacts: Mapping[str, Artifact],
    wallet: Sequence[tuple[datetime, float]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    starting = artifacts["canonical"].source_metrics["starting_balance"]
    rows: list[dict[str, Any]] = []
    for label in ARTIFACT_LABELS:
        artifact = artifacts[label]
        rows.append(summarize_trades(
            "period" if label != "canonical" else "overall",
            label,
            artifact.trades,
            artifact.source_metrics["starting_balance"],
            source_dd=artifact.source_metrics["source_max_drawdown_account_pct"],
        ))
    canonical = artifacts["canonical"].trades
    validation = artifacts["validation"].trades
    for year in range(2021, 2027):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        locked_end = parse_utc(PERIODS["canonical"][1], "canonical.end")
        actual_end = min(end, locked_end)
        if start >= actual_end:
            continue
        rows.append(summarize_trades(
            "year", str(year), _period_trades(canonical, start, actual_end), starting,
            wallet_dd=continuous_wallet_drawdown_pct(wallet, start, actual_end),
        ))
    for year in range(2021, 2027):
        for quarter in range(1, 5):
            start, end = _quarter_bounds(year, quarter)
            canonical_end = parse_utc(PERIODS["canonical"][1], "canonical.end")
            if start >= canonical_end:
                continue
            actual_end = min(end, canonical_end)
            row = summarize_trades(
                "quarter", f"{year}Q{quarter}", _period_trades(canonical, start, actual_end), starting,
                wallet_dd=continuous_wallet_drawdown_pct(wallet, start, actual_end),
            )
            row["full_period"] = end <= canonical_end
            rows.append(row)
    for pair in PAIRS:
        rows.append(summarize_trades(
            "pair", pair, [trade for trade in validation if trade.pair == pair], starting
        ))
    for side in ("long", "short"):
        rows.append(summarize_trades(
            "direction", side, [trade for trade in validation if trade.side == side], starting
        ))
    for setup in SETUPS:
        rows.append(summarize_trades(
            "setup", setup, [trade for trade in validation if trade.setup == setup], starting
        ))
    for regime in REGIMES:
        rows.append(summarize_trades(
            "regime", regime, [trade for trade in validation if trade.regime == regime], starting
        ))
    validation_start = parse_utc(PERIODS["validation"][0], "validation.start")
    validation_end = parse_utc(PERIODS["validation"][1], "validation.end")
    for scenario in STRESS_SCENARIOS:
        rows.append(summarize_trades(
            "stress", "validation", validation, starting, scenario=scenario
        ))
        for year in (2024, 2025):
            start = max(datetime(year, 1, 1, tzinfo=timezone.utc), validation_start)
            end = min(datetime(year + 1, 1, 1, tzinfo=timezone.utc), validation_end)
            rows.append(summarize_trades(
                "stress_year", str(year), _period_trades(validation, start, end), starting,
                scenario=scenario,
            ))
    pair_rows = [row for row in rows if row["scope"] == "pair"]
    positive = [row["net_profit_abs"] for row in pair_rows if row["net_profit_abs"] > 0]
    pair_concentration = max(positive) / math.fsum(positive) if positive else None
    validation_row = next(row for row in rows if row["scope"] == "period" and row["key"] == "validation")
    concentration = {
        "positive_pairs": len(positive),
        "largest_positive_pair_contribution": pair_concentration,
        "largest_winning_trade_contribution": validation_row["largest_winning_trade_contribution"],
    }
    return rows, concentration


def _metric_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    return {(row["scope"], row["key"], row["scenario"]): row for row in rows}


def _ratio_pass(row: Mapping[str, Any], minimum: float) -> bool:
    value = row.get("return_to_drawdown")
    if value is not None:
        return float(value) >= minimum
    return row.get("return_pct", 0) > 0 and (
        row.get("source_max_drawdown_account_pct") == 0
        or row.get("continuous_wallet_drawdown_pct") == 0
    )


def evaluate_locked_gates(
    rows: Sequence[Mapping[str, Any]], concentration: Mapping[str, Any]
) -> list[dict[str, Any]]:
    index = _metric_index(rows)
    gates: list[dict[str, Any]] = []

    def add(section: str, gate_id: str, passed: bool, actual: Any, requirement: str) -> None:
        gates.append({
            "section": section, "id": gate_id, "passed": bool(passed),
            "actual": actual, "requirement": requirement,
        })

    def value_gate(section: str, gate_id: str, row: Mapping[str, Any], key: str, op: str, threshold: float) -> None:
        actual = row.get(key)
        unbounded_pf = key == "profit_factor" and row.get("profit_factor_unbounded") is True
        if unbounded_pf:
            passed = op in (">", ">=")
            rendered_actual: Any = "UNBOUNDED_NO_LOSSES"
        else:
            passed = actual is not None and {
                ">=": actual >= threshold, ">": actual > threshold,
                "<=": actual <= threshold, "<": actual < threshold,
            }[op]
            rendered_actual = actual
        add(section, gate_id, passed, rendered_actual, f"{key} {op} {threshold}")

    train = index[("period", "train", "baseline")]
    value_gate("train", "train_trades", train, "trades", ">=", 180)
    value_gate("train", "train_return", train, "return_pct", ">", 0)
    value_gate("train", "train_pf", train, "profit_factor", ">=", 1.20)
    value_gate("train", "train_source_dd", train, "source_max_drawdown_account_pct", "<=", 15)
    add("train", "train_return_dd", _ratio_pass(train, 0.75), train.get("return_to_drawdown"), "return/drawdown >= 0.75")

    validation = index[("period", "validation", "baseline")]
    value_gate("validation", "validation_trades", validation, "trades", ">=", 120)
    value_gate("validation", "validation_return", validation, "return_pct", ">", 0)
    value_gate("validation", "validation_pf", validation, "profit_factor", ">=", 1.50)
    value_gate("validation", "validation_source_dd", validation, "source_max_drawdown_account_pct", "<=", 12)
    add("validation", "validation_return_dd", _ratio_pass(validation, 1.0), validation.get("return_to_drawdown"), "return/drawdown >= 1.00")
    for year in (2024, 2025):
        row = index[("year", str(year), "baseline")]
        value_gate("validation", f"{year}_trades", row, "trades", ">=", 40)
        value_gate("validation", f"{year}_return", row, "return_pct", ">", 0)
        value_gate("validation", f"{year}_pf", row, "profit_factor", ">=", 1.15)
        value_gate("validation", f"{year}_continuous_dd", row, "continuous_wallet_drawdown_pct", "<=", 10)
    for pair in PAIRS:
        row = index[("pair", pair, "baseline")]
        key = pair.split("/")[0].lower()
        value_gate("validation", f"pair_{key}_trades", row, "trades", ">=", 25)
        value_gate("validation", f"pair_{key}_pf", row, "profit_factor", ">=", 0.90)
        value_gate("validation", f"pair_{key}_return", row, "return_pct", ">", -2)
    add("validation", "positive_pair_breadth", concentration.get("positive_pairs", 0) >= 2, concentration.get("positive_pairs"), "at least 2/3 pairs positive")
    pair_contribution = concentration.get("largest_positive_pair_contribution")
    add("validation", "positive_pair_concentration", pair_contribution is not None and pair_contribution <= 0.60, pair_contribution, "largest positive-pair contribution <= 0.60")
    win_contribution = concentration.get("largest_winning_trade_contribution")
    add("validation", "winning_trade_concentration", win_contribution is not None and win_contribution <= 0.20, win_contribution, "largest winning-trade contribution <= 0.20")
    for side in ("long", "short"):
        row = index[("direction", side, "baseline")]
        value_gate("validation", f"{side}_trades", row, "trades", ">=", 40)
        value_gate("validation", f"{side}_net", row, "net_profit_abs", ">", 0)
        value_gate("validation", f"{side}_pf", row, "profit_factor", ">=", 1.05)

    current = index[("period", "current_partial", "baseline")]
    value_gate("current", "current_trades", current, "trades", ">=", 20)
    value_gate("current", "current_return", current, "return_pct", ">=", 0)
    value_gate("current", "current_pf", current, "profit_factor", ">=", 1.10)
    value_gate("current", "current_source_dd", current, "source_max_drawdown_account_pct", "<=", 8)

    years = [index[("year", str(year), "baseline")] for year in range(2021, 2026)]
    positive_years = sum(row["return_pct"] > 0 for row in years)
    add("stability", "positive_years", positive_years >= 4, positive_years, "at least 4/5 positive full years")
    yearly_pfs = [
        math.inf if row.get("profit_factor_unbounded") else row["profit_factor"]
        for row in years
    ]
    median_unbounded = False
    if all(value is not None for value in yearly_pfs):
        ordered = sorted(float(value) for value in yearly_pfs)
        raw_median_pf = ordered[len(ordered) // 2]
        median_unbounded = math.isinf(raw_median_pf)
        median_pf = None if median_unbounded else raw_median_pf
    else:
        median_pf = None
    add(
        "stability",
        "median_yearly_pf",
        median_unbounded or (median_pf is not None and median_pf >= 1.20),
        "UNBOUNDED_NO_LOSSES" if median_unbounded else median_pf,
        "median yearly PF >= 1.20",
    )
    worst_year = min(row["return_pct"] for row in years)
    add("stability", "worst_full_year_return", worst_year > -3, worst_year, "worst full-year return > -3%")
    full_quarters = [
        index[("quarter", f"{year}Q{quarter}", "baseline")]
        for year in range(2021, 2026) for quarter in range(1, 5)
    ]
    validation_quarters = [
        index[("quarter", f"{year}Q{quarter}", "baseline")]
        for year in (2024, 2025) for quarter in range(1, 5)
    ]
    positive_all = sum(row["return_pct"] > 0 for row in full_quarters)
    positive_validation = sum(row["return_pct"] > 0 for row in validation_quarters)
    worst_quarter = min(row["return_pct"] for row in full_quarters)
    add("stability", "positive_full_quarters", positive_all >= 12, positive_all, "at least 12/20 positive full quarters")
    add("stability", "positive_validation_quarters", positive_validation >= 5, positive_validation, "at least 5/8 positive validation quarters")
    add("stability", "worst_full_quarter_return", worst_quarter > -3, worst_quarter, "worst full-quarter return > -3%")

    for regime in REGIMES:
        row = index[("regime", regime, "baseline")]
        if regime in ("bull", "bear"):
            value_gate("regime", f"{regime}_trades", row, "trades", ">=", 30)
        applicable = row["trades"] >= 20
        add("regime", f"{regime}_net", (not applicable) or row["net_profit_abs"] >= 0, row["net_profit_abs"], "if trades >= 20, net >= 0")
        regime_pf_pass = row.get("profit_factor_unbounded") is True or (
            row["profit_factor"] is not None and row["profit_factor"] >= 1
        )
        add(
            "regime", f"{regime}_pf", (not applicable) or regime_pf_pass,
            "UNBOUNDED_NO_LOSSES" if row.get("profit_factor_unbounded") else row["profit_factor"],
            "if trades >= 20, PF >= 1.00",
        )
        value_gate("regime", f"{regime}_return", row, "return_pct", ">", -1)

    for scenario, pf_min, dd_max, ratio_min in (
        ("moderate", 1.20, 13, 0.75), ("severe", 1.05, 15, 0.50)
    ):
        row = index[("stress", "validation", scenario)]
        value_gate("stress", f"validation_{scenario}_return", row, "return_pct", ">", 0)
        value_gate("stress", f"validation_{scenario}_pf", row, "profit_factor", ">=", pf_min)
        value_gate("stress", f"validation_{scenario}_realized_dd", row, "realized_closed_trade_drawdown_pct", "<=", dd_max)
        derived_ratio = None if row["realized_closed_trade_drawdown_pct"] == 0 else row["return_pct"] / row["realized_closed_trade_drawdown_pct"]
        ratio_pass = derived_ratio is not None and derived_ratio >= ratio_min
        if derived_ratio is None and row["return_pct"] > 0:
            ratio_pass = True
        add("stress", f"validation_{scenario}_return_dd", ratio_pass, derived_ratio, f"return/realized-DD >= {ratio_min}")
    for year in (2024, 2025):
        moderate = index[("stress_year", str(year), "moderate")]
        severe = index[("stress_year", str(year), "severe")]
        value_gate("stress", f"{year}_moderate_net", moderate, "net_profit_abs", ">", 0)
        value_gate("stress", f"{year}_moderate_pf", moderate, "profit_factor", ">=", 1.10)
        value_gate("stress", f"{year}_severe_return", severe, "return_pct", ">", -2)
        value_gate("stress", f"{year}_severe_pf", severe, "profit_factor", ">=", 0.95)
    return gates


def technical_evidence_failures(manifest: Mapping[str, Any]) -> list[str]:
    evidence = manifest.get("qualification_evidence", manifest.get("evidence"))
    if not isinstance(evidence, Mapping):
        return ["qualification_evidence is missing"]
    failures: list[str] = []
    lookahead = evidence.get("lookahead")
    if not isinstance(lookahead, Mapping):
        failures.append("lookahead evidence is missing")
    else:
        try:
            if strict_integer(lookahead.get("baseline_signals"), "lookahead.baseline_signals") < 100:
                failures.append("lookahead baseline_signals < 100")
            if lookahead.get("has_bias") is not False:
                failures.append("lookahead has_bias is not false")
            for key in ("biased_entry_signals", "biased_exit_signals", "biased_indicators"):
                raw = lookahead.get(key)
                count = len(raw) if isinstance(raw, list) else strict_integer(raw, f"lookahead.{key}")
                if count != 0:
                    failures.append(f"lookahead {key} is not zero")
            sides = set(lookahead.get("represented_sides", []))
            setups = set(lookahead.get("represented_setups", []))
            if sides != {"long", "short"}:
                failures.append("lookahead does not represent both sides")
            if setups != set(SETUPS):
                failures.append("lookahead does not represent all locked setups")
        except EvaluationError as exc:
            failures.append(str(exc))
    recursive = evidence.get("recursive")
    if not isinstance(recursive, Mapping):
        failures.append("recursive evidence is missing")
    else:
        try:
            counts = recursive.get("candidate_counts")
            if not isinstance(counts, list) or tuple(strict_integer(v, "recursive.candidate_count") for v in counts) != RECURSIVE_COUNTS:
                failures.append("recursive candidate counts differ from locked list")
            if strict_integer(recursive.get("startup_candle_count"), "recursive.startup_candle_count") != STARTUP_CANDLE_COUNT:
                failures.append("recursive startup candle count is not 3199")
            if strict_integer(recursive.get("signal_differences"), "recursive.signal_differences") != 0:
                failures.append("recursive signal differences are non-zero")
            variance = recursive.get("indicator_variance_pct")
            if isinstance(variance, Mapping):
                values = [finite_number(value, f"recursive.indicator_variance_pct.{key}") for key, value in variance.items()]
                if not values:
                    failures.append("recursive indicator variance mapping is empty")
                elif max(abs(value) for value in values) > 0.01:
                    failures.append("recursive indicator variance exceeds 0.01%")
            else:
                if abs(finite_number(variance, "recursive.indicator_variance_pct")) > 0.01:
                    failures.append("recursive indicator variance exceeds 0.01%")
        except EvaluationError as exc:
            failures.append(str(exc))
    return failures


def locked_decision(technical_pass: bool, section_pass: Mapping[str, bool]) -> str:
    """Map locked technical/performance state to one of the three decisions."""
    if not technical_pass:
        return "REJECT_PRO_DAY_TRADER"
    required = ("train", "validation", "current", "stability", "regime", "stress")
    if all(section_pass.get(section, False) for section in required):
        return "APPROVE_SEPARATE_DRY_RUN"
    return "KEEP_OFFLINE_RESEARCH"


def build_report(
    manifest_path: Path,
    workspace: Path,
    explicit_artifacts: Mapping[str, Path],
) -> dict[str, Any]:
    manifest_raw = load_json(manifest_path, "evaluation manifest")
    if not isinstance(manifest_raw, Mapping):
        raise EvaluationError("Evaluation manifest root must be an object")
    manifest = dict(manifest_raw)
    paths, btc_4h_path = verify_manifest_inputs(manifest, workspace)
    frozen_config_raw = load_json(paths["config"], "frozen research config")
    if not isinstance(frozen_config_raw, Mapping):
        raise EvaluationError("Frozen research config root must be an object")
    frozen_strategy_hash = sha256_file(paths["strategy"])
    records = manifest.get("artifacts")
    if not isinstance(records, Mapping):
        raise EvaluationError("Manifest artifacts mapping is missing")
    artifacts: dict[str, Artifact] = {}
    for label in ARTIFACT_LABELS:
        record = records.get(label, records.get("current") if label == "current_partial" else None)
        artifacts[label] = load_artifact(
            label, explicit_artifacts[label], record, frozen_strategy_hash, frozen_config_raw
        )
    starting = artifacts["canonical"].source_metrics["starting_balance"]
    if any(abs(artifact.source_metrics["starting_balance"] - starting) > 1e-12 for artifact in artifacts.values()):
        raise EvaluationError("Artifact starting balances are not identical")
    available, regimes, regime_source = build_btc_regime_context(btc_4h_path)
    for artifact in artifacts.values():
        artifact.trades = assign_regimes(artifact.trades, available, regimes)
    canonical = artifacts["canonical"]
    if canonical.wallet_bytes is None:
        raise EvaluationError("Canonical artifact lacks the strategy wallet Feather")
    wallet = wallet_series(canonical.wallet_bytes)
    rows, concentration = build_metrics(artifacts, wallet)
    gates = evaluate_locked_gates(rows, concentration)
    technical_failures = technical_evidence_failures(manifest)
    technical_pass = not technical_failures
    section_pass = {
        section: all(gate["passed"] for gate in gates if gate["section"] == section)
        for section in ("train", "validation", "current", "stability", "regime", "stress")
    }
    train_unlock = technical_pass and section_pass["train"]
    validation_unlock = train_unlock and all(
        section_pass[key] for key in ("validation", "stability", "regime", "stress")
    )
    current_unlock = validation_unlock and section_pass["current"]
    decision = locked_decision(technical_pass, section_pass)
    canonical_start = parse_utc(PERIODS["canonical"][0], "canonical.start")
    canonical_end = parse_utc(PERIODS["canonical"][1], "canonical.end")
    report = {
        "schema_version": SCHEMA_VERSION,
        "candidate": STRATEGY,
        "decision": decision,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
        "technical_validation": {
            "passed": technical_pass,
            "failures": technical_failures,
            "manifest_sha256": sha256_file(manifest_path),
            "frozen_strategy_sha256": frozen_strategy_hash,
            "artifact_integrity": {
                label: {
                    "filename": artifact.path.name,
                    "zip_sha256": artifact.sha256,
                    "result": {"filename": artifact.result_member, "sha256": artifact.result_sha256},
                    "config": {"filename": artifact.config_member, "sha256": artifact.config_sha256},
                    "strategy": {"filename": artifact.strategy_member, "sha256": artifact.strategy_sha256},
                    "zip_integrity": "PASS", "sanitization": "PASS",
                    "source_reconciliation": "PASS",
                }
                for label, artifact in artifacts.items()
            },
        },
        "qualification_sequence": {
            "train": "PASS" if train_unlock else "FAIL",
            "validation": "PASS" if validation_unlock else ("NON_QUALIFYING_DIAGNOSTIC" if not train_unlock else "FAIL"),
            "current_partial": "PASS" if current_unlock else ("NON_QUALIFYING_DIAGNOSTIC" if not validation_unlock else "FAIL"),
        },
        "drawdown_semantics": {
            "canonical_source": "Freqtrade max_drawdown_account from each locked period artifact",
            "continuous_period": "canonical wallet curve with prior running peak; no wallet reset",
            "realized": "independent closed-trade equity drawdown; never relabeled as max_drawdown_account",
            "stress": "independent repriced closed-trade realized drawdown",
        },
        "regime_evidence": {
            **regime_source,
            "classification": "last closed BTC 4h candle at entry; EMA50/EMA200 and Wilder ADX14",
            "time_share": regime_time_share(available, regimes, canonical_start, canonical_end),
            "rejection_counts": {
                "source_total": canonical.source_metrics["rejected_signals"],
                "by_regime": None,
                "status": "UNAVAILABLE_FROM_STANDARD_FREQTRADE_ZIP",
            },
        },
        "concentration": concentration,
        "metrics": rows,
        "gates": gates,
        "performance_sections": section_pass,
        "limitations": [
            "Historical robustness evidence only; no sealed holdout or profit guarantee.",
            "APPROVE_SEPARATE_DRY_RUN permits only a credential-free isolated dry-run.",
            "Standard Freqtrade ZIPs do not retain per-candle rejection bitmasks by BTC regime.",
        ],
    }
    # Final strict serialization check prevents accidental NaN/Infinity output.
    json.dumps(report, allow_nan=False, sort_keys=True)
    return report


def _planned_artifact_path(
    label: str, explicit_path: Path, record: Any, workspace: Path
) -> Path:
    if not isinstance(record, Mapping):
        raise EvaluationError(f"Manifest artifact {label} must be a planned record")
    expected = resolve_record_path(record, workspace, f"artifacts.{label}")
    if explicit_path.resolve() != expected:
        raise EvaluationError(f"Explicit artifact {label} path does not match its planned manifest path")
    if explicit_path.suffix.lower() != ".zip" or not explicit_path.is_file():
        raise EvaluationError(f"Explicit artifact {label} is not an existing ZIP")
    return explicit_path.resolve()


def _hashed_artifact_record(
    label: str,
    path: Path,
    planned_record: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as bundle:
            names = _safe_member_names(bundle, path)
            bad = bundle.testzip()
            if bad is not None:
                raise EvaluationError(f"Artifact {label} failed ZIP integrity at a member")
            result_names = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            config_names = [name for name in names if name.endswith("_config.json")]
            strategy_names = [name for name in names if name.endswith(f"_{STRATEGY}.py")]
            if len(result_names) != 1 or len(config_names) != 1 or len(strategy_names) != 1:
                raise EvaluationError(
                    f"Artifact {label} must contain exactly one result/config/{STRATEGY} source"
                )
            payloads = {
                "result": bundle.read(result_names[0]),
                "config": bundle.read(config_names[0]),
                "strategy": bundle.read(strategy_names[0]),
            }
    except zipfile.BadZipFile as exc:
        raise EvaluationError(f"Artifact {label} is not a valid ZIP") from exc
    config = load_json_bytes(payloads["config"], f"artifact {label} config")
    if not isinstance(config, Mapping):
        raise EvaluationError(f"Artifact {label} config root must be an object")
    assert_sanitized(config)
    result = dict(planned_record)
    result.update({
        "path": str(planned_record["path"]),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "status": "READY",
        "sanitized": True,
        "members": {
            role: {
                "filename": name,
                "bytes": len(payloads[role]),
                "sha256": sha256_bytes(payloads[role]),
            }
            for role, name in (
                ("result", result_names[0]),
                ("config", config_names[0]),
                ("strategy", strategy_names[0]),
            )
        },
    })
    return result


def register_artifact(
    manifest_path: Path,
    workspace: Path,
    label: str,
    explicit_path: Path,
) -> dict[str, Any]:
    """Sanitize, validate, hash and atomically register one explicit planned ZIP."""
    aliases = {"current": "current_partial"}
    label = aliases.get(label, label)
    if label not in ARTIFACT_LABELS:
        raise EvaluationError(f"Unknown artifact label {label!r}")
    manifest_raw = load_json(manifest_path, "frozen manifest")
    if not isinstance(manifest_raw, Mapping):
        raise EvaluationError("Frozen manifest root must be an object")
    manifest = dict(manifest_raw)
    paths, _ = verify_manifest_inputs(manifest, workspace)
    records_raw = manifest.get("artifacts")
    if not isinstance(records_raw, Mapping):
        raise EvaluationError("Manifest artifacts mapping is missing")
    records = dict(records_raw)
    planned_raw = records.get(label)
    if not isinstance(planned_raw, Mapping):
        raise EvaluationError(f"Manifest artifact {label} record is missing")
    planned = dict(planned_raw)
    explicit = _planned_artifact_path(label, explicit_path, planned, workspace)
    status = planned.get("status")
    if isinstance(status, str) and status.upper() == "READY":
        frozen_config = load_json(paths["config"], "frozen research config")
        if not isinstance(frozen_config, Mapping):
            raise EvaluationError("Frozen research config root must be an object")
        load_artifact(
            label,
            explicit,
            planned,
            sha256_file(paths["strategy"]),
            frozen_config,
        )
        return {
            "label": label,
            "filename": explicit.name,
            "status": "READY",
            "sha256": planned["sha256"],
            "manifest_updated": False,
            "idempotent": True,
        }
    if not isinstance(status, str) or not any(
        token in status.upper() for token in ("PLANNED", "NOT_RUN")
    ):
        raise EvaluationError(f"Manifest artifact {label} is not in a registerable planned state")

    # Use the project's established sanitizer.  It rewrites only the config
    # snapshot and verifies its own output before replacing the ZIP.
    try:
        from sanitize_backtest_archive import SanitizeError, sanitize_archive

        sanitize_archive(explicit)
    except (ImportError, OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EvaluationError(f"Cannot sanitize artifact {label}") from exc
    except SanitizeError as exc:
        raise EvaluationError(f"Cannot sanitize artifact {label}: {exc}") from exc

    ready_record = _hashed_artifact_record(label, explicit, planned)
    frozen_config = load_json(paths["config"], "frozen research config")
    if not isinstance(frozen_config, Mapping):
        raise EvaluationError("Frozen research config root must be an object")
    # Full parse/reconciliation happens before the manifest state transition.
    load_artifact(
        label,
        explicit,
        ready_record,
        sha256_file(paths["strategy"]),
        frozen_config,
    )
    records[label] = ready_record
    manifest["artifacts"] = records
    ready_count = sum(
        isinstance(record, Mapping)
        and record.get("status") == "READY"
        for record in records.values()
    )
    manifest["qualification_state"] = (
        "ARTIFACTS_READY_FOR_EVALUATION"
        if ready_count == len(ARTIFACT_LABELS)
        else "ARTIFACTS_PARTIALLY_READY"
    )
    try:
        write_json_atomic(manifest_path, manifest)
    except OSError as exc:
        raise EvaluationError("Cannot atomically update the frozen manifest") from exc
    return {
        "label": label,
        "filename": explicit.name,
        "status": ready_record["status"],
        "sha256": ready_record["sha256"],
        "manifest_updated": True,
        "idempotent": False,
    }


CSV_FIELDS = (
    "scope", "key", "scenario", "trades", "wins", "losses", "draws", "longs", "shorts",
    "net_profit_abs", "return_pct", "profit_factor", "profit_factor_unbounded",
    "source_max_drawdown_account_pct",
    "continuous_wallet_drawdown_pct", "realized_closed_trade_drawdown_pct",
    "return_to_drawdown", "largest_winning_trade_contribution", "full_period",
)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_csv_atomic(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in CSV_FIELDS})
            handle.flush()
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="Evaluate four registered artifacts")
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--workspace", type=Path, default=Path("."))
    evaluate.add_argument(
        "--artifact", action="append", required=True, metavar="LABEL=ZIP",
        help="Explicit canonical/train/validation/current_partial sanitized ZIP; repeat four times",
    )
    evaluate.add_argument("--json-output", type=Path, required=True)
    evaluate.add_argument("--csv-output", type=Path, required=True)
    register = commands.add_parser(
        "register-artifact",
        help="Sanitize and atomically register one explicit planned artifact",
    )
    register.add_argument("--manifest", type=Path, required=True)
    register.add_argument("--workspace", type=Path, default=Path("."))
    register.add_argument("--artifact", required=True, metavar="LABEL=ZIP")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    # Preserve the initial evaluator CLI while making the two modes explicit.
    if raw_args and raw_args[0].startswith("-") and raw_args[0] not in ("-h", "--help"):
        raw_args.insert(0, "evaluate")
    args = parser().parse_args(raw_args)
    workspace = args.workspace.resolve()
    if args.command == "register-artifact":
        try:
            if not workspace.is_dir():
                raise EvaluationError(f"Workspace does not exist: {workspace}")
            manifest_path = args.manifest
            if not manifest_path.is_absolute():
                manifest_path = workspace / manifest_path
            manifest_path = within_workspace(manifest_path, workspace, "manifest")
            if "=" not in args.artifact:
                raise EvaluationError("--artifact must be LABEL=PATH")
            label, raw_path = args.artifact.split("=", 1)
            if not raw_path.strip():
                raise EvaluationError("--artifact path is empty")
            artifact_path = Path(raw_path.strip())
            if not artifact_path.is_absolute():
                artifact_path = workspace / artifact_path
            artifact_path = within_workspace(artifact_path, workspace, f"artifact {label}")
            registration = register_artifact(
                manifest_path, workspace, label.strip(), artifact_path
            )
            print(json.dumps(registration, sort_keys=True))
            return 0
        except EvaluationError as exc:
            print(json.dumps({
                "decision": "REJECT_PRO_DAY_TRADER",
                "registration": "FAILED",
                "error": str(exc),
            }, sort_keys=True))
            return 2
    try:
        if not workspace.is_dir():
            raise EvaluationError(f"Workspace does not exist: {workspace}")
        manifest_path = args.manifest
        if not manifest_path.is_absolute():
            manifest_path = workspace / manifest_path
        manifest_path = within_workspace(manifest_path, workspace, "manifest")
        artifacts = parse_explicit_artifacts(args.artifact, workspace)
        report = build_report(manifest_path, workspace, artifacts)
        write_json_atomic(args.json_output, report)
        write_csv_atomic(args.csv_output, report["metrics"])
        print(json.dumps({"decision": report["decision"], "json": str(args.json_output), "csv": str(args.csv_output)}, sort_keys=True))
        return 0 if report["decision"] == "APPROVE_SEPARATE_DRY_RUN" else 3
    except EvaluationError as exc:
        rejection = {
            "schema_version": SCHEMA_VERSION,
            "candidate": STRATEGY,
            "decision": "REJECT_PRO_DAY_TRADER",
            "live_trading_authorized": False,
            "automatic_promotion_authorized": False,
            "technical_validation": {"passed": False, "failures": [str(exc)]},
            "metrics": [], "gates": [],
        }
        write_json_atomic(args.json_output, rejection)
        write_csv_atomic(args.csv_output, [])
        print(json.dumps({"decision": rejection["decision"], "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
