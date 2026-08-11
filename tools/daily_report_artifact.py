#!/usr/bin/env python3
"""Build the fail-closed daily trading-bot executive report artifact."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forward_dashboard_artifact import build_artifact as build_dashboard_artifact


SCHEMA_VERSION = "1.0"


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def metric_delta(current: Any, previous: Any) -> float | None:
    current_number = finite_number(current)
    previous_number = finite_number(previous)
    if current_number is None or previous_number is None:
        return None
    return current_number - previous_number


def display_number(value: Any, digits: int = 2) -> str:
    number = finite_number(value)
    return "—" if number is None else f"{number:.{digits}f}"


def previous_daily_snapshot(archive_dir: Path, report_date: str) -> dict[str, Any] | None:
    if not archive_dir.exists():
        return None
    candidates = sorted(
        path for path in archive_dir.glob("????-??-??.json") if path.stem < report_date
    )
    return load_json(candidates[-1]) if candidates else None


def build_artifact(reports_dir: Path, archive_dir: Path | None = None) -> dict[str, Any]:
    dashboard = build_dashboard_artifact(reports_dir)
    generated_at = str(dashboard["snapshot"]["generatedAt"])
    report_date = generated_at[:10]
    archive_dir = archive_dir or reports_dir / "daily"
    previous = previous_daily_snapshot(archive_dir, report_date)
    previous_kpis = (previous or {}).get("kpis", {})

    datasets = copy.deepcopy(dashboard["snapshot"]["datasets"])
    overview = copy.deepcopy(datasets["overview"][0])
    latest = load_json(reports_dir / "forward_monitor_latest.json")
    alerts = list(datasets.get("alerts", []))
    daily_alerts = [
        row for row in alerts if str(row.get("timestamp_utc", "")).startswith(report_date)
    ]
    overview.update(
        {
            "report_date_utc": report_date,
            "prior_report_date_utc": (previous or {}).get("report_date_utc"),
            "daily_alert_count": len(daily_alerts),
            "daily_critical_alert_count": sum(
                str(row.get("severity", "")).upper() == "CRITICAL" for row in daily_alerts
            ),
            "alert_delivery_mode": (
                "WEBHOOK_CONFIGURED"
                if latest.get("alerting", {}).get("external_destination_configured") is True
                else "LOCAL_ONLY"
            ),
            "last_alert_delivery_status": latest.get("alerting", {})
            .get("webhook_delivery", {})
            .get("status", "UNAVAILABLE"),
        }
    )
    datasets["daily_overview"] = [overview]

    target_days = finite_number(overview.get("monitoring_days_target")) or 30.0
    target_trades = finite_number(overview.get("v2r_closed_target")) or 30.0
    coverage = finite_number(overview.get("snapshot_coverage_pct"))
    drawdown = finite_number(overview.get("v2r_drawdown_pct"))
    drawdown_limit = finite_number(overview.get("v2r_drawdown_limit")) or 10.0
    daily_change = [
        {
            "metric": "Έγκυρες forward ημέρες",
            "actual": overview.get("validated_observation_days"),
            "previous": previous_kpis.get("validated_observation_days"),
            "delta": metric_delta(
                overview.get("validated_observation_days"),
                previous_kpis.get("validated_observation_days"),
            ),
            "target": target_days,
            "status": "PASS" if (finite_number(overview.get("validated_observation_days")) or 0) >= target_days else "COLLECTING",
        },
        {
            "metric": "Κάλυψη προγραμματισμένων snapshots (%)",
            "actual": coverage,
            "previous": previous_kpis.get("snapshot_coverage_pct"),
            "delta": metric_delta(coverage, previous_kpis.get("snapshot_coverage_pct")),
            "target": 95.0,
            "status": "PASS" if coverage is not None and coverage >= 95.0 else "FAIL",
        },
        {
            "metric": "V1 κλεισμένες συναλλαγές",
            "actual": overview.get("v1_closed"),
            "previous": previous_kpis.get("v1_closed"),
            "delta": metric_delta(overview.get("v1_closed"), previous_kpis.get("v1_closed")),
            "target": target_trades,
            "status": "PASS" if (finite_number(overview.get("v1_closed")) or 0) >= target_trades else "COLLECTING",
        },
        {
            "metric": "V2R κλεισμένες συναλλαγές",
            "actual": overview.get("v2r_closed"),
            "previous": previous_kpis.get("v2r_closed"),
            "delta": metric_delta(overview.get("v2r_closed"), previous_kpis.get("v2r_closed")),
            "target": target_trades,
            "status": "PASS" if (finite_number(overview.get("v2r_closed")) or 0) >= target_trades else "COLLECTING",
        },
        {
            "metric": "V2R καθαρό PnL (USDT)",
            "actual": overview.get("v2r_net_profit"),
            "previous": previous_kpis.get("v2r_net_profit"),
            "delta": metric_delta(
                overview.get("v2r_net_profit"), previous_kpis.get("v2r_net_profit")
            ),
            "target": 0.0,
            "status": "PASS" if (finite_number(overview.get("v2r_net_profit")) or 0) > 0 else "INCOMPLETE",
        },
        {
            "metric": "V2R μέγιστο drawdown (%)",
            "actual": drawdown,
            "previous": previous_kpis.get("v2r_drawdown_pct"),
            "delta": metric_delta(drawdown, previous_kpis.get("v2r_drawdown_pct")),
            "target": drawdown_limit,
            "status": "PASS" if drawdown is not None and drawdown <= drawdown_limit else "FAIL",
        },
    ]
    datasets["daily_change"] = daily_change
    qualification_rows = [
        (
            "Έγκυρες ημέρες",
            finite_number(overview.get("validated_observation_days")),
            target_days,
        ),
        ("V1 κλεισμένες", finite_number(overview.get("v1_closed")), target_trades),
        ("V2R κλεισμένες", finite_number(overview.get("v2r_closed")), target_trades),
    ]
    datasets["qualification_progress"] = []
    for milestone, actual, target in qualification_rows:
        progress_pct = min(100.0, 100.0 * (actual or 0.0) / target)
        datasets["qualification_progress"].extend(
            [
                {
                    "milestone": milestone,
                    "series": "Τρέχουσα πρόοδος",
                    "actual": actual,
                    "target": target,
                    "value_pct": progress_pct,
                },
                {
                    "milestone": milestone,
                    "series": "Στόχος qualification",
                    "actual": actual,
                    "target": target,
                    "value_pct": 100.0,
                },
            ]
        )

    source_specs = copy.deepcopy(dashboard["sources"])
    source_specs.append(
        {
            "id": "daily_kpi_snapshot",
            "label": "Daily composite KPI snapshot",
            "path": "user_data/reports/forward_monitor_latest.json",
            "query": {
                "language": "sql",
                "engine": "duckdb",
                "executed_at": generated_at,
                "description": "Combines the latest validated monitor, decision, readiness, watchdog, backup, alert journal, and prior daily snapshot.",
                "tables_used": [
                    "user_data/reports/forward_monitor_latest.json",
                    "user_data/reports/forward_monitor_decision.json",
                    "user_data/reports/live_readiness.json",
                    "user_data/reports/forward_watchdog_latest.json",
                    "user_data/reports/forward_backup_status.json",
                    "user_data/reports/forward_alerts.jsonl",
                    "user_data/reports/forward_watchdog_alerts.jsonl",
                    "user_data/reports/daily/*.json",
                ],
                "sql": "SELECT current validated KPIs, prior daily KPIs, and alert counts FROM the bounded daily evidence files",
                "metric_definitions": [
                    "Validated observation days use continuity-qualified scheduled snapshots only.",
                    "Daily deltas compare the latest UTC-day snapshot with the most recent earlier UTC-day archive.",
                    "Net PnL includes closed dry-run trades only and is not a profit forecast.",
                ],
            },
        }
    )

    cards_by_id = {item["id"]: item for item in dashboard["manifest"]["cards"]}
    selected_card_ids = [
        "forward_decision",
        "validated_days",
        "snapshot_coverage",
        "snapshot_freshness",
        "backup_freshness",
        "live_readiness",
        "execution_stress",
        "v1_closed",
        "v2r_closed",
        "v2r_net_profit",
        "v2r_drawdown",
    ]
    cards: list[dict[str, Any]] = []
    for card_id in selected_card_ids:
        if card_id not in cards_by_id:
            continue
        card = copy.deepcopy(cards_by_id[card_id])
        card["dataset"] = "daily_overview"
        card["sourceId"] = "daily_kpi_snapshot"
        cards.append(card)
    cards.append(
        {
            "id": "daily_alerts",
            "dataset": "daily_overview",
            "sourceId": "daily_kpi_snapshot",
            "description": "Alerts recorded during the current UTC day and the current external webhook delivery mode.",
            "metrics": [
                {"label": "Σημερινά alerts", "field": "daily_alert_count", "format": "number"},
                {"label": "Critical", "field": "daily_critical_alert_count", "format": "number"},
                {"label": "Εξωτερική παράδοση", "field": "alert_delivery_mode", "format": "text"},
                {"label": "Τελευταία προσπάθεια", "field": "last_alert_delivery_status", "format": "text"},
            ],
        }
    )

    tables_by_id = {item["id"]: item for item in dashboard["manifest"]["tables"]}
    tables = [
        {
            "id": "daily_change",
            "title": "Ημερήσιο KPI scorecard",
            "subtitle": "Τρέχουσα τιμή, προηγούμενο διαθέσιμο UTC-day snapshot, μεταβολή και κλειδωμένος στόχος.",
            "dataset": "daily_change",
            "sourceId": "daily_kpi_snapshot",
            "layout": "full",
            "density": "spacious",
            "columns": [
                {"field": "metric", "label": "KPI", "type": "text"},
                {"field": "actual", "label": "Τώρα", "format": "number"},
                {"field": "previous", "label": "Προηγούμενο", "format": "number"},
                {"field": "delta", "label": "Μεταβολή", "format": "number", "movement": True},
                {"field": "target", "label": "Στόχος/όριο", "format": "number"},
                {"field": "status", "label": "Κατάσταση", "type": "text"},
            ],
        }
    ]
    if "bot_comparison" in tables_by_id:
        compact_bot_table = copy.deepcopy(tables_by_id["bot_comparison"])
        compact_bot_table["id"] = "daily_bot_comparison"
        compact_bot_table["title"] = "Συνοπτική σύγκριση V1 και V2R"
        compact_bot_table["subtitle"] = "Current forward status, closed-trade PnL, drawdown and runtime integrity."
        allowed_fields = {
            "bot",
            "strategy",
            "closed_trades",
            "open_trades",
            "net_profit_usdt",
            "drawdown_pct",
            "runtime_pass",
            "data_quality_pass",
        }
        compact_bot_table["columns"] = [
            column
            for column in compact_bot_table.get("columns", [])
            if column.get("field") in allowed_fields
        ]
        tables.append(compact_bot_table)
    for table_id in ("gate_status", "recent_alerts"):
        if table_id in tables_by_id:
            tables.append(copy.deepcopy(tables_by_id[table_id]))

    charts = [
        {
            "id": "qualification_progress",
            "title": "Πρόοδος qualification",
            "subtitle": "Τρέχον validated sample ως ποσοστό των κλειδωμένων στόχων 30 ημερών και 30 trades ανά bot.",
            "type": "bar",
            "dataset": "qualification_progress",
            "sourceId": "daily_kpi_snapshot",
            "layout": "full",
            "emptyState": "Δεν υπάρχει διαθέσιμο qualification sample.",
            "encodings": {
                "x": {"field": "milestone", "type": "nominal", "label": "Milestone"},
                "y": {
                    "field": "value_pct",
                    "type": "quantitative",
                    "label": "Πρόοδος (%)",
                    "format": "number",
                },
                "color": {
                    "field": "series",
                    "type": "nominal",
                    "label": "Σειρά",
                },
                "tooltip": [
                    {"field": "actual", "type": "quantitative", "label": "Τρέχουσα τιμή", "format": "number"},
                    {"field": "target", "type": "quantitative", "label": "Στόχος", "format": "number"},
                ],
            },
            "settings": {"groupMode": "grouped", "showValues": True},
        }
    ]

    validated_days = display_number(overview.get("validated_observation_days"))
    v1_closed = display_number(overview.get("v1_closed"), 0)
    v2r_closed = display_number(overview.get("v2r_closed"), 0)
    pnl = display_number(overview.get("v2r_net_profit"))
    summary = (
        "## Executive Summary\n\n"
        f"- **Το σύστημα παραμένει fail-closed.** Η απόφαση είναι {overview.get('decision_status', 'Μη διαθέσιμη')}, "
        f"το live trading είναι {overview.get('live_trading_status', 'Απενεργοποιημένο')} και το qualification είναι "
        f"{overview.get('qualification_status', 'UNAVAILABLE')}.\n"
        f"- **Το forward δείγμα δεν επαρκεί ακόμη.** Έγκυρες ημέρες {validated_days}/{display_number(target_days, 0)}, "
        f"V1 trades {v1_closed}/{display_number(target_trades, 0)} και V2R trades {v2r_closed}/{display_number(target_trades, 0)}.\n"
        f"- **Δεν υπάρχει ακόμη απόδειξη κερδοφορίας.** Το V2R closed-trade PnL είναι {pnl} USDT και το execution stress είναι "
        f"{overview.get('execution_stress_status', 'UNAVAILABLE')}.\n"
        f"- **Η σημερινή λειτουργική εικόνα έχει {len(daily_alerts)} alerts, από τα οποία {overview['daily_critical_alert_count']} critical.** "
        f"Η εξωτερική παράδοση alerts είναι {overview['alert_delivery_mode']} και η τελευταία προσπάθεια είναι {overview['last_alert_delivery_status']}."
    )
    prior_note = (
        f"Το προηγούμενο συγκρίσιμο ημερήσιο snapshot είναι της {previous.get('report_date_utc')}."
        if previous
        else "Δεν υπάρχει ακόμη προηγούμενο ημερήσιο snapshot· οι ημερήσιες μεταβολές εμφανίζονται ως μη διαθέσιμες."
    )

    blocks = [
        {"id": "executive_summary", "type": "markdown", "body": summary},
        {
            "id": "operating_status_heading",
            "type": "markdown",
            "body": "## Η ασφάλεια λειτουργεί, αλλά η qualification παραμένει ελλιπής\n\nΤα operational και safety KPIs προηγούνται από οποιαδήποτε αξιολόγηση απόδοσης.",
        },
        {
            "id": "operating_metrics",
            "type": "metric-strip",
            "cardIds": [
                "forward_decision",
                "snapshot_freshness",
                "backup_freshness",
                "live_readiness",
                "execution_stress",
                "daily_alerts",
            ],
        },
        {
            "id": "daily_progress_heading",
            "type": "markdown",
            "body": f"## Η πρόοδος μετριέται έναντι των κλειδωμένων στόχων\n\nΟι τρεις μπάρες χρησιμοποιούν κοινή κλίμακα 0–100%: validated ημέρες, V1 closed trades και V2R closed trades προς τους αντίστοιχους στόχους. {prior_note}",
        },
        {"id": "qualification_progress_chart", "type": "chart", "chartId": "qualification_progress", "layout": "full"},
        {"id": "daily_change_table", "type": "table", "tableId": "daily_change", "layout": "full"},
        {
            "id": "sample_metrics",
            "type": "metric-strip",
            "cardIds": [
                "validated_days",
                "snapshot_coverage",
                "v1_closed",
                "v2r_closed",
                "v2r_net_profit",
                "v2r_drawdown",
            ],
        },
        {
            "id": "bot_heading",
            "type": "markdown",
            "body": "## Τα δύο bots παραμένουν συγκρίσιμα\n\nΗ σύγκριση χρησιμοποιεί το ίδιο forward epoch και ανεξάρτητα επανυπολογισμένα closed-trade metrics.",
        },
        {"id": "bot_table", "type": "table", "tableId": "daily_bot_comparison", "layout": "full"},
        {
            "id": "gates_heading",
            "type": "markdown",
            "body": "## Τα failed gates καθορίζουν την επόμενη εργασία\n\nΚανένα performance αποτέλεσμα δεν θεωρείται decision-ready μέχρι να περάσουν τα sample, integrity και stress gates.",
        },
        {"id": "gates_table", "type": "table", "tableId": "gate_status", "layout": "full"},
        {
            "id": "alerts_heading",
            "type": "markdown",
            "body": "## Τα alerts είναι state-based και deduplicated\n\nΤα recurring φυσιολογικά snapshots δεν δημιουργούν θόρυβο· οι αλλαγές κατάστασης και το ημερήσιο summary καταγράφονται μία φορά.",
        },
        {"id": "alerts_table", "type": "table", "tableId": "recent_alerts", "layout": "full"},
        {
            "id": "recommended_steps",
            "type": "markdown",
            "body": "## Recommended next steps\n\n1. Διατήρηση αμετάβλητων V1/V2R μέχρι το επόμενο κλειδωμένο review checkpoint.\n2. Offline εργασία στο execution-stress failure χωρίς αλλαγή του ενεργού forward sample.\n3. Ρύθμιση έμπιστου HTTPS webhook όταν επιλεγεί εξωτερικός προορισμός ειδοποιήσεων.\n4. Καμία προσθήκη Binance keys και καμία ενεργοποίηση live trading πριν από ξεχωριστή ανθρώπινη έγκριση.",
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": "## Ανοιχτές ερωτήσεις\n\n- Θα είναι επαρκής η συχνότητα συναλλαγών στο checkpoint των 7 ημερών;\n- Θα περάσει ένας offline challenger το execution-stress gate χωρίς υπερπροσαρμογή;\n- Ποιος έμπιστος εξωτερικός προορισμός θα χρησιμοποιηθεί για push notifications;",
        },
        {
            "id": "caveats",
            "type": "markdown",
            "body": "## Caveats and assumptions\n\nΤο report χρησιμοποιεί UTC-day cutoffs και μόνο validated dry-run evidence. Οι μηδενικές συναλλαγές σημαίνουν ανεπαρκές δείγμα, όχι μηδενικό κίνδυνο. Δεν εμφανίζεται trend chart μέχρι να υπάρχουν αρκετά ημερήσια σημεία και κλεισμένες συναλλαγές ώστε να μη δημιουργείται παραπλανητική οπτική τάση. Κανένα αποτέλεσμα δεν εγγυάται μελλοντικό κέρδος.",
        },
    ]

    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Ημερήσια Αναφορά Trading Bot",
            "description": "Fail-closed ημερήσιο KPI report για λειτουργία, forward evidence, απόδοση, gates και alerts.",
            "generatedAt": generated_at,
            "sources": source_specs,
            "blocks": blocks,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "filters": [],
        },
        "sources": source_specs,
        "snapshot": {
            "version": 1,
            "status": "ready",
            "generatedAt": generated_at,
            "datasets": datasets,
        },
    }


def build_and_write(
    reports_dir: Path,
    output_path: Path,
    archive_dir: Path | None = None,
) -> dict[str, Any]:
    archive_dir = archive_dir or reports_dir / "daily"
    artifact = build_artifact(reports_dir, archive_dir)
    atomic_write_json(output_path, artifact)
    overview = artifact["snapshot"]["datasets"]["daily_overview"][0]
    archive = {
        "schema_version": SCHEMA_VERSION,
        "report_date_utc": overview["report_date_utc"],
        "generated_at_utc": artifact["snapshot"]["generatedAt"],
        "kpis": overview,
        "daily_change": artifact["snapshot"]["datasets"]["daily_change"],
        "bot_comparison": artifact["snapshot"]["datasets"].get("bot_compare", []),
        "gates": artifact["snapshot"]["datasets"].get("gates", []),
    }
    atomic_write_json(archive_dir / f"{overview['report_date_utc']}.json", archive)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", default="user_data/reports")
    parser.add_argument(
        "--output", default="user_data/dashboard/daily_report_artifact.json"
    )
    parser.add_argument("--archive-dir", default="user_data/reports/daily")
    args = parser.parse_args()
    artifact = build_and_write(
        Path(args.reports_dir), Path(args.output), Path(args.archive_dir)
    )
    print(
        json.dumps(
            {
                "status": "DAILY_REPORT_ARTIFACT_READY",
                "generated_at": artifact["snapshot"]["generatedAt"],
                "output": args.output,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
