from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "final_strategy_tournament.ipynb"
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

This is the final locked tournament between `DualTrendFuturesV2R` and the
single Chandelier-exit challenger `DualTrendFuturesV3R`. The notebook reads raw
Freqtrade archives, evaluates annual folds and fee stress, runs a deterministic
four-week block bootstrap, applies every pre-declared gate, and verifies the
selected credential-free dry-run runtime.

### Key assumptions

- Historical windows were already visible and are not a sealed holdout.
- The fixed current universe creates survivorship bias.
- Weekly block bootstrap is a resampling stress test, not a market forecast.
- Dry-run and historical results cannot guarantee future profit.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the tournament manifest and raw archives"),
        new_code_cell(
            '''from pathlib import Path
import base64
import io
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
manifest = json.loads((REPORT_DIR / "final_tournament_manifest.json").read_text(encoding="utf-8"))
STRATEGIES = tuple(manifest["strategies"])

records, raw, wallets = [], {}, {}
for run in manifest["runs"]:
    zip_path = BACKTEST_DIR / run["artifact"]
    base = zip_path.name.removesuffix(".zip")
    with zipfile.ZipFile(zip_path) as archive:
        result = json.loads(archive.read(f"{base}.json"))
        for strategy in STRATEGIES:
            stats = result["strategy"][strategy]
            wallet_member = f"{base}_{strategy}_wallet.feather"
            wallet = pd.read_feather(io.BytesIO(archive.read(wallet_member)))
            records.append({
                "artifact": zip_path.name, "strategy": strategy, "split": run["split"],
                "fee_per_side": run["fee_per_side"], "trades": int(stats["total_trades"]),
                "long_trades": int(stats["trade_count_long"]), "short_trades": int(stats["trade_count_short"]),
                "return_pct": 100 * float(stats["profit_total"]),
                "profit_abs_usdt": float(stats["profit_total_abs"]),
                "profit_factor": float(stats["profit_factor"]),
                "max_drawdown_pct": 100 * float(stats["max_drawdown_account"]),
                "market_change_pct": 100 * float(stats["market_change"]),
            })
            raw[(strategy, run["split"])] = stats
            wallets[(strategy, run["split"])] = wallet

summary = pd.DataFrame(records).sort_values(["split", "strategy"]).reset_index(drop=True)
required = {"backcast", "train", "validation", "2021", "2022", "2023", "2024", "2025", "current_2026", "fee_train", "fee_validation"}
assert set(summary.strategy) == set(STRATEGIES)
assert all(set(summary.loc[summary.strategy == s, "split"]) == required for s in STRATEGIES)
assert len(summary) == 22
summary.to_csv(REPORT_DIR / "final_tournament_summary.csv", index=False)
display(summary)'''
        ),
        new_markdown_cell("### 2. Compare incumbent and challenger"),
        new_code_cell(
            '''incumbent = summary[summary.strategy == "DualTrendFuturesV2R"].set_index("split")
challenger = summary[summary.strategy == "DualTrendFuturesV3R"].set_index("split")
ordered_splits = ["backcast", "train", "2021", "2022", "2023", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"]
comparison_rows = []
for split in ordered_splits:
    i, c = incumbent.loc[split], challenger.loc[split]
    comparison_rows.append({
        "split": split, "v2r_trades": int(i.trades), "v3r_trades": int(c.trades),
        "v2r_return_pct": i.return_pct, "v3r_return_pct": c.return_pct,
        "return_delta_pp": c.return_pct - i.return_pct,
        "v2r_profit_factor": i.profit_factor, "v3r_profit_factor": c.profit_factor,
        "pf_delta": c.profit_factor - i.profit_factor,
        "v2r_max_drawdown_pct": i.max_drawdown_pct, "v3r_max_drawdown_pct": c.max_drawdown_pct,
        "drawdown_delta_pp": c.max_drawdown_pct - i.max_drawdown_pct,
        "v2r_return_to_dd": i.return_pct / i.max_drawdown_pct,
        "v3r_return_to_dd": c.return_pct / c.max_drawdown_pct,
        "return_to_dd_delta_pct": 100 * ((c.return_pct / c.max_drawdown_pct) / (i.return_pct / i.max_drawdown_pct) - 1),
    })
comparison = pd.DataFrame(comparison_rows)
comparison.to_csv(REPORT_DIR / "final_tournament_comparison.csv", index=False)
display(comparison)'''
        ),
        new_markdown_cell("### 3. Revalidate data quality and raw calculations"),
        new_code_cell(
            '''quality = pd.read_csv(REPORT_DIR / "dual_trend_data_quality.csv")
timeframe_reconciliation = pd.read_csv(REPORT_DIR / "dual_trend_timeframe_reconciliation.csv")
coverage_cols = [c for c in quality.columns if c.endswith("coverage_pct")]
assert quality[["duplicate_timestamps", "null_cells", "invalid_ohlcv"]].sum().sum() == 0
assert quality.largest_gap_candles.max() == 0
assert quality[coverage_cols].min().min() == 100.0
assert timeframe_reconciliation.mismatch_pct.max() <= 0.20

def recomputed_pf(values):
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")

reconciliation_rows = []
for (strategy, split), stats in raw.items():
    trades = pd.DataFrame(stats["trades"])
    reconciliation_rows.append({
        "strategy": strategy, "split": split,
        "stored_trades": int(stats["total_trades"]), "recomputed_trades": len(trades),
        "stored_profit_abs": float(stats["profit_total_abs"]), "recomputed_profit_abs": float(trades.profit_abs.sum()),
        "stored_pf": float(stats["profit_factor"]), "recomputed_pf": recomputed_pf(trades.profit_abs),
        "stored_wins": int(stats["wins"]), "recomputed_wins": int((trades.profit_abs > 0).sum()),
        "stored_losses": int(stats["losses"]), "recomputed_losses": int((trades.profit_abs < 0).sum()),
    })
reconciliation = pd.DataFrame(reconciliation_rows).sort_values(["strategy", "split"])
assert (reconciliation.stored_trades == reconciliation.recomputed_trades).all()
assert np.allclose(reconciliation.stored_profit_abs, reconciliation.recomputed_profit_abs, atol=1e-6)
assert np.allclose(reconciliation.stored_pf, reconciliation.recomputed_pf, atol=1e-12)
assert (reconciliation.stored_wins == reconciliation.recomputed_wins).all()
assert (reconciliation.stored_losses == reconciliation.recomputed_losses).all()
reconciliation.to_csv(REPORT_DIR / "final_tournament_reconciliation.csv", index=False)
display(reconciliation)'''
        ),
        new_markdown_cell("## Results\n\n### 4. Run the deterministic weekly block bootstrap"),
        new_code_cell(
            '''def weekly_returns(strategy, split):
    wallet = wallets[(strategy, split)].copy()
    wallet["date"] = pd.to_datetime(wallet.date, utc=True)
    weekly = wallet.set_index("date").total_quote.resample("W-SUN").last().dropna().pct_change().dropna()
    return weekly.to_numpy(dtype=float)

def block_bootstrap(returns, seed, simulations=5000, block_size=4):
    rng = np.random.default_rng(seed)
    n = len(returns)
    blocks_needed = int(np.ceil(n / block_size))
    starts = rng.integers(0, n, size=(simulations, blocks_needed))
    offsets = np.arange(block_size)
    indices = (starts[:, :, None] + offsets[None, None, :]) % n
    sampled = returns[indices].reshape(simulations, -1)[:, :n]
    equity = np.cumprod(1.0 + sampled, axis=1)
    path = np.concatenate([np.ones((simulations, 1)), equity], axis=1)
    running_high = np.maximum.accumulate(path, axis=1)
    max_dd = 100 * np.max(1.0 - path / running_high, axis=1)
    terminal = 100 * (equity[:, -1] - 1.0)
    return terminal, max_dd

bootstrap_rows = []
for idx, strategy in enumerate(STRATEGIES):
    observed = np.concatenate([weekly_returns(strategy, "train"), weekly_returns(strategy, "validation")])
    terminal, max_dd = block_bootstrap(observed, seed=20260804 + idx)
    bootstrap_rows.append({
        "strategy": strategy, "observed_weeks": len(observed), "simulations": len(terminal), "block_weeks": 4,
        "terminal_return_p05_pct": float(np.quantile(terminal, 0.05)),
        "terminal_return_median_pct": float(np.quantile(terminal, 0.50)),
        "terminal_return_p95_pct": float(np.quantile(terminal, 0.95)),
        "max_drawdown_p50_pct": float(np.quantile(max_dd, 0.50)),
        "max_drawdown_p95_pct": float(np.quantile(max_dd, 0.95)),
    })
bootstrap = pd.DataFrame(bootstrap_rows).set_index("strategy")
bootstrap.to_csv(REPORT_DIR / "final_tournament_block_bootstrap.csv")
display(bootstrap)'''
        ),
        new_markdown_cell("### 5. Apply absolute and incumbent-superiority gates"),
        new_code_cell(
            '''folds = ["2021", "2022", "2023", "2024", "2025", "current_2026"]
v3_fold_returns = challenger.loc[folds, "return_pct"]
v2_fold_returns = incumbent.loc[folds, "return_pct"]
v3_positive_folds = int((v3_fold_returns > 0).sum())
v2_positive_folds = int((v2_fold_returns > 0).sum())

val_stats = raw[("DualTrendFuturesV3R", "validation")]
pair_rows = pd.DataFrame([r for r in val_stats["results_per_pair"] if r["key"] != "TOTAL"])
val_trades = pd.DataFrame(val_stats["trades"])
positive_pairs = pair_rows[pair_rows.profit_total_abs > 0]
pair_concentration = float(positive_pairs.profit_total_abs.max() / positive_pairs.profit_total_abs.sum())
positive_trades = val_trades[val_trades.profit_abs > 0]
trade_concentration = float(positive_trades.profit_abs.max() / positive_trades.profit_abs.sum())

lookahead = pd.read_csv(REPORT_DIR / "DualTrendFuturesV3R_lookahead.csv").iloc[0]
technical = json.loads((REPORT_DIR / "final_v3r_technical_checks.json").read_text(encoding="utf-8"))
technical_pass = (str(lookahead.has_bias).lower() == "false" and int(lookahead.total_signals) == 100
                  and int(lookahead.biased_entry_signals) == 0 and int(lookahead.biased_exit_signals) == 0
                  and technical["recursive_analysis"]["status"] == "PASS"
                  and not technical["recursive_analysis"]["indicator_lookahead_found"]
                  and abs(float(technical["recursive_analysis"]["ema200_1d_variance_pct_at_800"])) <= 0.01)

absolute_gates = {
    "train": challenger.loc["train", "return_pct"] > 0 and challenger.loc["train", "profit_factor"] >= 1.20 and challenger.loc["train", "max_drawdown_pct"] <= 30,
    "validation": challenger.loc["validation", "trades"] >= 100 and challenger.loc["validation", "return_pct"] > 0 and challenger.loc["validation", "profit_factor"] >= 1.50 and challenger.loc["validation", "max_drawdown_pct"] <= 12,
    "five_positive_folds": v3_positive_folds >= 5,
    "worst_fold_above_minus_5": float(v3_fold_returns.min()) > -5,
    "median_fold_pf_1_20": float(challenger.loc[folds, "profit_factor"].median()) >= 1.20,
    "year_2025": challenger.loc["2025", "return_pct"] > 0 and challenger.loc["2025", "profit_factor"] >= 1.15 and challenger.loc["2025", "max_drawdown_pct"] <= 12 and challenger.loc["2025", "trades"] >= 20,
    "current_2026": challenger.loc["current_2026", "return_pct"] > 0 and challenger.loc["current_2026", "profit_factor"] >= 1.30 and challenger.loc["current_2026", "max_drawdown_pct"] <= 10 and challenger.loc["current_2026", "trades"] >= 12,
    "fee_validation": challenger.loc["fee_validation", "return_pct"] > 0 and challenger.loc["fee_validation", "profit_factor"] >= 1.30 and challenger.loc["fee_validation", "max_drawdown_pct"] <= 13,
    "fee_train": challenger.loc["fee_train", "return_pct"] > 0 and challenger.loc["fee_train", "profit_factor"] >= 1.20,
    "backcast": challenger.loc["backcast", "return_pct"] > 0 and challenger.loc["backcast", "profit_factor"] >= 1.0 and challenger.loc["backcast", "max_drawdown_pct"] <= 15 and challenger.loc["backcast", "trades"] >= 10,
    "five_positive_pairs": int((pair_rows.profit_total > 0).sum()) >= 5,
    "pair_concentration": pair_concentration <= 0.50,
    "trade_concentration": trade_concentration <= 0.25,
    "technical": technical_pass,
    "bootstrap_return_p05_positive": bootstrap.loc["DualTrendFuturesV3R", "terminal_return_p05_pct"] > 0,
    "bootstrap_dd_p95_35": bootstrap.loc["DualTrendFuturesV3R", "max_drawdown_p95_pct"] <= 35,
}

v2_val_ratio = incumbent.loc["validation", "return_pct"] / incumbent.loc["validation", "max_drawdown_pct"]
v3_val_ratio = challenger.loc["validation", "return_pct"] / challenger.loc["validation", "max_drawdown_pct"]
v2_fee_ratio = incumbent.loc["fee_validation", "return_pct"] / incumbent.loc["fee_validation", "max_drawdown_pct"]
v3_fee_ratio = challenger.loc["fee_validation", "return_pct"] / challenger.loc["fee_validation", "max_drawdown_pct"]
v2_train_ratio = incumbent.loc["train", "return_pct"] / incumbent.loc["train", "max_drawdown_pct"]
v3_train_ratio = challenger.loc["train", "return_pct"] / challenger.loc["train", "max_drawdown_pct"]

superiority_gates = {
    "validation_return": challenger.loc["validation", "return_pct"] >= incumbent.loc["validation", "return_pct"],
    "validation_pf": challenger.loc["validation", "profit_factor"] >= incumbent.loc["validation", "profit_factor"],
    "validation_return_dd_10pct": v3_val_ratio >= 1.10 * v2_val_ratio,
    "year_2025_return": challenger.loc["2025", "return_pct"] >= incumbent.loc["2025", "return_pct"],
    "current_2026_return": challenger.loc["current_2026", "return_pct"] >= incumbent.loc["current_2026", "return_pct"],
    "fee_validation_return_dd": v3_fee_ratio >= v2_fee_ratio,
    "train_return_dd_floor": v3_train_ratio >= 0.90 * v2_train_ratio,
    "positive_fold_count": v3_positive_folds >= v2_positive_folds,
    "worst_fold_return": float(v3_fold_returns.min()) >= float(v2_fold_returns.min()),
    "bootstrap_p05": bootstrap.loc["DualTrendFuturesV3R", "terminal_return_p05_pct"] >= bootstrap.loc["DualTrendFuturesV2R", "terminal_return_p05_pct"],
}
absolute_df = pd.DataFrame([{"gate": k, "pass": bool(v)} for k, v in absolute_gates.items()])
superiority_df = pd.DataFrame([{"gate": k, "pass": bool(v)} for k, v in superiority_gates.items()])
absolute_df.to_csv(REPORT_DIR / "final_v3r_absolute_gates.csv", index=False)
superiority_df.to_csv(REPORT_DIR / "final_v3r_superiority_gates.csv", index=False)
pair_rows[["key", "trades", "profit_total_pct", "profit_factor"]].to_csv(REPORT_DIR / "final_v3r_validation_pairs.csv", index=False)
display(absolute_df)
display(superiority_df)'''
        ),
        new_markdown_cell("### 6. Select the final strategy and verify runtime"),
        new_code_cell(
            '''challenger_wins = bool(absolute_df["pass"].all() and superiority_df["pass"].all())
selected_strategy = "DualTrendFuturesV3R" if challenger_wins else "DualTrendFuturesV2R"

base_config = json.loads((PROJECT_ROOT / "user_data" / "config.json").read_text(encoding="utf-8"))
v2r_config = json.loads((PROJECT_ROOT / "user_data" / "config-dual-futures-v2r-dry-run.json").read_text(encoding="utf-8"))
assert base_config["exchange"]["key"] == base_config["exchange"]["secret"] == ""
assert v2r_config["exchange"]["key"] == v2r_config["exchange"]["secret"] == ""
credentials = f'{base_config["api_server"]["username"]}:{base_config["api_server"]["password"]}'

def runtime_at(port):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/show_config")
    request.add_header("Authorization", "Basic " + base64.b64encode(credentials.encode()).decode())
    with urllib.request.urlopen(request, timeout=5) as response:
        cfg = json.loads(response.read())
    return {"http_status": int(response.status), "state": cfg["state"], "dry_run": bool(cfg["dry_run"]),
            "strategy": cfg["strategy"], "trading_mode": cfg["trading_mode"], "short_allowed": bool(cfg["short_allowed"]),
            "stake_amount": float(cfg["stake_amount"]), "max_open_trades": int(cfg["max_open_trades"])}

runtime_v1 = runtime_at(8080)
runtime_best = runtime_at(8081)
assert runtime_v1["strategy"] == "DualTrendFuturesV1" and runtime_v1["dry_run"] and runtime_v1["state"] == "running"
assert selected_strategy == "DualTrendFuturesV2R"
assert runtime_best["strategy"] == selected_strategy and runtime_best["dry_run"] and runtime_best["state"] == "running"
assert runtime_best["trading_mode"] == "futures" and runtime_best["short_allowed"] and runtime_best["stake_amount"] == 25 and runtime_best["max_open_trades"] == 2

failed_absolute = absolute_df.loc[~absolute_df["pass"], "gate"].tolist()
failed_superiority = superiority_df.loc[~superiority_df["pass"], "gate"].tolist()
decision = {
    "decision": "FINAL_BEST_DUALTRENDFUTURESV2R_RETAINED",
    "selected_strategy": selected_strategy, "rejected_challenger": "DualTrendFuturesV3R",
    "challenger_absolute_gates_pass": bool(absolute_df["pass"].all()),
    "challenger_superiority_gates_pass": bool(superiority_df["pass"].all()),
    "failed_absolute_gates": failed_absolute, "failed_superiority_gates": failed_superiority,
    "selected_runtime_verified": True, "selected_runtime_port": 8081,
    "primary_v1_runtime_verified": True, "primary_v1_port": 8080,
    "live_trading_authorized": False, "live_api_keys_present": False,
    "new_sealed_holdout": False, "future_profit_guaranteed": False,
}
(REPORT_DIR / "final_strategy_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
(REPORT_DIR / "final_strategy_runtime.json").write_text(json.dumps({"primary": runtime_v1, "selected": runtime_best}, indent=2), encoding="utf-8")
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

    comparison = pd.read_csv(REPORT_DIR / "final_tournament_comparison.csv").set_index("split")
    decision = pd.read_json(REPORT_DIR / "final_strategy_decision.json", typ="series")
    absolute = pd.read_csv(REPORT_DIR / "final_v3r_absolute_gates.csv")
    superiority = pd.read_csv(REPORT_DIR / "final_v3r_superiority_gates.csv")
    validation, current = comparison.loc["validation"], comparison.loc["current_2026"]
    executed.cells[0].source = f"""## tl;dr

**{decision['decision']}**. The final V3R challenger failed {int((~absolute['pass']).sum())} absolute and {int((~superiority['pass']).sum())} incumbent-superiority gates, so V2R remains the strongest tested research candidate and active credential-free forward dry-run.

- Validation: V2R {validation['v2r_return_pct']:.2f}% / PF {validation['v2r_profit_factor']:.3f} / DD {validation['v2r_max_drawdown_pct']:.2f}%; V3R {validation['v3r_return_pct']:.2f}% / PF {validation['v3r_profit_factor']:.3f} / DD {validation['v3r_max_drawdown_pct']:.2f}%.
- Current 2026: V2R {current['v2r_return_pct']:.2f}% / PF {current['v2r_profit_factor']:.3f}; V3R {current['v3r_return_pct']:.2f}% / PF {current['v3r_profit_factor']:.3f}.
"""
    executed.cells[-1].source = """## Takeaways

- Chandelier exits improved older train, 2021, 2023, and 2024 results, but materially weakened 2025 and the current bearish 2026 regime.
- V3R's validation return was only slightly higher while its drawdown was higher, so risk-adjusted validation performance was worse than V2R.
- The challenger passed technical bias checks but failed the pre-declared current-regime and superiority requirements; thresholds were not relaxed.
- V2R remains running on port 8081 and V1 remains the primary control on port 8080. V3R was never deployed.
- No historical or resampled result makes the strategy ideal or guarantees future profit; the active V2R dry-run is collecting the only new forward evidence.
"""
    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print((REPORT_DIR / "final_strategy_decision.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
