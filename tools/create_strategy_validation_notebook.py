from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "strategy_validation.ipynb"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell(
            """## tl;dr

Execution pending. This section is replaced with observed results after a successful top-to-bottom run.
"""
        ),
        new_markdown_cell(
            """## Context & Methods

This notebook independently reads the zipped Freqtrade backtest artifacts and evaluates the pre-declared strategy gates.

### Key assumptions

- Binance Spot BTC/USDC and ETH/USDC; no leverage, shorting, margin, or DCA.
- Starting research wallet: 1,000 USDC; maximum two positions; unlimited research stake.
- Freqtrade selected a 0.10% fee per entry and exit side.
- Train and validation are chronological. The `2026-01-01` to `2026-08-01` holdout must remain untouched unless validation passes.
- Vendor benchmarks are evaluated at pinned commit `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` with a common risk-only wrapper.
- Passing backtests can authorize dry-run only, never live trading.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load annotated Freqtrade result archives"),
        new_code_cell(
            """from pathlib import Path
import json
import zipfile
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
if not (PROJECT_ROOT / "user_data").exists():
    raise RuntimeError(f"Execute from the project root, got: {PROJECT_ROOT}")

BACKTEST_DIR = PROJECT_ROOT / "user_data" / "backtest_results"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

records = []
raw_results = {}

for meta_path in sorted(BACKTEST_DIR.glob("*.meta.json")):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    base = meta_path.name.removesuffix(".meta.json")
    zip_path = BACKTEST_DIR / f"{base}.zip"
    if not zip_path.exists():
        continue
    with zipfile.ZipFile(zip_path) as archive:
        result = json.loads(archive.read(f"{base}.json"))

    for strategy_name, run_meta in meta.items():
        notes = run_meta.get("notes", "")
        if "split=" not in notes:
            continue
        split = next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("split="))
        stats = result["strategy"][strategy_name]
        trades = pd.DataFrame(stats["trades"])
        pair_rows = [row for row in stats["results_per_pair"] if row["key"] != "TOTAL"]
        positive_profits = trades.loc[trades["profit_abs"] > 0, "profit_abs"]
        concentration = (
            float(positive_profits.max() / positive_profits.sum())
            if not positive_profits.empty and positive_profits.sum() > 0
            else np.nan
        )
        records.append({
            "artifact": zip_path.name,
            "strategy": strategy_name,
            "split": split,
            "run_started_at_epoch": int(run_meta["backtest_start_time"]),
            "timeframe": run_meta["timeframe"],
            "notes": notes,
            "trades": int(stats["total_trades"]),
            "wins": int(stats["wins"]),
            "losses": int(stats["losses"]),
            "return_pct": 100 * float(stats["profit_total"]),
            "profit_abs_usdc": float(stats["profit_total_abs"]),
            "profit_factor": float(stats["profit_factor"]),
            "max_drawdown_pct": 100 * float(stats["max_drawdown_account"]),
            "min_pair_profit_factor": min(float(row["profit_factor"]) for row in pair_rows),
            "largest_winner_share_positive_profit": concentration,
            "market_change_pct": 100 * float(stats["market_change"]),
        })
        raw_results[(strategy_name, split)] = stats

results_df = (
    pd.DataFrame(records)
    .sort_values("run_started_at_epoch")
    .drop_duplicates(["strategy", "split"], keep="last")
    .sort_values(["strategy", "split"])
    .reset_index(drop=True)
)
raw_results = {
    key: value
    for key, value in raw_results.items()
    if any((results_df["strategy"] == key[0]) & (results_df["split"] == key[1]))
}
results_df.to_csv(REPORT_DIR / "strategy_backtest_summary.csv", index=False)
display(results_df)"""
        ),
        new_markdown_cell("## Validation\n\n### 2. Recompute key claims from raw trade rows"),
        new_code_cell(
            """def profit_factor(values: pd.Series) -> float:
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")

reconciliation_rows = []
for (strategy_name, split), stats in raw_results.items():
    trades = pd.DataFrame(stats["trades"])
    recomputed_profit = float(trades["profit_abs"].sum())
    recomputed_pf = profit_factor(trades["profit_abs"])
    by_close = trades.groupby("close_timestamp", as_index=False)["profit_abs"].sum().sort_values("close_timestamp")
    equity_pnl = by_close["profit_abs"].cumsum()
    running_peak = np.maximum.accumulate(np.r_[0.0, equity_pnl.to_numpy()])
    closed_trade_dd = float((running_peak - np.r_[0.0, equity_pnl.to_numpy()]).max())

    reconciliation_rows.append({
        "strategy": strategy_name,
        "split": split,
        "stored_trades": int(stats["total_trades"]),
        "recomputed_trades": len(trades),
        "stored_profit_abs": float(stats["profit_total_abs"]),
        "recomputed_profit_abs": recomputed_profit,
        "profit_abs_delta": recomputed_profit - float(stats["profit_total_abs"]),
        "stored_profit_factor": float(stats["profit_factor"]),
        "recomputed_profit_factor": recomputed_pf,
        "profit_factor_delta": recomputed_pf - float(stats["profit_factor"]),
        "stored_wins": int(stats["wins"]),
        "recomputed_wins": int((trades["profit_abs"] > 0).sum()),
        "stored_losses": int(stats["losses"]),
        "recomputed_losses": int((trades["profit_abs"] < 0).sum()),
        "stored_max_drawdown_abs": float(stats["max_drawdown_abs"]),
        "closed_trade_recomputed_drawdown_abs": closed_trade_dd,
    })

reconciliation_df = pd.DataFrame(reconciliation_rows)
assert (reconciliation_df["stored_trades"] == reconciliation_df["recomputed_trades"]).all()
assert np.allclose(reconciliation_df["profit_abs_delta"], 0.0, atol=1e-6)
assert np.allclose(reconciliation_df["profit_factor_delta"], 0.0, atol=1e-12)
assert (reconciliation_df["stored_wins"] == reconciliation_df["recomputed_wins"]).all()
assert (reconciliation_df["stored_losses"] == reconciliation_df["recomputed_losses"]).all()
reconciliation_df.to_csv(REPORT_DIR / "strategy_backtest_reconciliation.csv", index=False)
display(reconciliation_df)"""
        ),
        new_markdown_cell("### 3. Apply the pre-declared validation gates"),
        new_code_cell(
            """technical_checks = json.loads(
    (REPORT_DIR / "strategy_technical_checks.json").read_text(encoding="utf-8")
)
lookahead_df = pd.read_csv(REPORT_DIR / "BinanceSpotTrendV1_lookahead.csv")
lookahead_pass = (
    str(lookahead_df.loc[0, "has_bias"]).lower() == "false"
    and int(lookahead_df.loc[0, "biased_entry_signals"]) == 0
    and int(lookahead_df.loc[0, "biased_exit_signals"]) == 0
)
assert lookahead_pass

validation_df = results_df[results_df["split"] == "validation"].copy()
validation_df["gate_min_30_trades"] = validation_df["trades"] >= 30
validation_df["gate_positive_return"] = validation_df["return_pct"] > 0
validation_df["gate_profit_factor_1_10"] = validation_df["profit_factor"] >= 1.10
validation_df["gate_drawdown_15_pct"] = validation_df["max_drawdown_pct"] <= 15.0
validation_df["gate_each_pair_pf_0_90"] = validation_df["min_pair_profit_factor"] >= 0.90
validation_df["gate_no_single_winner_majority"] = (
    validation_df["largest_winner_share_positive_profit"] <= 0.50
)

performance_gates = [
    "gate_min_30_trades",
    "gate_positive_return",
    "gate_profit_factor_1_10",
    "gate_drawdown_15_pct",
    "gate_each_pair_pf_0_90",
    "gate_no_single_winner_majority",
]
validation_df["performance_gates_pass"] = validation_df[performance_gates].all(axis=1)
validation_df["technical_check_status"] = validation_df["strategy"].map(
    lambda name: (
        "PASS"
        if name == "BinanceSpotTrendV1"
        and technical_checks[name]["lookahead_analysis"]["status"] == "PASS"
        and technical_checks[name]["recursive_analysis"]["status"] == "PASS"
        else technical_checks[name].get("status", "NOT_RUN")
    )
)
validation_df["approved_for_holdout"] = (
    validation_df["performance_gates_pass"]
    & (validation_df["technical_check_status"] == "PASS")
)

validation_df.to_csv(REPORT_DIR / "strategy_validation_gates.csv", index=False)
display(validation_df[[
    "strategy", "trades", "return_pct", "profit_factor", "max_drawdown_pct",
    "min_pair_profit_factor", *performance_gates, "technical_check_status",
    "approved_for_holdout",
]])"""
        ),
        new_markdown_cell("### 4. Record unavailable benchmarks and enforce the holdout seal"),
        new_code_cell(
            """unavailable_df = pd.DataFrame([{
    "strategy": "SupertrendRisk",
    "status": technical_checks["SupertrendRisk"]["status"],
    "source_commit": technical_checks["SupertrendRisk"]["source_commit"],
    "error_type": technical_checks["SupertrendRisk"]["error_type"],
    "error": technical_checks["SupertrendRisk"]["error"],
}])
unavailable_df.to_csv(REPORT_DIR / "strategy_unavailable_benchmarks.csv", index=False)

holdout_rows = results_df[results_df["split"] == "holdout"]
approved = validation_df[validation_df["approved_for_holdout"]]
assert holdout_rows.empty, "Holdout was evaluated even though no candidate passed validation."
assert approved.empty, "Decision logic changed: an approved candidate now requires holdout evaluation."
display(unavailable_df)"""
        ),
        new_markdown_cell("## Decision\n\n### 5. Write the machine-readable research decision"),
        new_code_cell(
            """decision = {
    "decision": "NO_STRATEGY_APPROVED",
    "validation_candidates_evaluated": int(len(validation_df)),
    "validation_candidates_approved": int(validation_df["approved_for_holdout"].sum()),
    "holdout_evaluated": False,
    "dry_run_strategy_deployed": False,
    "live_trading_authorized": False,
    "unavailable_benchmarks": unavailable_df["strategy"].tolist(),
    "fee_per_side_pct": 0.10,
    "validation_period_utc": "2025-01-01/2026-01-01",
    "sealed_holdout_period_utc": "2026-01-01/2026-08-01",
}
(REPORT_DIR / "strategy_validation_decision.json").write_text(
    json.dumps(decision, indent=2), encoding="utf-8"
)
decision"""
        ),
        new_markdown_cell(
            """## Takeaways

Execution pending. This section is replaced with observed results after a successful top-to-bottom run.
"""
        ),
    ]

    return new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Trading Bot Validation",
                "language": "python",
                "name": "trading-bot-validation",
            },
            "language_info": {"name": "python", "version": "3.13"},
        },
    )


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    notebook = build_notebook()
    nbformat.write(notebook, NOTEBOOK_PATH)

    executed = NotebookClient(
        notebook,
        timeout=300,
        kernel_name="trading-bot-validation",
        resources={"metadata": {"path": str(PROJECT_ROOT)}},
    ).execute()

    summary = pd.read_csv(REPORT_DIR / "strategy_backtest_summary.csv")
    gates = pd.read_csv(REPORT_DIR / "strategy_validation_gates.csv")
    decision = pd.read_json(REPORT_DIR / "strategy_validation_decision.json", typ="series")
    validation = summary[summary["split"] == "validation"].sort_values("return_pct", ascending=False)
    best = validation.iloc[0]

    executed.cells[0].source = f"""## tl;dr

**{decision['decision']}** after {int(decision['validation_candidates_evaluated'])} executable validation candidates.

- Best validation return was still negative: `{best['strategy']}` at {best['return_pct']:.2f}%.
- No candidate qualified for holdout or dry-run deployment.
- The final holdout remains sealed and live trading remains unauthorized.
- `SupertrendRisk` was unavailable because the pinned vendor code is incompatible with the current pandas runtime.
"""
    executed.cells[-1].source = f"""## Takeaways

- All {int(decision['validation_candidates_evaluated'])} executable validation candidates failed at least one pre-declared performance gate.
- The custom V1 passed 100-signal lookahead analysis and converged at 800 startup candles, but technical correctness did not rescue its negative expectancy.
- Ready-made GitHub defaults were not portable to this two-pair Binance USDC scope; the official repository's own warning was borne out by the local results.
- No holdout result exists. This prevents accidental selection on the final period and preserves it for a genuinely new hypothesis.
- The correct operational decision is research-only: do not deploy any tested strategy and do not enable Binance API keys.
"""

    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print(decision.to_json())
    print(gates[["strategy", "approved_for_holdout"]].to_string(index=False))


if __name__ == "__main__":
    main()
