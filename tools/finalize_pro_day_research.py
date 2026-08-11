#!/usr/bin/env python3
"""Finalize a locked ProDayTraderV1 DATA_BLOCKED cycle without parsing PnL.

This command is intentionally narrow: it accepts one explicit data-quality
audit and the four explicit locked inputs, verifies their current bytes and
semantics, proves that no research freeze or ProDay backtest ZIP exists, and
atomically writes a deterministic terminal rejection.  It never discovers or
opens PnL artifacts and never authorizes any deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from freeze_pro_day_research import (
    FreezeError,
    validate_locked_plan,
    validate_research_config,
    validate_risk_policy,
    validate_strategy_source,
)


SCHEMA_VERSION = "1.0"
CANDIDATE = "ProDayTraderV1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("user_data/reports/pro_day/final_decision.json")
EXPECTED_PATHS = {
    "audit": Path("user_data/reports/pro_day/data_quality.json"),
    "plan": Path("docs/pro_day_trader_v1_locked_plan.md"),
    "strategy": Path("user_data/strategies/ProDayTraderV1.py"),
    "config": Path("user_data/config-pro-day-research.json"),
    "risk_policy": Path("user_data/risk_policy.json"),
}
PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT")
TIMEFRAMES = ("5m", "15m", "1h", "4h")
INFORMATIVE_TIMEFRAMES = ("15m", "1h", "4h")
SPLITS = ("TRAIN", "VALIDATION", "CURRENT_PARTIAL")
PAIR_STEMS = {
    "BTC/USDT:USDT": "BTC_USDT_USDT",
    "ETH/USDT:USDT": "ETH_USDT_USDT",
    "BNB/USDT:USDT": "BNB_USDT_USDT",
}
EXPECTED_THRESHOLDS = {
    "minimum_coverage_pct": 99.95,
    "maximum_undocumented_gap_candles": 3.0,
    "maximum_mismatch_days_pct": 0.2,
    "reconciliation_relative_tolerance": 1e-9,
    "reconciliation_absolute_tolerance": 1e-8,
}
EXPECTED_WINDOWS = {
    "download": {
        "start_utc": "2020-12-01T00:00:00Z",
        "end_utc": "2026-08-02T00:00:00Z",
    },
    "splits": [
        {"name": "TRAIN", "start_utc": "2021-01-01T00:00:00Z", "end_utc": "2024-01-01T00:00:00Z"},
        {"name": "VALIDATION", "start_utc": "2024-01-01T00:00:00Z", "end_utc": "2026-01-01T00:00:00Z"},
        {"name": "CURRENT_PARTIAL", "start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-08-01T00:00:00Z"},
    ],
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_FAILURE_CODES = {
    "MISSING_REQUIRED_DATA_FILE",
    "UNREADABLE_DATA_FILE",
    "FILE_QUALITY_OR_DOWNLOAD_COVERAGE_FAILED",
    "SPLIT_DATA_QUALITY_FAILED",
    "TIMEFRAME_RECONCILIATION_FAILED",
}


class FinalizeError(RuntimeError):
    """Raised whenever terminal DATA_BLOCKED evidence is not self-consistent."""


def _reject_constant(value: str) -> None:
    raise FinalizeError(f"JSON contains forbidden non-finite constant {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FinalizeError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FinalizeError(f"Cannot read {label}: {path}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FinalizeError(f"{label} is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except FinalizeError:
        raise
    except json.JSONDecodeError as exc:
        raise FinalizeError(f"{label} is invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise FinalizeError(f"{label} root must be an object")
    return value


def strict_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FinalizeError(f"{field} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise FinalizeError(f"{field} must be finite")
    return number


def strict_integer(value: Any, field: str, *, minimum: int = 0) -> int:
    number = strict_number(value, field)
    if not number.is_integer() or number < minimum:
        raise FinalizeError(f"{field} must be an integer >= {minimum}")
    return int(number)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FinalizeError(f"Cannot hash required file: {path}") from exc
    return digest.hexdigest()


def portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise FinalizeError(f"Path escapes project root: {path}") from exc


def resolve_explicit(root: Path, value: Path, field: str) -> Path:
    path = value if value.is_absolute() else root / value
    resolved = path.resolve()
    portable_path(resolved, root)
    expected = (root / EXPECTED_PATHS[field]).resolve()
    if resolved != expected:
        raise FinalizeError(f"Explicit {field} path is not the locked path")
    if not resolved.is_file():
        raise FinalizeError(f"Locked {field} file is missing")
    return resolved


def descriptor(path: Path, root: Path) -> dict[str, Any]:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise FinalizeError(f"Required file changed while hashing: {portable_path(path, root)}")
    return {
        "path": portable_path(path, root),
        "filename": path.name,
        "bytes": after.st_size,
        "sha256": digest,
    }


def _require_sequence(value: Any, expected: set[str], field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise FinalizeError(f"{field} must be a string list")
    if len(value) != len(expected) or set(value) != expected:
        raise FinalizeError(f"{field} does not match the locked set")


def _validate_thresholds(audit: Mapping[str, Any]) -> None:
    thresholds = audit.get("thresholds")
    if not isinstance(thresholds, Mapping) or set(thresholds) != set(EXPECTED_THRESHOLDS):
        raise FinalizeError("Audit thresholds do not match the locked schema")
    for key, expected in EXPECTED_THRESHOLDS.items():
        actual = strict_number(thresholds[key], f"thresholds.{key}")
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-15):
            raise FinalizeError(f"Audit threshold {key} differs from the locked value")


def _validate_windows(audit: Mapping[str, Any]) -> None:
    if audit.get("windows") != EXPECTED_WINDOWS:
        raise FinalizeError("Audit windows differ from the locked download/split periods")


def _validate_data_files(
    audit: Mapping[str, Any], root: Path
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str]]:
    rows = audit.get("data_files")
    if not isinstance(rows, list) or len(rows) != len(PAIRS) * len(TIMEFRAMES):
        raise FinalizeError("Audit must contain exactly 12 data file records")
    expected = {(pair, timeframe) for pair in PAIRS for timeframe in TIMEFRAMES}
    seen: dict[tuple[str, str], str] = {}
    verified: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FinalizeError(f"data_files[{index}] must be an object")
        pair, timeframe = row.get("pair"), row.get("timeframe")
        key = (pair, timeframe)
        if key not in expected or key in seen:
            raise FinalizeError(f"Invalid or duplicate data file key at index {index}")
        status = row.get("status")
        if status not in ("PASS", "FAIL"):
            raise FinalizeError(f"data_files[{index}].status must be PASS or FAIL")
        exists = row.get("exists")
        if not isinstance(exists, bool):
            raise FinalizeError(f"data_files[{index}].exists must be boolean")
        raw_path = row.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise FinalizeError(f"data_files[{index}].path is required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        portable_path(path, root)
        expected_path = (
            root
            / "user_data"
            / "data"
            / "binance"
            / "futures"
            / f"{PAIR_STEMS[pair]}-{timeframe}-futures.feather"
        ).resolve()
        if path != expected_path or row.get("filename") != expected_path.name:
            raise FinalizeError(f"data_files[{index}] path/filename is not the locked native file")
        if not exists:
            if path.exists() or status != "FAIL" or row.get("bytes") is not None or row.get("sha256") is not None:
                raise FinalizeError(f"data_files[{index}] missing-file evidence is stale or inconsistent")
            seen[key] = status
            verified.append({
                "pair": pair, "timeframe": timeframe,
                "path": portable_path(path, root), "exists": False,
                "status": status, "bytes": None, "sha256": None,
            })
            continue
        if not path.is_file():
            raise FinalizeError(f"Audited data file disappeared after the audit: {pair} {timeframe}")
        expected_bytes = strict_integer(row.get("bytes"), f"data_files[{index}].bytes")
        expected_hash = row.get("sha256")
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash.lower()):
            raise FinalizeError(f"data_files[{index}].sha256 is invalid or absent")
        before = path.stat()
        actual_hash = sha256_file(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise FinalizeError(f"Data file changed while verifying audit hash: {pair} {timeframe}")
        if after.st_size != expected_bytes or actual_hash != expected_hash.lower():
            raise FinalizeError(f"Stale or tampered audit hash for {pair} {timeframe}")
        seen[key] = status
        verified.append({
            "pair": pair,
            "timeframe": timeframe,
            "path": portable_path(path, root),
            "exists": True,
            "status": status,
            "bytes": after.st_size,
            "sha256": actual_hash,
        })
    if set(seen) != expected:
        raise FinalizeError("Audit data file set is incomplete")
    verified.sort(key=lambda item: (PAIRS.index(item["pair"]), TIMEFRAMES.index(item["timeframe"])))
    return verified, seen


def _validate_status_rows(
    audit: Mapping[str, Any], field: str, expected_keys: set[tuple[str, str, str]]
) -> tuple[int, dict[tuple[str, str, str], str]]:
    rows = audit.get(field)
    if not isinstance(rows, list) or len(rows) != len(expected_keys):
        raise FinalizeError(f"Audit {field} does not contain the locked number of records")
    seen: dict[tuple[str, str, str], str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FinalizeError(f"{field}[{index}] must be an object")
        split = row.get("split")
        pair = row.get("pair")
        timeframe = row.get("timeframe")
        key = (split, pair, timeframe)
        if key not in expected_keys or key in seen:
            raise FinalizeError(f"{field}[{index}] has an invalid or duplicate key")
        status = row.get("status")
        if status not in ("PASS", "FAIL"):
            raise FinalizeError(f"{field}[{index}].status must be PASS or FAIL")
        seen[key] = status
    return sum(status == "PASS" for status in seen.values()), seen


def _validate_failures(
    audit: Mapping[str, Any],
    data_status: Mapping[tuple[str, str], str],
    split_status: Mapping[tuple[str, str, str], str],
    reconciliation_status: Mapping[tuple[str, str, str], str],
) -> list[dict[str, Any]]:
    failures = audit.get("failures")
    if not isinstance(failures, list) or not failures:
        raise FinalizeError("DATA_BLOCKED audit must contain critical failures")
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[Any, ...]] = set()
    for index, failure in enumerate(failures):
        if not isinstance(failure, Mapping):
            raise FinalizeError(f"failures[{index}] must be an object")
        if failure.get("severity") != "CRITICAL":
            raise FinalizeError(f"failures[{index}] must have CRITICAL severity")
        code = failure.get("code")
        if code not in ALLOWED_FAILURE_CODES:
            raise FinalizeError(f"failures[{index}] has an unknown code")
        pair, timeframe, split = failure.get("pair"), failure.get("timeframe"), failure.get("split")
        if pair not in PAIRS or timeframe not in TIMEFRAMES:
            raise FinalizeError(f"failures[{index}] has an invalid pair/timeframe")
        if split is not None and split not in SPLITS:
            raise FinalizeError(f"failures[{index}] has an invalid split")
        detail = failure.get("detail")
        if not isinstance(detail, str) or not detail:
            raise FinalizeError(f"failures[{index}].detail is required")
        identity = (code, split, pair, timeframe)
        if identity in identities:
            raise FinalizeError(f"failures[{index}] duplicates another failure")
        identities.add(identity)
        if code == "TIMEFRAME_RECONCILIATION_FAILED":
            if split is None or reconciliation_status.get((split, pair, timeframe)) != "FAIL":
                raise FinalizeError(f"failures[{index}] lacks a matching failed reconciliation")
        elif code == "SPLIT_DATA_QUALITY_FAILED":
            if split is None or split_status.get((split, pair, timeframe)) != "FAIL":
                raise FinalizeError(f"failures[{index}] lacks a matching failed split")
        elif data_status.get((pair, timeframe)) != "FAIL":
            raise FinalizeError(f"failures[{index}] lacks a matching failed data file")
        normalized.append({
            key: failure[key]
            for key in ("severity", "code", "split", "pair", "timeframe", "detail")
            if key in failure
        })
    normalized.sort(key=lambda item: (
        item.get("code", ""), item.get("split", ""),
        item.get("pair", ""), item.get("timeframe", ""), item.get("detail", ""),
    ))
    return normalized


def validate_blocked_audit(audit: Mapping[str, Any], root: Path) -> dict[str, Any]:
    if str(audit.get("schema_version")) != SCHEMA_VERSION:
        raise FinalizeError("Unsupported data-quality schema_version")
    if audit.get("status") != "DATA_BLOCKED" or audit.get("decision") != "DATA_BLOCKED":
        raise FinalizeError("Audit must be a terminal DATA_BLOCKED result")
    if audit.get("candidate") != CANDIDATE:
        raise FinalizeError(f"Audit candidate must be {CANDIDATE}")
    if audit.get("pnl_evaluated") is not False:
        raise FinalizeError("Audit must prove pnl_evaluated=false")
    if audit.get("live_trading_authorized") is not False:
        raise FinalizeError("Audit must not authorize live trading")
    if strict_integer(audit.get("required_file_count"), "required_file_count") != 12:
        raise FinalizeError("Audit required_file_count must equal 12")
    _require_sequence(audit.get("expected_pairs"), set(PAIRS), "expected_pairs")
    _require_sequence(audit.get("expected_timeframes"), set(TIMEFRAMES), "expected_timeframes")
    _validate_thresholds(audit)
    _validate_windows(audit)
    verified_files, data_status = _validate_data_files(audit, root)
    split_keys = {(split, pair, timeframe) for split in SPLITS for pair in PAIRS for timeframe in TIMEFRAMES}
    reconciliation_keys = {
        (split, pair, timeframe)
        for split in SPLITS for pair in PAIRS for timeframe in INFORMATIVE_TIMEFRAMES
    }
    split_passed, split_status = _validate_status_rows(audit, "split_checks", split_keys)
    reconciliation_passed, reconciliation_status = _validate_status_rows(
        audit, "reconciliation_checks", reconciliation_keys
    )
    failures = _validate_failures(audit, data_status, split_status, reconciliation_status)
    summary = audit.get("summary")
    if not isinstance(summary, Mapping):
        raise FinalizeError("Audit summary must be an object")
    expected_summary = {
        "files_passed": sum(status == "PASS" for status in data_status.values()),
        "files_total": 12,
        "split_checks_passed": split_passed,
        "split_checks_total": len(split_keys),
        "reconciliation_checks_passed": reconciliation_passed,
        "reconciliation_checks_total": len(reconciliation_keys),
        "failure_count": len(failures),
    }
    for key, expected in expected_summary.items():
        if strict_integer(summary.get(key), f"summary.{key}") != expected:
            raise FinalizeError(f"Audit summary.{key} is inconsistent with evidence rows")
    if all(status == "PASS" for status in data_status.values()) and all(
        status == "PASS" for status in split_status.values()
    ) and all(status == "PASS" for status in reconciliation_status.values()):
        raise FinalizeError("DATA_BLOCKED audit has no failed gate")
    return {
        "verified_files": verified_files,
        "failures": failures,
        "summary": expected_summary,
    }


def validate_locked_inputs(paths: Mapping[str, Path], root: Path) -> dict[str, dict[str, Any]]:
    try:
        validate_locked_plan(paths["plan"])
        validate_strategy_source(paths["strategy"])
        config = load_json_object(paths["config"], "locked research config")
        risk = load_json_object(paths["risk_policy"], "locked risk policy")
        validate_research_config(config)
        validate_risk_policy(risk)
    except FreezeError as exc:
        raise FinalizeError(f"Locked input semantic validation failed: {exc}") from exc
    return {
        key: descriptor(paths[key], root)
        for key in ("plan", "strategy", "config", "risk_policy")
    }


def assert_no_pnl_state(root: Path, output: Path) -> dict[str, Any]:
    report_dir = (root / "user_data" / "reports" / "pro_day").resolve()
    manifest_candidates = sorted(
        path for path in report_dir.glob("*manifest*.json") if path.resolve() != output.resolve()
    ) if report_dir.is_dir() else []
    if manifest_candidates:
        raise FinalizeError("A ProDay research/freeze manifest exists; DATA_BLOCKED terminalization is unsafe")
    result_dir = (root / "user_data" / "backtest_results").resolve()
    artifacts = []
    if result_dir.is_dir():
        artifacts = sorted(
            path for path in result_dir.glob("*.zip")
            if "pro_day" in path.name.lower() or "proday" in path.name.lower()
        )
    if artifacts:
        raise FinalizeError("A ProDay backtest ZIP exists; cannot assert performance was not run")
    return {
        "freeze_manifest_present": False,
        "pro_day_backtest_zip_count": 0,
        "ready_artifacts_present": False,
    }


def build_final_decision(
    *,
    root: Path,
    audit_path: Path,
    plan_path: Path,
    strategy_path: Path,
    config_path: Path,
    risk_policy_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise FinalizeError(f"Project root does not exist: {root}")
    explicit = {
        "audit": resolve_explicit(root, audit_path, "audit"),
        "plan": resolve_explicit(root, plan_path, "plan"),
        "strategy": resolve_explicit(root, strategy_path, "strategy"),
        "config": resolve_explicit(root, config_path, "config"),
        "risk_policy": resolve_explicit(root, risk_policy_path, "risk_policy"),
    }
    output = output_path if output_path.is_absolute() else root / output_path
    output = output.resolve()
    portable_path(output, root)
    if output != (root / DEFAULT_OUTPUT).resolve():
        raise FinalizeError("Output path must be the locked final_decision.json path")
    audit = load_json_object(explicit["audit"], "data-quality audit")
    blocked = validate_blocked_audit(audit, root)
    locked_inputs = validate_locked_inputs(explicit, root)
    absence = assert_no_pnl_state(root, output)
    audit_descriptor = descriptor(explicit["audit"], root)
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": CANDIDATE,
        "research_status": "TERMINAL_DATA_BLOCKED",
        "decision": "REJECT_PRO_DAY_TRADER",
        "performance_status": "NOT_RUN_BY_LOCKED_DATA_GATE",
        "pnl_evaluated": False,
        "backtest_executed": False,
        "live_trading_authorized": False,
        "dry_run_deployment_authorized": False,
        "deployment_performed": False,
        "automatic_promotion_authorized": False,
        "data_gate": {
            "status": "DATA_BLOCKED",
            "audit": audit_descriptor,
            "summary": blocked["summary"],
            "critical_failure_count": len(blocked["failures"]),
            "critical_failure_codes": sorted({item["code"] for item in blocked["failures"]}),
            "critical_failures": blocked["failures"],
        },
        "locked_inputs": locked_inputs,
        "verified_data_files": blocked["verified_files"],
        "absence_checks": absence,
        "evidence_boundary": (
            "Terminal rejection caused only by the locked pre-PnL data gate. "
            "No profitability metric, backtest result, or deployment evidence was parsed."
        ),
    }


def encoded_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def write_terminal_decision(path: Path, payload: Mapping[str, Any]) -> bool:
    content = encoded_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise FinalizeError("Cannot read existing terminal decision") from exc
        if existing != content:
            raise FinalizeError("Existing terminal decision differs; refusing to overwrite")
        return False
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    result.add_argument("--audit", type=Path, required=True)
    result.add_argument("--plan", type=Path, required=True)
    result.add_argument("--strategy", type=Path, required=True)
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--risk-policy", type=Path, required=True)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = build_final_decision(
            root=args.project_root,
            audit_path=args.audit,
            plan_path=args.plan,
            strategy_path=args.strategy,
            config_path=args.config,
            risk_policy_path=args.risk_policy,
            output_path=args.output,
        )
        root = args.project_root.resolve()
        output = args.output if args.output.is_absolute() else root / args.output
        created = write_terminal_decision(output.resolve(), report)
        print(json.dumps({
            "decision": report["decision"],
            "performance_status": report["performance_status"],
            "output": portable_path(output.resolve(), root),
            "sha256": sha256_file(output.resolve()),
            "created": created,
        }, sort_keys=True))
        return 0
    except FinalizeError as exc:
        print(json.dumps({
            "decision": "REJECT_PRO_DAY_TRADER",
            "finalization": "FAILED_CLOSED",
            "error": str(exc),
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
