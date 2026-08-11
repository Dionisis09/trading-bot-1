#!/usr/bin/env python3
"""Apply deterministic adverse execution costs to locked Freqtrade trade exports."""

from __future__ import annotations

import argparse
import csv
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
DEFAULT_SPLITS = ("validation", "2021", "2022", "2023", "2024", "2025", "current_2026")
SCENARIOS = {
    "moderate": {
        "additional_fee_bps_per_side": 2.0,
        "slippage_bps_per_side": 5.0,
        "latency_penalty_bps": 2.0,
        "funding_cost_multiplier": 1.5,
        "minimum_profit_factor": 1.10,
        "maximum_realized_drawdown_pct": 15.0,
    },
    "severe": {
        "additional_fee_bps_per_side": 10.0,
        "slippage_bps_per_side": 15.0,
        "latency_penalty_bps": 5.0,
        "funding_cost_multiplier": 3.0,
        "minimum_profit_factor": 1.00,
        "maximum_realized_drawdown_pct": 20.0,
    },
}


class StressError(RuntimeError):
    pass


def finite(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_time(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(candidate)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    raise StressError(f"Trade has invalid close timestamp: {value!r}")


def load_strategy_trades(archive: Path, strategy: str) -> list[dict[str, Any]]:
    if not archive.is_file():
        raise StressError(f"Missing backtest archive: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        candidates = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(candidates) != 1:
            raise StressError(f"Expected one result JSON in {archive.name}")
        payload = json.loads(bundle.read(candidates[0]))
    strategy_payload = payload.get("strategy", {}).get(strategy)
    if not isinstance(strategy_payload, dict):
        raise StressError(f"Strategy {strategy} is missing from {archive.name}")
    trades = strategy_payload.get("trades")
    if not isinstance(trades, list) or any(not isinstance(item, dict) for item in trades):
        raise StressError(f"Strategy {strategy} has invalid trades in {archive.name}")
    return trades


def stress_profit(trade: dict[str, Any], scenario: dict[str, float]) -> float:
    base_profit = finite(trade.get("profit_abs"))
    amount = abs(finite(trade.get("amount")))
    entry_notional = amount * abs(finite(trade.get("open_rate")))
    exit_notional = amount * abs(finite(trade.get("close_rate")))
    round_trip_notional = entry_notional + exit_notional
    bps_cost = (
        scenario["additional_fee_bps_per_side"]
        + scenario["slippage_bps_per_side"]
    ) / 10_000.0 * round_trip_notional
    latency_cost = scenario["latency_penalty_bps"] / 10_000.0 * entry_notional
    funding_cost = abs(finite(trade.get("funding_fees"))) * max(
        0.0, scenario["funding_cost_multiplier"] - 1.0
    )
    return base_profit - bps_cost - latency_cost - funding_cost


def summarize(profits_with_times: list[tuple[datetime, float]], starting_wallet: float) -> dict[str, Any]:
    ordered = sorted(profits_with_times, key=lambda item: item[0])
    profits = [profit for _, profit in ordered]
    gross_profit = sum(value for value in profits if value > 0)
    gross_loss = abs(sum(value for value in profits if value < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    equity = starting_wallet
    peak = starting_wallet
    maximum_drawdown = 0.0
    for value in profits:
        equity += value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    return {
        "trades": len(profits),
        "net_profit_usdt": sum(profits),
        "profit_factor": profit_factor,
        "realized_drawdown_pct": maximum_drawdown / starting_wallet * 100.0,
        "profitable_trades": sum(1 for value in profits if value > 0),
        "losing_trades": sum(1 for value in profits if value < 0),
    }


def build_report(
    summary_csv: Path,
    backtest_dir: Path,
    *,
    strategy: str = "DualTrendFuturesV2R",
    splits: tuple[str, ...] = DEFAULT_SPLITS,
    starting_wallet: float = 1_000.0,
) -> dict[str, Any]:
    if starting_wallet <= 0:
        raise StressError("starting_wallet must be positive")
    with summary_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = {
        row["split"]: row
        for row in rows
        if row.get("strategy") == strategy and row.get("split") in splits
    }
    missing = [split for split in splits if split not in selected]
    if missing:
        raise StressError(f"Missing locked summary splits: {', '.join(missing)}")

    results: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    for split in splits:
        row = selected[split]
        trades = load_strategy_trades(backtest_dir / row["artifact"], strategy)
        base_total = sum(finite(trade.get("profit_abs")) for trade in trades)
        expected_total = finite(row.get("profit_abs_usdt"))
        reproduced = math.isclose(base_total, expected_total, rel_tol=1e-9, abs_tol=1e-6)
        gates.append(
            {
                "name": f"{split}_source_reconciliation",
                "status": "PASS" if reproduced else "FAIL",
                "actual": base_total,
                "requirement": expected_total,
            }
        )
        for scenario_name, scenario in SCENARIOS.items():
            stressed = [
                (
                    parse_time(trade.get("close_timestamp", trade.get("close_date"))),
                    stress_profit(trade, scenario),
                )
                for trade in trades
            ]
            metrics = summarize(stressed, starting_wallet)
            passed = (
                metrics["net_profit_usdt"] > 0
                and metrics["profit_factor"] is not None
                and metrics["profit_factor"] >= scenario["minimum_profit_factor"]
                and metrics["realized_drawdown_pct"] <= scenario["maximum_realized_drawdown_pct"]
            )
            results.append(
                {
                    "split": split,
                    "scenario": scenario_name,
                    **metrics,
                    "status": "PASS" if passed else "FAIL",
                }
            )
            gates.append(
                {
                    "name": f"{split}_{scenario_name}",
                    "status": "PASS" if passed else "FAIL",
                    "actual": {
                        "net_profit_usdt": metrics["net_profit_usdt"],
                        "profit_factor": metrics["profit_factor"],
                        "realized_drawdown_pct": metrics["realized_drawdown_pct"],
                    },
                    "requirement": {
                        "net_profit_usdt": "> 0",
                        "minimum_profit_factor": scenario["minimum_profit_factor"],
                        "maximum_realized_drawdown_pct": scenario[
                            "maximum_realized_drawdown_pct"
                        ],
                    },
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "strategy": strategy,
        "source": {
            "summary_csv": str(summary_csv).replace("\\", "/"),
            "backtest_directory": str(backtest_dir).replace("\\", "/"),
            "splits": list(splits),
            "starting_wallet_usdt": starting_wallet,
        },
        "scenarios": SCENARIOS,
        "results": results,
        "gates": gates,
        "status": "PASS" if all(item["status"] == "PASS" for item in gates) else "FAIL",
        "live_trading_authorized": False,
        "note": "Deterministic adverse-cost diagnostic; it is not a forecast or profit guarantee.",
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-csv", default="user_data/reports/professional_risk_backtest_summary.csv")
    parser.add_argument("--backtest-dir", default="user_data/backtest_results")
    parser.add_argument("--output", default="user_data/reports/execution_stress_report.json")
    parser.add_argument("--strategy", default="DualTrendFuturesV2R")
    args = parser.parse_args()
    report = build_report(Path(args.summary_csv), Path(args.backtest_dir), strategy=args.strategy)
    write_report(Path(args.output), report)
    print(json.dumps({"status": report["status"], "gates": len(report["gates"]), "output": args.output}))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
