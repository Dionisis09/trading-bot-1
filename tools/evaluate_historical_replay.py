#!/usr/bin/env python3
"""Evaluate an accelerated chronological replay of the active dry-run bots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from validate_execution_stress import SCENARIOS, finite, parse_time, stress_profit, summarize


SCHEMA_VERSION = "1.0"
STARTING_WALLET = 1_000.0
STRATEGIES = ("DualTrendFuturesV1", "DualTrendFuturesV2R")
PAIRS = (
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
    "ADA/USDT:USDT",
    "DOGE/USDT:USDT",
)
FULL_YEARS = (2021, 2022, 2023, 2024, 2025)


class ReplayError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_strategy(archive: Path, strategy: str) -> dict[str, Any]:
    if not archive.is_file():
        raise ReplayError(f"Missing replay archive: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        result_names = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(result_names) != 1:
            raise ReplayError(f"Expected one result JSON in {archive.name}")
        payload = json.loads(bundle.read(result_names[0]))
    strategy_payload = payload.get("strategy", {}).get(strategy)
    if not isinstance(strategy_payload, dict):
        raise ReplayError(f"Strategy {strategy} is missing from {archive.name}")
    trades = strategy_payload.get("trades")
    if not isinstance(trades, list) or any(not isinstance(item, dict) for item in trades):
        raise ReplayError(f"Strategy {strategy} has invalid trades in {archive.name}")
    return strategy_payload


def close_time(trade: dict[str, Any]) -> datetime:
    return parse_time(trade.get("close_timestamp", trade.get("close_date")))


def scenario_metrics(
    trades: Iterable[dict[str, Any]], scenario: dict[str, float] | None
) -> dict[str, Any]:
    values = []
    for trade in trades:
        profit = finite(trade.get("profit_abs")) if scenario is None else stress_profit(trade, scenario)
        values.append((close_time(trade), profit))
    return summarize(values, STARTING_WALLET)


def row(
    strategy: str,
    view: str,
    period: str,
    trades: list[dict[str, Any]],
    scenario_name: str,
    scenario: dict[str, float] | None,
) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "view": view,
        "period": period,
        "scenario": scenario_name,
        **scenario_metrics(trades, scenario),
    }


def strategy_rows(strategy: str, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[tuple[str, str, list[dict[str, Any]]]] = [("overall", "all", trades)]
    years = sorted({close_time(trade).year for trade in trades} | set(FULL_YEARS) | {2026})
    for year in years:
        groups.append(("year", str(year), [trade for trade in trades if close_time(trade).year == year]))
    quarters = [
        f"{year}-Q{quarter}"
        for year in range(2021, 2027)
        for quarter in range(1, 5)
        if year < 2026 or quarter <= 3
    ]
    for quarter in quarters:
        groups.append(
            (
                "quarter",
                quarter,
                [
                    trade
                    for trade in trades
                    for timestamp in [close_time(trade)]
                    if f"{timestamp.year}-Q{((timestamp.month - 1) // 3) + 1}" == quarter
                ],
            )
        )
    for pair in PAIRS:
        groups.append(("pair", pair, [trade for trade in trades if trade.get("pair") == pair]))
    for direction, is_short in (("long", False), ("short", True)):
        groups.append(
            ("direction", direction, [trade for trade in trades if bool(trade.get("is_short")) is is_short])
        )

    rows: list[dict[str, Any]] = []
    scenarios: list[tuple[str, dict[str, float] | None]] = [("standard", None), *SCENARIOS.items()]
    for view, period, selected in groups:
        for scenario_name, scenario in scenarios:
            rows.append(row(strategy, view, period, selected, scenario_name, scenario))
    return rows


def index_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    return {
        (item["strategy"], item["view"], item["period"], item["scenario"]): item
        for item in rows
    }


def gate(name: str, passed: bool, actual: Any, requirement: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "actual": actual,
        "requirement": requirement,
    }


def diagnostic_gates(
    rows: list[dict[str, Any]], source_reconciled: dict[str, bool]
) -> list[dict[str, Any]]:
    indexed = index_rows(rows)
    strategy = "DualTrendFuturesV2R"
    standard = indexed[(strategy, "overall", "all", "standard")]
    moderate = indexed[(strategy, "overall", "all", "moderate")]
    severe = indexed[(strategy, "overall", "all", "severe")]

    gates = [
        gate(
            "source_reconciliation",
            all(source_reconciled.values()),
            source_reconciled,
            "true for both archives",
        ),
        gate("standard_net_positive", standard["net_profit_usdt"] > 0, standard["net_profit_usdt"], "> 0"),
        gate(
            "standard_profit_factor",
            standard["profit_factor"] is not None and standard["profit_factor"] >= 1.20,
            standard["profit_factor"],
            ">= 1.20",
        ),
        gate(
            "standard_drawdown",
            standard["realized_drawdown_pct"] <= 15.0,
            standard["realized_drawdown_pct"],
            "<= 15%",
        ),
        gate(
            "moderate_whole_period",
            moderate["net_profit_usdt"] > 0
            and moderate["profit_factor"] is not None
            and moderate["profit_factor"] >= 1.10,
            {"net_profit_usdt": moderate["net_profit_usdt"], "profit_factor": moderate["profit_factor"]},
            {"net_profit_usdt": "> 0", "profit_factor": ">= 1.10"},
        ),
        gate(
            "severe_whole_period",
            severe["net_profit_usdt"] > 0
            and severe["profit_factor"] is not None
            and severe["profit_factor"] >= 1.00,
            {"net_profit_usdt": severe["net_profit_usdt"], "profit_factor": severe["profit_factor"]},
            {"net_profit_usdt": "> 0", "profit_factor": ">= 1.00"},
        ),
    ]

    positive_pairs = sum(
        indexed[(strategy, "pair", pair, "standard")]["net_profit_usdt"] > 0 for pair in PAIRS
    )
    gates.append(gate("positive_pair_breadth", positive_pairs >= 4, positive_pairs, ">= 4 of 6"))

    full_year_profits = {
        str(year): indexed[(strategy, "year", str(year), "standard")]["net_profit_usdt"]
        for year in FULL_YEARS
    }
    positive_years = sum(value > 0 for value in full_year_profits.values())
    gates.append(gate("positive_full_years", positive_years >= 4, positive_years, ">= 4 of 5"))
    worst_year = min(full_year_profits.values())
    gates.append(
        gate(
            "worst_full_year_loss",
            worst_year >= -0.05 * STARTING_WALLET,
            {"worst_net_profit_usdt": worst_year, "years": full_year_profits},
            ">= -50 USDT",
        )
    )
    return gates


def replay_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = index_rows(rows)
    strategy = "DualTrendFuturesV2R"
    moderate_failures: list[str] = []
    severe_failures: list[str] = []
    for year in (*FULL_YEARS, 2026):
        period = str(year)
        for scenario_name, failures in (
            ("moderate", moderate_failures),
            ("severe", severe_failures),
        ):
            metrics = indexed[(strategy, "year", period, scenario_name)]
            scenario = SCENARIOS[scenario_name]
            if not (
                metrics["net_profit_usdt"] > 0
                and metrics["profit_factor"] is not None
                and metrics["profit_factor"] >= scenario["minimum_profit_factor"]
            ):
                failures.append(period)

    negative_quarters = [
        item["period"]
        for item in rows
        if item["strategy"] == strategy
        and item["view"] == "quarter"
        and item["scenario"] == "standard"
        and item["net_profit_usdt"] < 0
    ]
    no_trade_pairs = [
        pair
        for pair in PAIRS
        if indexed[(strategy, "pair", pair, "standard")]["trades"] == 0
    ]
    return {
        "yearly_moderate_cost_failures": moderate_failures,
        "yearly_severe_cost_failures": severe_failures,
        "negative_standard_quarters": negative_quarters,
        "negative_standard_quarter_count": len(negative_quarters),
        "total_quarters": 23,
        "pairs_with_no_trades": no_trade_pairs,
        "standard_direction_net_profit_usdt": {
            direction: indexed[(strategy, "direction", direction, "standard")]["net_profit_usdt"]
            for direction in ("long", "short")
        },
    }


def evaluate(archives: dict[str, Path]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    source_reconciled: dict[str, bool] = {}
    source_totals: dict[str, dict[str, float]] = {}
    for strategy in STRATEGIES:
        archive = archives[strategy]
        payload = load_strategy(archive, strategy)
        trades = payload["trades"]
        expected = finite(payload.get("profit_total_abs"))
        reproduced = sum(finite(trade.get("profit_abs")) for trade in trades)
        source_reconciled[strategy] = math.isclose(expected, reproduced, rel_tol=1e-9, abs_tol=1e-6)
        source_totals[strategy] = {"expected_profit_usdt": expected, "reproduced_profit_usdt": reproduced}
        rows.extend(strategy_rows(strategy, trades))

    gates = diagnostic_gates(rows, source_reconciled)
    status = "PASS" if all(item["status"] == "PASS" for item in gates) else "FAIL"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locked_plan": "docs/historical_replay_locked_plan.md",
        "timerange": {"start_utc": "2021-01-01T00:00:00Z", "end_utc": "2026-08-01T00:00:00Z"},
        "artifacts": {
            strategy: {
                "path": str(path).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for strategy, path in archives.items()
        },
        "source_totals": source_totals,
        "scenarios": SCENARIOS,
        "gates": gates,
        "diagnostics": replay_diagnostics(rows),
        "status": status,
        "decision": "HISTORICAL_DIAGNOSTIC_PASS" if status == "PASS" else "HISTORICAL_DIAGNOSTIC_FAIL",
        "active_strategy_changed": False,
        "counts_as_forward_evidence": False,
        "live_trading_authorized": False,
        "profit_guaranteed": False,
        "note": "Accelerated historical diagnostic only; past performance is not a forecast.",
    }
    return report, rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1", default="user_data/backtest_results/historical_replay_v1_active.zip")
    parser.add_argument("--v2r", default="user_data/backtest_results/historical_replay_v2r_active.zip")
    parser.add_argument("--output", default="user_data/reports/historical_replay_decision.json")
    parser.add_argument("--csv", default="user_data/reports/historical_replay_metrics.csv")
    args = parser.parse_args()
    report, rows = evaluate(
        {
            "DualTrendFuturesV1": Path(args.v1),
            "DualTrendFuturesV2R": Path(args.v2r),
        }
    )
    write_json(Path(args.output), report)
    write_csv(Path(args.csv), rows)
    print(json.dumps({"status": report["status"], "gates": len(report["gates"]), "output": args.output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
