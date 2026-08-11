#!/usr/bin/env python3
"""Local dead-man watchdog for forward-monitor snapshot freshness."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forward_dashboard_artifact import build_and_write
from monitor_forward_dry_runs import (
    MAX_FUTURE_CLOCK_SKEW_SECONDS,
    SCHEMA_VERSION,
    STALE_MONITOR_SECONDS,
    alert_event,
    append_json_lines,
    atomic_write_json,
    deliver_alert_webhook,
    iso_utc,
    parse_datetime,
)


def load_previous(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def send_deadman_heartbeat(
    heartbeat_url: str | None,
    *,
    snapshot_fresh: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Send a secret-safe success ping without ever returning the configured URL."""
    if not heartbeat_url:
        return {"status": "DISABLED"}
    parsed = urllib.parse.urlparse(heartbeat_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return {"status": "INVALID_URL", "requirement": "absolute HTTPS URL"}
    if not snapshot_fresh:
        return {"status": "SUPPRESSED_STALE"}
    request = urllib.request.Request(
        heartbeat_url,
        headers={"Accept": "text/plain", "User-Agent": "forward-watchdog/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        return {"status": "HTTP_ERROR", "http_status": int(exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "NETWORK_ERROR"}
    if 200 <= status_code < 300:
        return {"status": "DELIVERED", "http_status": status_code}
    return {"status": "HTTP_ERROR", "http_status": status_code}


def evaluate_heartbeat_alerts(
    delivery: dict[str, Any],
    now: datetime,
    previous: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    failed_statuses = {"INVALID_URL", "HTTP_ERROR", "NETWORK_ERROR"}
    failed = delivery.get("status") in failed_statuses
    previously_failed = previous.get("heartbeat_failed") is True
    alerts: list[dict[str, Any]] = []
    if failed and not previously_failed:
        alerts.append(
            alert_event(
                iso_utc(now),
                "WARNING",
                "DEADMAN_HEARTBEAT_FAILED",
                "The external dead-man heartbeat could not be delivered.",
                actual=delivery.get("status"),
            )
        )
    elif not failed and previously_failed and delivery.get("status") == "DELIVERED":
        alerts.append(
            alert_event(
                iso_utc(now),
                "INFO",
                "DEADMAN_HEARTBEAT_RECOVERED",
                "External dead-man heartbeat delivery recovered.",
                actual=delivery.get("status"),
            )
        )
    return alerts, failed


def evaluate_freshness(
    snapshot_utc: Any,
    now: datetime,
    stale_seconds: int,
    previous: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    snapshot_time = parse_datetime(snapshot_utc)
    age_seconds = (now - snapshot_time).total_seconds() if snapshot_time else None
    if snapshot_time is None:
        status = "UNAVAILABLE"
        stale = True
    elif age_seconds is not None and age_seconds < -MAX_FUTURE_CLOCK_SKEW_SECONDS:
        status = "CLOCK_SKEW"
        stale = True
    elif age_seconds is not None and age_seconds > stale_seconds:
        status = "STALE"
        stale = True
    else:
        status = "FRESH"
        stale = False

    alerts: list[dict[str, Any]] = []
    previously_initialized = "stale" in previous
    previously_stale = previous.get("stale") is True
    if stale and (not previously_initialized or not previously_stale):
        message = (
            "The scheduled monitor snapshot is older than the five-hour freshness limit."
            if status == "STALE"
            else "The scheduled monitor snapshot is unavailable or has invalid clock timing."
        )
        alerts.append(
            alert_event(
                iso_utc(now),
                "CRITICAL",
                "STALE_MONITOR",
                message,
                actual=age_seconds,
                threshold=stale_seconds,
            )
        )
    elif not stale and previously_stale:
        alerts.append(
            alert_event(
                iso_utc(now),
                "INFO",
                "STALE_MONITOR_RECOVERED",
                "Scheduled monitor snapshots are fresh again.",
                actual=age_seconds,
                threshold=stale_seconds,
            )
        )
    result = {
        "schema_version": SCHEMA_VERSION,
        "checked_utc": iso_utc(now),
        "snapshot_utc": iso_utc(snapshot_time) if snapshot_time else None,
        "snapshot_age_seconds": age_seconds,
        "stale_after_seconds": stale_seconds,
        "status": status,
        "stale": stale,
    }
    next_state = {
        "schema_version": SCHEMA_VERSION,
        "last_checked_utc": iso_utc(now),
        "last_snapshot_utc": result["snapshot_utc"],
        "last_status": status,
        "stale": stale,
    }
    return result, alerts, next_state


def check_once(args: argparse.Namespace, now: datetime | None = None) -> dict[str, Any]:
    observed_at = now or datetime.now(timezone.utc)
    reports_dir = Path(args.reports_dir)
    latest_path = reports_dir / "forward_monitor_latest.json"
    snapshot_utc = None
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            snapshot_utc = latest.get("snapshot_utc") if isinstance(latest, dict) else None
        except (OSError, json.JSONDecodeError):
            snapshot_utc = None
    state_path = reports_dir / "forward_watchdog_state.json"
    previous = load_previous(state_path)
    result, alerts, next_state = evaluate_freshness(
        snapshot_utc, observed_at, args.stale_seconds, previous
    )
    heartbeat = send_deadman_heartbeat(
        os.environ.get("FORWARD_HEARTBEAT_URL") or None,
        snapshot_fresh=not result["stale"],
        timeout_seconds=args.timeout_seconds,
    )
    heartbeat_alerts, heartbeat_failed = evaluate_heartbeat_alerts(
        heartbeat, observed_at, previous
    )
    alerts.extend(heartbeat_alerts)
    next_state["heartbeat_failed"] = heartbeat_failed
    delivery = deliver_alert_webhook(
        os.environ.get("FORWARD_ALERT_WEBHOOK_URL") or None,
        result["checked_utc"],
        alerts,
        args.timeout_seconds,
    )
    result["deadman_heartbeat"] = heartbeat
    result["new_alert_count"] = len(alerts)
    result["webhook_delivery"] = delivery
    atomic_write_json(state_path, next_state)
    append_json_lines(reports_dir / "forward_watchdog_alerts.jsonl", alerts)
    atomic_write_json(
        reports_dir / "forward_watchdog_latest.json",
        {**result, "alerts": alerts},
    )
    dashboard_output = Path(args.dashboard_output)
    if alerts or not dashboard_output.exists():
        try:
            build_and_write(reports_dir, dashboard_output)
            result["dashboard_artifact_status"] = "READY"
        except Exception as exc:
            result["dashboard_artifact_status"] = "ERROR"
            result["dashboard_artifact_error"] = f"{type(exc).__name__}: {exc}"
    else:
        result["dashboard_artifact_status"] = "NOT_REQUIRED"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", default="user_data/reports")
    parser.add_argument(
        "--dashboard-output",
        default="user_data/dashboard/forward_dashboard_artifact.json",
    )
    parser.add_argument("--stale-seconds", type=int, default=STALE_MONITOR_SECONDS)
    parser.add_argument("--loop-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stale_seconds <= 0 or args.loop_seconds < 0 or args.timeout_seconds <= 0:
        raise SystemExit("watchdog intervals and timeout must be valid positive values")
    while True:
        try:
            result = check_once(args)
            print(json.dumps(result, separators=(",", ":"), allow_nan=False), flush=True)
            for alert in json.loads(
                (Path(args.reports_dir) / "forward_watchdog_latest.json").read_text(
                    encoding="utf-8"
                )
            ).get("alerts", []):
                print(
                    "ALERT " + json.dumps(alert, separators=(",", ":"), allow_nan=False),
                    flush=True,
                )
            exit_code = 0
        except Exception as exc:
            print(
                f"forward watchdog error: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            exit_code = 2
        if args.loop_seconds == 0:
            return exit_code
        time.sleep(args.loop_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
