#!/usr/bin/env python3
"""Build the canonical source-backed artifact for the forward dashboard."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_HISTORY_ROWS = 500
MAX_ALERT_ROWS = 50


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_hours(newer: Any, older: Any) -> float | None:
    current = parse_utc(newer)
    prior = parse_utc(older)
    if current is None or prior is None:
        return None
    return max(0.0, (current - prior).total_seconds() / 3600.0)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def optional_number(value: Any) -> int | float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def compact_value(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, dict):
        return ", ".join(f"{key}={compact_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(compact_value(item) for item in value)
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))[-MAX_HISTORY_ROWS:]
    return [
        {
            "snapshot_utc": row.get("snapshot_utc", ""),
            "bot": str(row.get("bot_key", "")).upper(),
            "closed_trades": optional_number(row.get("closed_trades")),
            "open_trades": optional_number(row.get("open_trades")),
            "net_profit_abs": optional_number(row.get("net_profit_abs")),
            "return_pct": optional_number(row.get("return_pct_of_start_wallet")),
            "profit_factor": optional_number(row.get("profit_factor")),
            "drawdown_pct": optional_number(row.get("max_drawdown_pct_of_start_wallet")),
            "return_to_drawdown": optional_number(row.get("return_to_drawdown")),
            "distinct_pairs": optional_number(row.get("distinct_pairs")),
            "collection_status": row.get("collection_status", ""),
        }
        for row in rows
    ]


def read_alerts(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(
                    {
                        "timestamp_utc": value.get("timestamp_utc"),
                        "severity": value.get("severity"),
                        "event_type": value.get("event_type"),
                        "bot": value.get("bot") or "SYSTEM",
                        "message": value.get("message"),
                    }
                )
    records.sort(key=lambda item: str(item.get("timestamp_utc") or ""))
    return records[-MAX_ALERT_ROWS:]


def source_specs(generated_at: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "latest_overview",
            "label": "Latest forward-monitor KPI extract",
            "path": "user_data/reports/forward_monitor_latest.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Extracts validated continuity, coverage, freshness, and V1/V2R headline metrics.",
                "tables_used": ["user_data/reports/forward_monitor_latest.json"],
                "metric_definitions": [
                    "Net profit is the sum of closed-trade profit_abs in USDT.",
                    "Profit factor is gross positive profit divided by absolute gross negative profit and is null when undefined.",
                    "Drawdown percent is maximum chronological equity decline divided by starting dry-run wallet.",
                ],
                "sql": (
                    "SELECT monitoring.elapsed_days AS calendar_monitoring_days, "
                    "monitoring.continuity.validated_observation_days AS validated_observation_days, "
                    "monitoring.continuity.coverage_ratio * 100 AS snapshot_coverage_pct, "
                    "locked_thresholds.minimum_monitoring_days AS monitoring_days_target, "
                    "bots.v1.metrics.closed_trades AS v1_closed, "
                    "bots.v2r.metrics.closed_trades AS v2r_closed, "
                    "bots.v2r.metrics.net_profit_abs AS v2r_net_profit, "
                    "bots.v2r.metrics.profit_factor AS v2r_profit_factor, "
                    "bots.v2r.metrics.max_drawdown_pct_of_start_wallet AS v2r_drawdown_pct, "
                    "bots.v1.account_risk.new_entries_allowed AS v1_entry_guard, "
                    "bots.v2r.account_risk.new_entries_allowed AS v2r_entry_guard "
                    "FROM read_json_auto('user_data/reports/forward_monitor_latest.json')"
                ),
            },
        },
        {
            "id": "latest_comparison",
            "label": "Latest V1 versus V2R comparison extract",
            "path": "user_data/reports/forward_monitor_latest.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Normalizes the two latest bot metric objects into comparison rows.",
                "tables_used": ["user_data/reports/forward_monitor_latest.json"],
                "sql": (
                    "WITH src AS (SELECT bots FROM read_json_auto('user_data/reports/forward_monitor_latest.json')) "
                    "SELECT 'V1' AS bot, bots.v1.strategy AS strategy, bots.v1.metrics.closed_trades AS closed_trades, "
                    "bots.v1.metrics.net_profit_abs AS net_profit_usdt, bots.v1.metrics.profit_factor AS profit_factor, "
                    "bots.v1.runtime.bot_loop_age_seconds AS bot_loop_age_seconds, "
                    "bots.v1.market_data_freshness.maximum_candle_close_age_seconds AS candle_age_seconds "
                    "FROM src UNION ALL SELECT 'V2R', bots.v2r.strategy, bots.v2r.metrics.closed_trades, "
                    "bots.v2r.metrics.net_profit_abs, bots.v2r.metrics.profit_factor, "
                    "bots.v2r.runtime.bot_loop_age_seconds, "
                    "bots.v2r.market_data_freshness.maximum_candle_close_age_seconds FROM src"
                ),
            },
        },
        {
            "id": "forward_decision",
            "label": "Current forward decision",
            "path": "user_data/reports/forward_monitor_decision.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Reads the current machine decision and safety flags.",
                "tables_used": ["user_data/reports/forward_monitor_decision.json"],
                "sql": (
                    "SELECT snapshot_utc, decision, auto_promotion_enabled, live_trading_authorized, profit_guaranteed "
                    "FROM read_json_auto('user_data/reports/forward_monitor_decision.json')"
                ),
            },
        },
        {
            "id": "forward_gates",
            "label": "Locked forward gate extract",
            "path": "user_data/reports/forward_monitor_decision.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Expands integrity, account-risk, sample, and performance gates into one review table.",
                "tables_used": ["user_data/reports/forward_monitor_decision.json"],
                "sql": (
                    "SELECT decision, integrity_gates, risk_gates, sample_gates, performance_gates "
                    "FROM read_json_auto('user_data/reports/forward_monitor_decision.json')"
                ),
            },
        },
        {
            "id": "monitor_history",
            "label": "Forward-monitor snapshot history",
            "path": "user_data/reports/forward_monitor_history.csv",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Loads the most recent bounded bot-level snapshots for the time-series charts.",
                "tables_used": ["user_data/reports/forward_monitor_history.csv"],
                "filters": [f"Most recent {MAX_HISTORY_ROWS} rows maximum"],
                "sql": (
                    "SELECT snapshot_utc, upper(bot_key) AS bot, closed_trades, open_trades, net_profit_abs, "
                    "return_pct_of_start_wallet AS return_pct, profit_factor, "
                    "max_drawdown_pct_of_start_wallet AS drawdown_pct, return_to_drawdown, distinct_pairs "
                    "FROM read_csv_auto('user_data/reports/forward_monitor_history.csv', header=true) "
                    f"ORDER BY snapshot_utc DESC LIMIT {MAX_HISTORY_ROWS}"
                ),
            },
        },
        {
            "id": "alert_journal",
            "label": "Combined deduplicated forward alert journal",
            "path": "user_data/reports/forward*_alerts.jsonl",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Loads recent state-transition alerts emitted by the monitor and watchdog.",
                "tables_used": [
                    "user_data/reports/forward_alerts.jsonl",
                    "user_data/reports/forward_watchdog_alerts.jsonl",
                ],
                "filters": [f"Most recent {MAX_ALERT_ROWS} alerts maximum"],
                "sql": (
                    "SELECT timestamp_utc, severity, event_type, coalesce(bot, 'SYSTEM') AS bot, message "
                    "FROM read_json_auto('user_data/reports/forward*_alerts.jsonl', "
                    "format='newline_delimited') "
                    f"ORDER BY timestamp_utc DESC LIMIT {MAX_ALERT_ROWS}"
                ),
            },
        },
        {
            "id": "watchdog_status",
            "label": "Local snapshot freshness watchdog",
            "path": "user_data/reports/forward_watchdog_latest.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Reads the latest independent watchdog freshness state.",
                "tables_used": ["user_data/reports/forward_watchdog_latest.json"],
                "sql": (
                    "SELECT checked_utc, snapshot_age_seconds / 3600.0 AS snapshot_age_hours, "
                    "stale_after_seconds, status AS watchdog_status, stale, "
                    "deadman_heartbeat.status AS heartbeat_status "
                    "FROM read_json_auto('user_data/reports/forward_watchdog_latest.json')"
                ),
            },
        },
        {
            "id": "backup_status",
            "label": "Latest forward evidence backup status",
            "path": "user_data/reports/forward_backup_status.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Reads the latest daily backup result and next due timestamp.",
                "tables_used": ["user_data/reports/forward_backup_status.json"],
                "sql": (
                    "SELECT status AS backup_status, last_successful_backup_utc, "
                    f"date_diff('second', last_successful_backup_utc::TIMESTAMPTZ, TIMESTAMPTZ '{generated_at}') / 3600.0 AS backup_age_hours, "
                    "next_due_utc, retention_days "
                    "FROM read_json_auto('user_data/reports/forward_backup_status.json')"
                ),
            },
        },
        {
            "id": "live_readiness",
            "label": "Fail-closed live qualification status",
            "path": "user_data/reports/live_readiness.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Reads qualification gates while preserving the hard live-trading block.",
                "tables_used": ["user_data/reports/live_readiness.json"],
                "sql": (
                    "SELECT qualification_status, live_trading_authorized, "
                    "automatic_live_launch_available, evidence_gates, safety_gates "
                    "FROM read_json_auto('user_data/reports/live_readiness.json')"
                ),
            },
        },
        {
            "id": "execution_stress",
            "label": "Adverse execution-cost stress report",
            "path": "user_data/reports/execution_stress_report.json",
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "executed_at": generated_at,
                "description": "Reads deterministic moderate and severe fee, slippage, latency, and funding diagnostics.",
                "tables_used": ["user_data/reports/execution_stress_report.json"],
                "sql": (
                    "SELECT status, unnest(results) AS stress_result "
                    "FROM read_json_auto('user_data/reports/execution_stress_report.json')"
                ),
            },
        },
    ]


def build_artifact(reports_dir: Path) -> dict[str, Any]:
    latest = load_json(reports_dir / "forward_monitor_latest.json")
    decision = load_json(reports_dir / "forward_monitor_decision.json")
    watchdog = load_optional_json(reports_dir / "forward_watchdog_latest.json")
    backup = load_optional_json(reports_dir / "forward_backup_status.json")
    readiness = load_optional_json(reports_dir / "live_readiness.json")
    stress = load_optional_json(reports_dir / "execution_stress_report.json")
    latest_time = parse_utc(latest["snapshot_utc"])
    watchdog_time = parse_utc(watchdog.get("checked_utc"))
    generated_time = max(
        item for item in (latest_time, watchdog_time) if item is not None
    )
    generated_at = generated_time.isoformat().replace("+00:00", "Z")
    v1 = latest["bots"]["v1"]
    v2r = latest["bots"]["v2r"]
    v1m = v1.get("metrics", {})
    v2m = v2r.get("metrics", {})
    elapsed_days = float(latest["monitoring"]["elapsed_days"])
    continuity = latest.get("monitoring", {}).get("continuity", {})
    validated_days = float(continuity.get("validated_observation_days", elapsed_days))
    coverage_ratio = float(continuity.get("coverage_ratio", 1.0))
    watchdog_age = optional_number(watchdog.get("snapshot_age_seconds"))
    if watchdog_age is None:
        watchdog_age_hours = age_hours(generated_at, latest.get("snapshot_utc"))
    else:
        watchdog_age_hours = max(0.0, float(watchdog_age) / 3600.0)
    backup_age_hours = age_hours(generated_at, backup.get("last_successful_backup_utc"))
    thresholds = latest["locked_thresholds"]
    sources = source_specs(generated_at)
    decision_code = str(decision.get("decision", "UNKNOWN"))
    decision_labels = {
        "INSUFFICIENT_FORWARD_SAMPLE": "Συλλογή δείγματος",
        "MONITORING_ERROR": "Απαιτείται έλεγχος",
        "FORWARD_GATES_FAILED_KEEP_RUNNING": "Αποτυχία gates",
        "FORWARD_REVIEW_READY": "Έτοιμο για ανθρώπινο review",
        "RISK_LIMIT_BREACH": "Μπλοκάρισμα από risk limit",
    }
    decision_label = decision_labels.get(decision_code, decision_code)
    overview = [
        {
            "decision_status": decision_label,
            "live_trading_status": "Απενεργοποιημένο",
            "calendar_monitoring_days": elapsed_days,
            "validated_observation_days": validated_days,
            "snapshot_coverage_pct": coverage_ratio * 100.0,
            "snapshot_age_hours": watchdog_age_hours,
            "watchdog_status": watchdog.get("status", "UNAVAILABLE"),
            "heartbeat_status": watchdog.get("deadman_heartbeat", {}).get(
                "status", "DISABLED"
            ),
            "backup_age_hours": backup_age_hours,
            "backup_status": backup.get("status", "UNAVAILABLE"),
            "qualification_status": readiness.get("qualification_status", "UNAVAILABLE"),
            "execution_stress_status": stress.get("status", "UNAVAILABLE"),
            "v1_entry_guard": v1.get("account_risk", {}).get("new_entries_allowed"),
            "v2r_entry_guard": v2r.get("account_risk", {}).get("new_entries_allowed"),
            "monitoring_days_target": thresholds["minimum_monitoring_days"],
            "v1_closed": v1m.get("closed_trades"),
            "v1_closed_target": thresholds["minimum_closed_trades_per_bot"],
            "v2r_closed": v2m.get("closed_trades"),
            "v2r_closed_target": thresholds["minimum_closed_trades_per_bot"],
            "v2r_net_profit": v2m.get("net_profit_abs"),
            "v2r_profit_factor": v2m.get("profit_factor"),
            "v2r_profit_factor_target": thresholds["minimum_v2r_profit_factor"],
            "v2r_drawdown_pct": v2m.get("max_drawdown_pct_of_start_wallet"),
            "v2r_drawdown_limit": thresholds["maximum_v2r_drawdown_pct_of_start_wallet"],
        }
    ]
    bot_compare = []
    for label, bot in (("V1", v1), ("V2R", v2r)):
        metrics = bot.get("metrics", {})
        runtime = bot.get("runtime", {})
        market_freshness = bot.get("market_data_freshness", {})
        bot_compare.append(
            {
                "bot": label,
                "strategy": bot.get("strategy"),
                "status": bot.get("status"),
                "closed_trades": metrics.get("closed_trades"),
                "open_trades": metrics.get("open_trades"),
                "net_profit_usdt": metrics.get("net_profit_abs"),
                "return_pct": metrics.get("return_pct_of_start_wallet"),
                "profit_factor": metrics.get("profit_factor"),
                "drawdown_pct": metrics.get("max_drawdown_pct_of_start_wallet"),
                "return_to_drawdown": metrics.get("return_to_drawdown"),
                "distinct_pairs": metrics.get("distinct_pairs"),
                "bot_loop_age_seconds": runtime.get("bot_loop_age_seconds"),
                "max_candle_age_hours": (
                    float(market_freshness["maximum_candle_close_age_seconds"]) / 3600.0
                    if market_freshness.get("maximum_candle_close_age_seconds") is not None
                    else None
                ),
                "restart_count": continuity.get("bot_restart_counts", {}).get(label.lower(), 0),
                "runtime_pass": bot.get("runtime_validation", {}).get("pass"),
                "data_quality_pass": bot.get("data_quality", {}).get("pass"),
                "new_entries_allowed": bot.get("account_risk", {}).get("new_entries_allowed"),
            }
        )
    risk_status = []
    for label, bot in (("V1", v1), ("V2R", v2r)):
        risk = bot.get("account_risk", {})
        risk_status.append(
            {
                "bot": label,
                "policy_id": risk.get("policy_id"),
                "new_entries_allowed": risk.get("new_entries_allowed"),
                "daily_loss_pct": risk.get("daily_realized_loss_pct"),
                "weekly_loss_pct": risk.get("weekly_realized_loss_pct"),
                "open_stake_pct": risk.get("conservative_open_stake_pct"),
                "failed_checks": ", ".join(
                    str(item.get("name"))
                    for item in risk.get("checks", [])
                    if item.get("status") == "FAIL"
                ),
            }
        )
    stress_results = [
        {
            "split": item.get("split"),
            "scenario": item.get("scenario"),
            "status": item.get("status"),
            "net_profit_usdt": item.get("net_profit_usdt"),
            "profit_factor": item.get("profit_factor"),
            "realized_drawdown_pct": item.get("realized_drawdown_pct"),
            "trades": item.get("trades"),
        }
        for item in stress.get("results", [])
        if isinstance(item, dict)
    ]
    gates = []
    for category, key in (
        ("Integrity", "integrity_gates"),
        ("Risk", "risk_gates"),
        ("Sample", "sample_gates"),
        ("Performance", "performance_gates"),
    ):
        for item in decision.get(key, []):
            gates.append(
                {
                    "category": category,
                    "gate": item.get("name"),
                    "status": item.get("status"),
                    "actual": compact_value(item.get("actual")),
                    "requirement": item.get("requirement"),
                }
            )
    history = read_history(reports_dir / "forward_monitor_history.csv")
    alerts = read_alerts(
        [
            reports_dir / "forward_alerts.jsonl",
            reports_dir / "forward_watchdog_alerts.jsonl",
        ]
    )

    cards = [
        {
            "id": "forward_decision",
            "description": "Η τρέχουσα machine decision του locked forward-review workflow· δεν αποτελεί άδεια για live trading.",
            "dataset": "overview",
            "sourceId": "forward_decision",
            "metrics": [
                {"label": "Κατάσταση", "field": "decision_status", "format": "text"},
                {"label": "Live trading", "field": "live_trading_status", "format": "text"},
            ],
        },
        {
            "id": "validated_days",
            "description": "Ημέρες που μετρούν μόνο μέσα στο τρέχον έγκυρο segment και σταθμίζονται με την κάλυψη των προγραμματισμένων snapshots.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "Έγκυρες ημέρες", "field": "validated_observation_days", "format": "number"},
                {"label": "Ελάχιστος στόχος", "field": "monitoring_days_target", "format": "number"},
            ],
        },
        {
            "id": "snapshot_coverage",
            "description": "Έγκυρα προγραμματισμένα 4ωρα slots προς όλα τα αναμενόμενα slots του τρέχοντος segment.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "Κάλυψη snapshots (%)", "field": "snapshot_coverage_pct", "format": "number"},
                {"label": "Ημερολογιακές ημέρες", "field": "calendar_monitoring_days", "format": "number"},
            ],
        },
        {
            "id": "snapshot_freshness",
            "description": "Ανεξάρτητος έλεγχος ηλικίας του τελευταίου ολοκληρωμένου προγραμματισμένου snapshot.",
            "dataset": "overview",
            "sourceId": "watchdog_status",
            "metrics": [
                {"label": "Ηλικία snapshot (ώρες)", "field": "snapshot_age_hours", "format": "number"},
                {"label": "Watchdog", "field": "watchdog_status", "format": "text"},
                {"label": "Εξωτερικό heartbeat", "field": "heartbeat_status", "format": "text"},
            ],
        },
        {
            "id": "backup_freshness",
            "description": "Ηλικία και αποτέλεσμα του τελευταίου ημερήσιου integrity-checked backup.",
            "dataset": "overview",
            "sourceId": "backup_status",
            "metrics": [
                {"label": "Ηλικία backup (ώρες)", "field": "backup_age_hours", "format": "number"},
                {"label": "Backup", "field": "backup_status", "format": "text"},
            ],
        },
        {
            "id": "live_readiness",
            "description": "Fail-closed qualification status. Ακόμη και το review-ready δεν ενεργοποιεί live trading.",
            "dataset": "overview",
            "sourceId": "live_readiness",
            "metrics": [
                {"label": "Live readiness", "field": "qualification_status", "format": "text"}
            ],
        },
        {
            "id": "execution_stress",
            "description": "Αποτέλεσμα δυσμενών σεναρίων για fees, slippage, latency και funding.",
            "dataset": "overview",
            "sourceId": "execution_stress",
            "metrics": [
                {"label": "Execution stress", "field": "execution_stress_status", "format": "text"}
            ],
        },
        {
            "id": "v1_entry_guard",
            "description": "Account-level risk guard που επιτρέπει ή απορρίπτει νέες V1 εισόδους.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V1 νέες είσοδοι", "field": "v1_entry_guard", "format": "text"}
            ],
        },
        {
            "id": "v2r_entry_guard",
            "description": "Account-level risk guard που επιτρέπει ή απορρίπτει νέες V2R εισόδους.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V2R νέες είσοδοι", "field": "v2r_entry_guard", "format": "text"}
            ],
        },
        {
            "id": "v1_closed",
            "description": "Κλεισμένες συναλλαγές του V1 control μετά την έναρξη του forward epoch.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V1 κλεισμένες", "field": "v1_closed", "format": "number"},
                {"label": "Ελάχιστος στόχος", "field": "v1_closed_target", "format": "number"},
            ],
        },
        {
            "id": "v2r_closed",
            "description": "Κλεισμένες συναλλαγές του V2R candidate μετά την έναρξη του forward epoch.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V2R κλεισμένες", "field": "v2r_closed", "format": "number"},
                {"label": "Ελάχιστος στόχος", "field": "v2r_closed_target", "format": "number"},
            ],
        },
        {
            "id": "v2r_net_profit",
            "description": "Άθροισμα κέρδους των κλεισμένων V2R trades στο USDT dry-run wallet.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V2R καθαρό PnL (USDT)", "field": "v2r_net_profit", "format": "number", "signed": True}
            ],
        },
        {
            "id": "v2r_profit_factor",
            "description": "Μικτό κέρδος V2R προς απόλυτη μικτή ζημιά· παραμένει κενό μέχρι να υπάρξουν ζημιογόνα trades.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V2R profit factor", "field": "v2r_profit_factor", "format": "number"},
                {"label": "Ελάχιστος στόχος", "field": "v2r_profit_factor_target", "format": "number"},
            ],
        },
        {
            "id": "v2r_drawdown",
            "description": "Μέγιστη πτώση του V2R equity ως ποσοστό του αρχικού dry-run wallet.",
            "dataset": "overview",
            "sourceId": "latest_overview",
            "metrics": [
                {"label": "V2R drawdown (%)", "field": "v2r_drawdown_pct", "format": "number"},
                {"label": "Μέγιστο όριο (%)", "field": "v2r_drawdown_limit", "format": "number"},
            ],
        },
    ]
    charts = [
        {
            "id": "closed_trade_trend",
            "title": "Ανάπτυξη forward δείγματος",
            "subtitle": "Συσσώρευση κλεισμένων trades για το V1 control και το V2R candidate.",
            "type": "line",
            "dataset": "history",
            "sourceId": "monitor_history",
            "encodings": {
                "x": {"field": "snapshot_utc", "type": "temporal", "label": "Snapshot"},
                "y": {"field": "closed_trades", "type": "quantitative", "label": "Κλεισμένες συναλλαγές", "format": "number"},
                "color": {"field": "bot", "type": "nominal", "label": "Bot"},
            },
            "emptyState": "Δεν υπάρχει ακόμη ιστορικό monitor.",
            "layout": "full",
        },
        {
            "id": "net_profit_trend",
            "title": "Εξέλιξη forward καθαρού PnL",
            "subtitle": "PnL κλεισμένων trades σε κάθε dry-run wallet των 1.000 USDT.",
            "type": "line",
            "dataset": "history",
            "sourceId": "monitor_history",
            "encodings": {
                "x": {"field": "snapshot_utc", "type": "temporal", "label": "Snapshot"},
                "y": {"field": "net_profit_abs", "type": "quantitative", "label": "Καθαρό PnL", "format": "number", "unit": "USDT"},
                "color": {"field": "bot", "type": "nominal", "label": "Bot"},
            },
            "emptyState": "Δεν υπάρχει ακόμη PnL από κλεισμένες συναλλαγές.",
            "layout": "full",
        },
    ]
    tables = [
        {
            "id": "bot_comparison",
            "title": "Τρέχουσα σύγκριση V1 και V2R",
            "subtitle": "Τελευταία forward metrics, υπολογισμένα ανεξάρτητα από το API summary.",
            "dataset": "bot_compare",
            "sourceId": "latest_comparison",
            "defaultSort": {"field": "bot", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "bot", "label": "Bot", "type": "text"},
                {"field": "strategy", "label": "Στρατηγική", "type": "text"},
                {"field": "closed_trades", "label": "Κλεισμένες", "format": "number"},
                {"field": "open_trades", "label": "Ανοιχτές", "format": "number"},
                {"field": "net_profit_usdt", "label": "Καθαρό PnL (USDT)", "format": "number"},
                {"field": "profit_factor", "label": "PF", "format": "number"},
                {"field": "drawdown_pct", "label": "DD (%)", "format": "number"},
                {"field": "return_to_drawdown", "label": "Return/DD", "format": "number"},
                {"field": "distinct_pairs", "label": "Ζεύγη", "format": "number"},
                {"field": "bot_loop_age_seconds", "label": "Ηλικία loop (s)", "format": "number"},
                {"field": "max_candle_age_hours", "label": "Ηλικία candle (h)", "format": "number"},
                {"field": "restart_count", "label": "Επανεκκινήσεις", "format": "number"},
                {"field": "runtime_pass", "label": "Runtime", "type": "text"},
                {"field": "data_quality_pass", "label": "Ποιότητα δεδομένων", "type": "text"},
                {"field": "new_entries_allowed", "label": "Νέες είσοδοι", "type": "text"},
            ],
        },
        {
            "id": "gate_status",
            "title": "Τι χρειάζεται ακόμη",
            "subtitle": "Κλειδωμένες απαιτήσεις ακεραιότητας, ελάχιστου δείγματος και απόδοσης.",
            "dataset": "gates",
            "sourceId": "forward_gates",
            "defaultSort": {"field": "category", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "category", "label": "Κατηγορία", "type": "text"},
                {"field": "gate", "label": "Έλεγχος", "type": "text"},
                {"field": "status", "label": "Κατάσταση", "type": "text"},
                {"field": "actual", "label": "Τρέχουσα τιμή", "type": "text"},
                {"field": "requirement", "label": "Απαίτηση", "type": "text"},
            ],
        },
        {
            "id": "risk_status",
            "title": "Account-level risk policy",
            "subtitle": "Ημερήσια/εβδομαδιαία ζημιά και συντηρητική εκτίμηση ανοικτού exposure.",
            "dataset": "risk_status",
            "sourceId": "latest_overview",
            "defaultSort": {"field": "bot", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "bot", "label": "Bot", "type": "text"},
                {"field": "policy_id", "label": "Policy", "type": "text"},
                {"field": "new_entries_allowed", "label": "Νέες είσοδοι", "type": "text"},
                {"field": "daily_loss_pct", "label": "Ημερήσια ζημιά (%)", "format": "number"},
                {"field": "weekly_loss_pct", "label": "Εβδομαδιαία ζημιά (%)", "format": "number"},
                {"field": "open_stake_pct", "label": "Open stake (%)", "format": "number"},
                {"field": "failed_checks", "label": "Αποτυχημένοι έλεγχοι", "type": "text"},
            ],
        },
        {
            "id": "stress_results",
            "title": "Execution stress ανά market regime",
            "subtitle": "Moderate και severe πρόσθετα κόστη πάνω στα κλειδωμένα trade exports.",
            "dataset": "stress_results",
            "sourceId": "execution_stress",
            "defaultSort": {"field": "split", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "split", "label": "Περίοδος", "type": "text"},
                {"field": "scenario", "label": "Σενάριο", "type": "text"},
                {"field": "status", "label": "Κατάσταση", "type": "text"},
                {"field": "trades", "label": "Trades", "format": "number"},
                {"field": "net_profit_usdt", "label": "Net PnL (USDT)", "format": "number"},
                {"field": "profit_factor", "label": "PF", "format": "number"},
                {"field": "realized_drawdown_pct", "label": "Realized DD (%)", "format": "number"},
            ],
        },
        {
            "id": "recent_alerts",
            "title": "Πρόσφατες ειδοποιήσεις",
            "subtitle": "Αλλαγές κατάστασης, νέα trades, προειδοποιήσεις ασφαλείας και recoveries χωρίς διπλοεγγραφές.",
            "dataset": "alerts",
            "sourceId": "alert_journal",
            "defaultSort": {"field": "timestamp_utc", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "timestamp_utc", "label": "Ώρα UTC", "type": "date"},
                {"field": "severity", "label": "Σοβαρότητα", "type": "text"},
                {"field": "event_type", "label": "Συμβάν", "type": "text"},
                {"field": "bot", "label": "Bot", "type": "text"},
                {"field": "message", "label": "Μήνυμα", "type": "text"},
            ],
        },
    ]
    operational_card_ids = [
        "forward_decision",
        "validated_days",
        "snapshot_coverage",
        "snapshot_freshness",
        "backup_freshness",
        "live_readiness",
        "execution_stress",
        "v1_entry_guard",
        "v2r_entry_guard",
    ]
    performance_card_ids = [
        "v1_closed",
        "v2r_closed",
        "v2r_net_profit",
        "v2r_profit_factor",
        "v2r_drawdown",
    ]
    return {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Κέντρο Ελέγχου Trading Bot",
            "description": "Απλή read-only εικόνα για λειτουργία, forward sample, V1/V2R απόδοση, risk gates και alerts.",
            "generatedAt": generated_at,
            "filters": [
                {
                    "id": "bot_filter",
                    "label": "Bot στα γραφήματα",
                    "dataset": "history",
                    "field": "bot",
                    "includeAll": True,
                    "targets": [{"dataset": "history", "field": "bot"}],
                }
            ],
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": [
                {
                    "id": "current_status",
                    "type": "markdown",
                    "sourceId": "forward_decision",
                    "body": (
                        "## Τρέχουσα forward κατάσταση\n\n"
                        f"**Κατάσταση: {decision_label}.** "
                        "Το live trading και η αυτόματη προώθηση στρατηγικής παραμένουν απενεργοποιημένα."
                    ),
                },
                {
                    "id": "operations_heading",
                    "type": "markdown",
                    "body": "## Λειτουργία και ασφάλεια\n\nΤα βασικά στοιχεία που πρέπει να είναι πράσινα πριν εξετάσουμε οποιαδήποτε απόδοση.",
                },
                {"id": "operations_metrics", "type": "metric-strip", "cardIds": operational_card_ids},
                {
                    "id": "performance_heading",
                    "type": "markdown",
                    "body": "## Forward απόδοση\n\nΣύγκριση του V1 control με το V2R candidate. Οι μηδενικές τιμές σημαίνουν ότι δεν έχει κλείσει ακόμη trade.",
                },
                {"id": "performance_metrics", "type": "metric-strip", "cardIds": performance_card_ids},
                {"id": "closed_trades_chart", "type": "chart", "chartId": "closed_trade_trend", "layout": "full"},
                {"id": "profit_chart", "type": "chart", "chartId": "net_profit_trend", "layout": "full"},
                {"id": "comparison_table", "type": "table", "tableId": "bot_comparison", "layout": "full"},
                {"id": "gates_table", "type": "table", "tableId": "gate_status", "layout": "full"},
                {"id": "risk_table", "type": "table", "tableId": "risk_status", "layout": "full"},
                {"id": "stress_table", "type": "table", "tableId": "stress_results", "layout": "full"},
                {"id": "alerts_table", "type": "table", "tableId": "recent_alerts", "layout": "full"},
                {
                    "id": "methodology",
                    "type": "markdown",
                    "sourceId": "forward_decision",
                    "body": (
                        "## Όριο απόφασης\n\n"
                        "Το review απαιτεί τον κλειδωμένο ελάχιστο χρόνο, το απαιτούμενο δείγμα trades και επιτυχία όλων των integrity/performance gates. "
                        "Ακόμη και το review-ready δεν αποτελεί άδεια για live trading ούτε εγγύηση κέρδους."
                    ),
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "overview": overview,
                "history": history,
                "bot_compare": bot_compare,
                "gates": gates,
                "risk_status": risk_status,
                "stress_results": stress_results,
                "alerts": alerts,
            },
        },
        "sources": sources,
    }


def build_and_write(reports_dir: Path, output_path: Path) -> dict[str, Any]:
    artifact = build_artifact(reports_dir)
    atomic_write_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", default="user_data/reports")
    parser.add_argument(
        "--output", default="user_data/dashboard/forward_dashboard_artifact.json"
    )
    args = parser.parse_args()
    artifact = build_and_write(Path(args.reports_dir), Path(args.output))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "generated_at": artifact["snapshot"]["generatedAt"],
                "datasets": len(artifact["snapshot"]["datasets"]),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
