#!/usr/bin/env python3
"""Create the immutable pre-PnL research freeze for ProDayTraderV1.

This tool validates source/config/risk semantics, refuses missing or failed data
evidence, re-hashes every exact input, and creates a new manifest exclusively.
It deliberately does not open, discover, select, or parse any backtest result.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "ProDayTraderV1"

DEFAULT_PLAN = Path("docs/pro_day_trader_v1_locked_plan.md")
DEFAULT_STRATEGY = Path("user_data/strategies/ProDayTraderV1.py")
DEFAULT_CONFIG = Path("user_data/config-pro-day-research.json")
DEFAULT_RISK_POLICY = Path("user_data/risk_policy.json")
DEFAULT_DATA_QUALITY = Path("user_data/reports/pro_day/data_quality.json")
DEFAULT_OUTPUT = Path("user_data/reports/pro_day/research_freeze_manifest.json")

PAIRS: tuple[str, ...] = (
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "BNB/USDT:USDT",
)
TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "4h")
INFORMATIVE_TIMEFRAMES: tuple[str, ...] = ("15m", "1h", "4h")
CANONICAL_TIMERANGE = "20210101-20260801"
BASELINE_FEE = 0.0005
EXPECTED_RISK_LIMITS: Mapping[str, float | int] = {
    "maximum_daily_realized_loss_pct": 2.0,
    "maximum_weekly_realized_loss_pct": 5.0,
    "maximum_wallet_drawdown_pct": 10.0,
    "maximum_total_open_stake_pct": 20.0,
    "maximum_open_trades": 2,
}
ARTIFACT_KEYS: tuple[str, ...] = (
    "canonical",
    "train",
    "validation",
    "current_partial",
)
DEFAULT_ARTIFACTS: Mapping[str, Path] = {
    "canonical": Path("user_data/backtest_results/pro_day_canonical.zip"),
    "train": Path("user_data/backtest_results/pro_day_train.zip"),
    "validation": Path("user_data/backtest_results/pro_day_validation.zip"),
    "current_partial": Path("user_data/backtest_results/pro_day_current_partial.zip"),
}

SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|api[_-]?secret|secret|password|passwd|jwt|token|"
    r"webhook|private[_-]?key|access[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
PRIVATE_KEY_MARKER = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
WEBHOOK_URL = re.compile(r"https?://[^\s\"']*(?:webhook|hooks\.)[^\s\"']*", re.IGNORECASE)


class FreezeError(RuntimeError):
    """Raised when a locked freeze precondition is not satisfied."""


def locked_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_input(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def descriptor(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FreezeError(f"Missing required freeze input: {portable_path(path, root)}")
    stat_before = path.stat()
    digest = sha256_file(path)
    stat_after = path.stat()
    if (stat_before.st_size, stat_before.st_mtime_ns) != (
        stat_after.st_size,
        stat_after.st_mtime_ns,
    ):
        raise FreezeError(f"Input changed while hashing: {portable_path(path, root)}")
    return {
        "path": portable_path(path, root),
        "filename": path.name,
        "bytes": stat_after.st_size,
        "sha256": digest,
    }


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FreezeError(f"Missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreezeError(f"Invalid {label} JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FreezeError(f"{label} must be a JSON object: {path}")
    return payload


def _has_sensitive_value(value: Any) -> bool:
    if value in (None, "", False, [], {}):
        return False
    # Boolean/numeric policy flags such as ``requires_trade_only_api_key`` are
    # controls, not credential material.  Actual credentials are string/byte
    # values (or are found recursively inside a container).
    if isinstance(value, (bool, int, float)):
        return False
    if isinstance(value, (dict, list)):
        return False
    if isinstance(value, str) and value.strip().lower() in {
        "redacted",
        "<redacted>",
        "changeme",
        "not-set",
        "none",
    }:
        return False
    return True


def secret_bearing_paths(payload: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}"
            if SENSITIVE_KEY.search(str(key)) and _has_sensitive_value(value):
                findings.append(path)
            findings.extend(secret_bearing_paths(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            findings.extend(secret_bearing_paths(value, f"{prefix}[{index}]"))
    return findings


def validate_no_secret_json(payload: Mapping[str, Any], label: str) -> None:
    findings = secret_bearing_paths(payload)
    if findings:
        # Never echo values.  Key paths are sufficient and safe for remediation.
        raise FreezeError(f"{label} contains credential-bearing fields: {', '.join(findings)}")


def _numeric(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise FreezeError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FreezeError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise FreezeError(f"{label} must be finite")
    return number


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise FreezeError(f"{label} must equal {expected!r}; got {actual!r}")


def validate_research_config(config: Mapping[str, Any]) -> dict[str, Any]:
    validate_no_secret_json(config, "Research config")
    _require_equal(config.get("trading_mode"), "futures", "trading_mode")
    _require_equal(config.get("margin_mode"), "isolated", "margin_mode")
    _require_equal(config.get("dry_run"), True, "dry_run")
    _require_equal(config.get("max_open_trades"), 2, "max_open_trades")
    _require_equal(config.get("stake_currency"), "USDT", "stake_currency")
    stake_amount = config.get("stake_amount")
    if stake_amount != "unlimited":
        stake_value = _numeric(stake_amount, "stake_amount")
        if stake_value <= 0:
            raise FreezeError("stake_amount must be positive or 'unlimited'")
    _require_equal(config.get("timeframe"), "5m", "timeframe")
    wallet = _numeric(config.get("dry_run_wallet"), "dry_run_wallet")
    if wallet <= 0:
        raise FreezeError("dry_run_wallet must be positive")
    fee = _numeric(config.get("fee"), "fee")
    if not math.isclose(fee, BASELINE_FEE, rel_tol=0.0, abs_tol=1e-12):
        raise FreezeError(f"fee must equal locked baseline {BASELINE_FEE}")

    exchange = config.get("exchange")
    if not isinstance(exchange, dict):
        raise FreezeError("exchange must be an object")
    credential_fields = [
        field
        for field in ("key", "secret", "password", "uid")
        if _has_sensitive_value(exchange.get(field))
    ]
    if credential_fields:
        raise FreezeError(
            "Research config contains exchange credential fields: "
            + ", ".join(f"$.exchange.{field}" for field in credential_fields)
        )
    whitelist = exchange.get("pair_whitelist")
    if not isinstance(whitelist, list) or any(not isinstance(pair, str) for pair in whitelist):
        raise FreezeError("exchange.pair_whitelist must be a string list")
    if len(whitelist) != len(set(whitelist)) or set(whitelist) != set(PAIRS):
        raise FreezeError("exchange.pair_whitelist must contain the exact locked 3-pair universe")
    blacklist = exchange.get("pair_blacklist", [])
    if blacklist not in ([], None):
        raise FreezeError("exchange.pair_blacklist must be empty for the locked universe")

    metadata = config.get("pro_day_research")
    if not isinstance(metadata, dict):
        raise FreezeError("config requires a pro_day_research metadata object")
    informative = metadata.get("informative_timeframes")
    if not isinstance(informative, list) or len(informative) != len(set(informative)):
        raise FreezeError("pro_day_research.informative_timeframes must be a unique list")
    if set(informative) != set(INFORMATIVE_TIMEFRAMES):
        raise FreezeError("informative_timeframes must be exactly 15m, 1h, and 4h")
    _require_equal(metadata.get("timerange"), CANONICAL_TIMERANGE, "pro_day_research.timerange")
    leverage = _numeric(metadata.get("leverage"), "pro_day_research.leverage")
    if not math.isclose(leverage, 1.0, rel_tol=0.0, abs_tol=0.0):
        raise FreezeError("pro_day_research.leverage must equal 1.0")

    return {
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "leverage": 1.0,
        "dry_run": True,
        "wallet_usdt": wallet,
        "stake_amount": stake_amount,
        "max_open_trades": 2,
        "fee_per_side": fee,
        "pairs": list(whitelist),
        "main_timeframe": "5m",
        "informative_timeframes": list(informative),
        "timerange": CANONICAL_TIMERANGE,
    }


def validate_risk_policy(policy: Mapping[str, Any]) -> None:
    validate_no_secret_json(policy, "Risk policy")
    limits = policy.get("limits")
    if not isinstance(limits, dict):
        raise FreezeError("risk policy requires a limits object")
    for key, expected in EXPECTED_RISK_LIMITS.items():
        actual = _numeric(limits.get(key), f"risk_policy.limits.{key}")
        if not math.isclose(actual, float(expected), rel_tol=0.0, abs_tol=1e-12):
            raise FreezeError(f"risk limit {key} must equal {expected}")
    live_launch = policy.get("live_launch")
    if not isinstance(live_launch, dict):
        raise FreezeError("risk policy requires live_launch controls")
    _require_equal(live_launch.get("authorized"), False, "risk_policy.live_launch.authorized")
    _require_equal(
        live_launch.get("requires_human_authorization"),
        True,
        "risk_policy.live_launch.requires_human_authorization",
    )
    leverage = _numeric(
        live_launch.get("maximum_leverage"), "risk_policy.live_launch.maximum_leverage"
    )
    if leverage != 1.0:
        raise FreezeError("risk policy maximum leverage must equal 1.0")
    _require_equal(
        live_launch.get("margin_mode"), "isolated", "risk_policy.live_launch.margin_mode"
    )


def _literal_assignment(class_node: ast.ClassDef, name: str) -> Any:
    for statement in class_node.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            value_node = statement.value
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                try:
                    return ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    return None
    return None


def _return_literals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Any]:
    values: list[Any] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Return):
            try:
                values.append(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                values.append(None)
    return values


def validate_strategy_source(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FreezeError(f"Cannot read strategy source: {path}: {exc}") from exc
    if PRIVATE_KEY_MARKER.search(source) or WEBHOOK_URL.search(source):
        raise FreezeError("Strategy source contains a credential-like literal")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise FreezeError(f"Strategy source is not valid Python: {exc}") from exc

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == CANDIDATE]
    if len(classes) != 1:
        raise FreezeError(f"Strategy source must define exactly one {CANDIDATE} class")
    strategy_class = classes[0]
    _require_equal(_literal_assignment(strategy_class, "timeframe"), "5m", "strategy.timeframe")
    _require_equal(_literal_assignment(strategy_class, "can_short"), True, "strategy.can_short")
    _require_equal(
        _literal_assignment(strategy_class, "position_adjustment_enable"),
        False,
        "strategy.position_adjustment_enable",
    )
    _require_equal(
        _literal_assignment(strategy_class, "startup_candle_count"),
        3199,
        "strategy.startup_candle_count",
    )

    leverage_methods = [
        node
        for node in strategy_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "leverage"
    ]
    if len(leverage_methods) != 1:
        raise FreezeError("Strategy must define exactly one leverage callback")
    returns = _return_literals(leverage_methods[0])
    if not returns or any(value not in (1, 1.0) for value in returns):
        raise FreezeError("Every strategy leverage return must be the literal 1.0")

    literals = {
        node.value for node in ast.walk(strategy_class) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    missing_timeframes = sorted(set(INFORMATIVE_TIMEFRAMES) - literals)
    if missing_timeframes:
        raise FreezeError(
            "Strategy source does not explicitly reference informative timeframes: "
            + ", ".join(missing_timeframes)
        )

    suspicious_assignments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and SENSITIVE_KEY.search(target.id):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        value = "nonliteral"
                    if _has_sensitive_value(value):
                        suspicious_assignments.append(target.id)
    if suspicious_assignments:
        raise FreezeError(
            "Strategy source contains credential-bearing assignments: "
            + ", ".join(sorted(set(suspicious_assignments)))
        )


def validate_locked_plan(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FreezeError(f"Cannot read locked plan: {path}: {exc}") from exc
    required_markers = (
        "LOCKED_BEFORE_FIRST_PRO_DAY_PNL_RUN",
        CANDIDATE,
        "DATA_BLOCKED",
        "20210101" if "20210101" in text else "2021-01-01",
        "20260801" if "20260801" in text else "2026-08-01",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise FreezeError("Locked plan is missing required markers: " + ", ".join(missing))


def _audit_data_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise FreezeError("Data audit contains an invalid data-file path")
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def validate_data_audit(
    audit: Mapping[str, Any], root: Path
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], Path]]:
    if audit.get("schema_version") != "1.0":
        raise FreezeError("Unsupported or missing data-audit schema_version")
    if audit.get("status") != "PASS" or audit.get("decision") != "READY_FOR_RESEARCH_FREEZE":
        raise FreezeError("Data audit is not PASS/READY_FOR_RESEARCH_FREEZE")
    if audit.get("pnl_evaluated") is not False:
        raise FreezeError("Data audit evidence boundary is invalid: pnl_evaluated must be false")
    if audit.get("live_trading_authorized") is not False:
        raise FreezeError("Data audit must not authorize live trading")
    if audit.get("expected_pairs") != list(PAIRS):
        raise FreezeError("Data audit pair universe differs from the locked universe")
    if audit.get("expected_timeframes") != list(TIMEFRAMES):
        raise FreezeError("Data audit timeframes differ from the locked timeframes")

    thresholds = audit.get("thresholds")
    if not isinstance(thresholds, dict):
        raise FreezeError("Data audit thresholds are missing")
    expected_thresholds = {
        "minimum_coverage_pct": 99.95,
        "maximum_undocumented_gap_candles": 3,
        "maximum_mismatch_days_pct": 0.20,
        "reconciliation_relative_tolerance": 1e-9,
        "reconciliation_absolute_tolerance": 1e-8,
    }
    for key, expected in expected_thresholds.items():
        actual = _numeric(thresholds.get(key), f"data_audit.thresholds.{key}")
        if not math.isclose(actual, float(expected), rel_tol=0.0, abs_tol=1e-15):
            raise FreezeError(f"Data audit threshold {key} differs from the locked value")

    rows = audit.get("data_files")
    if not isinstance(rows, list) or len(rows) != len(PAIRS) * len(TIMEFRAMES):
        raise FreezeError("Data audit must contain exactly twelve data-file records")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    paths: dict[tuple[str, str], Path] = {}
    frozen_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise FreezeError("Data audit contains a non-object data-file record")
        key = (row.get("pair"), row.get("timeframe"))
        if key in indexed:
            raise FreezeError(f"Duplicate data-audit record: {key}")
        if key[0] not in PAIRS or key[1] not in TIMEFRAMES:
            raise FreezeError(f"Unexpected data-audit record: {key}")
        if row.get("status") != "PASS" or row.get("exists") is not True:
            raise FreezeError(f"Data file did not pass its audit: {key}")
        path = _audit_data_path(root, row.get("path"))
        current = descriptor(path, root)
        if row.get("sha256") != current["sha256"] or row.get("bytes") != current["bytes"]:
            raise FreezeError(f"Data file changed after its PASS audit: {key}")
        expected_filename = f"{key[0].split('/')[0]}_USDT_USDT-{key[1]}-futures.feather"
        if path.name != expected_filename or row.get("filename") != expected_filename:
            raise FreezeError(f"Data filename is not the locked native futures filename: {key}")
        frozen_rows.append(
            {
                "pair": key[0],
                "timeframe": key[1],
                **current,
            }
        )
        indexed[key] = row
        paths[key] = path
    expected_keys = {(pair, timeframe) for pair in PAIRS for timeframe in TIMEFRAMES}
    if set(indexed) != expected_keys:
        raise FreezeError("Data audit does not cover the exact locked 3 x 4 matrix")
    frozen_rows.sort(key=lambda row: (PAIRS.index(row["pair"]), TIMEFRAMES.index(row["timeframe"])))
    return frozen_rows, paths


def _runtime_image(root: Path) -> str:
    compose = root / "docker-compose.yml"
    if not compose.is_file():
        raise FreezeError("Missing docker-compose.yml for pinned runtime validation")
    text = compose.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*image:\s*(freqtradeorg/freqtrade:2026\.7@sha256:[0-9a-f]{64})\s*$",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise FreezeError("docker-compose.yml lacks the locked Freqtrade 2026.7 digest")
    return match.group(1)


def normalize_artifacts(
    root: Path, artifacts: Mapping[str, str | Path] | None
) -> dict[str, dict[str, Any]]:
    selected = DEFAULT_ARTIFACTS if artifacts is None else artifacts
    if set(selected) != set(ARTIFACT_KEYS):
        missing = sorted(set(ARTIFACT_KEYS) - set(selected))
        extra = sorted(set(selected) - set(ARTIFACT_KEYS))
        raise FreezeError(f"Artifacts must be explicit; missing={missing}, extra={extra}")
    normalized: dict[str, dict[str, Any]] = {}
    seen_paths: set[Path] = set()
    for key in ARTIFACT_KEYS:
        path = resolve_input(root, selected[key])
        if path in seen_paths:
            raise FreezeError("Every planned artifact must have a distinct explicit path")
        seen_paths.add(path)
        if path.suffix.lower() != ".zip":
            raise FreezeError(f"Planned {key} artifact must be an explicit ZIP filename")
        normalized[key] = {
            "path": portable_path(path, root),
            "filename": path.name,
            "sha256": None,
            "status": "PLANNED_NOT_RUN",
        }
    return normalized


def parse_artifact_args(values: Sequence[str]) -> Mapping[str, Path] | None:
    if not values:
        return None
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise FreezeError(f"Artifact must be KEY=EXPLICIT_PATH: {value}")
        key, path = value.split("=", 1)
        if key in parsed:
            raise FreezeError(f"Duplicate artifact key: {key}")
        if not path:
            raise FreezeError(f"Artifact path is empty: {key}")
        parsed[key] = Path(path)
    return parsed


def _write_new_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish a manifest and refuse replacement of any existing file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FreezeError(f"Refusing to overwrite immutable freeze manifest: {path}")
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FreezeError(f"Refusing to overwrite immutable freeze manifest: {path}") from exc
        except OSError:
            # Windows/filesystems without hard-link support still get exclusive creation.
            try:
                with path.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                raise FreezeError(f"Refusing to overwrite immutable freeze manifest: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def freeze_research(
    *,
    project_root: Path = PROJECT_ROOT,
    plan_path: str | Path = DEFAULT_PLAN,
    strategy_path: str | Path = DEFAULT_STRATEGY,
    config_path: str | Path = DEFAULT_CONFIG,
    risk_policy_path: str | Path = DEFAULT_RISK_POLICY,
    data_quality_path: str | Path = DEFAULT_DATA_QUALITY,
    output_path: str | Path = DEFAULT_OUTPUT,
    artifacts: Mapping[str, str | Path] | None = None,
    lock_time_utc: str | None = None,
    write_output: bool = True,
) -> dict[str, Any]:
    root = project_root.resolve()
    plan = resolve_input(root, plan_path)
    strategy = resolve_input(root, strategy_path)
    config_file = resolve_input(root, config_path)
    risk_file = resolve_input(root, risk_policy_path)
    audit_file = resolve_input(root, data_quality_path)
    output = resolve_input(root, output_path)

    validate_locked_plan(plan)
    validate_strategy_source(strategy)
    config = load_json_object(config_file, "research config")
    frozen_parameters = validate_research_config(config)
    risk = load_json_object(risk_file, "risk policy")
    validate_risk_policy(risk)
    audit = load_json_object(audit_file, "data-quality report")
    data_files, _ = validate_data_audit(audit, root)

    file_descriptors = {
        "plan": descriptor(plan, root),
        "strategy": descriptor(strategy, root),
        "config": descriptor(config_file, root),
        "risk_policy": descriptor(risk_file, root),
        "data_quality": descriptor(audit_file, root),
    }
    # ``inputs`` is retained with evaluator-oriented names; all descriptors are
    # immutable value copies rather than filesystem aliases or mtime selectors.
    inputs = {
        "plan": dict(file_descriptors["plan"]),
        "strategy": dict(file_descriptors["strategy"]),
        "research_config": dict(file_descriptors["config"]),
        "risk_policy": dict(file_descriptors["risk_policy"]),
        "data_audit": dict(file_descriptors["data_quality"]),
    }
    frozen_parameters = {
        **frozen_parameters,
        "runtime_image": _runtime_image(root),
        "download_window": "20201201-20260802",
        "train_timerange": "20210101-20240101",
        "validation_timerange": "20240101-20260101",
        "current_partial_timerange": "20260101-20260801",
        "canonical_timerange": CANONICAL_TIMERANGE,
        "timezone": "UTC",
        "closed_candles_only": True,
        "earliest_fill": "next_5m_open",
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "RESEARCH_FROZEN",
        "candidate": CANDIDATE,
        "locked_at_utc": lock_time_utc or locked_at_utc(),
        "qualification_state": "NOT_STARTED_NO_PNL_PARSED",
        "pnl_parsed": False,
        "files": file_descriptors,
        "inputs": inputs,
        "data_files": data_files,
        "frozen_parameters": frozen_parameters,
        "artifacts": normalize_artifacts(root, artifacts),
        "data_quality_status": "PASS",
        "active_strategies_changed": False,
        "live_trading_authorized": False,
        "automatic_promotion_authorized": False,
        "evidence_boundary": (
            "Immutable pre-PnL input freeze only. No result artifact was opened or parsed; "
            "this is not profitability, forward, dry-run, or live-trading evidence."
        ),
    }
    if write_output:
        _write_new_manifest(output, manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--strategy", default=str(DEFAULT_STRATEGY))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--risk-policy", default=str(DEFAULT_RISK_POLICY))
    parser.add_argument("--data-quality", default=str(DEFAULT_DATA_QUALITY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="KEY=EXPLICIT_ZIP_PATH",
        help="Override all four planned artifacts using explicit paths; no latest/mtime lookup.",
    )
    args = parser.parse_args(argv)
    try:
        manifest = freeze_research(
            project_root=args.project_root,
            plan_path=args.plan,
            strategy_path=args.strategy,
            config_path=args.config,
            risk_policy_path=args.risk_policy,
            data_quality_path=args.data_quality,
            output_path=args.output,
            artifacts=parse_artifact_args(args.artifact),
        )
    except (FreezeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FREEZE_REFUSED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "candidate": manifest["candidate"],
                "qualification_state": manifest["qualification_state"],
                "pnl_parsed": False,
                "output": portable_path(resolve_input(args.project_root.resolve(), args.output), args.project_root),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
