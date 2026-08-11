#!/usr/bin/env python3
"""Read-only forward monitor for the V1 and V2R Freqtrade dry-runs."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
PAGE_LIMIT = 500
MIN_MONITORING_DAYS = 30.0
MIN_CLOSED_TRADES = 30
MIN_V2R_PAIRS = 4
MIN_V2R_PROFIT_FACTOR = 1.20
MAX_V2R_DRAWDOWN_PCT = 10.0
MAX_V2R_PF_DEFICIT_VS_V1 = 0.10
V2R_DRAWDOWN_WARNING_PCT = 8.0
EXPECTED_SNAPSHOT_INTERVAL_SECONDS = 14_400
MIN_SNAPSHOT_COVERAGE_RATIO = 0.95
STALE_MONITOR_SECONDS = 18_000
MAX_SNAPSHOT_GAP_SECONDS = 28_800
MAX_BOT_LOOP_AGE_SECONDS = 120
MAX_CANDLE_CLOSE_AGE_SECONDS = 18_000
MAX_FUTURE_CLOCK_SKEW_SECONDS = 30


class MonitorError(RuntimeError):
    """Raised when a monitoring input cannot be trusted."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def first_present(mapping: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorError(f"Cannot read valid JSON config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MonitorError(f"Expected a JSON object in {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_json_lines(path: Path, values: list[dict[str, Any]]) -> None:
    if not values:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")


def load_alert_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def alert_event(
    timestamp_utc: str,
    severity: str,
    event_type: str,
    message: str,
    *,
    bot: str | None = None,
    actual: Any = None,
    threshold: Any = None,
) -> dict[str, Any]:
    return {
        "timestamp_utc": timestamp_utc,
        "severity": severity,
        "event_type": event_type,
        "bot": bot,
        "message": message,
        "actual": actual,
        "threshold": threshold,
    }


def evaluate_alerts(
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    previous: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timestamp = str(snapshot["snapshot_utc"])
    if previous.get("last_snapshot_utc") == timestamp:
        return [], previous

    current_decision = str(decision["decision"])
    bots = snapshot.get("bots", {})
    counts = {
        key: int(bot.get("metrics", {}).get("closed_trades", 0))
        for key, bot in bots.items()
        if bot.get("status") == "OK"
    }
    v2r_drawdown = finite_float(
        bots.get("v2r", {}).get("metrics", {}).get("max_drawdown_pct_of_start_wallet")
    )
    active = {
        "monitoring_error": current_decision == "MONITORING_ERROR",
        "risk_limit_breach": current_decision == "RISK_LIMIT_BREACH",
        "backup_error": snapshot.get("backup", {}).get("status") == "ERROR",
        "v2r_drawdown_warning": (
            v2r_drawdown is not None and v2r_drawdown >= V2R_DRAWDOWN_WARNING_PCT
        ),
        "v2r_drawdown_critical": (
            v2r_drawdown is not None and v2r_drawdown >= MAX_V2R_DRAWDOWN_PCT
        ),
    }
    events: list[dict[str, Any]] = []
    initialized = bool(previous.get("last_snapshot_utc"))
    if not initialized:
        events.append(
            alert_event(
                timestamp,
                "INFO",
                "MONITOR_BASELINE",
                f"Alert baseline initialized with decision {current_decision}.",
            )
        )
    else:
        previous_decision = previous.get("last_decision")
        if previous_decision != current_decision:
            severity = (
                "CRITICAL"
                if current_decision == "MONITORING_ERROR"
                else "INFO"
                if current_decision in {"INSUFFICIENT_FORWARD_SAMPLE", "FORWARD_REVIEW_READY"}
                else "WARNING"
            )
            events.append(
                alert_event(
                    timestamp,
                    severity,
                    "DECISION_CHANGED",
                    f"Forward decision changed from {previous_decision} to {current_decision}.",
                    actual=current_decision,
                )
            )
        previous_counts = previous.get("closed_trades", {})
        for key, count in counts.items():
            old_count = int(previous_counts.get(key, count))
            if count > old_count:
                events.append(
                    alert_event(
                        timestamp,
                        "INFO",
                        "NEW_CLOSED_TRADES",
                        f"{key.upper()} recorded {count - old_count} new closed trade(s); total {count}.",
                        bot=key,
                        actual=count,
                    )
                )

        previous_active = previous.get("active", {})
        if active["monitoring_error"] and not previous_active.get("monitoring_error", False):
            events.append(
                alert_event(
                    timestamp,
                    "CRITICAL",
                    "MONITORING_ERROR_ACTIVE",
                    "A runtime, API, schema, or data-integrity gate is failing.",
                )
            )
        elif not active["monitoring_error"] and previous_active.get("monitoring_error", False):
            events.append(
                alert_event(
                    timestamp,
                    "INFO",
                    "MONITORING_ERROR_RECOVERED",
                    "Runtime and data-integrity monitoring recovered.",
                )
            )

        if active["risk_limit_breach"] and not previous_active.get("risk_limit_breach", False):
            events.append(
                alert_event(
                    timestamp,
                    "CRITICAL",
                    "ACCOUNT_RISK_LIMIT_REACHED",
                    "At least one locked account-level risk limit is blocking new entries.",
                )
            )
        elif not active["risk_limit_breach"] and previous_active.get("risk_limit_breach", False):
            events.append(
                alert_event(
                    timestamp,
                    "INFO",
                    "ACCOUNT_RISK_LIMIT_CLEARED",
                    "All locked account-level entry limits are back inside policy.",
                )
            )
        if active["backup_error"] and not previous_active.get("backup_error", False):
            events.append(
                alert_event(
                    timestamp,
                    "WARNING",
                    "BACKUP_FAILED",
                    "The scheduled forward-state backup failed; trading evidence collection continues.",
                )
            )
        elif not active["backup_error"] and previous_active.get("backup_error", False):
            events.append(
                alert_event(
                    timestamp,
                    "INFO",
                    "BACKUP_RECOVERED",
                    "The forward-state backup process recovered.",
                )
            )

        if active["v2r_drawdown_critical"] and not previous_active.get("v2r_drawdown_critical", False):
            events.append(
                alert_event(
                    timestamp,
                    "CRITICAL",
                    "V2R_DRAWDOWN_LIMIT_REACHED",
                    "V2R reached or exceeded the locked 10% wallet drawdown limit.",
                    bot="v2r",
                    actual=v2r_drawdown,
                    threshold=MAX_V2R_DRAWDOWN_PCT,
                )
            )
        elif (
            active["v2r_drawdown_warning"]
            and not active["v2r_drawdown_critical"]
            and not previous_active.get("v2r_drawdown_warning", False)
        ):
            events.append(
                alert_event(
                    timestamp,
                    "WARNING",
                    "V2R_DRAWDOWN_WARNING",
                    "V2R reached the 8% early-warning drawdown level.",
                    bot="v2r",
                    actual=v2r_drawdown,
                    threshold=V2R_DRAWDOWN_WARNING_PCT,
                )
            )
        if (
            not active["v2r_drawdown_warning"]
            and previous_active.get("v2r_drawdown_warning", False)
        ):
            events.append(
                alert_event(
                    timestamp,
                    "INFO",
                    "V2R_DRAWDOWN_WARNING_CLEARED",
                    "V2R drawdown is below the 8% early-warning level.",
                    bot="v2r",
                    actual=v2r_drawdown,
                    threshold=V2R_DRAWDOWN_WARNING_PCT,
                )
            )

    for event in snapshot.get("monitoring", {}).get("continuity_events", []):
        events.append(
            alert_event(
                timestamp,
                str(event.get("severity", "INFO")),
                str(event.get("event_type", "CONTINUITY_EVENT")),
                str(event.get("message", "Continuity state changed.")),
                bot=event.get("bot"),
                actual=event.get("actual"),
                threshold=event.get("threshold"),
            )
        )

    daily_summary_date = timestamp[:10]
    if previous.get("last_daily_summary_date") != daily_summary_date:
        continuity = snapshot.get("monitoring", {}).get("continuity", {})
        v2r_metrics = bots.get("v2r", {}).get("metrics", {})
        events.append(
            alert_event(
                timestamp,
                "INFO",
                "DAILY_FORWARD_SUMMARY",
                f"Daily forward summary: decision={current_decision}, "
                f"validated_days={finite_float(continuity.get('validated_observation_days'))}, "
                f"V1_closed={counts.get('v1', 0)}, V2R_closed={counts.get('v2r', 0)}.",
                actual={
                    "decision": current_decision,
                    "validated_observation_days": finite_float(
                        continuity.get("validated_observation_days")
                    ),
                    "snapshot_coverage_ratio": finite_float(
                        continuity.get("coverage_ratio")
                    ),
                    "v1_closed_trades": counts.get("v1", 0),
                    "v2r_closed_trades": counts.get("v2r", 0),
                    "v2r_net_profit_usdt": finite_float(
                        v2r_metrics.get("net_profit_abs")
                    ),
                    "v2r_drawdown_pct": v2r_drawdown,
                },
                threshold={
                    "minimum_validated_days": MIN_MONITORING_DAYS,
                    "minimum_closed_trades_per_bot": MIN_CLOSED_TRADES,
                    "maximum_v2r_drawdown_pct": MAX_V2R_DRAWDOWN_PCT,
                },
            )
        )

    next_state = {
        "schema_version": SCHEMA_VERSION,
        "last_snapshot_utc": timestamp,
        "last_daily_summary_date": daily_summary_date,
        "last_decision": current_decision,
        "closed_trades": counts,
        "active": active,
    }
    return events, next_state


def deliver_alert_webhook(
    url: str | None,
    snapshot_utc: str,
    alerts: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    if not alerts:
        return {"status": "NO_NEW_ALERTS", "delivered": 0}
    if not url:
        return {"status": "LOCAL_ONLY", "delivered": 0}
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"status": "FAILED", "delivered": 0, "error": "InvalidWebhookUrl"}

    headers = {"User-Agent": "trading-forward-monitor/1.0"}
    ntfy_topic = parsed.path.strip("/")
    if parsed.hostname == "ntfy.sh" and (
        not ntfy_topic
        or "/" in ntfy_topic
        or len(ntfy_topic) > 64
        or not all(character.isalnum() or character in "_-" for character in ntfy_topic)
    ):
        return {"status": "FAILED", "delivered": 0, "error": "InvalidNtfyTopic"}

    if parsed.hostname == "ntfy.sh":
        severity_rank = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
        highest = max(
            (str(item.get("severity", "INFO")).upper() for item in alerts),
            key=lambda item: severity_rank.get(item, 0),
        )
        lines = [
            f"{str(item.get('severity', 'INFO')).upper()} | "
            f"{item.get('event_type', 'ALERT')}: {item.get('message', '')}"
            for item in alerts
        ]
        message = f"Snapshot: {snapshot_utc}\n" + "\n".join(lines)
        body = message[:3900].encode("utf-8")
        headers.update(
            {
                "Content-Type": "text/plain; charset=utf-8",
                "X-Title": "Trading Bot Alert",
                "X-Priority": (
                    "max" if highest == "CRITICAL" else "high" if highest == "WARNING" else "default"
                ),
                "X-Tags": "warning,chart_with_upwards_trend",
            }
        )
    else:
        body = json.dumps(
            {
                "source": "trading-forward-monitor",
                "snapshot_utc": snapshot_utc,
                "alerts": alerts,
            },
            allow_nan=False,
        ).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return {
            "status": "FAILED",
            "delivered": 0,
            "error": type(exc).__name__,
        }
    return {
        "status": "DELIVERED" if 200 <= status_code < 300 else "FAILED",
        "delivered": len(alerts) if 200 <= status_code < 300 else 0,
        "http_status": status_code,
    }


def api_credentials(base_config: dict[str, Any]) -> tuple[str, str]:
    api_server = base_config.get("api_server")
    if not isinstance(api_server, dict):
        raise MonitorError("Base config has no api_server object")
    username = api_server.get("username")
    password = api_server.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise MonitorError("API username/password are missing from the base config")
    return username, password


def local_exchange_credentials_empty(*configs: dict[str, Any]) -> bool:
    for config in configs:
        exchange = config.get("exchange", {})
        if not isinstance(exchange, dict):
            return False
        for key_name in ("key", "secret"):
            value = exchange.get(key_name)
            if value not in (None, ""):
                return False
    return True


def validate_risk_policy(policy: dict[str, Any]) -> dict[str, Any]:
    limits = policy.get("limits")
    if not isinstance(limits, dict):
        raise MonitorError("Risk policy has no limits object")
    required = (
        "maximum_daily_realized_loss_pct",
        "maximum_weekly_realized_loss_pct",
        "maximum_wallet_drawdown_pct",
        "maximum_total_open_stake_pct",
        "maximum_open_trades",
    )
    for name in required:
        value = finite_float(limits.get(name))
        if value is None or value <= 0:
            raise MonitorError(f"Risk policy limit {name} must be positive")
    live_launch = policy.get("live_launch")
    if not isinstance(live_launch, dict) or live_launch.get("authorized") is not False:
        raise MonitorError("Risk policy must keep live launch explicitly unauthorized")
    return policy


def expected_bot_config(
    base: dict[str, Any], override: dict[str, Any], strategy: str
) -> dict[str, Any]:
    def pick(name: str, default: Any = None) -> Any:
        return override.get(name, base.get(name, default))

    wallet = finite_float(pick("dry_run_wallet"))
    if wallet is None or wallet <= 0:
        raise MonitorError(f"Invalid dry_run_wallet for {strategy}")
    override_exchange = override.get("exchange", {})
    base_exchange = base.get("exchange", {})
    pair_whitelist = (
        override_exchange.get("pair_whitelist")
        if isinstance(override_exchange, dict)
        else None
    ) or (base_exchange.get("pair_whitelist") if isinstance(base_exchange, dict) else None)
    if not isinstance(pair_whitelist, list) or not pair_whitelist:
        raise MonitorError(f"No pair_whitelist configured for {strategy}")
    return {
        "strategy": strategy,
        "dry_run": True,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "short_allowed": True,
        "state": "RUNNING",
        "starting_wallet": wallet,
        "stake_currency": pick("stake_currency"),
        "stake_amount": finite_float(pick("stake_amount")),
        "credential_free": local_exchange_credentials_empty(base, override),
        "pair_whitelist": [str(pair) for pair in pair_whitelist],
    }


def api_get_json(
    base_url: str,
    endpoint: str,
    username: str,
    password: str,
    timeout_seconds: float,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/v1/" + endpoint.lstrip("/")
    if query:
        url += "?" + urllib.parse.urlencode(query)
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MonitorError(f"GET {endpoint} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise MonitorError(f"GET {endpoint} failed: {exc.reason}") from exc
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MonitorError(f"GET {endpoint} returned no valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MonitorError(f"GET {endpoint} did not return a JSON object")
    return payload


def fetch_all_trades(
    base_url: str,
    username: str,
    password: str,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], int]:
    trades: list[dict[str, Any]] = []
    offset = 0
    reported_total = 0
    for _ in range(10_000):
        payload = api_get_json(
            base_url,
            "trades",
            username,
            password,
            timeout_seconds,
            {"limit": PAGE_LIMIT, "offset": offset, "order_by_id": "true"},
        )
        page = payload.get("trades")
        if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
            raise MonitorError("GET trades response has an invalid trades list")
        total_value = payload.get("total_trades", payload.get("trades_count"))
        if isinstance(total_value, bool) or not isinstance(total_value, (int, float)):
            raise MonitorError("GET trades response has no numeric total_trades")
        reported_total = int(total_value)
        trades.extend(page)
        offset += len(page)
        if offset >= reported_total:
            break
        if not page:
            raise MonitorError("GET trades pagination stopped before total_trades")
    else:
        raise MonitorError("GET trades pagination exceeded the safety limit")
    return trades, reported_total


def fetch_market_data_freshness(
    base_url: str,
    username: str,
    password: str,
    timeout_seconds: float,
    pairs: list[str],
    timeframe: str,
    observed_at: datetime,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for pair in pairs:
        payload = api_get_json(
            base_url,
            "pair_candles",
            username,
            password,
            timeout_seconds,
            {"pair": pair, "timeframe": timeframe, "limit": 2},
        )
        columns = payload.get("columns")
        rows = payload.get("data")
        timeframe_ms = finite_float(payload.get("timeframe_ms"))
        if not isinstance(columns, list) or "date" not in columns:
            raise MonitorError(f"pair_candles for {pair} has no date column")
        if not isinstance(rows, list) or not rows:
            raise MonitorError(f"pair_candles for {pair} has no candle rows")
        last_row = rows[-1]
        if isinstance(last_row, dict):
            candle_open = parse_datetime(last_row.get("date"))
        elif isinstance(last_row, list):
            date_index = columns.index("date")
            candle_open = parse_datetime(last_row[date_index] if date_index < len(last_row) else None)
        else:
            candle_open = None
        if candle_open is None or timeframe_ms is None or timeframe_ms <= 0:
            raise MonitorError(f"pair_candles for {pair} has invalid candle time metadata")
        candle_close = candle_open + timedelta(milliseconds=timeframe_ms)
        age_seconds = (observed_at - candle_close).total_seconds()
        fresh = (
            age_seconds <= MAX_CANDLE_CLOSE_AGE_SECONDS
            and age_seconds >= -MAX_FUTURE_CLOCK_SKEW_SECONDS
        )
        results.append(
            {
                "pair": pair,
                "latest_completed_candle_open_utc": iso_utc(candle_open),
                "latest_completed_candle_close_utc": iso_utc(candle_close),
                "candle_close_age_seconds": age_seconds,
                "fresh": fresh,
            }
        )
    ages = [item["candle_close_age_seconds"] for item in results]
    return {
        "timeframe": timeframe,
        "pairs_checked": len(results),
        "all_pairs_fresh": all(item["fresh"] for item in results),
        "maximum_candle_close_age_seconds": max(ages) if ages else None,
        "pair_results": results,
    }


def is_closed_trade(trade: dict[str, Any]) -> bool:
    is_open = trade.get("is_open")
    if is_open is True:
        return False
    if is_open is False or is_open == 0:
        return True
    return first_present(trade, ("close_date", "close_timestamp")) is not None


def trade_profit_abs(trade: dict[str, Any]) -> float | None:
    return finite_float(
        first_present(trade, ("profit_abs", "close_profit_abs", "realized_profit"))
    )


def trade_profit_ratio(trade: dict[str, Any]) -> float | None:
    direct = finite_float(
        first_present(trade, ("profit_ratio", "close_profit", "realized_profit_ratio"))
    )
    if direct is not None:
        return direct
    percent = finite_float(trade.get("profit_pct"))
    return percent / 100.0 if percent is not None else None


def trade_close_time(trade: dict[str, Any]) -> datetime | None:
    return parse_datetime(first_present(trade, ("close_date", "close_timestamp")))


def trade_side(trade: dict[str, Any]) -> str:
    direction = trade.get("trade_direction")
    if isinstance(direction, str) and direction.lower() in {"long", "short"}:
        return direction.lower()
    is_short = trade.get("is_short")
    if is_short is True:
        return "short"
    if is_short is False:
        return "long"
    return "unknown"


def compute_trade_metrics(
    trades: list[dict[str, Any]], starting_wallet: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    closed = [trade for trade in trades if is_closed_trade(trade)]
    open_count = len(trades) - len(closed)
    missing = {name: 0 for name in ("trade_id", "pair", "close_time", "profit_abs", "profit_ratio")}
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    normalized: list[tuple[datetime | None, str, float, float | None, str, str]] = []

    for index, trade in enumerate(closed):
        raw_id = first_present(trade, ("trade_id", "id"))
        trade_id = str(raw_id) if raw_id is not None else f"missing-{index}"
        if raw_id is None:
            missing["trade_id"] += 1
        elif trade_id in seen_ids:
            duplicate_ids.append(trade_id)
        else:
            seen_ids.add(trade_id)

        pair = trade.get("pair")
        if not isinstance(pair, str) or not pair:
            missing["pair"] += 1
            pair = "UNKNOWN"
        close_time = trade_close_time(trade)
        if close_time is None:
            missing["close_time"] += 1
        profit_abs = trade_profit_abs(trade)
        if profit_abs is None:
            missing["profit_abs"] += 1
        profit_ratio = trade_profit_ratio(trade)
        if profit_ratio is None:
            missing["profit_ratio"] += 1
        if profit_abs is not None:
            normalized.append((close_time, trade_id, profit_abs, profit_ratio, pair, trade_side(trade)))

    normalized.sort(
        key=lambda row: (
            row[0].timestamp() if row[0] is not None else float("inf"),
            row[1],
        )
    )
    profits = [row[2] for row in normalized]
    ratios = [row[3] for row in normalized if row[3] is not None]
    gross_profit = sum(value for value in profits if value > 0)
    gross_loss_abs = -sum(value for value in profits if value < 0)
    net_profit = sum(profits)
    wins = sum(value > 0 for value in profits)
    losses = sum(value < 0 for value in profits)
    breakeven = sum(value == 0 for value in profits)
    profit_factor = gross_profit / gross_loss_abs if gross_loss_abs > 0 else None

    equity = starting_wallet
    high_water = starting_wallet
    max_drawdown_abs = 0.0
    for profit in profits:
        equity += profit
        high_water = max(high_water, equity)
        max_drawdown_abs = max(max_drawdown_abs, high_water - equity)
    return_pct = net_profit / starting_wallet * 100.0
    drawdown_pct = max_drawdown_abs / starting_wallet * 100.0
    return_to_drawdown = return_pct / drawdown_pct if drawdown_pct > 0 else None

    dated = [row[0] for row in normalized if row[0] is not None]
    pairs = sorted({row[4] for row in normalized if row[4] != "UNKNOWN"})
    metrics = {
        "total_trades": len(trades),
        "open_trades": open_count,
        "closed_trades": len(closed),
        "closed_trades_with_valid_profit": len(profits),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": wins / len(profits) if profits else None,
        "gross_profit_abs": gross_profit,
        "gross_loss_abs": gross_loss_abs,
        "net_profit_abs": net_profit,
        "profit_factor": profit_factor,
        "average_profit_ratio": statistics.fmean(ratios) if ratios else None,
        "median_profit_ratio": statistics.median(ratios) if ratios else None,
        "return_pct_of_start_wallet": return_pct,
        "max_drawdown_abs": max_drawdown_abs,
        "max_drawdown_pct_of_start_wallet": drawdown_pct,
        "return_to_drawdown": return_to_drawdown,
        "distinct_pairs": len(pairs),
        "pairs": pairs,
        "long_trades": sum(row[5] == "long" for row in normalized),
        "short_trades": sum(row[5] == "short" for row in normalized),
        "unknown_side_trades": sum(row[5] == "unknown" for row in normalized),
        "first_close_utc": iso_utc(min(dated)) if dated else None,
        "last_close_utc": iso_utc(max(dated)) if dated else None,
        "starting_wallet": starting_wallet,
    }
    required_slots = len(closed) * len(missing)
    missing_slots = sum(missing.values())
    quality = {
        "missing_required_values": missing,
        "required_field_completeness": (
            1.0 - missing_slots / required_slots if required_slots else 1.0
        ),
        "duplicate_trade_ids": sorted(set(duplicate_ids)),
        "duplicates_pass": not duplicate_ids,
        "required_fields_pass": missing_slots == 0,
    }
    return metrics, quality


def compute_account_risk(
    trades: list[dict[str, Any]],
    metrics: dict[str, Any],
    starting_wallet: float,
    current_open_trades: int,
    configured_stake_amount: float | None,
    policy: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    limits = policy["limits"]
    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    daily_profit = 0.0
    weekly_profit = 0.0
    for trade in trades:
        close_time = trade_close_time(trade)
        profit = trade_profit_abs(trade)
        if close_time is None or profit is None or not is_closed_trade(trade):
            continue
        if close_time >= week_start:
            weekly_profit += profit
        if close_time >= day_start:
            daily_profit += profit
    daily_loss_pct = max(0.0, -daily_profit) / starting_wallet * 100.0
    weekly_loss_pct = max(0.0, -weekly_profit) / starting_wallet * 100.0
    conservative_open_stake = (
        current_open_trades * configured_stake_amount
        if configured_stake_amount is not None and configured_stake_amount > 0
        else None
    )
    open_stake_pct = (
        conservative_open_stake / starting_wallet * 100.0
        if conservative_open_stake is not None
        else None
    )
    checks = [
        gate(
            "daily_realized_loss",
            daily_loss_pct < float(limits["maximum_daily_realized_loss_pct"]),
            daily_loss_pct,
            f"< {float(limits['maximum_daily_realized_loss_pct']):g}%",
        ),
        gate(
            "weekly_realized_loss",
            weekly_loss_pct < float(limits["maximum_weekly_realized_loss_pct"]),
            weekly_loss_pct,
            f"< {float(limits['maximum_weekly_realized_loss_pct']):g}%",
        ),
        gate(
            "wallet_drawdown",
            metrics["max_drawdown_pct_of_start_wallet"]
            <= float(limits["maximum_wallet_drawdown_pct"]),
            metrics["max_drawdown_pct_of_start_wallet"],
            f"<= {float(limits['maximum_wallet_drawdown_pct']):g}%",
        ),
        gate(
            "open_trade_count",
            current_open_trades <= int(limits["maximum_open_trades"]),
            current_open_trades,
            f"<= {int(limits['maximum_open_trades'])}",
        ),
        gate(
            "conservative_open_stake",
            open_stake_pct is not None
            and open_stake_pct <= float(limits["maximum_total_open_stake_pct"]),
            open_stake_pct,
            f"<= {float(limits['maximum_total_open_stake_pct']):g}% of starting wallet",
        ),
    ]
    return {
        "policy_id": policy.get("policy_id"),
        "daily_realized_profit_abs": daily_profit,
        "weekly_realized_profit_abs": weekly_profit,
        "daily_realized_loss_pct": daily_loss_pct,
        "weekly_realized_loss_pct": weekly_loss_pct,
        "conservative_open_stake_abs": conservative_open_stake,
        "conservative_open_stake_pct": open_stake_pct,
        "checks": checks,
        "new_entries_allowed": all(item["status"] == "PASS" for item in checks),
    }


def numbers_close(actual: Any, expected: Any) -> bool:
    left = finite_float(actual)
    right = finite_float(expected)
    if left is None or right is None:
        return False
    return math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-8)


def reconcile_profit_api(
    api_profit: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def exact(name: str, api_field: str, metric_field: str) -> None:
        actual = api_profit.get(api_field)
        expected = metrics[metric_field]
        passed = (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and int(actual) == int(expected)
        )
        checks.append(
            {"name": name, "status": "PASS" if passed else "FAIL", "api": actual, "recomputed": expected}
        )

    exact("total_trade_count", "trade_count", "total_trades")
    exact("closed_trade_count", "closed_trade_count", "closed_trades")
    api_wins = api_profit.get("winning_trades")
    recomputed_api_wins = metrics["wins"] + metrics["breakeven"]
    wins_pass = (
        isinstance(api_wins, (int, float))
        and not isinstance(api_wins, bool)
        and int(api_wins) == recomputed_api_wins
    )
    checks.append(
        {
            "name": "winning_trades_including_breakeven",
            "status": "PASS" if wins_pass else "FAIL",
            "api": api_wins,
            "recomputed": recomputed_api_wins,
        }
    )
    exact("losing_trades", "losing_trades", "losses")
    api_closed_profit = api_profit.get("profit_closed_coin")
    checks.append(
        {
            "name": "closed_profit_abs",
            "status": "PASS" if numbers_close(api_closed_profit, metrics["net_profit_abs"]) else "FAIL",
            "api": api_closed_profit,
            "recomputed": metrics["net_profit_abs"],
        }
    )
    recomputed_pf = metrics["profit_factor"]
    if recomputed_pf is None:
        checks.append(
            {
                "name": "profit_factor",
                "status": "NOT_APPLICABLE",
                "api": api_profit.get("profit_factor"),
                "recomputed": None,
            }
        )
    else:
        api_pf = api_profit.get("profit_factor")
        checks.append(
            {
                "name": "profit_factor",
                "status": "PASS" if numbers_close(api_pf, recomputed_pf) else "FAIL",
                "api": api_pf,
                "recomputed": recomputed_pf,
            }
        )
    return {
        "checks": checks,
        "pass": all(item["status"] != "FAIL" for item in checks),
    }


def runtime_checks(
    runtime: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    definitions = (
        ("dry_run", runtime.get("dry_run") is True, runtime.get("dry_run"), True),
        (
            "trading_mode",
            str(runtime.get("trading_mode", "")).lower() == expected["trading_mode"],
            runtime.get("trading_mode"),
            expected["trading_mode"],
        ),
        (
            "margin_mode",
            str(runtime.get("margin_mode", "")).lower() == expected["margin_mode"],
            runtime.get("margin_mode"),
            expected["margin_mode"],
        ),
        (
            "short_allowed",
            runtime.get("short_allowed") is True,
            runtime.get("short_allowed"),
            True,
        ),
        (
            "strategy",
            runtime.get("strategy") == expected["strategy"],
            runtime.get("strategy"),
            expected["strategy"],
        ),
        (
            "state",
            str(runtime.get("state", "")).upper() == expected["state"],
            runtime.get("state"),
            expected["state"],
        ),
        (
            "local_exchange_credentials_empty",
            expected["credential_free"] is True,
            expected["credential_free"],
            True,
        ),
    )
    checks = [
        {"name": name, "status": "PASS" if passed else "FAIL", "actual": actual, "expected": wanted}
        for name, passed, actual, wanted in definitions
    ]
    return {"checks": checks, "pass": all(item["status"] == "PASS" for item in checks)}


def collect_bot(
    key: str,
    base_url: str,
    expected: dict[str, Any],
    username: str,
    password: str,
    timeout_seconds: float,
    observed_at: datetime,
    risk_policy: dict[str, Any],
) -> dict[str, Any]:
    ping = api_get_json(base_url, "ping", username, password, timeout_seconds)
    if str(ping.get("status", "")).lower() != "pong":
        raise MonitorError("GET ping did not return pong")
    runtime = api_get_json(base_url, "show_config", username, password, timeout_seconds)
    health = api_get_json(base_url, "health", username, password, timeout_seconds)
    last_process = parse_datetime(
        first_present(health, ("last_process", "last_process_ts"))
    )
    if last_process is None:
        raise MonitorError("GET health has no valid last_process timestamp")
    bot_loop_age_seconds = (observed_at - last_process).total_seconds()
    bot_loop_fresh = (
        bot_loop_age_seconds <= MAX_BOT_LOOP_AGE_SECONDS
        and bot_loop_age_seconds >= -MAX_FUTURE_CLOCK_SKEW_SECONDS
    )
    timeframe = runtime.get("timeframe")
    if not isinstance(timeframe, str) or not timeframe:
        raise MonitorError("show_config has no valid timeframe")
    market_freshness = fetch_market_data_freshness(
        base_url,
        username,
        password,
        timeout_seconds,
        expected["pair_whitelist"],
        timeframe,
        observed_at,
    )
    api_profit = api_get_json(base_url, "profit", username, password, timeout_seconds)
    api_count = api_get_json(base_url, "count", username, password, timeout_seconds)
    open_count = api_count.get("current")
    if (
        isinstance(open_count, bool)
        or not isinstance(open_count, (int, float))
        or int(open_count) < 0
    ):
        raise MonitorError("GET count response has no valid current trade count")
    trades, reported_total = fetch_all_trades(
        base_url, username, password, timeout_seconds
    )
    if len(trades) != reported_total:
        raise MonitorError(
            f"Paginated trade count {len(trades)} does not match API total {reported_total}"
        )
    metrics, trade_quality = compute_trade_metrics(trades, expected["starting_wallet"])
    # Freqtrade's /trades endpoint is closed-trade history. Open positions come
    # from the read-only /count endpoint and are added to the overall total.
    metrics["open_trades"] = int(open_count)
    metrics["total_trades"] = metrics["closed_trades"] + int(open_count)
    account_risk = compute_account_risk(
        trades,
        metrics,
        expected["starting_wallet"],
        int(open_count),
        expected.get("stake_amount"),
        risk_policy,
        observed_at,
    )
    reconciliation = reconcile_profit_api(api_profit, metrics)
    quality = {
        **trade_quality,
        "api_reconciliation": reconciliation,
        "pass": (
            trade_quality["duplicates_pass"]
            and trade_quality["required_fields_pass"]
            and reconciliation["pass"]
        ),
    }
    validation = runtime_checks(runtime, expected)
    validation["checks"].extend(
        [
            {
                "name": "bot_loop_fresh",
                "status": "PASS" if bot_loop_fresh else "FAIL",
                "actual": bot_loop_age_seconds,
                "expected": f"between -{MAX_FUTURE_CLOCK_SKEW_SECONDS}s and {MAX_BOT_LOOP_AGE_SECONDS}s",
            },
            {
                "name": "all_pair_candles_fresh",
                "status": "PASS" if market_freshness["all_pairs_fresh"] else "FAIL",
                "actual": market_freshness["maximum_candle_close_age_seconds"],
                "expected": f"between -{MAX_FUTURE_CLOCK_SKEW_SECONDS}s and {MAX_CANDLE_CLOSE_AGE_SECONDS}s",
            },
        ]
    )
    validation["pass"] = all(item["status"] == "PASS" for item in validation["checks"])
    return {
        "key": key,
        "status": "OK",
        "api_url": base_url,
        "strategy": runtime.get("strategy"),
        "runtime": {
            "dry_run": runtime.get("dry_run"),
            "trading_mode": runtime.get("trading_mode"),
            "margin_mode": runtime.get("margin_mode"),
            "short_allowed": runtime.get("short_allowed"),
            "state": runtime.get("state"),
            "stake_currency": runtime.get("stake_currency"),
            "stake_amount": runtime.get("stake_amount"),
            "max_open_trades": runtime.get("max_open_trades"),
            "bot_start_date": api_profit.get("bot_start_date"),
            "health_bot_start_utc": first_present(health, ("bot_start", "bot_start_ts")),
            "last_process_utc": iso_utc(last_process),
            "bot_loop_age_seconds": bot_loop_age_seconds,
        },
        "runtime_validation": validation,
        "market_data_freshness": market_freshness,
        "metrics": metrics,
        "account_risk": account_risk,
        "data_quality": quality,
        "api_summary": {
            "trade_count": api_profit.get("trade_count"),
            "closed_trade_count": api_profit.get("closed_trade_count"),
            "open_trade_count": int(open_count),
            "profit_closed_coin": api_profit.get("profit_closed_coin"),
            "profit_factor": api_profit.get("profit_factor"),
            "max_drawdown": api_profit.get("max_drawdown"),
        },
    }


def continuity_eligible(bots: dict[str, Any]) -> bool:
    return all(
        (bots.get(key) or {}).get("status") == "OK"
        and (bots.get(key) or {}).get("runtime_validation", {}).get("pass") is True
        and (bots.get(key) or {}).get("data_quality", {}).get("pass") is True
        for key in ("v1", "v2r")
    )


def continuity_metrics(
    state: dict[str, Any] | None, now: datetime, scheduled: bool
) -> dict[str, Any]:
    if not state:
        return {
            "status": "WAITING_FOR_SCHEDULED_VALID_BASELINE",
            "scheduled_run": scheduled,
            "tracking_started_utc": None,
            "segment_started_utc": None,
            "expected_slots": 0,
            "observed_valid_slots": 0,
            "coverage_ratio": 0.0,
            "validated_observation_days": 0.0,
            "current_segment_calendar_days": 0.0,
            "current_segment_max_gap_seconds": None,
            "last_valid_snapshot_utc": None,
            "last_valid_snapshot_age_seconds": None,
            "major_gap_count": 0,
            "bot_restart_counts": {"v1": 0, "v2r": 0},
            "pass": False,
        }
    segment_start = parse_datetime(state.get("segment_started_utc"))
    last_valid = parse_datetime(state.get("last_valid_snapshot_utc"))
    if segment_start is None or last_valid is None:
        raise MonitorError("Continuity state has invalid segment timestamps")
    elapsed_seconds = max(0.0, (now - segment_start).total_seconds())
    expected_slots = math.floor(elapsed_seconds / EXPECTED_SNAPSHOT_INTERVAL_SECONDS) + 1
    observed_slots = sorted(
        {
            int(slot)
            for slot in state.get("observed_slots", [])
            if isinstance(slot, int) and 0 <= slot < expected_slots
        }
    )
    coverage = min(1.0, len(observed_slots) / expected_slots) if expected_slots else 0.0
    calendar_days = elapsed_seconds / 86_400.0
    last_age = (now - last_valid).total_seconds()
    current_max_gap = finite_float(state.get("current_segment_max_gap_seconds")) or 0.0
    passed = (
        bool(observed_slots)
        and coverage >= MIN_SNAPSHOT_COVERAGE_RATIO
        and current_max_gap <= MAX_SNAPSHOT_GAP_SECONDS
        and last_age <= STALE_MONITOR_SECONDS
        and last_age >= -MAX_FUTURE_CLOCK_SKEW_SECONDS
    )
    if last_age > STALE_MONITOR_SECONDS:
        status = "STALE"
    elif current_max_gap > MAX_SNAPSHOT_GAP_SECONDS:
        status = "MAJOR_GAP"
    elif coverage < MIN_SNAPSHOT_COVERAGE_RATIO:
        status = "DEGRADED_COVERAGE"
    else:
        status = "VALID"
    return {
        "status": status,
        "scheduled_run": scheduled,
        "tracking_started_utc": state.get("tracking_started_utc"),
        "segment_started_utc": state.get("segment_started_utc"),
        "expected_slots": expected_slots,
        "observed_valid_slots": len(observed_slots),
        "coverage_ratio": coverage,
        "validated_observation_days": calendar_days * coverage,
        "current_segment_calendar_days": calendar_days,
        "current_segment_max_gap_seconds": current_max_gap,
        "last_valid_snapshot_utc": state.get("last_valid_snapshot_utc"),
        "last_valid_snapshot_age_seconds": last_age,
        "major_gap_count": int(state.get("major_gap_count", 0)),
        "bot_restart_counts": state.get("bot_restart_counts", {"v1": 0, "v2r": 0}),
        "pass": passed,
    }


def update_continuity(
    previous: dict[str, Any] | None,
    now: datetime,
    *,
    scheduled: bool,
    eligible: bool,
    bot_starts: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    if not scheduled:
        return previous, continuity_metrics(previous, now, scheduled), []
    events: list[dict[str, Any]] = []
    if previous is None:
        if not eligible:
            return None, continuity_metrics(None, now, scheduled), []
        state = {
            "schema_version": SCHEMA_VERSION,
            "tracking_started_utc": iso_utc(now),
            "segment_started_utc": iso_utc(now),
            "last_valid_snapshot_utc": iso_utc(now),
            "last_scheduled_attempt_utc": iso_utc(now),
            "observed_slots": [0],
            "current_segment_max_gap_seconds": 0.0,
            "lifetime_max_gap_seconds": 0.0,
            "major_gap_count": 0,
            "scheduled_attempts": 1,
            "ineligible_attempts": 0,
            "bot_starts": bot_starts,
            "bot_restart_counts": {"v1": 0, "v2r": 0},
        }
        return state, continuity_metrics(state, now, scheduled), []

    state = json.loads(json.dumps(previous))
    state["last_scheduled_attempt_utc"] = iso_utc(now)
    state["scheduled_attempts"] = int(state.get("scheduled_attempts", 0)) + 1
    if not eligible:
        state["ineligible_attempts"] = int(state.get("ineligible_attempts", 0)) + 1
        return state, continuity_metrics(state, now, scheduled), events

    previous_starts = state.get("bot_starts", {})
    restart_counts = state.get("bot_restart_counts", {"v1": 0, "v2r": 0})
    for key, current_start in bot_starts.items():
        old_start = previous_starts.get(key)
        if old_start is not None and current_start is not None and old_start != current_start:
            restart_counts[key] = int(restart_counts.get(key, 0)) + 1
            events.append(
                {
                    "severity": "INFO",
                    "event_type": "BOT_RESTART_DETECTED",
                    "bot": key,
                    "message": f"{key.upper()} bot_start changed; restart count is now {restart_counts[key]}.",
                    "actual": restart_counts[key],
                }
            )
    state["bot_starts"] = bot_starts
    state["bot_restart_counts"] = restart_counts

    last_valid = parse_datetime(state.get("last_valid_snapshot_utc"))
    if last_valid is None:
        raise MonitorError("Continuity state has no valid last snapshot")
    gap_seconds = (now - last_valid).total_seconds()
    state["lifetime_max_gap_seconds"] = max(
        finite_float(state.get("lifetime_max_gap_seconds")) or 0.0,
        gap_seconds,
    )
    if gap_seconds > MAX_SNAPSHOT_GAP_SECONDS:
        state["major_gap_count"] = int(state.get("major_gap_count", 0)) + 1
        state["segment_started_utc"] = iso_utc(now)
        state["observed_slots"] = [0]
        state["current_segment_max_gap_seconds"] = 0.0
        events.append(
            {
                "severity": "WARNING",
                "event_type": "CONTINUITY_SEGMENT_RESET",
                "bot": None,
                "message": "A gap above 8 hours reset the validated 30-day continuity segment.",
                "actual": gap_seconds,
                "threshold": MAX_SNAPSHOT_GAP_SECONDS,
            }
        )
    else:
        segment_start = parse_datetime(state.get("segment_started_utc"))
        if segment_start is None:
            raise MonitorError("Continuity state has no valid segment start")
        elapsed = max(0.0, (now - segment_start).total_seconds())
        slot = math.floor(elapsed / EXPECTED_SNAPSHOT_INTERVAL_SECONDS)
        slots = {int(value) for value in state.get("observed_slots", []) if isinstance(value, int)}
        slots.add(slot)
        state["observed_slots"] = sorted(slots)
        state["current_segment_max_gap_seconds"] = max(
            finite_float(state.get("current_segment_max_gap_seconds")) or 0.0,
            gap_seconds,
        )
    state["last_valid_snapshot_utc"] = iso_utc(now)
    return state, continuity_metrics(state, now, scheduled), events


def gate(name: str, passed: bool, actual: Any, requirement: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "actual": actual,
        "requirement": requirement,
    }


def make_decision(snapshot: dict[str, Any]) -> dict[str, Any]:
    bots = snapshot["bots"]
    v1 = bots.get("v1", {})
    v2r = bots.get("v2r", {})
    days = snapshot["monitoring"]["elapsed_days"]
    continuity = snapshot["monitoring"].get("continuity")
    validated_days = (
        continuity.get("validated_observation_days", 0.0)
        if isinstance(continuity, dict)
        else days
    )
    coverage_ratio = (
        continuity.get("coverage_ratio", 1.0)
        if isinstance(continuity, dict)
        else 1.0
    )
    segment_max_gap = (
        continuity.get("current_segment_max_gap_seconds", 0.0)
        if isinstance(continuity, dict)
        else 0.0
    )
    collection_ok = v1.get("status") == "OK" and v2r.get("status") == "OK"
    risk_gates = [
        gate(
            f"{key}_account_risk",
            bot.get("account_risk", {}).get("new_entries_allowed") is True,
            bot.get("account_risk", {}).get("new_entries_allowed"),
            "true",
        )
        for key, bot in (("v1", v1), ("v2r", v2r))
        if "account_risk" in bot
    ]
    risk_pass = all(item["status"] == "PASS" for item in risk_gates)

    if collection_ok:
        v1m = v1["metrics"]
        v2m = v2r["metrics"]
        integrity_gates = [
            gate(
                "v1_runtime_and_data_quality",
                v1["runtime_validation"]["pass"] and v1["data_quality"]["pass"],
                {
                    "runtime": v1["runtime_validation"]["pass"],
                    "data_quality": v1["data_quality"]["pass"],
                },
                "both true",
            ),
            gate(
                "v2r_runtime_and_data_quality",
                v2r["runtime_validation"]["pass"] and v2r["data_quality"]["pass"],
                {
                    "runtime": v2r["runtime_validation"]["pass"],
                    "data_quality": v2r["data_quality"]["pass"],
                },
                "both true",
            ),
        ]
        sample_gates = [
            gate(
                "validated_observation_days",
                validated_days >= MIN_MONITORING_DAYS,
                validated_days,
                f">= {MIN_MONITORING_DAYS:g}",
            ),
            gate(
                "scheduled_snapshot_coverage",
                coverage_ratio >= MIN_SNAPSHOT_COVERAGE_RATIO,
                coverage_ratio,
                f">= {MIN_SNAPSHOT_COVERAGE_RATIO:.0%}",
            ),
            gate(
                "current_segment_max_gap",
                segment_max_gap is not None and segment_max_gap <= MAX_SNAPSHOT_GAP_SECONDS,
                segment_max_gap,
                f"<= {MAX_SNAPSHOT_GAP_SECONDS} seconds",
            ),
            gate(
                "v1_closed_trades",
                v1m["closed_trades"] >= MIN_CLOSED_TRADES,
                v1m["closed_trades"],
                f">= {MIN_CLOSED_TRADES}",
            ),
            gate(
                "v2r_closed_trades",
                v2m["closed_trades"] >= MIN_CLOSED_TRADES,
                v2m["closed_trades"],
                f">= {MIN_CLOSED_TRADES}",
            ),
        ]
        v1_pf = v1m["profit_factor"]
        v2_pf = v2m["profit_factor"]
        v1_rdd = v1m["return_to_drawdown"]
        v2_rdd = v2m["return_to_drawdown"]
        performance_gates = [
            gate("v2r_pair_breadth", v2m["distinct_pairs"] >= MIN_V2R_PAIRS, v2m["distinct_pairs"], f">= {MIN_V2R_PAIRS}"),
            gate("v2r_positive_net_profit", v2m["net_profit_abs"] > 0, v2m["net_profit_abs"], "> 0"),
            gate(
                "v2r_profit_factor",
                v2_pf is not None and v2_pf >= MIN_V2R_PROFIT_FACTOR,
                v2_pf,
                f">= {MIN_V2R_PROFIT_FACTOR:.2f}",
            ),
            gate(
                "v2r_max_drawdown",
                v2m["max_drawdown_pct_of_start_wallet"] <= MAX_V2R_DRAWDOWN_PCT,
                v2m["max_drawdown_pct_of_start_wallet"],
                f"<= {MAX_V2R_DRAWDOWN_PCT:.1f}% of starting wallet",
            ),
            gate(
                "v2r_positive_defined_return_to_drawdown",
                v2_rdd is not None and v2_rdd > 0,
                v2_rdd,
                "> 0 and defined",
            ),
            gate(
                "v2r_profit_factor_vs_v1",
                v1_pf is not None and v2_pf is not None and v2_pf >= v1_pf - MAX_V2R_PF_DEFICIT_VS_V1,
                {"v1": v1_pf, "v2r": v2_pf},
                f"V2R >= V1 - {MAX_V2R_PF_DEFICIT_VS_V1:.2f}",
            ),
            gate(
                "v2r_return_to_drawdown_vs_v1",
                v1_rdd is not None and v2_rdd is not None and v2_rdd >= v1_rdd,
                {"v1": v1_rdd, "v2r": v2_rdd},
                "V2R >= V1",
            ),
        ]
    else:
        integrity_gates = []
        sample_gates = []
        performance_gates = []

    integrity_pass = collection_ok and all(item["status"] == "PASS" for item in integrity_gates)
    sample_pass = collection_ok and all(item["status"] == "PASS" for item in sample_gates)
    performance_pass = collection_ok and all(item["status"] == "PASS" for item in performance_gates)
    if not collection_ok or not integrity_pass:
        decision = "MONITORING_ERROR"
        action = "Inspect API/runtime/data-quality failures; do not use this snapshot for promotion."
    elif not risk_pass:
        decision = "RISK_LIMIT_BREACH"
        action = "Keep live trading disabled and block new entries until every account-risk limit clears."
    elif not sample_pass:
        decision = "INSUFFICIENT_FORWARD_SAMPLE"
        action = "Keep both credential-free dry-runs running and continue evidence collection."
    elif performance_pass:
        decision = "FORWARD_REVIEW_READY"
        action = "Begin a human review; no automatic replacement or live trading is authorized."
    else:
        decision = "FORWARD_GATES_FAILED_KEEP_RUNNING"
        action = "Retain V1 as control and continue monitoring without changing the locked strategy."
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_utc": snapshot["snapshot_utc"],
        "decision": decision,
        "selected_candidate": "DualTrendFuturesV2R",
        "integrity_gates": integrity_gates,
        "risk_gates": risk_gates,
        "sample_gates": sample_gates,
        "performance_gates": performance_gates,
        "recommended_action": action,
        "auto_promotion_enabled": False,
        "live_trading_authorized": False,
        "profit_guaranteed": False,
    }


HISTORY_FIELDS = (
    "snapshot_utc",
    "monitoring_elapsed_days",
    "bot_key",
    "strategy",
    "collection_status",
    "runtime_validation_pass",
    "data_quality_pass",
    "total_trades",
    "open_trades",
    "closed_trades",
    "wins",
    "losses",
    "net_profit_abs",
    "return_pct_of_start_wallet",
    "profit_factor",
    "max_drawdown_pct_of_start_wallet",
    "return_to_drawdown",
    "distinct_pairs",
)


def append_history(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        if not exists:
            writer.writeheader()
        for key in ("v1", "v2r"):
            bot = snapshot["bots"].get(key, {})
            metrics = bot.get("metrics", {})
            row = {
                "snapshot_utc": snapshot["snapshot_utc"],
                "monitoring_elapsed_days": snapshot["monitoring"]["elapsed_days"],
                "bot_key": key,
                "strategy": bot.get("strategy"),
                "collection_status": bot.get("status"),
                "runtime_validation_pass": bot.get("runtime_validation", {}).get("pass"),
                "data_quality_pass": bot.get("data_quality", {}).get("pass"),
            }
            for field in HISTORY_FIELDS[7:]:
                row[field] = metrics.get(field)
            writer.writerow(row)


def load_monitor_state(path: Path, now: datetime) -> tuple[dict[str, Any], bool]:
    if path.exists():
        state = load_json(path)
        started = parse_datetime(state.get("monitoring_started_utc"))
        if started is None:
            raise MonitorError(f"Invalid monitoring_started_utc in {path}")
        return state, False
    return {
        "schema_version": SCHEMA_VERSION,
        "monitoring_started_utc": iso_utc(now),
        "note": "Persistent forward epoch; normal monitor restarts must not reset it.",
    }, True


def run_snapshot(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    now = utc_now()
    reports_dir = Path(args.reports_dir)
    state_path = reports_dir / "forward_monitor_state.json"
    state, state_is_new = load_monitor_state(state_path, now)
    started = parse_datetime(state["monitoring_started_utc"])
    if started is None or started > now:
        raise MonitorError("Monitoring epoch is invalid or in the future")

    base_config = load_json(Path(args.config))
    v1_config = load_json(Path(args.v1_config))
    v2r_config = load_json(Path(args.v2r_config))
    risk_policy = validate_risk_policy(load_json(Path(args.risk_policy)))
    username, password = api_credentials(base_config)
    specs = {
        "v1": (
            args.v1_url,
            expected_bot_config(base_config, v1_config, "DualTrendFuturesV1"),
        ),
        "v2r": (
            args.v2r_url,
            expected_bot_config(base_config, v2r_config, "DualTrendFuturesV2R"),
        ),
    }
    bots: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for key, (url, expected) in specs.items():
        try:
            bots[key] = collect_bot(
                key,
                url,
                expected,
                username,
                password,
                args.timeout_seconds,
                now,
                risk_policy,
            )
        except MonitorError as exc:
            bots[key] = {
                "key": key,
                "status": "ERROR",
                "api_url": url,
                "strategy": expected["strategy"],
                "error": str(exc),
            }
            errors.append({"bot": key, "error": str(exc)})

    continuity_path = reports_dir / "forward_continuity_state.json"
    previous_continuity = load_json(continuity_path) if continuity_path.exists() else None
    eligible = continuity_eligible(bots)
    bot_starts = {
        key: (bots.get(key) or {}).get("runtime", {}).get("health_bot_start_utc")
        for key in ("v1", "v2r")
    }
    continuity_state, continuity, continuity_events = update_continuity(
        previous_continuity,
        now,
        scheduled=args.loop_seconds > 0,
        eligible=eligible,
        bot_starts=bot_starts,
    )
    if continuity_state is not None and args.loop_seconds > 0:
        atomic_write_json(continuity_path, continuity_state)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_utc": iso_utc(now),
        "monitoring": {
            "started_utc": state["monitoring_started_utc"],
            "elapsed_days": (now - started).total_seconds() / 86_400.0,
            "cadence_seconds": args.loop_seconds if args.loop_seconds > 0 else None,
            "continuity": continuity,
            "continuity_events": continuity_events,
        },
        "source": {
            "type": "Freqtrade REST API read-only GET requests",
            "endpoints": [
                "ping",
                "show_config",
                "health",
                "pair_candles",
                "profit",
                "count",
                "trades",
            ],
            "trade_page_limit": PAGE_LIMIT,
        },
        "locked_thresholds": {
            "minimum_monitoring_days": MIN_MONITORING_DAYS,
            "minimum_snapshot_coverage_ratio": MIN_SNAPSHOT_COVERAGE_RATIO,
            "expected_snapshot_interval_seconds": EXPECTED_SNAPSHOT_INTERVAL_SECONDS,
            "stale_monitor_seconds": STALE_MONITOR_SECONDS,
            "maximum_snapshot_gap_seconds": MAX_SNAPSHOT_GAP_SECONDS,
            "maximum_bot_loop_age_seconds": MAX_BOT_LOOP_AGE_SECONDS,
            "maximum_candle_close_age_seconds": MAX_CANDLE_CLOSE_AGE_SECONDS,
            "minimum_closed_trades_per_bot": MIN_CLOSED_TRADES,
            "minimum_v2r_distinct_pairs": MIN_V2R_PAIRS,
            "minimum_v2r_profit_factor": MIN_V2R_PROFIT_FACTOR,
            "v2r_drawdown_warning_pct_of_start_wallet": V2R_DRAWDOWN_WARNING_PCT,
            "maximum_v2r_drawdown_pct_of_start_wallet": MAX_V2R_DRAWDOWN_PCT,
            "maximum_v2r_profit_factor_deficit_vs_v1": MAX_V2R_PF_DEFICIT_VS_V1,
        },
        "risk_policy": {
            "policy_id": risk_policy.get("policy_id"),
            "status": risk_policy.get("status"),
            "limits": risk_policy["limits"],
            "live_launch_authorized": risk_policy["live_launch"]["authorized"],
        },
        "bots": bots,
        "errors": errors,
        "live_trading_authorized": False,
    }
    decision = make_decision(snapshot)
    if state_is_new and not errors:
        atomic_write_json(state_path, state)
    # Write the current evidence before the daily backup so the archive contains
    # this snapshot. A final write below adds backup and alert delivery status.
    atomic_write_json(reports_dir / "forward_monitor_latest.json", snapshot)
    atomic_write_json(reports_dir / "forward_monitor_decision.json", decision)
    append_history(reports_dir / "forward_monitor_history.csv", snapshot)
    try:
        from backup_forward_state import run_backup_if_due

        backup_status = run_backup_if_due(
            Path(args.user_data_dir),
            Path(args.backup_dir),
            reports_dir / "forward_backup_state.json",
            now,
            interval_seconds=args.backup_interval_seconds,
            retention_days=args.backup_retention_days,
        )
    except Exception as exc:  # Backup failure is alerted but cannot stop monitoring.
        backup_status = {
            "status": "ERROR",
            "snapshot_utc": snapshot["snapshot_utc"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    snapshot["backup"] = backup_status
    atomic_write_json(reports_dir / "forward_backup_status.json", backup_status)
    alert_state_path = reports_dir / "forward_alert_state.json"
    alert_state = load_alert_state(alert_state_path)
    new_alerts, next_alert_state = evaluate_alerts(snapshot, decision, alert_state)
    webhook_delivery = deliver_alert_webhook(
        os.environ.get("FORWARD_ALERT_WEBHOOK_URL") or None,
        snapshot["snapshot_utc"],
        new_alerts,
        args.timeout_seconds,
    )
    snapshot["alerting"] = {
        "new_alert_count": len(new_alerts),
        "events": new_alerts,
        "webhook_delivery": webhook_delivery,
        "external_destination_configured": bool(
            os.environ.get("FORWARD_ALERT_WEBHOOK_URL")
        ),
        "journal": "user_data/reports/forward_alerts.jsonl",
    }
    atomic_write_json(alert_state_path, next_alert_state)
    append_json_lines(reports_dir / "forward_alerts.jsonl", new_alerts)
    atomic_write_json(
        reports_dir / "forward_alert_latest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_utc": snapshot["snapshot_utc"],
            "alerts": new_alerts,
            "webhook_delivery": webhook_delivery,
        },
    )
    try:
        from build_live_readiness import build_readiness

        readiness = build_readiness(
            snapshot,
            decision,
            load_json(Path(args.execution_stress_report)),
            risk_policy,
        )
    except Exception as exc:
        readiness = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_utc": snapshot["snapshot_utc"],
            "qualification_status": "SAFETY_BLOCK",
            "error": f"{type(exc).__name__}: {exc}",
            "live_trading_authorized": False,
            "automatic_live_launch_available": False,
            "profit_guaranteed": False,
        }
    atomic_write_json(Path(args.live_readiness_output), readiness)
    snapshot["live_readiness"] = {
        "qualification_status": readiness["qualification_status"],
        "live_trading_authorized": False,
        "report": "user_data/reports/live_readiness.json",
    }
    atomic_write_json(reports_dir / "forward_monitor_latest.json", snapshot)
    atomic_write_json(reports_dir / "forward_monitor_decision.json", decision)
    try:
        from forward_dashboard_artifact import build_and_write

        artifact = build_and_write(reports_dir, Path(args.dashboard_output))
        dashboard_status = {
            "status": "ARTIFACT_READY",
            "generated_at": artifact["snapshot"]["generatedAt"],
            "output": args.dashboard_output,
        }
    except Exception as exc:  # Dashboard failure must not interrupt evidence collection.
        dashboard_status = {
            "status": "ARTIFACT_ERROR",
            "generated_at": snapshot["snapshot_utc"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    atomic_write_json(reports_dir / "forward_dashboard_artifact_status.json", dashboard_status)
    try:
        from daily_report_artifact import build_and_write as build_daily_report

        daily_artifact = build_daily_report(
            reports_dir,
            Path(args.daily_report_output),
            reports_dir / "daily",
        )
        daily_report_status = {
            "status": "ARTIFACT_READY",
            "generated_at": daily_artifact["snapshot"]["generatedAt"],
            "output": args.daily_report_output,
        }
    except Exception as exc:  # Daily-report failure must not interrupt evidence collection.
        daily_report_status = {
            "status": "ARTIFACT_ERROR",
            "generated_at": snapshot["snapshot_utc"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    atomic_write_json(
        reports_dir / "daily_report_artifact_status.json", daily_report_status
    )
    return snapshot, decision


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="user_data/config.json")
    parser.add_argument(
        "--v1-config", default="user_data/config-dual-futures-dry-run.json"
    )
    parser.add_argument(
        "--v2r-config", default="user_data/config-dual-futures-v2r-dry-run.json"
    )
    parser.add_argument("--reports-dir", default="user_data/reports")
    parser.add_argument("--user-data-dir", default="user_data")
    parser.add_argument("--backup-dir", default="user_data/backups")
    parser.add_argument("--backup-interval-seconds", type=int, default=86_400)
    parser.add_argument("--backup-retention-days", type=int, default=35)
    parser.add_argument("--risk-policy", default="user_data/risk_policy.json")
    parser.add_argument(
        "--execution-stress-report",
        default="user_data/reports/execution_stress_report.json",
    )
    parser.add_argument(
        "--live-readiness-output",
        default="user_data/reports/live_readiness.json",
    )
    parser.add_argument(
        "--dashboard-output",
        default="user_data/dashboard/forward_dashboard_artifact.json",
    )
    parser.add_argument(
        "--daily-report-output",
        default="user_data/dashboard/daily_report_artifact.json",
    )
    parser.add_argument("--v1-url", default="http://127.0.0.1:8080")
    parser.add_argument("--v2r-url", default="http://127.0.0.1:8081")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--loop-seconds",
        type=int,
        default=0,
        help="Repeat at this interval; 0 runs exactly one snapshot.",
    )
    parser.add_argument(
        "--error-retry-seconds",
        type=int,
        default=60,
        help="Retry this soon after a collection error instead of waiting for the normal cadence.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        args.timeout_seconds <= 0
        or args.loop_seconds < 0
        or args.error_retry_seconds <= 0
        or args.backup_interval_seconds <= 0
        or args.backup_retention_days <= 0
    ):
        raise SystemExit("timeouts, backup interval, and retention must be valid positive values")
    while True:
        try:
            snapshot, decision = run_snapshot(args)
            error_count = len(snapshot["errors"])
            print(
                json.dumps(
                    {
                        "snapshot_utc": snapshot["snapshot_utc"],
                        "decision": decision["decision"],
                        "collection_errors": error_count,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            for alert in snapshot.get("alerting", {}).get("events", []):
                print(
                    "ALERT " + json.dumps(alert, separators=(",", ":"), allow_nan=False),
                    flush=True,
                )
            exit_code = 2 if error_count else 0
        except MonitorError as exc:
            print(f"forward monitor error: {exc}", file=sys.stderr, flush=True)
            exit_code = 2
        if args.loop_seconds == 0:
            return exit_code
        retry_after_error = exit_code != 0
        sleep_seconds = (
            min(args.loop_seconds, args.error_retry_seconds)
            if retry_after_error
            else args.loop_seconds
        )
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
