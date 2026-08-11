#!/usr/bin/env python3
"""Build the canonical, fail-closed ProDayTraderV1 technical report artifact.

The script only reads saved audit evidence.  It does not execute a backtest,
contact an exchange, or infer missing PnL.  When qualification PnL has not run,
the report is deliberately emitted with a blocked snapshot and an explicit
``PNL_NOT_RUN`` access issue.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"
ARTIFACT_VERSION = 1
DEFAULT_SPLIT_ORDER = ("TRAIN", "VALIDATION", "CURRENT_PARTIAL")
STATUS_ORDER = ("PASS", "FAIL")


class ReportBuildError(ValueError):
    """Raised when required report evidence is missing or malformed."""


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportBuildError(f"Missing required {label}: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportBuildError(f"Cannot read valid JSON for {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ReportBuildError(f"Expected a JSON object for {label}: {path}")
    return value


def load_csv_rows(path: Path, label: str) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ReportBuildError(f"CSV has no header for {label}: {path}")
            return [dict(row) for row in reader]
    except FileNotFoundError as exc:
        raise ReportBuildError(f"Missing required {label}: {path}") from exc
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ReportBuildError(f"Cannot read valid CSV for {label}: {path}") from exc


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write strict JSON atomically in the destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_relative_path(path: Path, workspace: Path, label: str) -> str:
    """Return a portable source path and reject absolute/parent traversal output."""

    workspace = workspace.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise ReportBuildError(f"{label} must be inside the workspace: {path}") from exc
    value = relative.as_posix()
    if not value or value.startswith("/") or ".." in relative.parts:
        raise ReportBuildError(f"Unsafe relative source path for {label}: {value}")
    return value


def require_inside_workspace(path: Path, workspace: Path, label: str) -> Path:
    safe_relative_path(path, workspace, label)
    return path.resolve()


def as_text(value: Any) -> str:
    if value is None:
        return "NOT_AVAILABLE"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def optional_key_value_rows(
    value: Mapping[str, Any], *, maximum_cell_characters: int = 3500
) -> list[dict[str, str]]:
    """Flatten arbitrary optional evidence into bounded, lossless scalar rows.

    The portable artifact validator caps every string cell at 4,000 characters.
    Nested objects and arrays are therefore represented by deterministic JSON-path-
    like field names.  An unusually long scalar is split into numbered chunks rather
    than silently truncated; the canonical source JSON remains linked as provenance.
    """

    if maximum_cell_characters <= 0 or maximum_cell_characters >= 4000:
        raise ReportBuildError("maximum_cell_characters must be between 1 and 3999")
    rows: list[dict[str, str]] = []

    def append_scalar(field: str, item: Any) -> None:
        text = as_text(item)
        if len(text) <= maximum_cell_characters:
            rows.append({"field": field, "value": text})
            return
        chunks = [
            text[index : index + maximum_cell_characters]
            for index in range(0, len(text), maximum_cell_characters)
        ]
        for index, chunk in enumerate(chunks, start=1):
            rows.append(
                {
                    "field": f"{field} [part {index}/{len(chunks)}]",
                    "value": chunk,
                }
            )

    def visit(field: str, item: Any) -> None:
        if isinstance(item, Mapping):
            if not item:
                append_scalar(field, {})
                return
            for key, child in sorted(item.items(), key=lambda pair: str(pair[0])):
                child_field = f"{field}.{key}" if field else str(key)
                visit(child_field, child)
            return
        if isinstance(item, list):
            if not item:
                append_scalar(field, [])
                return
            for index, child in enumerate(item):
                visit(f"{field}[{index}]", child)
            return
        append_scalar(field, item)

    visit("", value)
    return rows


def materialize_report_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Materialize reviewed rows through the SQL recorded in source metadata.

    The stdlib parsers and deterministic transformations establish the reviewed
    rows.  This final SQLite materialization is the actual SQL query used for the
    canonical native table/chart dataset, satisfying the portable artifact source
    contract without introducing a non-stdlib dependency.
    """

    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(str(field))
    empty_schema = not fields
    if empty_schema:
        fields = ["__empty"]

    boolean_fields: set[str] = set()
    types: dict[str, str] = {}
    for field in fields:
        values = [row.get(field) for row in rows if row.get(field) is not None]
        if values and all(isinstance(value, bool) for value in values):
            types[field] = "INTEGER"
            boolean_fields.add(field)
        elif values and all(
            isinstance(value, int) and not isinstance(value, bool) for value in values
        ):
            types[field] = "INTEGER"
        elif values and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ):
            types[field] = "REAL"
        else:
            types[field] = "TEXT"

    def quote(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "CREATE TABLE report_rows ("
            + ", ".join(f"{quote(field)} {types[field]}" for field in fields)
            + ")"
        )
        if rows:
            placeholders = ", ".join("?" for _ in fields)
            connection.executemany(
                f"INSERT INTO report_rows VALUES ({placeholders})",
                [
                    tuple(
                        int(value) if isinstance(value := row.get(field), bool) else value
                        for field in fields
                    )
                    for row in rows
                ],
            )
        selected = connection.execute("SELECT * FROM report_rows").fetchall()
    finally:
        connection.close()
    if empty_schema:
        return []
    return [
        {
            field: (bool(item[field]) if field in boolean_fields and item[field] is not None else item[field])
            for field in fields
        }
        for item in selected
    ]


def source_spec(
    source_id: str,
    label: str,
    path: str,
    generated_at: str,
    description: str,
    *,
    filters: Sequence[str] | None = None,
    metric_definitions: Sequence[str] | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "description": (
            description
            + " The builder deterministically parses/transforms the saved source, materializes the reviewed "
            "native artifact rows into an in-memory SQLite table named report_rows, and executes the recorded SQL."
        ),
        "engine": "sqlite3",
        "executed_at": generated_at,
        "language": "sql",
        "sql": "SELECT * FROM report_rows",
        "tables_used": [path, "main.report_rows"],
    }
    if filters:
        query["filters"] = list(filters)
    if metric_definitions:
        query["metric_definitions"] = list(metric_definitions)
    return {"id": source_id, "label": label, "path": path, "query": query}


def split_names(data_quality: Mapping[str, Any], reconciliation: Sequence[Mapping[str, Any]]) -> list[str]:
    declared: list[str] = []
    windows = data_quality.get("windows")
    if isinstance(windows, Mapping):
        splits = windows.get("splits")
        if isinstance(splits, list):
            for row in splits:
                if isinstance(row, Mapping) and row.get("name"):
                    declared.append(str(row["name"]).upper())
    observed = [str(row.get("split", "")).upper() for row in reconciliation if row.get("split")]
    result: list[str] = []
    for name in (*DEFAULT_SPLIT_ORDER, *declared, *observed):
        if name and name not in result:
            result.append(name)
    return result


def reconciliation_chart_rows(
    data_quality: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    counts = Counter(
        (str(row.get("split", "")).upper(), str(row.get("status", "")).upper())
        for row in rows
    )
    result: list[dict[str, Any]] = []
    for split in split_names(data_quality, rows):
        pass_count = counts[(split, "PASS")]
        fail_count = counts[(split, "FAIL")]
        total = sum(count for (row_split, _), count in counts.items() if row_split == split)
        for status in STATUS_ORDER:
            result.append(
                {
                    "category": f"{split} · {status}",
                    "split": split,
                    "status": status,
                    "check_count": counts[(split, status)],
                    "total_split_checks": total,
                    "pass_count": pass_count,
                    "fail_count": fail_count,
                    "pass_rate": (pass_count / total) if total else None,
                }
            )
    return result


def summary_row(
    data_quality: Mapping[str, Any],
    file_rows: Sequence[Mapping[str, Any]],
    split_rows: Sequence[Mapping[str, Any]],
    reconciliation_rows: Sequence[Mapping[str, Any]],
    gap_rows: Sequence[Mapping[str, Any]],
    final_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    file_pass = sum(str(row.get("status", "")).upper() == "PASS" for row in file_rows)
    split_pass = sum(str(row.get("status", "")).upper() == "PASS" for row in split_rows)
    reconciliation_pass = sum(
        str(row.get("status", "")).upper() == "PASS" for row in reconciliation_rows
    )
    reconciliation_fail = sum(
        str(row.get("status", "")).upper() == "FAIL" for row in reconciliation_rows
    )
    return {
        "candidate": str(data_quality.get("candidate", "ProDayTraderV1")),
        "data_status": str(data_quality.get("status", "UNKNOWN")),
        "data_decision": str(data_quality.get("decision", "UNKNOWN")),
        "pnl_evaluated": data_quality.get("pnl_evaluated") is True,
        "qualification_pnl_status": "EVALUATED" if data_quality.get("pnl_evaluated") is True else "NOT_RUN",
        "final_decision_available": final_decision is not None,
        "final_decision": (
            str(final_decision.get("decision", "UNKNOWN")) if final_decision else "NOT_AVAILABLE"
        ),
        "live_trading_authorized": False,
        "files_passed": file_pass,
        "files_total": len(file_rows),
        "split_checks_passed": split_pass,
        "split_checks_total": len(split_rows),
        "reconciliation_checks_passed": reconciliation_pass,
        "reconciliation_checks_failed": reconciliation_fail,
        "reconciliation_checks_total": len(reconciliation_rows),
        "documented_gap_rows": len(gap_rows),
        "critical_failure_rows": len(data_quality.get("failures", []))
        if isinstance(data_quality.get("failures"), list)
        else 0,
    }


def scope_definition_rows(data_quality: Mapping[str, Any]) -> list[dict[str, str]]:
    expected_pairs = data_quality.get("expected_pairs", [])
    expected_timeframes = data_quality.get("expected_timeframes", [])
    windows = data_quality.get("windows", {})
    split_windows = windows.get("splits", []) if isinstance(windows, Mapping) else []
    rows = [
        {
            "dimension": "Candidate",
            "definition": str(data_quality.get("candidate", "ProDayTraderV1")),
            "requirement": "Μοναδικός frozen υποψήφιος του κύκλου",
        },
        {
            "dimension": "Universe",
            "definition": ", ".join(str(item) for item in expected_pairs),
            "requirement": "Κανένα pair δεν αφαιρείται μετά το lock",
        },
        {
            "dimension": "Χρονική ανάλυση",
            "definition": ", ".join(str(item) for item in expected_timeframes),
            "requirement": str(data_quality.get("intended_grain", "native futures candles")),
        },
    ]
    if isinstance(split_windows, list):
        for window in split_windows:
            if not isinstance(window, Mapping):
                continue
            name = str(window.get("name", "SPLIT"))
            rows.append(
                {
                    "dimension": name,
                    "definition": f"[{window.get('start_utc', 'UNKNOWN')}, {window.get('end_utc', 'UNKNOWN')})",
                    "requirement": "UTC, το δεξί άκρο εξαιρείται",
                }
            )
    rows.append(
        {
            "dimension": "Qualification boundary",
            "definition": "DATA_BLOCKED ⇒ qualification PnL NOT_RUN",
            "requirement": "Αποτυχία data/source gate δεν επιτρέπει performance qualification",
        }
    )
    return rows


def quality_definition_rows(data_quality: Mapping[str, Any]) -> list[dict[str, Any]]:
    thresholds = data_quality.get("thresholds", {})
    if not isinstance(thresholds, Mapping):
        thresholds = {}
    return [
        {
            "metric": "Coverage ανά pair/timeframe/split",
            "definition": "observed native timestamps / expected aligned timestamps × 100",
            "locked_requirement": f">= {thresholds.get('minimum_coverage_pct', 99.95)}%",
        },
        {
            "metric": "Undocumented gap",
            "definition": "διαδοχικά αναμενόμενα native candles που απουσιάζουν χωρίς τεκμηρίωση",
            "locked_requirement": f"<= {thresholds.get('maximum_undocumented_gap_candles', 3)} base candles",
        },
        {
            "metric": "Timestamp/OHLCV integrity",
            "definition": "duplicate/null/non-finite/invalid OHLC, nonpositive low ή negative volume rows",
            "locked_requirement": "0",
        },
        {
            "metric": "Timeframe reconciliation",
            "definition": "ημέρες όπου native 15m/1h/4h δεν συμφωνούν με πλήρη 5m bins, με τις frozen tolerances",
            "locked_requirement": f"mismatch days <= {thresholds.get('maximum_mismatch_days_pct', 0.2)}%",
        },
        {
            "metric": "Numeric tolerance",
            "definition": "absolute και relative tolerance για aggregated OHLCV equality",
            "locked_requirement": (
                f"abs={thresholds.get('reconciliation_absolute_tolerance', 'UNKNOWN')}, "
                f"rel={thresholds.get('reconciliation_relative_tolerance', 'UNKNOWN')}"
            ),
        },
        {
            "metric": "PnL NOT_RUN",
            "definition": "δεν εκτελέστηκε qualification PnL επειδή το προαπαιτούμενο data gate απέτυχε",
            "locked_requirement": "Δεν ισοδυναμεί με μηδενική απόδοση ή μηδενικό κίνδυνο",
        },
    ]


def normalize_gate_rows(final_decision: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not final_decision or not isinstance(final_decision.get("gates"), list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, gate in enumerate(final_decision["gates"]):
        if not isinstance(gate, Mapping):
            continue
        normalized.append(
            {
                "index": index + 1,
                "section": as_text(gate.get("section")),
                "gate": as_text(gate.get("gate", gate.get("name"))),
                "passed": gate.get("passed") is True,
                "actual": as_text(gate.get("actual")),
                "requirement": as_text(gate.get("requirement")),
            }
        )
    return normalized


def make_table(
    table_id: str,
    title: str,
    subtitle: str,
    dataset: str,
    source_id: str,
    columns: Sequence[tuple[str, str, str]],
    *,
    default_sort: tuple[str, str] | None = None,
) -> dict[str, Any]:
    table: dict[str, Any] = {
        "id": table_id,
        "title": title,
        "subtitle": subtitle,
        "dataset": dataset,
        "sourceId": source_id,
        "layout": "full",
        "density": "dense",
        "columns": [
            {"field": field, "label": label, "type": kind}
            for field, label, kind in columns
        ],
    }
    if default_sort:
        table["defaultSort"] = {"field": default_sort[0], "direction": default_sort[1]}
    return table


def build_artifact(
    *,
    workspace: Path,
    locked_plan_path: Path,
    data_quality_path: Path,
    files_csv_path: Path,
    splits_csv_path: Path,
    reconciliation_csv_path: Path,
    reconciliation_daily_csv_path: Path,
    gaps_csv_path: Path,
    final_decision_path: Path | None = None,
    orderflow_path: Path | None = None,
    deployment_evidence_path: Path | None = None,
    archive_security_audit_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = workspace.resolve()
    required_paths = {
        "locked plan": locked_plan_path,
        "data quality JSON": data_quality_path,
        "file audit CSV": files_csv_path,
        "split audit CSV": splits_csv_path,
        "reconciliation CSV": reconciliation_csv_path,
        "daily reconciliation CSV": reconciliation_daily_csv_path,
        "gap audit CSV": gaps_csv_path,
    }
    for label, path in required_paths.items():
        require_inside_workspace(path, workspace, label)

    try:
        locked_plan_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ReportBuildError(f"Missing required locked plan: {locked_plan_path}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportBuildError(f"Cannot read locked plan: {locked_plan_path}") from exc

    data_quality = load_json_object(data_quality_path, "data quality evidence")
    file_rows = load_csv_rows(files_csv_path, "file audit")
    split_rows = load_csv_rows(splits_csv_path, "split audit")
    reconciliation_rows = load_csv_rows(reconciliation_csv_path, "reconciliation audit")
    reconciliation_daily_rows = load_csv_rows(
        reconciliation_daily_csv_path, "daily reconciliation audit"
    )
    gap_rows = load_csv_rows(gaps_csv_path, "gap audit")

    optional_inputs: dict[str, tuple[Path | None, str]] = {
        "final_decision": (final_decision_path, "final decision"),
        "orderflow": (orderflow_path, "order-flow compatibility"),
        "deployment": (deployment_evidence_path, "deployment evidence"),
        "archive_security": (archive_security_audit_path, "archive security audit"),
    }
    optional_values: dict[str, dict[str, Any] | None] = {}
    for key, (path, label) in optional_inputs.items():
        if path is None or not path.exists():
            optional_values[key] = None
            continue
        require_inside_workspace(path, workspace, label)
        optional_values[key] = load_json_object(path, label)

    final_decision = optional_values["final_decision"]
    orderflow = optional_values["orderflow"]
    deployment = optional_values["deployment"]
    archive_security = optional_values["archive_security"]
    generated_at = str(data_quality.get("generated_at_utc", "1970-01-01T00:00:00Z"))

    paths = {
        label: safe_relative_path(path, workspace, label)
        for label, path in required_paths.items()
    }
    sources = [
        source_spec(
            "locked_plan",
            "Frozen ProDay research plan",
            paths["locked plan"],
            generated_at,
            "Defines the pre-PnL universe, periods, data gates, methodology and decision boundary.",
            metric_definitions=[
                "DATA_BLOCKED prevents qualification PnL from running.",
                "Historical evidence is not a sealed holdout, forward evidence, a profit guarantee, or live-trading authorization.",
            ],
        ),
        source_spec(
            "data_quality_json",
            "ProDay data-quality decision",
            paths["data quality JSON"],
            generated_at,
            "Reads the saved data gate, thresholds, failure register and PnL boundary.",
            metric_definitions=[
                "PNL NOT_RUN means qualification PnL was not executed; it is not a zero-return observation.",
                "Failure count is the number of recorded critical data-quality failures.",
            ],
        ),
        source_spec(
            "dq_files_csv",
            "Native futures file audit",
            paths["file audit CSV"],
            generated_at,
            "Loads every required pair/timeframe file audit row without sampling.",
            filters=["No rows omitted"],
        ),
        source_spec(
            "dq_splits_csv",
            "Pair/timeframe/split coverage audit",
            paths["split audit CSV"],
            generated_at,
            "Loads every split-level coverage and integrity check without sampling.",
            filters=["No rows omitted"],
        ),
        source_spec(
            "dq_reconciliation_csv",
            "Timeframe reconciliation checks",
            paths["reconciliation CSV"],
            generated_at,
            "Loads all aggregate 5m-to-15m/1h/4h reconciliation checks.",
            filters=["No rows omitted"],
            metric_definitions=[
                "PASS requires mismatch_days_pct to be no greater than maximum_mismatch_days_pct.",
                "Chart counts include explicit zero rows for the absent PASS/FAIL status within each split.",
            ],
        ),
        source_spec(
            "dq_reconciliation_daily_csv",
            "Daily timeframe reconciliation detail",
            paths["daily reconciliation CSV"],
            generated_at,
            "Loads the exact failed daily rows into the bounded report; the complete CSV remains the canonical source.",
            filters=["Visible table includes status = FAIL only", "All failed rows retained"],
        ),
        source_spec(
            "dq_gaps_csv",
            "Documented and undocumented gap audit",
            paths["gap audit CSV"],
            generated_at,
            "Loads all recorded gap rows without sampling.",
            filters=["No rows omitted"],
        ),
    ]

    if final_decision is not None and final_decision_path is not None:
        path = safe_relative_path(final_decision_path, workspace, "final decision")
        sources.append(
            source_spec(
                "final_decision_json",
                "ProDay final evaluator decision",
                path,
                generated_at,
                "Reads a caller-provided saved evaluator decision and its locked gate rows.",
            )
        )
    if orderflow is not None and orderflow_path is not None:
        path = safe_relative_path(orderflow_path, workspace, "order-flow compatibility")
        sources.append(
            source_spec(
                "orderflow_json",
                "Local order-flow compatibility evidence",
                path,
                generated_at,
                "Reads caller-provided local compatibility evidence; it is not a qualification gate.",
            )
        )
    if deployment is not None and deployment_evidence_path is not None:
        path = safe_relative_path(deployment_evidence_path, workspace, "deployment evidence")
        sources.append(
            source_spec(
                "deployment_json",
                "Deployment and runtime isolation evidence",
                path,
                generated_at,
                "Reads caller-provided saved deployment evidence without contacting the VPS.",
            )
        )
    if archive_security is not None and archive_security_audit_path is not None:
        path = safe_relative_path(
            archive_security_audit_path, workspace, "archive security audit"
        )
        sources.append(
            source_spec(
                "archive_security_json",
                "Backtest archive security audit",
                path,
                generated_at,
                "Reads caller-provided aggregate ZIP integrity, config cardinality, redaction and ProDay archive-presence evidence; no archive contents are embedded.",
            )
        )

    summary = summary_row(
        data_quality,
        file_rows,
        split_rows,
        reconciliation_rows,
        gap_rows,
        final_decision,
    )
    chart_rows = reconciliation_chart_rows(data_quality, reconciliation_rows)
    failed_daily_rows = [
        row for row in reconciliation_daily_rows if str(row.get("status", "")).upper() == "FAIL"
    ]
    failed_daily_distinct_dates = len(
        {
            str(row.get("date_utc"))
            for row in failed_daily_rows
            if row.get("date_utc") not in (None, "")
        }
    )
    summary.update(
        {
            "failed_daily_check_rows": len(failed_daily_rows),
            "failed_daily_distinct_utc_dates": failed_daily_distinct_dates,
        }
    )
    failure_rows = [
        dict(row)
        for row in data_quality.get("failures", [])
        if isinstance(row, Mapping)
    ]
    final_gate_rows = normalize_gate_rows(final_decision)

    datasets: dict[str, list[dict[str, Any]]] = {
        "audit_summary": [summary],
        "reconciliation_status_counts": chart_rows,
        "file_checks": [dict(row) for row in file_rows],
        "split_checks": [dict(row) for row in split_rows],
        "reconciliation_checks": [dict(row) for row in reconciliation_rows],
        "reconciliation_daily_failures": [dict(row) for row in failed_daily_rows],
        "gap_checks": [dict(row) for row in gap_rows],
        "failure_register": failure_rows,
        "scope_definitions": scope_definition_rows(data_quality),
        "quality_definitions": quality_definition_rows(data_quality),
    }
    if final_decision is not None:
        datasets["final_decision_fields"] = optional_key_value_rows(final_decision)
        datasets["final_gate_results"] = final_gate_rows
    if orderflow is not None:
        datasets["orderflow_fields"] = optional_key_value_rows(orderflow)
    if deployment is not None:
        datasets["deployment_fields"] = optional_key_value_rows(deployment)
    if archive_security is not None:
        datasets["archive_security_fields"] = optional_key_value_rows(archive_security)

    # Every final native dataset is emitted from the exact SQL recorded on its
    # canonical source.  Empty datasets still execute the same query against an
    # explicit empty in-memory schema.
    datasets = {
        dataset_id: materialize_report_rows(rows)
        for dataset_id, rows in datasets.items()
    }

    tables = [
        make_table(
            "audit_summary_table",
            "Κατάσταση του pre-PnL audit",
            "Ακριβείς μετρήσεις από τα αποθηκευμένα data-quality outputs.",
            "audit_summary",
            "data_quality_json",
            (
                ("data_status", "Data gate", "text"),
                ("qualification_pnl_status", "Qualification PnL", "text"),
                ("files_passed", "Files PASS", "number"),
                ("files_total", "Files total", "number"),
                ("split_checks_passed", "Split checks PASS", "number"),
                ("split_checks_total", "Split checks total", "number"),
                ("reconciliation_checks_passed", "Reconciliation PASS", "number"),
                ("reconciliation_checks_failed", "Reconciliation FAIL", "number"),
                ("failed_daily_check_rows", "FAIL day-check rows", "number"),
                ("failed_daily_distinct_utc_dates", "Distinct FAIL UTC dates", "number"),
                ("critical_failure_rows", "Critical failures", "number"),
            ),
        ),
        make_table(
            "reconciliation_table",
            "Όλοι οι aggregate reconciliation checks",
            "Κάθε pair, timeframe και locked split· mismatch-days όριο 0.20%.",
            "reconciliation_checks",
            "dq_reconciliation_csv",
            (
                ("split", "Split", "text"),
                ("pair", "Pair", "text"),
                ("timeframe", "Timeframe", "text"),
                ("compared_days", "Compared days", "number"),
                ("mismatch_days", "Mismatch days", "number"),
                ("mismatch_days_pct", "Mismatch days (%)", "number"),
                ("maximum_mismatch_days_pct", "Μέγιστο (%)", "number"),
                ("status", "Status", "text"),
            ),
            default_sort=("split", "asc"),
        ),
        make_table(
            "daily_failure_table",
            "Ημερήσιες αποκλίσεις που απέτυχαν",
            "Όλα και μόνο τα FAIL pair/timeframe/day check rows· το πλήρες daily CSV παραμένει διαθέσιμο από το source affordance.",
            "reconciliation_daily_failures",
            "dq_reconciliation_daily_csv",
            (
                ("split", "Split", "text"),
                ("pair", "Pair", "text"),
                ("timeframe", "Timeframe", "text"),
                ("date_utc", "Ημέρα UTC", "date"),
                ("complete_5m_bins", "Complete 5m bins", "number"),
                ("missing_native_bins", "Missing native", "number"),
                ("duplicate_native_bins", "Duplicate native", "number"),
                ("mismatched_bins", "Mismatched bins", "number"),
                ("mismatch_fields", "Fields", "text"),
                ("status", "Status", "text"),
            ),
            default_sort=("date_utc", "asc"),
        ),
        make_table(
            "failure_register_table",
            "Critical failure register",
            "Οι εγγραφές που οδήγησαν το data gate σε DATA_BLOCKED.",
            "failure_register",
            "data_quality_json",
            (
                ("code", "Code", "text"),
                ("severity", "Severity", "text"),
                ("split", "Split", "text"),
                ("pair", "Pair", "text"),
                ("timeframe", "Timeframe", "text"),
                ("detail", "Detail", "text"),
            ),
            default_sort=("split", "asc"),
        ),
        make_table(
            "split_checks_table",
            "Coverage και integrity ανά split",
            "Όλοι οι pair/timeframe/split έλεγχοι, χωρίς sampling.",
            "split_checks",
            "dq_splits_csv",
            (
                ("split", "Split", "text"),
                ("pair", "Pair", "text"),
                ("timeframe", "Timeframe", "text"),
                ("expected_candles", "Expected", "number"),
                ("observed_candles", "Observed", "number"),
                ("missing_candles", "Missing", "number"),
                ("coverage_pct", "Coverage (%)", "number"),
                ("undocumented_gaps_over_limit", "Gaps over limit", "number"),
                ("status", "Status", "text"),
            ),
            default_sort=("split", "asc"),
        ),
        make_table(
            "file_checks_table",
            "Native futures input files",
            "Τα απαιτούμενα pair/timeframe αρχεία και οι ακριβείς integrity μετρήσεις τους.",
            "file_checks",
            "dq_files_csv",
            (
                ("pair", "Pair", "text"),
                ("timeframe", "Timeframe", "text"),
                ("filename", "Filename", "text"),
                ("rows", "Rows", "number"),
                ("first_utc", "First UTC", "date"),
                ("last_utc", "Last UTC", "date"),
                ("download_window_coverage_pct", "Coverage (%)", "number"),
                ("duplicate_timestamps", "Duplicates", "number"),
                ("null_ohlcv_cells", "Null OHLCV", "number"),
                ("invalid_ohlc_rows", "Invalid OHLC", "number"),
                ("status", "Status", "text"),
            ),
            default_sort=("pair", "asc"),
        ),
        make_table(
            "gap_checks_table",
            "Gap register",
            "Ακριβές περιεχόμενο του gap audit· κενός πίνακας σημαίνει μηδέν καταγεγραμμένα gap rows.",
            "gap_checks",
            "dq_gaps_csv",
            (
                ("split", "Split", "text"),
                ("pair", "Pair", "text"),
                ("timeframe", "Timeframe", "text"),
                ("gap_start_utc", "Gap start UTC", "date"),
                ("gap_end_utc", "Gap end UTC", "date"),
                ("missing_candles", "Missing candles", "number"),
                ("documented", "Documented", "text"),
                ("over_limit", "Over limit", "text"),
                ("status", "Status", "text"),
            ),
        ),
        make_table(
            "scope_definitions_table",
            "Scope και evidence boundary",
            "Universe, timeframes, windows και fail-closed qualification boundary του frozen plan.",
            "scope_definitions",
            "locked_plan",
            (
                ("dimension", "Διάσταση", "text"),
                ("definition", "Ορισμός", "text"),
                ("requirement", "Κλειδωμένη απαίτηση", "text"),
            ),
        ),
        make_table(
            "quality_definitions_table",
            "Ορισμοί και locked thresholds",
            "Οι ακριβείς ορισμοί που απαιτούνται για την ερμηνεία του data gate.",
            "quality_definitions",
            "data_quality_json",
            (
                ("metric", "Metric", "text"),
                ("definition", "Ακριβής ορισμός", "text"),
                ("locked_requirement", "Locked requirement", "text"),
            ),
        ),
    ]

    if final_decision is not None:
        tables.append(
            make_table(
                "final_decision_fields_table",
                "Caller-provided final decision fields",
                "Top-level fields από το saved evaluator output, χωρίς schema inference.",
                "final_decision_fields",
                "final_decision_json",
                (("field", "Field", "text"), ("value", "Value", "text")),
                default_sort=("field", "asc"),
            )
        )
        if final_gate_rows:
            tables.append(
                make_table(
                    "final_gate_results_table",
                    "Locked evaluator gates",
                    "Ακριβείς gate rows από το caller-provided final decision.",
                    "final_gate_results",
                    "final_decision_json",
                    (
                        ("section", "Section", "text"),
                        ("gate", "Gate", "text"),
                        ("passed", "Passed", "text"),
                        ("actual", "Actual", "text"),
                        ("requirement", "Requirement", "text"),
                    ),
                    default_sort=("section", "asc"),
                )
            )
    if orderflow is not None:
        tables.append(
            make_table(
                "orderflow_fields_table",
                "Local order-flow compatibility evidence",
                "Saved local-only evidence· δεν αποτελεί qualification gate.",
                "orderflow_fields",
                "orderflow_json",
                (("field", "Field", "text"), ("value", "Value", "text")),
                default_sort=("field", "asc"),
            )
        )
    if deployment is not None:
        tables.append(
            make_table(
                "deployment_fields_table",
                "Deployment isolation evidence",
                "Saved caller-provided evidence· το report δεν έκανε live VPS query.",
                "deployment_fields",
                "deployment_json",
                (("field", "Field", "text"), ("value", "Value", "text")),
                default_sort=("field", "asc"),
            )
        )
    if archive_security is not None:
        tables.append(
            make_table(
                "archive_security_fields_table",
                "Backtest archive security audit",
                "Aggregate integrity/redaction counts από το caller-provided audit· κανένα ZIP member ή config value δεν ενσωματώνεται.",
                "archive_security_fields",
                "archive_security_json",
                (("field", "Field", "text"), ("value", "Value", "text")),
                default_sort=("field", "asc"),
            )
        )

    chart = {
        "id": "reconciliation_status_chart",
        "title": "Reconciliation checks ανά split και status",
        "subtitle": (
            f"Απόλυτο πλήθος των {len(reconciliation_rows)} aggregate checks· "
            "κάθε split έχει ρητή PASS και FAIL κατηγορία."
        ),
        "type": "bar",
        "intent": "comparison",
        "question": "Σε ποια locked splits συγκεντρώνονται οι αποτυχίες timeframe reconciliation;",
        "rationale": "Μία σειρά από bars επιτρέπει άμεση σύγκριση των απόλυτων counts χωρίς redundant color encoding.",
        "comparisonContext": {
            "baseline": "0 checks",
            "denominator": "all pair × informative-timeframe checks within each split",
            "grain": "split × status",
            "unit": "checks",
        },
        "dataset": "reconciliation_status_counts",
        "sourceId": "dq_reconciliation_csv",
        "layout": "full",
        "emptyState": "Δεν υπάρχουν reconciliation checks.",
        "encodings": {
            "x": {"field": "category", "type": "nominal", "label": "Split · status"},
            "y": {
                "field": "check_count",
                "type": "quantitative",
                "label": "Πλήθος checks",
                "format": "number",
            },
            "tooltip": [
                {"field": "split", "type": "nominal", "label": "Split"},
                {"field": "status", "type": "nominal", "label": "Status"},
                {
                    "field": "check_count",
                    "type": "quantitative",
                    "label": "Checks",
                    "format": "number",
                },
                {
                    "field": "total_split_checks",
                    "type": "quantitative",
                    "label": "Total split checks",
                    "format": "number",
                },
            ],
        },
        "labels": {"values": "all"},
        "settings": {
            "categoryLabelPolicy": "wrap",
            "groupMode": "single",
            "showValues": True,
            "sort": "none",
        },
        "surface": {"surface": "export", "showControls": False, "viewMode": "both"},
    }

    files_total = summary["files_total"]
    files_passed = summary["files_passed"]
    split_total = summary["split_checks_total"]
    split_passed = summary["split_checks_passed"]
    reconciliation_total = summary["reconciliation_checks_total"]
    reconciliation_passed = summary["reconciliation_checks_passed"]
    reconciliation_failed = summary["reconciliation_checks_failed"]
    data_status = summary["data_status"]

    blocks: list[dict[str, Any]] = [
        {
            "id": "title",
            "type": "markdown",
            "body": "# Τεχνικός Έλεγχος ProDayTraderV1",
        },
        {
            "id": "technical_summary",
            "type": "markdown",
            "body": (
                "## Τεχνικό συμπέρασμα: το qualification παραμένει μπλοκαρισμένο\n\n"
                f"- **Κύριο αποτέλεσμα:** το data gate είναι `{data_status}` και το qualification PnL είναι "
                "`NOT_RUN`. Αυτό δεν αποτελεί μέτρηση μηδενικής απόδοσης.\n"
                f"- **Τι πέρασε:** {files_passed}/{files_total} native files και "
                f"{split_passed}/{split_total} pair/timeframe/split integrity checks.\n"
                f"- **Τι απέτυχε:** {reconciliation_failed}/{reconciliation_total} aggregate timeframe "
                f"reconciliation checks απέτυχαν· πέρασαν {reconciliation_passed}/{reconciliation_total}.\n"
                "- **Απόφαση τώρα:** δεν υπάρχει τεκμηριωμένη βάση για performance qualification, "
                "ξεχωριστό ProDay dry-run ή live trading. Τα ενεργά bots δεν αξιολογούνται από αυτό το report."
            ),
        },
        {
            "id": "reconciliation_finding",
            "type": "markdown",
            "sourceId": "dq_reconciliation_csv",
            "body": (
                "## Οι αποκλίσεις reconciliation είναι ο αποκλειστικός blocker του pre-PnL gate\n\n"
                "Το chart μετρά checks, όχι candles ή αποδόσεις. Κάθε split εμφανίζει ξεχωριστά PASS και FAIL, "
                "συμπεριλαμβανομένων των μηδενικών counts. Η μία σειρά και η κοινή μηδενική βάση αποφεύγουν "
                "παραπλανητική χρωματική ή κλιμακωτή σύγκριση. Συνεπώς, το επόμενο βήμα είναι source-level "
                "διάγνωση των mismatched bins και όχι tuning της strategy."
            ),
        },
        {
            "id": "reconciliation_chart_block",
            "type": "chart",
            "chartId": "reconciliation_status_chart",
            "layout": "full",
        },
        {
            "id": "audit_evidence_heading",
            "type": "markdown",
            "body": (
                "## Τα ακριβή audit rows διαχωρίζουν file integrity από timeframe equality\n\n"
                "Οι επόμενοι πίνακες κρατούν χωριστά το συνολικό αποτέλεσμα, τα aggregate checks, τις ακριβείς "
                "αποτυχημένες ημέρες, το critical failure register, την κάλυψη ανά split, τα input files και τα gaps. "
                "Έτσι ένα PASS στην κάλυψη δεν συγχέεται με PASS στη συμφωνία των native timeframes."
            ),
        },
        {"id": "audit_summary_block", "type": "table", "tableId": "audit_summary_table", "layout": "full"},
        {"id": "reconciliation_table_block", "type": "table", "tableId": "reconciliation_table", "layout": "full"},
        {"id": "daily_failure_table_block", "type": "table", "tableId": "daily_failure_table", "layout": "full"},
        {"id": "failure_register_table_block", "type": "table", "tableId": "failure_register_table", "layout": "full"},
        {"id": "split_checks_table_block", "type": "table", "tableId": "split_checks_table", "layout": "full"},
        {"id": "file_checks_table_block", "type": "table", "tableId": "file_checks_table", "layout": "full"},
        {"id": "gap_checks_table_block", "type": "table", "tableId": "gap_checks_table", "layout": "full"},
        {
            "id": "scope_heading",
            "type": "markdown",
            "body": (
                "## Scope και ορισμοί που απαιτούνται για σωστή ερμηνεία\n\n"
                "Η μονάδα του file audit είναι pair × native timeframe. Η μονάδα του split audit είναι "
                "pair × native timeframe × locked split. Η μονάδα του reconciliation audit είναι "
                "pair × informative timeframe × locked split. Το `PNL NOT_RUN` είναι evidence state, όχι return metric."
            ),
        },
        {"id": "scope_definitions_block", "type": "table", "tableId": "scope_definitions_table", "layout": "full"},
        {"id": "quality_definitions_block", "type": "table", "tableId": "quality_definitions_table", "layout": "full"},
        {
            "id": "methodology",
            "type": "markdown",
            "sourceId": "locked_plan",
            "body": (
                "## Η μεθοδολογία παραμένει pre-PnL και fail-closed\n\n"
                "Το report διαβάζει μόνο αποθηκευμένα JSON/CSV artifacts. Δεν εκτελεί backtest, δεν αλλάζει "
                "strategy ή thresholds και δεν επικοινωνεί με Binance ή VPS. Η 5m-to-informative reconciliation "
                "ελέγχεται πριν από οποιοδήποτε performance αποτέλεσμα. Αν έστω ένα required technical/data/source "
                "gate αποτύχει, το frozen plan επιβάλλει τεχνικό αποκλεισμό αντί για επιλεκτική αφαίρεση pair ή tuning."
            ),
        },
    ]

    if final_decision is not None:
        blocks.extend(
            [
                {
                    "id": "final_decision_heading",
                    "type": "markdown",
                    "body": (
                        "## Το caller-provided evaluator output παρατίθεται χωρίς επανερμηνεία\n\n"
                        "Τα top-level fields και, όταν υπάρχουν, τα gate rows προέρχονται αυτούσια από το saved JSON."
                    ),
                },
                {"id": "final_decision_fields_block", "type": "table", "tableId": "final_decision_fields_table", "layout": "full"},
            ]
        )
        if final_gate_rows:
            blocks.append(
                {"id": "final_gate_results_block", "type": "table", "tableId": "final_gate_results_table", "layout": "full"}
            )
    if orderflow is not None:
        blocks.extend(
            [
                {
                    "id": "orderflow_heading",
                    "type": "markdown",
                    "body": (
                        "## Το order-flow evidence παραμένει local και μη qualifying\n\n"
                        "Η συμβατότητα παρατίθεται ως τεχνικό evidence. Δεν αλλάζει το ιστορικό data gate και δεν "
                        "χρησιμοποιείται για να δικαιολογήσει entry rules σε αυτόν τον frozen κύκλο."
                    ),
                },
                {"id": "orderflow_fields_block", "type": "table", "tableId": "orderflow_fields_table", "layout": "full"},
            ]
        )
    if deployment is not None:
        blocks.extend(
            [
                {
                    "id": "deployment_heading",
                    "type": "markdown",
                    "body": (
                        "## Το deployment evidence είναι αποθηκευμένο snapshot, όχι live query\n\n"
                        "Το report εμφανίζει μόνο το caller-provided JSON και δεν ισχυρίζεται τρέχουσα κατάσταση VPS "
                        "πέρα από εκείνο το snapshot."
                    ),
                },
                {"id": "deployment_fields_block", "type": "table", "tableId": "deployment_fields_table", "layout": "full"},
            ]
        )
    if archive_security is not None:
        blocks.extend(
            [
                {
                    "id": "archive_security_heading",
                    "type": "markdown",
                    "body": (
                        "## Το archive audit επιβεβαιώνει integrity και redaction χωρίς να εισάγει ProDay PnL\n\n"
                        "Το saved aggregate evidence παρατίθεται χωρίς ZIP contents ή config values. "
                        "Η απουσία ProDay ZIP συμφωνεί με το locked `PNL NOT_RUN` state και δεν μετατρέπεται σε performance result."
                    ),
                },
                {"id": "archive_security_fields_block", "type": "table", "tableId": "archive_security_fields_table", "layout": "full"},
            ]
        )

    optional_limitations = []
    if orderflow is None:
        optional_limitations.append(
            "Δεν δόθηκε orderflow_compatibility.json· είναι optional και μη qualifying evidence."
        )
    if deployment is None:
        optional_limitations.append(
            "Δεν δόθηκε deployment evidence JSON· το report δεν κάνει inference για τρέχουσα κατάσταση VPS."
        )
    limitation_lines = [
        "Η αποτυχία reconciliation δείχνει ασυμφωνία πηγών/timeframes· δεν αποδεικνύει αιτία μέχρι να αναλυθούν τα mismatched bins.",
        (
            f"Το πλήρες daily reconciliation CSV ({len(reconciliation_daily_rows)} rows) δεν ενσωματώνεται "
            f"ολόκληρο ως visible table· ενσωματώνονται και τα {len(failed_daily_rows)} FAIL day-check rows "
            f"σε {failed_daily_distinct_dates} διακριτές UTC ημερομηνίες, ενώ το πλήρες αρχείο "
            "παραμένει canonical source."
        ),
        "Δεν υπάρχουν qualification PnL, walk-forward, cost-stress, lookahead ή recursive αποτελέσματα σε αυτό το evidence state.",
        "Καμία ιστορική μέτρηση δεν αποτελεί forward evidence, εγγύηση κέρδους ή άδεια live trading.",
        *optional_limitations,
    ]
    blocks.extend(
        [
            {
                "id": "limitations",
                "type": "markdown",
                "body": "## Περιορισμοί, αβεβαιότητα και robustness gaps\n\n"
                + "\n".join(f"- {line}" for line in limitation_lines),
            },
            {
                "id": "recommended_steps",
                "type": "markdown",
                "body": (
                    "## Προτεινόμενα επόμενα βήματα\n\n"
                    "1. Εντόπισε για κάθε FAIL pair/timeframe/day check row τα ακριβή mismatched OHLCV fields και τις native-versus-aggregated τιμές.\n"
                    "2. Ταξινόμησε την αιτία ως exchange source revision, incomplete native bin, timestamp alignment ή auditor defect.\n"
                    "3. Διόρθωσε μόνο την αποδεδειγμένη source/auditor αιτία και επανέλαβε ολόκληρο το data audit με νέο immutable evidence set.\n"
                    "4. Εκτέλεσε qualification PnL μόνο αν όλα τα frozen data/source gates περάσουν, χωρίς αλλαγή strategy ή thresholds.\n"
                    "5. Διατήρησε live trading, API keys, automatic promotion και ProDay deployment απενεργοποιημένα μέχρι ξεχωριστή τεκμηριωμένη απόφαση."
                ),
            },
            {
                "id": "further_questions",
                "type": "markdown",
                "body": (
                    "## Ανοιχτές ερωτήσεις\n\n"
                    f"- Συγκεντρώνονται τα {len(failed_daily_rows)} FAIL day-check rows σε "
                    f"{failed_daily_distinct_dates} διακριτές UTC ημερομηνίες και σε κοινά exchange "
                    "maintenance/source-revision timestamps;\n"
                    "- Οι αποκλίσεις αφορούν price fields, volume ή και τα δύο, και είναι ίδιες ανά pair/timeframe;\n"
                    "- Μπορεί η αιτία να διορθωθεί χωρίς να αλλάξει κανένα frozen strategy/config/threshold input;\n"
                    "- Μετά από καθαρό data gate, θα παράγει η κλειδωμένη strategy επαρκές και αμερόληπτο sample;"
                ),
            },
        ]
    )

    pnl_not_run = data_quality.get("pnl_evaluated") is not True
    if pnl_not_run:
        snapshot_status = "blocked"
        access_issues = [
            {
                "id": "pnl_not_run",
                "scope": "qualification",
                "sourceId": "data_quality_json",
                "dataset": "audit_summary",
                "message": (
                    "PnL NOT_RUN: το υποχρεωτικό data/source reconciliation gate είναι DATA_BLOCKED, "
                    "άρα δεν υπάρχει qualification performance evidence."
                ),
            }
        ]
    elif final_decision is None:
        snapshot_status = "partial"
        access_issues = [
            {
                "id": "final_decision_not_available",
                "scope": "qualification",
                "dataset": "audit_summary",
                "message": "Το PnL δηλώνεται evaluated αλλά δεν δόθηκε final_decision.json.",
            }
        ]
    else:
        snapshot_status = "ready"
        access_issues = []

    artifact = {
        "surface": "report",
        "manifest": {
            "version": ARTIFACT_VERSION,
            "surface": "report",
            "title": "Τεχνικός Έλεγχος ProDayTraderV1",
            "description": (
                "Answer-first technical audit of the frozen ProDayTraderV1 data gate, evidence boundary and decision readiness."
            ),
            "generatedAt": generated_at,
            "sources": sources,
            "blocks": blocks,
            "cards": [],
            "charts": [chart],
            "tables": tables,
            "filters": [],
        },
        "sources": sources,
        "snapshot": {
            "version": ARTIFACT_VERSION,
            "status": snapshot_status,
            "generatedAt": generated_at,
            "datasets": datasets,
            "accessIssues": access_issues,
        },
    }
    # Strict serialization here catches NaN/Infinity and unsupported accidental values.
    json.dumps(artifact, ensure_ascii=False, allow_nan=False, sort_keys=True)

    notes = {
        "schema_version": SCHEMA_VERSION,
        "surface": "report",
        "delivery_mode": "html",
        "audience": "technical",
        "generated_at": generated_at,
        "required_structure_map": [
            {"role": "Title", "block_id": "title"},
            {"role": "Technical summary", "block_id": "technical_summary"},
            {"role": "Key findings with visual evidence", "block_id": "reconciliation_finding"},
            {"role": "Scope, data, and metric definitions", "block_id": "scope_heading"},
            {"role": "Methodology", "block_id": "methodology"},
            {"role": "Limitations, uncertainty, and robustness checks", "block_id": "limitations"},
            {"role": "Recommended next steps", "block_id": "recommended_steps"},
            {"role": "Further questions", "block_id": "further_questions"},
        ],
        "chart_map": [
            {
                "chart_id": "reconciliation_status_chart",
                "report_segment": "Key findings with visual evidence",
                "analytical_question": "Where do PASS and FAIL aggregate reconciliation checks occur across locked splits?",
                "supported_claim": "The pre-PnL blocker is isolated to aggregate timeframe reconciliation checks.",
                "family": "Comparison & Ranking",
                "type": "bar",
                "variant": "single-series vertical bar",
                "dataset": "reconciliation_status_counts",
                "fields": {"x": "category", "y": "check_count"},
                "expected_rows": len(chart_rows),
                "zero_baseline": True,
                "palette_policy": "Single default neutral series; no color or legend encoding.",
                "non_color_distinction": "Axis category includes split and status; every bar has a direct value label.",
                "source_id": "dq_reconciliation_csv",
            }
        ],
        "source_notes": {
            "snapshot_status": snapshot_status,
            "pnl_boundary": "PNL_NOT_RUN" if pnl_not_run else "PNL_EVALUATED",
            "reconciliation_chart": (
                "Counts are computed from every aggregate reconciliation row. Explicit zero rows preserve "
                "the absent status within each split; no category is silently dropped."
            ),
            "daily_detail": (
                f"The source contains {len(reconciliation_daily_rows)} daily rows. The bounded artifact includes "
                f"all {len(failed_daily_rows)} FAIL day-check rows across {failed_daily_distinct_dates} distinct "
                "UTC dates and omits PASS rows from the visible table."
            ),
            "optional_final_decision": "included" if final_decision is not None else "not provided",
            "optional_orderflow": "included" if orderflow is not None else "not provided",
            "optional_deployment": "included" if deployment is not None else "not provided",
            "optional_archive_security": "included" if archive_security is not None else "not provided",
            "sql_materialization": (
                "Every final snapshot dataset was materialized in-memory with Python sqlite3 and selected with "
                "the exact `SELECT * FROM report_rows` query recorded on its canonical source. Upstream parsing "
                "and deterministic calculations remain implemented in tools/build_pro_day_report_artifact.py."
            ),
            "omitted_metrics": [
                {
                    "metric_family": "qualification PnL and downstream diagnostics",
                    "reason": "NOT_RUN because the required data/source gate is blocked",
                    "needed_evidence": "A complete PASS of every frozen data/source check before PnL execution",
                }
            ] if pnl_not_run else [],
            "bounded_dataset_counts": {key: len(rows) for key, rows in datasets.items()},
        },
    }
    json.dumps(notes, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return artifact, notes


def build_and_write(
    *,
    output_path: Path,
    supporting_notes_path: Path,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = Path(kwargs["workspace"]).resolve()
    require_inside_workspace(output_path, workspace, "report artifact output")
    require_inside_workspace(supporting_notes_path, workspace, "supporting notes output")
    artifact, notes = build_artifact(**kwargs)
    atomic_write_json(output_path, artifact)
    atomic_write_json(supporting_notes_path, notes)
    return artifact, notes


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--workspace", type=Path, default=Path("."))
    result.add_argument("--locked-plan", type=Path, default=Path("docs/pro_day_trader_v1_locked_plan.md"))
    result.add_argument("--data-quality", type=Path, default=Path("user_data/reports/pro_day/data_quality.json"))
    result.add_argument("--files-csv", type=Path, default=Path("user_data/reports/pro_day/data_quality_files.csv"))
    result.add_argument("--splits-csv", type=Path, default=Path("user_data/reports/pro_day/data_quality_splits.csv"))
    result.add_argument("--reconciliation-csv", type=Path, default=Path("user_data/reports/pro_day/data_quality_reconciliation.csv"))
    result.add_argument("--reconciliation-daily-csv", type=Path, default=Path("user_data/reports/pro_day/data_quality_reconciliation_daily.csv"))
    result.add_argument("--gaps-csv", type=Path, default=Path("user_data/reports/pro_day/data_quality_gaps.csv"))
    result.add_argument("--final-decision", type=Path, default=Path("user_data/reports/pro_day/final_decision.json"))
    result.add_argument("--orderflow", type=Path, default=Path("user_data/reports/pro_day/orderflow_compatibility.json"))
    result.add_argument("--deployment-evidence", type=Path)
    result.add_argument(
        "--archive-security-audit",
        type=Path,
        default=Path("user_data/reports/pro_day/archive_security_audit.json"),
    )
    result.add_argument("--output", type=Path, default=Path("user_data/reports/pro_day/report_artifact.json"))
    result.add_argument(
        "--supporting-notes",
        type=Path,
        default=Path("user_data/reports/pro_day/report_supporting_notes.json"),
    )
    return result


def resolve_input(path: Path | None, workspace: Path) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else workspace / path


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    workspace = args.workspace.resolve()
    try:
        artifact, _ = build_and_write(
            workspace=workspace,
            locked_plan_path=resolve_input(args.locked_plan, workspace),
            data_quality_path=resolve_input(args.data_quality, workspace),
            files_csv_path=resolve_input(args.files_csv, workspace),
            splits_csv_path=resolve_input(args.splits_csv, workspace),
            reconciliation_csv_path=resolve_input(args.reconciliation_csv, workspace),
            reconciliation_daily_csv_path=resolve_input(args.reconciliation_daily_csv, workspace),
            gaps_csv_path=resolve_input(args.gaps_csv, workspace),
            final_decision_path=resolve_input(args.final_decision, workspace),
            orderflow_path=resolve_input(args.orderflow, workspace),
            deployment_evidence_path=resolve_input(args.deployment_evidence, workspace),
            archive_security_audit_path=resolve_input(args.archive_security_audit, workspace),
            output_path=resolve_input(args.output, workspace),
            supporting_notes_path=resolve_input(args.supporting_notes, workspace),
        )
    except ReportBuildError as exc:
        print(json.dumps({"status": "REPORT_ARTIFACT_FAILED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": "REPORT_ARTIFACT_READY",
                "snapshot_status": artifact["snapshot"]["status"],
                "output": safe_relative_path(resolve_input(args.output, workspace), workspace, "output"),
                "supporting_notes": safe_relative_path(
                    resolve_input(args.supporting_notes, workspace), workspace, "supporting notes"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
