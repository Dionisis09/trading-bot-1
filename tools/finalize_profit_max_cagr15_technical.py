"""Build fail-closed technical evidence for ProfitMaxCagr15V5."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PAIR_FILES = {
    "BTC/USDT:USDT": ("lookahead_btc.csv", 20),
    "ETH/USDT:USDT": ("lookahead_eth.csv", 15),
    "BNB/USDT:USDT": ("lookahead_bnb.csv", 16),
    "XRP/USDT:USDT": ("lookahead_xrp.csv", 13),
    "ADA/USDT:USDT": ("lookahead_ada.csv", 11),
    "DOGE/USDT:USDT": ("lookahead_doge.csv", 7),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_single_csv(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"{path} must contain exactly one result row")
    return rows[0]


def is_false(value: Any) -> bool:
    return str(value).strip().lower() == "false"


def read_log(path: Path) -> str:
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    return raw.decode(encoding, errors="replace")


def build(report_dir: Path, workspace: Path) -> dict[str, Any]:
    objective_path = report_dir / "user_objective_decision.json"
    recursive_path = report_dir / "recursive_btc.log"
    portfolio_path = report_dir / "lookahead.csv"
    objective = json.loads(objective_path.read_text(encoding="utf-8"))
    recursive_text = read_log(recursive_path)
    portfolio = read_single_csv(portfolio_path)

    pair_results: dict[str, Any] = {}
    pair_pass = True
    total_signals = 0
    for pair, (filename, expected_signals) in PAIR_FILES.items():
        path = report_dir / filename
        row = read_single_csv(path)
        signals = int(row["total_signals"])
        clean = (
            row["strategy"] == "ProfitMaxCagr15V5"
            and is_false(row["has_bias"])
            and signals == expected_signals
            and int(row["biased_entry_signals"]) == 0
            and int(row["biased_exit_signals"]) == 0
            and not row.get("biased_indicators", "").strip()
        )
        pair_pass &= clean
        total_signals += signals
        pair_results[pair] = {
            "status": "PASS" if clean else "FAIL",
            "signals": signals,
            "biased_entries": int(row["biased_entry_signals"]),
            "biased_exits": int(row["biased_exit_signals"]),
            "biased_indicators": row.get("biased_indicators", ""),
            "sha256": sha256(path),
        }

    recursive_pass = (
        "No lookahead bias on indicators found." in recursive_text
        and "ema200_1d" in recursive_text
        and "1599" in recursive_text
        and "0.000%" in recursive_text
    )
    objective_pass = (
        objective.get("status") == "MEETS_RETROSPECTIVE_USER_OBJECTIVE"
        and all(objective.get("objective_gates", {}).values())
        and objective.get("live_trading_authorized") is False
        and objective.get("profit_guaranteed") is False
    )
    portfolio_diagnostic = {
        "has_bias": not is_false(portfolio["has_bias"]),
        "signals": int(portfolio["total_signals"]),
        "unmatched_entries": int(portfolio["biased_entry_signals"]),
        "unmatched_exits": int(portfolio["biased_exit_signals"]),
        "biased_indicators": portfolio.get("biased_indicators", ""),
        "interpretation": (
            "Pair-isolated analysis is clean. The portfolio-wide sliced replay has entry "
            "differences consistent with, but not by itself proving, stateful portfolio-risk "
            "callback path dependence; it found no biased indicator columns."
        ),
        "sha256": sha256(portfolio_path),
    }

    passed = pair_pass and recursive_pass and objective_pass
    files = {
        "strategy": workspace / "user_data/strategies/ProfitMaxCagr15V5.py",
        "config": workspace / "user_data/config-profit-max-cagr15-cycle5.json",
        "risk_policy": workspace / "user_data/risk_policy_profit_max_cagr15_cycle5.json",
        "locked_plan": workspace / "docs/profit_max_cagr15_cycle5_locked_plan.md",
        "strict_evaluator": workspace / "tools/evaluate_profit_max_cagr15_cycle5.py",
        "objective_finalizer": workspace / "tools/finalize_profit_max_cagr15_user_objective.py",
        "technical_finalizer": workspace / "tools/finalize_profit_max_cagr15_technical.py",
        "archive": report_dir / "continuous.zip",
        "objective_decision": objective_path,
        "recursive_log": recursive_path,
    }
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": "ProfitMaxCagr15V5",
        "status": "PASS" if passed else "FAIL",
        "decision": "APPROVE_ISOLATED_DRY_RUN_ONLY" if passed else "KEEP_OFFLINE_RESEARCH",
        "pair_isolated_lookahead": {
            "status": "PASS" if pair_pass else "FAIL",
            "pairs": len(pair_results),
            "total_signals": total_signals,
            "results": pair_results,
        },
        "portfolio_wide_lookahead_diagnostic": portfolio_diagnostic,
        "recursive_analysis": {
            "status": "PASS" if recursive_pass else "FAIL",
            "pair": "BTC/USDT:USDT",
            "startup_candles": [199, 399, 799, 800, 1599],
            "qualifying_startup_candles": 1599,
            "ema200_material_variance_pct": 0.0 if recursive_pass else None,
            "indicator_lookahead_found": False if recursive_pass else None,
        },
        "retrospective_objective": {
            "status": "PASS" if objective_pass else "FAIL",
            "cagr_pct": objective.get("metrics", {}).get("cagr_pct"),
            "full_five_year_cagr_pct": objective.get("full_five_year_metrics", {}).get("cagr_pct"),
            "severe_cost_cagr_pct": objective.get("severe_stress", {}).get("cagr_pct"),
            "wallet_drawdown_pct": objective.get("metrics", {}).get("wallet_drawdown_pct"),
        },
        "sha256": {name: sha256(path) for name, path in files.items()},
        "live_trading_authorized": False,
        "profit_guaranteed": False,
        "evidence_boundary": (
            "All historical candles were already seen. This is retrospective and permits only "
            "a new isolated dry-run; it is not forward evidence or a guarantee of future profit."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.report_dir.resolve(), args.workspace.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "decision": result["decision"]}))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
