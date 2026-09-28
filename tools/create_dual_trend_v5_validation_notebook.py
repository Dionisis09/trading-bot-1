from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "dual_trend_v5_validation.ipynb"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell(
            """## tl;dr

Execution pending. This section is replaced after a successful top-to-bottom run.
"""
        ),
        new_markdown_cell(
            """## Context & Methods

This notebook validates the new matched-risk sizing candidate `DualTrendFuturesV5`
against the existing `DualTrendFuturesV2R` benchmark. It reads raw Freqtrade
archive exports, recomputes metrics from trade rows, compares the candidate to
the incumbent across every locked split, and writes the decision evidence.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the annotated V5 archives"),
        new_code_cell(
            """from pathlib import Path
import json
import zipfile
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
BACKTEST_DIR = PROJECT_ROOT / "user_data" / "backtest_results"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
STRATEGIES = ("DualTrendFuturesV2R", "DualTrendFuturesV5")

records, raw = [], {}
for meta_path in sorted(BACKTEST_DIR.glob("*.meta.json")):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # Collect any strategy entries whose notes indicate they're part of the
    # V5 validation phase or the V2R baseline for the same split.
    selected = []
    for strat_key, strat_meta in meta.items():
        notes = strat_meta.get("notes", "")
        if notes.startswith("phase=dual_v5;") or notes.startswith("phase=dual_v2r;"):
            selected.append(strat_key)
    if not selected:
        continue
    base = meta_path.name.removesuffix(".meta.json")
    zip_path = BACKTEST_DIR / f"{base}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        result = json.loads(archive.read(f"{base}.json"))
    for strategy in selected:
        run_meta = meta[strategy]
        notes = run_meta.get("notes", "")
        split = next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("split="))
        fee = float(next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("fee=")))
        stats = result["strategy"][strategy]
        records.append({
            "artifact": zip_path.name,
            "strategy": strategy,
            "split": split,
            "fee_per_side": fee,
            "run_epoch": int(run_meta["backtest_start_time"]),
            "trades": int(stats["total_trades"]),
            "long_trades": int(stats.get("trade_count_long", 0)),
            "short_trades": int(stats.get("trade_count_short", 0)),
            "return_pct": 100 * float(stats.get("profit_total", 0)),
            "profit_abs_usdt": float(stats.get("profit_total_abs", 0)),
            "profit_factor": float(stats.get("profit_factor", 0)),
            "max_drawdown_pct": 100 * float(stats.get("max_drawdown_account", 0)),
            "market_change_pct": 100 * float(stats.get("market_change", 0)),
        })
        raw[(strategy, split)] = stats

summary = pd.DataFrame(records).sort_values(["run_epoch", "strategy"]).reset_index(drop=True)
required_splits = {"train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"}
assert set(summary.split) == required_splits, (required_splits - set(summary.split), set(summary.split) - required_splits)
summary.to_csv(REPORT_DIR / "dual_trend_v5_backtest_summary.csv", index=False)
display(summary)
"""
        ),
        new_markdown_cell("### 2. Compare V5 candidate with incumbent V2R"),
        new_code_cell(
            """summary = pd.read_csv(REPORT_DIR / "dual_trend_v5_backtest_summary.csv")
incumbent = summary[summary.strategy == "DualTrendFuturesV2R"].set_index("split")
challenger = summary[summary.strategy == "DualTrendFuturesV5"].set_index("split")
comparison_rows = []
for split in ["train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"]:
    i = incumbent.loc[split]
    c = challenger.loc[split]
    comparison_rows.append({
        "split": split,
        "v2r_trades": int(i.trades),
        "v5_trades": int(c.trades),
        "v2r_return_pct": i.return_pct,
        "v5_return_pct": c.return_pct,
        "return_delta_pp": c.return_pct - i.return_pct,
        "v2r_profit_factor": i.profit_factor,
        "v5_profit_factor": c.profit_factor,
        "pf_delta": c.profit_factor - i.profit_factor,
        "v2r_max_drawdown_pct": i.max_drawdown_pct,
        "v5_max_drawdown_pct": c.max_drawdown_pct,
        "drawdown_delta_pp": c.max_drawdown_pct - i.max_drawdown_pct,
        "v2r_return_to_dd": i.return_pct / i.max_drawdown_pct,
        "v5_return_to_dd": c.return_pct / c.max_drawdown_pct,
        "return_to_dd_delta_pct": 100 * ((c.return_pct / c.max_drawdown_pct) / (i.return_pct / i.max_drawdown_pct) - 1),
    })
comparison = pd.DataFrame(comparison_rows)
comparison.to_csv(REPORT_DIR / "dual_trend_v5_vs_v2r.csv", index=False)
display(comparison)
"""
        ),
        new_markdown_cell("### 3. Recompute raw trade metrics for every run"),
        new_code_cell(
            """def recomputed_pf(values):
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")

reconciliation_rows = []
for (strategy, split), stats in raw.items():
    trades = pd.DataFrame(stats["trades"]) if isinstance(stats.get("trades"), list) else pd.DataFrame(stats.get("trades", []))
    reconciliation_rows.append({
        "strategy": strategy,
        "split": split,
        "stored_trades": int(stats.get("total_trades", 0)),
        "recomputed_trades": len(trades),
        "stored_profit_abs": float(stats.get("profit_total_abs", 0)),
        "recomputed_profit_abs": float(trades.profit_abs.sum()) if not trades.empty and 'profit_abs' in trades.columns else float(0.0),
        "stored_pf": float(stats.get("profit_factor", 0)),
        "recomputed_pf": recomputed_pf(trades.profit_abs) if not trades.empty and 'profit_abs' in trades.columns else float(0.0),
        "stored_wins": int(stats.get("wins", 0)),
        "recomputed_wins": int((trades.profit_abs > 0).sum()) if not trades.empty and 'profit_abs' in trades.columns else int(0),
        "stored_losses": int(stats.get("losses", 0)),
        "recomputed_losses": int((trades.profit_abs < 0).sum()) if not trades.empty and 'profit_abs' in trades.columns else int(0),
    })
reconciliation = pd.DataFrame(reconciliation_rows).sort_values(["strategy", "split"])
reconciliation.to_csv(REPORT_DIR / "dual_trend_v5_backtest_reconciliation.csv", index=False)
display(reconciliation)
"""
        ),
        new_markdown_cell("### 4. Apply direct superiority gates for V5"),
        new_code_cell(
            """comparison = pd.read_csv(REPORT_DIR / "dual_trend_v5_vs_v2r.csv").set_index("split")

gates = {
    "validation_return_at_least_v2r": comparison.loc["validation", "v5_return_pct"] >= comparison.loc["validation", "v2r_return_pct"],
    "validation_pf_at_least_v2r": comparison.loc["validation", "v5_profit_factor"] >= comparison.loc["validation", "v2r_profit_factor"],
    "validation_dd_not_worse": comparison.loc["validation", "v5_max_drawdown_pct"] <= comparison.loc["validation", "v2r_max_drawdown_pct"],
    "year_2025_return_at_least_v2r": comparison.loc["2025", "v5_return_pct"] >= comparison.loc["2025", "v2r_return_pct"],
    "current_2026_return_at_least_v2r": comparison.loc["current_2026", "v5_return_pct"] >= comparison.loc["current_2026", "v2r_return_pct"],
    "fee_validation_return_at_least_v2r": comparison.loc["fee_validation", "v5_return_pct"] >= comparison.loc["fee_validation", "v2r_return_pct"],
    "fee_validation_pf_at_least_v2r": comparison.loc["fee_validation", "v5_profit_factor"] >= comparison.loc["fee_validation", "v2r_profit_factor"],
}
G = pd.DataFrame([{"gate": k, "pass": bool(v)} for k, v in gates.items()])
G.to_csv(REPORT_DIR / "dual_trend_v5_superiority_gates.csv", index=False)
display(G)
"""
        ),
        new_markdown_cell("### 5. Write the candidate decision evidence"),
        new_code_cell(
            """comparison = pd.read_csv(REPORT_DIR / "dual_trend_v5_vs_v2r.csv").set_index("split")
from pathlib import Path

REPORT_DIR = Path("user_data") / "reports"
G = pd.read_csv(REPORT_DIR / "dual_trend_v5_superiority_gates.csv")

decision = {
    "decision": "DUAL_TREND_V5_SUPERIOR" if G["pass"].all() else "DUAL_TREND_V5_NOT_SUPERIOR",
    "candidate": "DualTrendFuturesV5",
    "baseline": "DualTrendFuturesV2R",
    "validation_return_pct": float(comparison.loc["validation", "v5_return_pct"]),
    "baseline_validation_return_pct": float(comparison.loc["validation", "v2r_return_pct"]),
    "validation_profit_factor": float(comparison.loc["validation", "v5_profit_factor"]),
    "baseline_validation_profit_factor": float(comparison.loc["validation", "v2r_profit_factor"]),
    "validation_drawdown_pct": float(comparison.loc["validation", "v5_max_drawdown_pct"]),
    "baseline_validation_drawdown_pct": float(comparison.loc["validation", "v2r_max_drawdown_pct"]),
    "superiority_gates_passed": int(G["pass"].sum()),
    "superiority_gates_total": len(G),
}
(REPORT_DIR / "dual_trend_v5_validation_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
display(decision)
"""
        ),
    ]
    return new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {"display_name": "Trading Bot Validation", "language": "python", "name": "trading-bot-validation"},
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
    print(NOTEBOOK_PATH)
    print((REPORT_DIR / "dual_trend_v5_validation_decision.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
