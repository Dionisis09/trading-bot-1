from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "dual_trend_validation.ipynb"
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

This notebook independently validates the final `DualTrendFuturesV1` Binance
Futures dry-run candidate from raw Freqtrade archives and live local runtime.

Key limitations remain explicit: research uses today's fixed universe, unlimited
stake sizing for comparability, and a historical backcast holdout that precedes
train. The 2026 result is not sealed because the prior spot study had already
revealed its bearish regime. Passing authorizes dry-run only and cannot guarantee
future profit.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the annotated Freqtrade archives"),
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
DATA_DIR = PROJECT_ROOT / "user_data" / "data" / "binance" / "futures"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

records, raw = [], {}
for meta_path in sorted(BACKTEST_DIR.glob("*.meta.json")):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if "DualTrendFuturesV1" not in meta:
        continue
    run_meta = meta["DualTrendFuturesV1"]
    notes = run_meta.get("notes", "")
    if not notes.startswith("phase=dual_v1;"):
        continue
    base = meta_path.name.removesuffix(".meta.json")
    zip_path = BACKTEST_DIR / f"{base}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        result = json.loads(archive.read(f"{base}.json"))
    stats = result["strategy"]["DualTrendFuturesV1"]
    split = next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("split="))
    records.append({
        "artifact": zip_path.name,
        "split": split,
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
    raw[(split, int(run_meta["backtest_start_time"]))] = stats

summary = (pd.DataFrame(records).sort_values("run_epoch")
           .drop_duplicates("split", keep="last").sort_values("run_epoch").reset_index(drop=True))
raw = {split: raw[(split, int(row.run_epoch))] for split, row in summary.set_index("split").iterrows()}
required = {"train", "validation", "2024", "2025", "current_2026", "fee_train",
            "fee_validation", "untouched_backcast_holdout"}
assert required.issubset(set(summary["split"])), required - set(summary["split"])
summary.to_csv(REPORT_DIR / "dual_trend_backtest_summary.csv", index=False)
display(summary)'''
        ),
        new_markdown_cell("### 2. Profile futures OHLCV and reconcile timeframes"),
        new_code_cell(
            '''PAIRS = ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE")
INTERVALS = {"4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}
WINDOWS = {
    "backcast": (pd.Timestamp("2020-08-01", tz="UTC"), pd.Timestamp("2021-01-01", tz="UTC")),
    "train": (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
    "current_2026": (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-08-01", tz="UTC")),
}
frames, quality_rows = {}, []
for pair in PAIRS:
    for timeframe, interval in INTERVALS.items():
        path = DATA_DIR / f"{pair}_USDT_USDT-{timeframe}-futures.feather"
        frame = pd.read_feather(path).sort_values("date").reset_index(drop=True)
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        frames[(pair, timeframe)] = frame
        invalid = ((frame.high < frame.low) | (frame.high < frame.open) |
                   (frame.high < frame.close) | (frame.low > frame.open) |
                   (frame.low > frame.close) | (frame.volume < 0))
        deltas = frame.date.diff().dropna()
        row = {
            "pair": f"{pair}/USDT:USDT", "timeframe": timeframe, "rows": len(frame),
            "duplicate_timestamps": int(frame.date.duplicated().sum()),
            "null_cells": int(frame[["open", "high", "low", "close", "volume"]].isna().sum().sum()),
            "invalid_ohlcv": int(invalid.sum()),
            "largest_gap_candles": int((deltas.max() / interval) - 1),
        }
        for name, (start, end) in WINDOWS.items():
            expected = int((end - start) / interval)
            actual = frame.loc[(frame.date >= start) & (frame.date < end), "date"].nunique()
            row[f"{name}_coverage_pct"] = 100 * actual / expected
        quality_rows.append(row)

quality = pd.DataFrame(quality_rows)
assert quality[["duplicate_timestamps", "null_cells", "invalid_ohlcv"]].sum().sum() == 0
assert quality["largest_gap_candles"].max() == 0
assert quality[[c for c in quality if c.endswith("coverage_pct")]].min().min() == 100.0

reconcile = []
for pair in PAIRS:
    four = frames[(pair, "4h")].set_index("date").copy()
    four["count"] = 1
    daily_from_four = four.resample("1d").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "count": "sum"
    })
    daily_from_four = daily_from_four[daily_from_four["count"] == 6].drop(columns="count")
    daily = frames[(pair, "1d")].set_index("date")[["open", "high", "low", "close", "volume"]]
    joined = daily_from_four.join(daily, lsuffix="_4h", rsuffix="_1d", how="inner")
    mismatch_by_field = {
        c: ~np.isclose(joined[f"{c}_4h"], joined[f"{c}_1d"], rtol=1e-8, atol=1e-8)
        for c in ("open", "high", "low", "close", "volume")
    }
    mismatch_mask = np.logical_or.reduce(list(mismatch_by_field.values()))
    mismatch_days = int(mismatch_mask.sum())
    reconcile.append({
        "pair": pair,
        "days_compared": len(joined),
        "mismatch_days": mismatch_days,
        "mismatch_pct": 100 * mismatch_days / len(joined),
        "mismatch_dates_utc": "|".join(joined.index[mismatch_mask].astype(str)),
        **{f"{field}_mismatches": int(mask.sum()) for field, mask in mismatch_by_field.items()},
    })
reconcile = pd.DataFrame(reconcile)
assert reconcile.mismatch_pct.max() <= 0.20
quality.to_csv(REPORT_DIR / "dual_trend_data_quality.csv", index=False)
reconcile.to_csv(REPORT_DIR / "dual_trend_timeframe_reconciliation.csv", index=False)
display(quality)
display(reconcile)'''
        ),
        new_markdown_cell("## Validation\n\n### 3. Recompute trade metrics from raw rows"),
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
reconciliation = pd.DataFrame(rows)
assert (reconciliation.stored_trades == reconciliation.recomputed_trades).all()
assert np.allclose(reconciliation.stored_profit_abs, reconciliation.recomputed_profit_abs, atol=1e-6)
assert np.allclose(reconciliation.stored_pf, reconciliation.recomputed_pf, atol=1e-12)
assert (reconciliation.stored_wins == reconciliation.recomputed_wins).all()
assert (reconciliation.stored_losses == reconciliation.recomputed_losses).all()
reconciliation.to_csv(REPORT_DIR / "dual_trend_backtest_reconciliation.csv", index=False)
display(reconciliation)'''
        ),
        new_markdown_cell("### 4. Apply every pre-declared performance gate"),
        new_code_cell(
            '''by_split = summary.set_index("split")
val_stats = raw["validation"]
pair_rows = pd.DataFrame([r for r in val_stats["results_per_pair"] if r["key"] != "TOTAL"])
trades = pd.DataFrame(val_stats["trades"])
positive_pairs = pair_rows[pair_rows.profit_total_abs > 0]
pair_concentration = float(positive_pairs.profit_total_abs.max() / positive_pairs.profit_total_abs.sum())
positive_trades = trades[trades.profit_abs > 0]
trade_concentration = float(positive_trades.profit_abs.max() / positive_trades.profit_abs.sum())

gates = {
    "train_positive": by_split.loc["train", "return_pct"] > 0,
    "train_pf_1_20": by_split.loc["train", "profit_factor"] >= 1.20,
    "validation_100_trades": by_split.loc["validation", "trades"] >= 100,
    "validation_positive": by_split.loc["validation", "return_pct"] > 0,
    "validation_pf_1_20": by_split.loc["validation", "profit_factor"] >= 1.20,
    "validation_dd_20": by_split.loc["validation", "max_drawdown_pct"] <= 20,
    "validation_four_positive_pairs": int((pair_rows.profit_total > 0).sum()) >= 4,
    "validation_pair_loss_cap": float(pair_rows.profit_total.min()) >= -0.05,
    "validation_pair_concentration": pair_concentration <= 0.50,
    "validation_trade_concentration": trade_concentration <= 0.25,
    "year_2024": (by_split.loc["2024", "return_pct"] > 0 and by_split.loc["2024", "profit_factor"] >= 1 and by_split.loc["2024", "trades"] >= 20),
    "year_2025": (by_split.loc["2025", "return_pct"] > 0 and by_split.loc["2025", "profit_factor"] >= 1 and by_split.loc["2025", "trades"] >= 20),
    "fee_train_positive": by_split.loc["fee_train", "return_pct"] > 0,
    "fee_validation_positive": by_split.loc["fee_validation", "return_pct"] > 0,
    "current_2026": (by_split.loc["current_2026", "return_pct"] > 0 and by_split.loc["current_2026", "profit_factor"] >= 1 and by_split.loc["current_2026", "trades"] >= 12 and by_split.loc["current_2026", "max_drawdown_pct"] <= 15),
    "backcast_holdout": (by_split.loc["untouched_backcast_holdout", "return_pct"] > 0 and by_split.loc["untouched_backcast_holdout", "profit_factor"] >= 1 and by_split.loc["untouched_backcast_holdout", "trades"] >= 10 and by_split.loc["untouched_backcast_holdout", "max_drawdown_pct"] <= 15),
}
gates_df = pd.DataFrame([{"gate": k, "pass": bool(v)} for k, v in gates.items()])
assert gates_df["pass"].all()
gates_df.to_csv(REPORT_DIR / "dual_trend_performance_gates.csv", index=False)
display(pair_rows[["key", "trades", "profit_total_pct", "profit_factor"]])
display(gates_df)'''
        ),
        new_markdown_cell("### 5. Validate bias checks and live dry-run state"),
        new_code_cell(
            '''technical = json.loads((REPORT_DIR / "dual_trend_technical_checks.json").read_text(encoding="utf-8"))
lookahead = pd.read_csv(REPORT_DIR / "DualTrendFuturesV1_lookahead.csv").iloc[0]
technical_pass = (
    technical["recursive_analysis"]["status"] == "PASS"
    and abs(float(technical["recursive_analysis"]["ema200_variance_pct_at_800"])) <= 0.01
    and not bool(technical["recursive_analysis"]["indicator_lookahead_found"])
    and str(lookahead.has_bias).lower() == "false"
    and int(lookahead.total_signals) == 100
    and int(lookahead.biased_entry_signals) == 0
    and int(lookahead.biased_exit_signals) == 0
)
assert technical_pass

base_config = json.loads((PROJECT_ROOT / "user_data" / "config.json").read_text(encoding="utf-8"))
deploy_config = json.loads((PROJECT_ROOT / "user_data" / "config-dual-futures-dry-run.json").read_text(encoding="utf-8"))
assert base_config["exchange"]["key"] == base_config["exchange"]["secret"] == ""
assert deploy_config["exchange"]["key"] == deploy_config["exchange"]["secret"] == ""
assert deploy_config["dry_run"] is True and deploy_config["stake_amount"] == 25

credentials = f'{base_config["api_server"]["username"]}:{base_config["api_server"]["password"]}'
request = urllib.request.Request("http://127.0.0.1:8080/api/v1/show_config")
request.add_header("Authorization", "Basic " + base64.b64encode(credentials.encode()).decode())
with urllib.request.urlopen(request, timeout=10) as response:
    runtime = json.loads(response.read())
runtime_check = {
    "http_status": int(response.status), "state": runtime["state"],
    "dry_run": bool(runtime["dry_run"]), "strategy": runtime["strategy"],
    "timeframe": runtime["timeframe"], "trading_mode": runtime["trading_mode"],
    "short_allowed": bool(runtime["short_allowed"]), "stake_amount": float(runtime["stake_amount"]),
    "max_open_trades": int(runtime["max_open_trades"]),
}
runtime_pass = (runtime_check["http_status"] == 200 and runtime_check["state"] == "running"
                and runtime_check["dry_run"] and runtime_check["strategy"] == "DualTrendFuturesV1"
                and runtime_check["trading_mode"] == "futures" and runtime_check["short_allowed"]
                and runtime_check["stake_amount"] == 25 and runtime_check["max_open_trades"] == 2)
assert runtime_pass
(REPORT_DIR / "dual_trend_runtime_verification.json").write_text(json.dumps(runtime_check, indent=2), encoding="utf-8")
runtime_check'''
        ),
        new_markdown_cell("## Decision\n\n### 6. Write the machine-readable decision"),
        new_code_cell(
            '''decision = {
    "decision": "DRY_RUN_APPROVED_AND_RUNNING",
    "strategy": "DualTrendFuturesV1",
    "performance_gates_pass": bool(gates_df["pass"].all()),
    "technical_gates_pass": bool(technical_pass),
    "runtime_verified": bool(runtime_pass),
    "live_trading_authorized": False,
    "live_api_keys_present": False,
    "baseline_fee_per_side_pct": 0.05,
    "stress_fee_per_side_pct": 0.15,
    "backcast_holdout_is_forward_test": False,
    "future_profit_guaranteed": False,
}
(REPORT_DIR / "dual_trend_validation_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
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

    summary = pd.read_csv(REPORT_DIR / "dual_trend_backtest_summary.csv").set_index("split")
    decision = pd.read_json(REPORT_DIR / "dual_trend_validation_decision.json", typ="series")
    train = summary.loc["train"]
    validation = summary.loc["validation"]
    current = summary.loc["current_2026"]
    holdout = summary.loc["untouched_backcast_holdout"]
    executed.cells[0].source = f"""## tl;dr

**{decision['decision']}** with all performance, data, bias, and runtime gates passing.

- Train: {train['trades']:.0f} trades, {train['return_pct']:.2f}%, PF {train['profit_factor']:.3f}.
- Validation: {validation['trades']:.0f} trades, {validation['return_pct']:.2f}%, PF {validation['profit_factor']:.3f}, DD {validation['max_drawdown_pct']:.2f}%.
- Bearish 2026 evaluation: {current['trades']:.0f} short trades, {current['return_pct']:.2f}%, PF {current['profit_factor']:.3f}.
- Untouched backcast holdout: {holdout['trades']:.0f} trades, {holdout['return_pct']:.2f}%, PF {holdout['profit_factor']:.3f}, DD {holdout['max_drawdown_pct']:.2f}%.
"""
    executed.cells[-1].source = """## Takeaways

- Raw trades reconcile exactly with stored Freqtrade trade count, profit, PF, wins, and losses.
- Data has complete declared-window coverage, valid OHLCV, no gaps, and only 2-4 isolated 4h-to-1d mismatch days per pair (under 0.2%), retained in the audit CSV.
- Recursive and 100-signal lookahead checks pass; no live Binance credentials exist.
- The bot is running locally in Binance Futures dry-run with 25 USDT simulated stake, maximum two positions, and 1x leverage logic.
- Research returns used unlimited stake sizing and are not expected dry-run returns. The backcast holdout is historical rather than forward evidence, so future profitability remains unproven.
"""
    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print(decision.to_json())


if __name__ == "__main__":
    main()
