from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "dual_trend_v2_validation.ipynb"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell(
            """## tl;dr

Execution pending. This section is replaced after a successful top-to-bottom run.
"""
        ),
        new_markdown_cell(
            """## Context and methods

This notebook validates the single pre-declared `DualTrendFuturesV2` challenger
from raw Freqtrade archives. It compares V2 with the running V1, recomputes the
stored metrics from trade rows, applies every locked V2 gate, reads independent
lookahead/recursive checks, and verifies that V1 remains the active local
dry-run. The reused periods are not a new sealed holdout.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load annotated V2 archives and V1 benchmark"),
        new_code_cell(
            '''from pathlib import Path
import base64
import json
import urllib.request
import zipfile
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
BACKTEST_DIR = PROJECT_ROOT / "user_data" / "backtest_results"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

records, raw = [], {}
for meta_path in sorted(BACKTEST_DIR.glob("*.meta.json")):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if "DualTrendFuturesV2" not in meta:
        continue
    run_meta = meta["DualTrendFuturesV2"]
    notes = run_meta.get("notes", "")
    if not notes.startswith("phase=dual_v2;"):
        continue
    split = next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("split="))
    fee = float(next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("fee=")))
    base = meta_path.name.removesuffix(".meta.json")
    zip_path = BACKTEST_DIR / f"{base}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        result = json.loads(archive.read(f"{base}.json"))
    stats = result["strategy"]["DualTrendFuturesV2"]
    records.append({
        "artifact": zip_path.name, "split": split, "fee_per_side": fee,
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
    raw[split] = stats

summary = pd.DataFrame(records).sort_values("run_epoch").reset_index(drop=True)
required = {"train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"}
assert set(summary.split) == required, (required - set(summary.split), set(summary.split) - required)
summary.to_csv(REPORT_DIR / "dual_trend_v2_backtest_summary.csv", index=False)

v1 = pd.read_csv(REPORT_DIR / "dual_trend_backtest_summary.csv").set_index("split")
v2 = summary.set_index("split")
comparison_rows = []
for split in ["train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"]:
    comparison_rows.append({
        "split": split,
        "v1_trades": int(v1.loc[split, "trades"]), "v2_trades": int(v2.loc[split, "trades"]),
        "v1_return_pct": v1.loc[split, "return_pct"], "v2_return_pct": v2.loc[split, "return_pct"],
        "return_delta_pp": v2.loc[split, "return_pct"] - v1.loc[split, "return_pct"],
        "v1_profit_factor": v1.loc[split, "profit_factor"], "v2_profit_factor": v2.loc[split, "profit_factor"],
        "pf_delta": v2.loc[split, "profit_factor"] - v1.loc[split, "profit_factor"],
        "v1_max_drawdown_pct": v1.loc[split, "max_drawdown_pct"],
        "v2_max_drawdown_pct": v2.loc[split, "max_drawdown_pct"],
        "drawdown_delta_pp": v2.loc[split, "max_drawdown_pct"] - v1.loc[split, "max_drawdown_pct"],
    })
comparison = pd.DataFrame(comparison_rows)
comparison.to_csv(REPORT_DIR / "dual_trend_v2_vs_v1.csv", index=False)
display(summary)
display(comparison)'''
        ),
        new_markdown_cell("### 2. Confirm the reused market data remains valid"),
        new_code_cell(
            '''quality = pd.read_csv(REPORT_DIR / "dual_trend_data_quality.csv")
timeframe_reconciliation = pd.read_csv(REPORT_DIR / "dual_trend_timeframe_reconciliation.csv")
assert quality[["duplicate_timestamps", "null_cells", "invalid_ohlcv"]].sum().sum() == 0
assert quality["largest_gap_candles"].max() == 0
coverage_cols = [c for c in quality.columns if c.endswith("coverage_pct")]
assert quality[coverage_cols].min().min() == 100.0
assert timeframe_reconciliation["mismatch_pct"].max() <= 0.20
data_check = {
    "same_archives_as_v1": True,
    "rows_profiled": int(quality.rows.sum()),
    "duplicate_timestamps": int(quality.duplicate_timestamps.sum()),
    "null_cells": int(quality.null_cells.sum()),
    "invalid_ohlcv": int(quality.invalid_ohlcv.sum()),
    "largest_gap_candles": int(quality.largest_gap_candles.max()),
    "minimum_split_coverage_pct": float(quality[coverage_cols].min().min()),
    "maximum_4h_1d_mismatch_pct": float(timeframe_reconciliation.mismatch_pct.max()),
}
(REPORT_DIR / "dual_trend_v2_data_check.json").write_text(json.dumps(data_check, indent=2), encoding="utf-8")
data_check'''
        ),
        new_markdown_cell("## Validation\n\n### 3. Recompute metrics from every raw trade row"),
        new_code_cell(
            '''def recomputed_pf(values):
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")

rows = []
for split, stats in raw.items():
    trades = pd.DataFrame(stats["trades"])
    rows.append({
        "split": split,
        "stored_trades": int(stats["total_trades"]), "recomputed_trades": len(trades),
        "stored_profit_abs": float(stats["profit_total_abs"]),
        "recomputed_profit_abs": float(trades.profit_abs.sum()),
        "stored_pf": float(stats["profit_factor"]),
        "recomputed_pf": recomputed_pf(trades.profit_abs),
        "stored_wins": int(stats["wins"]), "recomputed_wins": int((trades.profit_abs > 0).sum()),
        "stored_losses": int(stats["losses"]), "recomputed_losses": int((trades.profit_abs < 0).sum()),
    })
reconciliation = pd.DataFrame(rows).sort_values("split")
assert (reconciliation.stored_trades == reconciliation.recomputed_trades).all()
assert np.allclose(reconciliation.stored_profit_abs, reconciliation.recomputed_profit_abs, atol=1e-6)
assert np.allclose(reconciliation.stored_pf, reconciliation.recomputed_pf, atol=1e-12)
assert (reconciliation.stored_wins == reconciliation.recomputed_wins).all()
assert (reconciliation.stored_losses == reconciliation.recomputed_losses).all()
reconciliation.to_csv(REPORT_DIR / "dual_trend_v2_backtest_reconciliation.csv", index=False)
display(reconciliation)'''
        ),
        new_markdown_cell("### 4. Apply every locked V2 performance gate"),
        new_code_cell(
            '''by_split = summary.set_index("split")
val_stats = raw["validation"]
pair_rows = pd.DataFrame([r for r in val_stats["results_per_pair"] if r["key"] != "TOTAL"])
val_trades = pd.DataFrame(val_stats["trades"])
positive_pairs = pair_rows[pair_rows.profit_total_abs > 0]
pair_concentration = float(positive_pairs.profit_total_abs.max() / positive_pairs.profit_total_abs.sum())
positive_trades = val_trades[val_trades.profit_abs > 0]
trade_concentration = float(positive_trades.profit_abs.max() / positive_trades.profit_abs.sum())

gates = {
    "train_positive": by_split.loc["train", "return_pct"] > 0,
    "train_pf_1_20": by_split.loc["train", "profit_factor"] >= 1.20,
    "validation_100_trades": by_split.loc["validation", "trades"] >= 100,
    "validation_positive": by_split.loc["validation", "return_pct"] > 0,
    "validation_pf_1_50": by_split.loc["validation", "profit_factor"] >= 1.50,
    "validation_dd_12": by_split.loc["validation", "max_drawdown_pct"] <= 12.0,
    "year_2024": (by_split.loc["2024", "return_pct"] > 0 and by_split.loc["2024", "profit_factor"] >= 1.20 and by_split.loc["2024", "trades"] >= 20),
    "year_2025_return_above_v1": by_split.loc["2025", "return_pct"] > v1.loc["2025", "return_pct"],
    "year_2025_pf_1_15": by_split.loc["2025", "profit_factor"] >= 1.15,
    "year_2025_dd_not_above_v1": by_split.loc["2025", "max_drawdown_pct"] <= v1.loc["2025", "max_drawdown_pct"],
    "year_2025_20_trades": by_split.loc["2025", "trades"] >= 20,
    "current_2026": (by_split.loc["current_2026", "return_pct"] > 0 and by_split.loc["current_2026", "profit_factor"] >= 1.30 and by_split.loc["current_2026", "trades"] >= 12 and by_split.loc["current_2026", "max_drawdown_pct"] <= 12),
    "fee_validation_positive": by_split.loc["fee_validation", "return_pct"] > 0,
    "fee_validation_pf_1_30": by_split.loc["fee_validation", "profit_factor"] >= 1.30,
    "validation_five_positive_pairs": int((pair_rows.profit_total > 0).sum()) >= 5,
    "validation_pair_concentration": pair_concentration <= 0.50,
    "validation_trade_concentration": trade_concentration <= 0.25,
}
gates_df = pd.DataFrame([{"gate": key, "pass": bool(value)} for key, value in gates.items()])
assert not gates_df["pass"].all()
assert not gates["validation_dd_12"]
assert not gates["year_2025_dd_not_above_v1"]
gates_df.to_csv(REPORT_DIR / "dual_trend_v2_performance_gates.csv", index=False)
pair_audit = pair_rows[["key", "trades", "profit_total_pct", "profit_factor"]].copy()
pair_audit.to_csv(REPORT_DIR / "dual_trend_v2_validation_pairs.csv", index=False)
concentration = {"positive_pairs": int((pair_rows.profit_total > 0).sum()), "pair_profit_concentration": pair_concentration, "winning_trade_concentration": trade_concentration}
(REPORT_DIR / "dual_trend_v2_concentration.json").write_text(json.dumps(concentration, indent=2), encoding="utf-8")
display(pair_audit)
display(gates_df)
concentration'''
        ),
        new_markdown_cell("### 5. Check bias evidence and confirm V1 remains active"),
        new_code_cell(
            '''lookahead = pd.read_csv(REPORT_DIR / "DualTrendFuturesV2_lookahead.csv").iloc[0]
technical = json.loads((REPORT_DIR / "dual_trend_v2_technical_checks.json").read_text(encoding="utf-8"))
technical_pass = (
    str(lookahead.has_bias).lower() == "false"
    and int(lookahead.total_signals) == 100
    and int(lookahead.biased_entry_signals) == 0
    and int(lookahead.biased_exit_signals) == 0
    and technical["recursive_analysis"]["status"] == "PASS"
    and abs(float(technical["recursive_analysis"]["ema200_1d_variance_pct_at_800"])) <= 0.01
)
assert technical_pass

base_config = json.loads((PROJECT_ROOT / "user_data" / "config.json").read_text(encoding="utf-8"))
deploy_config = json.loads((PROJECT_ROOT / "user_data" / "config-dual-futures-dry-run.json").read_text(encoding="utf-8"))
assert base_config["exchange"]["key"] == base_config["exchange"]["secret"] == ""
assert deploy_config["exchange"]["key"] == deploy_config["exchange"]["secret"] == ""
credentials = f'{base_config["api_server"]["username"]}:{base_config["api_server"]["password"]}'
request = urllib.request.Request("http://127.0.0.1:8080/api/v1/show_config")
request.add_header("Authorization", "Basic " + base64.b64encode(credentials.encode()).decode())
with urllib.request.urlopen(request, timeout=10) as response:
    runtime = json.loads(response.read())
runtime_check = {
    "http_status": int(response.status), "state": runtime["state"], "dry_run": bool(runtime["dry_run"]),
    "strategy": runtime["strategy"], "trading_mode": runtime["trading_mode"],
    "short_allowed": bool(runtime["short_allowed"]), "stake_amount": float(runtime["stake_amount"]),
    "max_open_trades": int(runtime["max_open_trades"]),
}
assert runtime_check["strategy"] == "DualTrendFuturesV1" and runtime_check["state"] == "running" and runtime_check["dry_run"]
(REPORT_DIR / "dual_trend_v2_runtime_safety_check.json").write_text(json.dumps(runtime_check, indent=2), encoding="utf-8")
runtime_check'''
        ),
        new_markdown_cell("## Decision\n\n### 6. Write the machine-readable challenger decision"),
        new_code_cell(
            '''failed_gates = gates_df.loc[~gates_df["pass"], "gate"].tolist()
decision = {
    "decision": "CHALLENGER_REJECTED_KEEP_V1_RUNNING",
    "challenger": "DualTrendFuturesV2",
    "active_strategy": runtime_check["strategy"],
    "performance_gates_pass": bool(gates_df["pass"].all()),
    "technical_gates_pass": bool(technical_pass),
    "failed_gates": failed_gates,
    "parallel_v2_dry_run_started": False,
    "live_trading_authorized": False,
    "future_profit_guaranteed": False,
    "new_sealed_holdout": False,
}
assert decision["decision"] == "CHALLENGER_REJECTED_KEEP_V1_RUNNING"
(REPORT_DIR / "dual_trend_v2_validation_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
decision'''
        ),
        new_markdown_cell(
            """## Takeaways

Execution pending. This section is replaced after a successful top-to-bottom run.
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

    summary = pd.read_csv(REPORT_DIR / "dual_trend_v2_backtest_summary.csv").set_index("split")
    comparison = pd.read_csv(REPORT_DIR / "dual_trend_v2_vs_v1.csv").set_index("split")
    gates = pd.read_csv(REPORT_DIR / "dual_trend_v2_performance_gates.csv")
    validation = summary.loc["validation"]
    year_2025 = summary.loc["2025"]
    current = summary.loc["current_2026"]
    executed.cells[0].source = f"""## tl;dr

**CHALLENGER_REJECTED_KEEP_V1_RUNNING.** V2 improved return and profit factor,
but failed {int((~gates['pass']).sum())} locked risk/concentration gates.

- Validation: {validation['trades']:.0f} trades, {validation['return_pct']:.2f}%, PF {validation['profit_factor']:.3f}, DD {validation['max_drawdown_pct']:.2f}%.
- Return improvement versus V1: {comparison.loc['validation', 'return_delta_pp']:+.2f} percentage points.
- 2025: {year_2025['return_pct']:.2f}%, PF {year_2025['profit_factor']:.3f}, DD {year_2025['max_drawdown_pct']:.2f}%.
- 2026: {current['return_pct']:.2f}%, PF {current['profit_factor']:.3f}, DD {current['max_drawdown_pct']:.2f}%.
"""
    executed.cells[-1].source = """## Takeaways

- The confluence hypothesis improved V1's validation return/PF and all three recent calendar/regime returns.
- It did not satisfy the locked drawdown requirements, so it was not deployed and V1 remains active.
- Raw rows reconcile with every stored trade/profit/PF count; the reused OHLCV audit remains clean and fully covered.
- The 100-signal lookahead test found zero bias; recursive EMA200 variance at startup 800 was -0.005%.
- These reused historical periods are selection evidence, not a fresh forward holdout, and cannot guarantee future profit.
"""
    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print((REPORT_DIR / "dual_trend_v2_validation_decision.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
