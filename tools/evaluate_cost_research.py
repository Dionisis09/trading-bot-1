#!/usr/bin/env python3
"""Evaluate the locked cost-robust candidate matrix from raw trade exports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_execution_stress import SCENARIOS, finite, parse_time, stress_profit, summarize


SCHEMA_VERSION = "1.0"
INCUMBENT = "DualTrendFuturesV2R"
CANDIDATES = (
    "CostRobustRoc5",
    "CostRobustRoc10",
    "CostRobustEma1",
    "CostRobustAtr1",
    "CostRobustBreakout50",
    "CostRobustRoc5Ema1",
)
TRAINING_SPLITS = ("2021", "2022", "2023")
VALIDATION_SPLITS = ("2024", "2025", "current_2026")


class ResearchError(RuntimeError):
    pass


def load_payload(archive: Path) -> dict[str, Any]:
    if not archive.is_file():
        raise ResearchError(f"Missing backtest archive: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        names = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(names) != 1:
            raise ResearchError(f"Expected one result JSON in {archive.name}")
        payload = json.loads(bundle.read(names[0]))
    if not isinstance(payload.get("strategy"), dict):
        raise ResearchError(f"Invalid strategy payload in {archive.name}")
    return payload


def metric_row(
    split: str,
    strategy: str,
    archive: Path,
    strategy_payload: dict[str, Any],
    scenario_name: str,
    scenario: dict[str, float] | None,
) -> dict[str, Any]:
    trades = strategy_payload.get("trades")
    if not isinstance(trades, list) or any(not isinstance(item, dict) for item in trades):
        raise ResearchError(f"Invalid trades for {strategy} in {archive.name}")
    expected_total = finite(strategy_payload.get("profit_total_abs"))
    reproduced_total = sum(finite(trade.get("profit_abs")) for trade in trades)
    reconciled = math.isclose(expected_total, reproduced_total, rel_tol=1e-9, abs_tol=1e-6)
    profits = []
    for trade in trades:
        profit = finite(trade.get("profit_abs")) if scenario is None else stress_profit(trade, scenario)
        profits.append((parse_time(trade.get("close_timestamp", trade.get("close_date"))), profit))
    metrics = summarize(profits, 1_000.0)
    return {
        "split": split,
        "strategy": strategy,
        "scenario": scenario_name,
        "artifact": archive.name,
        "trades": metrics["trades"],
        "net_profit_usdt": metrics["net_profit_usdt"],
        "profit_factor": metrics["profit_factor"],
        "realized_drawdown_pct": metrics["realized_drawdown_pct"],
        "source_expected_profit_usdt": expected_total,
        "source_reproduced_profit_usdt": reproduced_total,
        "source_reconciled": reconciled,
    }


def evaluate_artifacts(artifacts: dict[str, Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, archive in artifacts.items():
        payload = load_payload(archive)
        for strategy in (INCUMBENT, *CANDIDATES):
            strategy_payload = payload["strategy"].get(strategy)
            if not isinstance(strategy_payload, dict):
                raise ResearchError(f"Missing {strategy} in {archive.name}")
            rows.append(metric_row(split, strategy, archive, strategy_payload, "standard", None))
            for scenario_name, scenario in SCENARIOS.items():
                rows.append(
                    metric_row(split, strategy, archive, strategy_payload, scenario_name, scenario)
                )
    return rows


def row_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(row["strategy"], row["split"], row["scenario"]): row for row in rows}


def scenario_pass(row: dict[str, Any], scenario_name: str) -> bool:
    scenario = SCENARIOS[scenario_name]
    profit_factor = row["profit_factor"]
    return bool(
        row["source_reconciled"]
        and row["net_profit_usdt"] > 0
        and profit_factor is not None
        and profit_factor >= scenario["minimum_profit_factor"]
        and row["realized_drawdown_pct"] <= scenario["maximum_realized_drawdown_pct"]
    )


def training_selection(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    indexed = row_index(rows)
    results: list[dict[str, Any]] = []
    for strategy in CANDIDATES:
        gates: list[dict[str, Any]] = []
        for split in TRAINING_SPLITS:
            standard = indexed[(strategy, split, "standard")]
            gates.append(
                {
                    "name": f"{split}_minimum_20_trades",
                    "status": "PASS" if standard["trades"] >= 20 else "FAIL",
                    "actual": standard["trades"],
                    "requirement": ">= 20",
                }
            )
            for scenario_name in SCENARIOS:
                row = indexed[(strategy, split, scenario_name)]
                gates.append(
                    {
                        "name": f"{split}_{scenario_name}",
                        "status": "PASS" if scenario_pass(row, scenario_name) else "FAIL",
                        "actual": {
                            "net_profit_usdt": row["net_profit_usdt"],
                            "profit_factor": row["profit_factor"],
                            "realized_drawdown_pct": row["realized_drawdown_pct"],
                        },
                    }
                )
        standard_net = sum(indexed[(strategy, split, "standard")]["net_profit_usdt"] for split in TRAINING_SPLITS)
        gates.append(
            {
                "name": "aggregate_standard_profit_positive",
                "status": "PASS" if standard_net > 0 else "FAIL",
                "actual": standard_net,
                "requirement": "> 0",
            }
        )
        severe_pfs = [indexed[(strategy, split, "severe")]["profit_factor"] for split in TRAINING_SPLITS]
        minimum_severe_pf = min(value for value in severe_pfs if value is not None) if all(value is not None for value in severe_pfs) else None
        aggregate_severe_net = sum(indexed[(strategy, split, "severe")]["net_profit_usdt"] for split in TRAINING_SPLITS)
        results.append(
            {
                "strategy": strategy,
                "eligible": all(gate["status"] == "PASS" for gate in gates),
                "minimum_yearly_severe_profit_factor": minimum_severe_pf,
                "aggregate_severe_net_profit_usdt": aggregate_severe_net,
                "aggregate_standard_net_profit_usdt": standard_net,
                "gates": gates,
            }
        )
    eligible = [item for item in results if item["eligible"]]
    selected = None
    if eligible:
        eligible.sort(
            key=lambda item: (
                item["minimum_yearly_severe_profit_factor"],
                item["aggregate_severe_net_profit_usdt"],
            ),
            reverse=True,
        )
        selected = eligible[0]["strategy"]
    return results, selected


def validation_result(
    rows: list[dict[str, Any]], selected: str | None, provided_splits: set[str]
) -> dict[str, Any]:
    if selected is None:
        return {"status": "NOT_RUN_NO_TRAINING_WINNER", "strategy": None, "gates": []}
    if not set(VALIDATION_SPLITS).issubset(provided_splits):
        return {"status": "PENDING", "strategy": selected, "gates": []}
    indexed = row_index(rows)
    gates: list[dict[str, Any]] = []
    for split in VALIDATION_SPLITS:
        standard = indexed[(selected, split, "standard")]
        if split in ("2024", "2025"):
            gates.append(
                {
                    "name": f"{split}_minimum_20_trades",
                    "status": "PASS" if standard["trades"] >= 20 else "FAIL",
                    "actual": standard["trades"],
                    "requirement": ">= 20",
                }
            )
        for scenario_name in SCENARIOS:
            row = indexed[(selected, split, scenario_name)]
            gates.append(
                {
                    "name": f"{split}_{scenario_name}",
                    "status": "PASS" if scenario_pass(row, scenario_name) else "FAIL",
                    "actual": {
                        "net_profit_usdt": row["net_profit_usdt"],
                        "profit_factor": row["profit_factor"],
                        "realized_drawdown_pct": row["realized_drawdown_pct"],
                    },
                }
            )
    return {
        "status": "PASS" if all(gate["status"] == "PASS" for gate in gates) else "FAIL",
        "strategy": selected,
        "gates": gates,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_artifacts(values: list[str]) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ResearchError(f"Artifact must be SPLIT=PATH: {value}")
        split, path = value.split("=", 1)
        if split in artifacts:
            raise ResearchError(f"Duplicate split: {split}")
        artifacts[split] = Path(path)
    missing = sorted(set(TRAINING_SPLITS) - set(artifacts))
    if missing:
        raise ResearchError(f"Missing training splits: {', '.join(missing)}")
    return artifacts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", required=True, help="SPLIT=ARCHIVE")
    parser.add_argument("--output", default="user_data/reports/cost_research_decision.json")
    parser.add_argument("--csv", default="user_data/reports/cost_research_metrics.csv")
    args = parser.parse_args()
    artifacts = parse_artifacts(args.artifact)
    rows = evaluate_artifacts(artifacts)
    candidates, selected = training_selection(rows)
    validation = validation_result(rows, selected, set(artifacts))
    if selected is None:
        decision = "RETAIN_V2R"
    elif validation["status"] == "PASS":
        decision = "OFFLINE_CHALLENGER_ONLY"
    elif validation["status"] == "FAIL":
        decision = "RETAIN_V2R"
    else:
        decision = "VALIDATE_SINGLE_TRAINING_WINNER"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locked_plan": "docs/cost_robust_challenger_locked_plan.md",
        "artifacts": {
            key: {
                "path": str(value).replace("\\", "/"),
                "bytes": value.stat().st_size,
                "sha256": sha256_file(value),
            }
            for key, value in artifacts.items()
        },
        "training_candidates": candidates,
        "selected_training_winner": selected,
        "validation": validation,
        "decision": decision,
        "active_strategy_changed": False,
        "live_trading_authorized": False,
        "note": "Historical diagnostic only; no profit guarantee and no fresh sealed holdout.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    write_csv(Path(args.csv), rows)
    print(json.dumps({"decision": decision, "selected": selected, "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
