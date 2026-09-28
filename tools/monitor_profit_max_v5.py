#!/usr/bin/env python3
"""Fail-closed forward monitor for the isolated Profit-Max V5 dry-run."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
MINIMUM_DAYS = 30.0
MINIMUM_CLOSED_TRADES = 30
MINIMUM_PROFIT_FACTOR = 1.20
MAXIMUM_DRAWDOWN_PCT = 10.0
MINIMUM_LONG_CLOSES = 5
MINIMUM_SHORT_CLOSES = 5
MINIMUM_ACTIVE_PAIRS = 3
REQUIRED_COLUMNS = {
    "pair", "is_open", "close_profit_abs", "open_date", "close_date",
    "strategy", "trading_mode", "leverage", "is_short",
}


class MonitorError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def finite(value: Any) -> float:
    if value is None or isinstance(value, bool):
        raise MonitorError(f"non-numeric profit value: {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise MonitorError(f"non-finite numeric value: {value!r}")
    return number


def summarize_closed(rows: Iterable[sqlite3.Row], starting_wallet: float) -> dict[str, Any]:
    trades = list(rows)
    profits = [finite(row["close_profit_abs"]) for row in trades]
    gains = sum(value for value in profits if value > 0)
    losses = -sum(value for value in profits if value < 0)
    equity = starting_wallet
    peak = starting_wallet
    maximum_drawdown = 0.0
    for value in profits:
        equity += value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    long_rows = [row for row in trades if not bool(row["is_short"])]
    short_rows = [row for row in trades if bool(row["is_short"])]
    pairs: dict[str, dict[str, Any]] = {}
    for row, profit in zip(trades, profits):
        item = pairs.setdefault(str(row["pair"]), {"closed_trades": 0, "net_profit_usdt": 0.0})
        item["closed_trades"] += 1
        item["net_profit_usdt"] += profit
    return {
        "closed_trades": len(trades),
        "net_profit_usdt": sum(profits),
        "return_pct_on_starting_wallet": sum(profits) / starting_wallet * 100.0,
        "profit_factor": gains / losses if losses > 0 else None,
        "maximum_realized_drawdown_usdt": maximum_drawdown,
        "maximum_realized_drawdown_pct": maximum_drawdown / starting_wallet * 100.0,
        "winning_trades": sum(value > 0 for value in profits),
        "losing_trades": sum(value < 0 for value in profits),
        "draw_trades": sum(value == 0 for value in profits),
        "long": {"closed_trades": len(long_rows), "net_profit_usdt": sum(finite(row["close_profit_abs"]) for row in long_rows)},
        "short": {"closed_trades": len(short_rows), "net_profit_usdt": sum(finite(row["close_profit_abs"]) for row in short_rows)},
        "pairs": dict(sorted(pairs.items())),
    }


def build_report(database: Path, strategy: str, started_at: datetime, starting_wallet: float, *, now: datetime | None = None) -> dict[str, Any]:
    if starting_wallet <= 0:
        raise MonitorError("starting wallet must be positive")
    current = (now or utc_now()).astimezone(timezone.utc)
    if started_at > current:
        raise MonitorError("dry-run start is in the future")
    connection = sqlite3.connect(database.resolve(), timeout=30.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("pragma query_only = on")
        columns = {row[1] for row in connection.execute("pragma table_info(trades)")}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise MonitorError(f"trades schema missing: {sorted(missing)}")
        total = int(connection.execute("select count(*) from trades").fetchone()[0])
        open_count = int(connection.execute("select count(*) from trades where is_open = 1").fetchone()[0])
        closed_rows = list(connection.execute(
            "select pair,is_short,close_profit_abs,close_date,strategy,trading_mode,leverage "
            "from trades where is_open = 0 order by close_date,id"
        ))
        identity_rows = list(connection.execute(
            "select distinct strategy,trading_mode,leverage from trades"
        ))
    finally:
        connection.close()
    identity_ok = all(
        row["strategy"] == strategy
        and row["trading_mode"] == "futures"
        and finite(row["leverage"]) <= 1.0
        for row in identity_rows
    )
    if not identity_ok:
        raise MonitorError("trade identity or leverage differs from dry-run contract")
    metrics = summarize_closed(closed_rows, starting_wallet)
    elapsed_days = (current - started_at).total_seconds() / 86400.0
    active_pairs = sum(item["closed_trades"] > 0 for item in metrics["pairs"].values())
    pf = metrics["profit_factor"]
    gates = {
        "observation_days_gte_30": elapsed_days >= MINIMUM_DAYS,
        "closed_trades_gte_30": metrics["closed_trades"] >= MINIMUM_CLOSED_TRADES,
        "net_profit_positive": metrics["net_profit_usdt"] > 0,
        "profit_factor_gte_1_20": pf is not None and pf >= MINIMUM_PROFIT_FACTOR,
        "drawdown_lte_10pct": metrics["maximum_realized_drawdown_pct"] <= MAXIMUM_DRAWDOWN_PCT,
        "long_closes_gte_5": metrics["long"]["closed_trades"] >= MINIMUM_LONG_CLOSES,
        "short_closes_gte_5": metrics["short"]["closed_trades"] >= MINIMUM_SHORT_CLOSES,
        "active_pairs_gte_3": active_pairs >= MINIMUM_ACTIVE_PAIRS,
        "database_reconciliation": total == open_count + metrics["closed_trades"],
    }
    sample_complete = gates["observation_days_gte_30"] and gates["closed_trades_gte_30"]
    if not sample_complete:
        qualification = "EVIDENCE_INCOMPLETE"
        decision = "CONTINUE_DRY_RUN"
    elif all(gates.values()):
        qualification = "FORWARD_GATES_PASS_HUMAN_REVIEW_REQUIRED"
        decision = "KEEP_DRY_RUN_PENDING_HUMAN_REVIEW"
    else:
        qualification = "FORWARD_GATES_FAIL"
        decision = "KEEP_DRY_RUN_RESEARCH"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": current.isoformat().replace("+00:00", "Z"),
        "strategy": strategy,
        "mode": "dry_run",
        "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
        "observation_days": elapsed_days,
        "database": {"path": str(database).replace("\\", "/"), "total_trades": total, "open_trades": open_count},
        "metrics": metrics,
        "active_pairs": active_pairs,
        "gates": gates,
        "qualification_status": qualification,
        "decision": decision,
        "auto_promotion_enabled": False,
        "live_trading_authorized": False,
        "profit_guaranteed": False,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def healthcheck(output: Path, max_age_seconds: float, *, now: datetime | None = None) -> bool:
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
        generated = parse_utc(payload["generated_at_utc"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    age = ((now or utc_now()).astimezone(timezone.utc) - generated).total_seconds()
    return (
        0 <= age <= max_age_seconds
        and payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("mode") == "dry_run"
        and payload.get("qualification_status") != "MONITOR_ERROR"
        and payload.get("decision") in {
            "CONTINUE_DRY_RUN",
            "KEEP_DRY_RUN_PENDING_HUMAN_REVIEW",
            "KEEP_DRY_RUN_RESEARCH",
        }
        and payload.get("live_trading_authorized") is False
        and payload.get("auto_promotion_enabled") is False
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strategy", default="ProfitMaxV5Asymmetric50")
    parser.add_argument("--started-at-utc")
    parser.add_argument("--starting-wallet", type=float, default=1000.0)
    parser.add_argument("--loop-seconds", type=int, default=0)
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--health-max-age-seconds", type=float, default=7200.0)
    args = parser.parse_args()
    if args.healthcheck:
        return 0 if healthcheck(args.output, args.health_max_age_seconds) else 1
    if args.database is None or not args.started_at_utc:
        parser.error("--database and --started-at-utc are required outside healthcheck mode")
    while True:
        try:
            report = build_report(args.database, args.strategy, parse_utc(args.started_at_utc), args.starting_wallet)
            atomic_write(args.output, report)
        except (MonitorError, OSError, sqlite3.Error, ValueError) as exc:
            error = {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
                "mode": "dry_run",
                "qualification_status": "MONITOR_ERROR",
                "decision": "KEEP_DRY_RUN_RESEARCH",
                "error": str(exc),
                "auto_promotion_enabled": False,
                "live_trading_authorized": False,
                "profit_guaranteed": False,
            }
            atomic_write(args.output, error)
            if args.loop_seconds <= 0:
                return 2
        if args.loop_seconds <= 0:
            return 0
        time.sleep(args.loop_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
