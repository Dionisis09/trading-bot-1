from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "dual_trend_v4r_validation.ipynb"
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

This notebook validates the new matched-risk sizing candidate `DualTrendFuturesV4R`
against the existing `DualTrendFuturesV2R` benchmark. It reads raw Freqtrade
archive exports, recomputes metrics from trade rows, compares the candidate to
the incumbent across every locked split, and writes the decision evidence.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the annotated V4R archives"),
        new_code_cell(
            '''from pathlib import Path
import json
import zipfile
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
BACKTEST_DIR = PROJECT_ROOT / "user_data" / "backtest_results"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
STRATEGIES = ("DualTrendFuturesV2R", "DualTrendFuturesV4R")

records, raw = [], {}
for meta_path in sorted(BACKTEST_DIR.glob("*.meta.json")):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    selected = [s for s in STRATEGIES if s in meta and meta[s].get("notes", "").startswith("phase=dual_v4r;")]
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
            "long_trades": int(stats["trade_count_long"]),
            "short_trades": int(stats["trade_count_short"]),
            "return_pct": 100 * float(stats["profit_total"]),
            "profit_abs_usdt": float(stats["profit_total_abs"]),
            "profit_factor": float(stats["profit_factor"]),
            "max_drawdown_pct": 100 * float(stats["max_drawdown_account"]),
            "market_change_pct": 100 * float(stats["market_change"]),
        })
        raw[(strategy, split)] = stats

summary = pd.DataFrame(records).sort_values(["run_epoch", "strategy"]).reset_index(drop=True)
required_splits = {"train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"}
assert set(summary.split) == required_splits, (required_splits - set(summary.split), set(summary.split) - required_splits)
summary.to_csv(REPORT_DIR / "dual_trend_v4r_backtest_summary.csv", index=False)
display(summary)
'''
        ),
        new_markdown_cell("### 2. Compare V4R candidate with incumbent V2R"),
        new_code_cell(
            '''summary = pd.read_csv(REPORT_DIR / "dual_trend_v4r_backtest_summary.csv")
incumbent = summary[summary.strategy == "DualTrendFuturesV2R"].set_index("split")
challenger = summary[summary.strategy == "DualTrendFuturesV4R"].set_index("split")
comparison_rows = []
for split in ["train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"]:
    i = incumbent.loc[split]
    c = challenger.loc[split]
    comparison_rows.append({
        "split": split,
        "v2r_trades": int(i.trades),
        "v4r_trades": int(c.trades),
        "v2r_return_pct": i.return_pct,
        "v4r_return_pct": c.return_pct,
        "return_delta_pp": c.return_pct - i.return_pct,
        "v2r_profit_factor": i.profit_factor,
        "v4r_profit_factor": c.profit_factor,
        "pf_delta": c.profit_factor - i.profit_factor,
        "v2r_max_drawdown_pct": i.max_drawdown_pct,
        "v4r_max_drawdown_pct": c.max_drawdown_pct,
        "drawdown_delta_pp": c.max_drawdown_pct - i.max_drawdown_pct,
        "v2r_return_to_dd": i.return_pct / i.max_drawdown_pct,
        "v4r_return_to_dd": c.return_pct / c.max_drawdown_pct,
        "return_to_dd_delta_pct": 100 * ((c.return_pct / c.max_drawdown_pct) / (i.return_pct / i.max_drawdown_pct) - 1),
    })
comparison = pd.DataFrame(comparison_rows)
comparison.to_csv(REPORT_DIR / "dual_trend_v4r_vs_v2r.csv", index=False)
display(comparison)
'''
        ),
        new_markdown_cell("### 3. Recompute raw trade metrics for every run"),
        new_code_cell(
            '''def recomputed_pf(values):
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")

reconciliation_rows = []
for (strategy, split), stats in raw.items():
    trades = pd.DataFrame(stats["trades"])
    reconciliation_rows.append({
        "strategy": strategy,
        "split": split,
        "stored_trades": int(stats["total_trades"]),
        "recomputed_trades": len(trades),
        "stored_profit_abs": float(stats["profit_total_abs"]),
        "recomputed_profit_abs": float(trades.profit_abs.sum()),
        "stored_pf": float(stats["profit_factor"]),
        "recomputed_pf": recomputed_pf(trades.profit_abs),
        "stored_wins": int(stats["wins"]),
        "recomputed_wins": int((trades.profit_abs > 0).sum()),
        "stored_losses": int(stats["losses"]),
        "recomputed_losses": int((trades.profit_abs < 0).sum()),
    })
reconciliation = pd.DataFrame(reconciliation_rows).sort_values(["strategy", "split"])
assert (reconciliation.stored_trades == reconciliation.recomputed_trades).all()
assert np.allclose(reconciliation.stored_profit_abs, reconciliation.recomputed_profit_abs, atol=1e-6)
assert np.allclose(reconciliation.stored_pf, reconciliation.recomputed_pf, atol=1e-12)
assert (reconciliation.stored_wins == reconciliation.recomputed_wins).all()
assert (reconciliation.stored_losses == reconciliation.recomputed_losses).all()
reconciliation.to_csv(REPORT_DIR / "dual_trend_v4r_backtest_reconciliation.csv", index=False)
display(reconciliation)
'''
        ),
        new_markdown_cell("### 4. Apply direct superiority gates for V4R"),
        new_code_cell(
            '''comparison = pd.read_csv(REPORT_DIR / "dual_trend_v4r_vs_v2r.csv").set_index("split")

gates = {
    "validation_return_at_least_v2r": comparison.loc["validation", "v4r_return_pct"] >= comparison.loc["validation", "v2r_return_pct"],
    "validation_pf_at_least_v2r": comparison.loc["validation", "v4r_profit_factor"] >= comparison.loc["validation", "v2r_profit_factor"],
    "validation_dd_not_worse": comparison.loc["validation", "v4r_max_drawdown_pct"] <= comparison.loc["validation", "v2r_max_drawdown_pct"],
    "year_2025_return_at_least_v2r": comparison.loc["2025", "v4r_return_pct"] >= comparison.loc["2025", "v2r_return_pct"],
    "current_2026_return_at_least_v2r": comparison.loc["current_2026", "v4r_return_pct"] >= comparison.loc["current_2026", "v2r_return_pct"],
    "fee_validation_return_at_least_v2r": comparison.loc["fee_validation", "v4r_return_pct"] >= comparison.loc["fee_validation", "v2r_return_pct"],
    "fee_validation_pf_at_least_v2r": comparison.loc["fee_validation", "v4r_profit_factor"] >= comparison.loc["fee_validation", "v2r_profit_factor"],
}
gates_df = pd.DataFrame([{"gate": k, "pass": bool(v)} for k, v in gates.items()])
gates_df.to_csv(REPORT_DIR / "dual_trend_v4r_superiority_gates.csv", index=False)
display(gates_df)
'''
        ),
        new_markdown_cell("### 5. Write the candidate decision evidence"),
        new_code_cell(
            '''comparison = pd.read_csv(REPORT_DIR / "dual_trend_v4r_vs_v2r.csv").set_index("split")
from pathlib import Path

REPORT_DIR = Path("user_data") / "reports"
gates_df = pd.read_csv(REPORT_DIR / "dual_trend_v4r_superiority_gates.csv")

decision = {
    "decision": "DUAL_TREND_V4R_SUPERIOR" if gates_df["pass"].all() else "DUAL_TREND_V4R_NOT_SUPERIOR",
    "candidate": "DualTrendFuturesV4R",
    "baseline": "DualTrendFuturesV2R",
    "validation_return_pct": float(comparison.loc["validation", "v4r_return_pct"]),
    "baseline_validation_return_pct": float(comparison.loc["validation", "v2r_return_pct"]),
    "validation_profit_factor": float(comparison.loc["validation", "v4r_profit_factor"]),
    "baseline_validation_profit_factor": float(comparison.loc["validation", "v2r_profit_factor"]),
    "validation_drawdown_pct": float(comparison.loc["validation", "v4r_max_drawdown_pct"]),
    "baseline_validation_drawdown_pct": float(comparison.loc["validation", "v2r_max_drawdown_pct"]),
    "superiority_gates_passed": int(gates_df["pass"].sum()),
    "superiority_gates_total": len(gates_df),
}
(REPORT_DIR / "dual_trend_v4r_validation_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
display(decision)
'''
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
    print((REPORT_DIR / "dual_trend_v4r_validation_decision.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
