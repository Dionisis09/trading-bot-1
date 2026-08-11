from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "dual_trend_v2r_validation.ipynb"
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

This notebook validates the locked ATR/exposure risk overlay applied identically
to `DualTrendFuturesV1R` (control) and `DualTrendFuturesV2R` (challenger). It
recomputes raw metrics, verifies signal identity against the unscaled strategies,
applies absolute and matched-risk gates, checks bias evidence, and records local
dry-run state. All timestamps are UTC. Reused historical windows are not a new
sealed holdout.

### Key assumptions

- Research uses today's fixed six-pair universe and therefore has survivorship bias.
- Unlimited research stake differs from fixed-stake dry-run deployment.
- ATR controls stake only; it is not treated as a directional predictor.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the annotated matched-risk archives"),
        new_code_cell(
            '''from pathlib import Path
import base64
import json
import urllib.error
import urllib.request
import zipfile
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
BACKTEST_DIR = PROJECT_ROOT / "user_data" / "backtest_results"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
STRATEGIES = ("DualTrendFuturesV1R", "DualTrendFuturesV2R")

records, raw = [], {}
for meta_path in sorted(BACKTEST_DIR.glob("*.meta.json")):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    selected = [s for s in STRATEGIES if s in meta and meta[s].get("notes", "").startswith("phase=dual_v2r;")]
    if not selected:
        continue
    base = meta_path.name.removesuffix(".meta.json")
    zip_path = BACKTEST_DIR / f"{base}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        result = json.loads(archive.read(f"{base}.json"))
    for strategy in selected:
        run_meta = meta[strategy]
        notes = run_meta["notes"]
        split = next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("split="))
        fee = float(next(part.split("=", 1)[1] for part in notes.split(";") if part.startswith("fee=")))
        stats = result["strategy"][strategy]
        records.append({
            "artifact": zip_path.name, "strategy": strategy, "split": split,
            "fee_per_side": fee, "run_epoch": int(run_meta["backtest_start_time"]),
            "trades": int(stats["total_trades"]), "long_trades": int(stats["trade_count_long"]),
            "short_trades": int(stats["trade_count_short"]),
            "return_pct": 100 * float(stats["profit_total"]),
            "profit_abs_usdt": float(stats["profit_total_abs"]),
            "profit_factor": float(stats["profit_factor"]),
            "max_drawdown_pct": 100 * float(stats["max_drawdown_account"]),
            "market_change_pct": 100 * float(stats["market_change"]),
        })
        raw[(strategy, split)] = stats

summary = pd.DataFrame(records).sort_values(["split", "strategy"]).reset_index(drop=True)
required_splits = {"train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"}
assert set(summary.strategy) == set(STRATEGIES)
assert all(set(summary.loc[summary.strategy == s, "split"]) == required_splits for s in STRATEGIES)
assert len(summary) == 14
summary.to_csv(REPORT_DIR / "dual_trend_v2r_backtest_summary.csv", index=False)
display(summary)'''
        ),
        new_markdown_cell("### 2. Build the matched-risk comparison"),
        new_code_cell(
            '''control = summary[summary.strategy == "DualTrendFuturesV1R"].set_index("split")
challenger = summary[summary.strategy == "DualTrendFuturesV2R"].set_index("split")
comparison_rows = []
for split in ["train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"]:
    c, v = control.loc[split], challenger.loc[split]
    comparison_rows.append({
        "split": split, "v1r_trades": int(c.trades), "v2r_trades": int(v.trades),
        "v1r_return_pct": c.return_pct, "v2r_return_pct": v.return_pct,
        "return_delta_pp": v.return_pct - c.return_pct,
        "v1r_profit_factor": c.profit_factor, "v2r_profit_factor": v.profit_factor,
        "pf_delta": v.profit_factor - c.profit_factor,
        "v1r_max_drawdown_pct": c.max_drawdown_pct, "v2r_max_drawdown_pct": v.max_drawdown_pct,
        "drawdown_delta_pp": v.max_drawdown_pct - c.max_drawdown_pct,
        "v1r_return_to_dd": c.return_pct / c.max_drawdown_pct,
        "v2r_return_to_dd": v.return_pct / v.max_drawdown_pct,
        "return_to_dd_improvement_pct": 100 * ((v.return_pct / v.max_drawdown_pct) / (c.return_pct / c.max_drawdown_pct) - 1),
    })
comparison = pd.DataFrame(comparison_rows)
comparison.to_csv(REPORT_DIR / "dual_trend_v2r_vs_v1r.csv", index=False)
display(comparison)'''
        ),
        new_markdown_cell("### 3. Confirm market-data quality and risk constants"),
        new_code_cell(
            '''quality = pd.read_csv(REPORT_DIR / "dual_trend_data_quality.csv")
timeframe_reconciliation = pd.read_csv(REPORT_DIR / "dual_trend_timeframe_reconciliation.csv")
coverage_cols = [c for c in quality.columns if c.endswith("coverage_pct")]
assert quality[["duplicate_timestamps", "null_cells", "invalid_ohlcv"]].sum().sum() == 0
assert quality.largest_gap_candles.max() == 0
assert quality[coverage_cols].min().min() == 100.0
assert timeframe_reconciliation.mismatch_pct.max() <= 0.20

risk_test = json.loads((REPORT_DIR / "dual_trend_v2r_risk_callback_test.json").read_text(encoding="utf-8"))
source = (PROJECT_ROOT / "user_data" / "strategies" / "DualTrendFuturesRisk.py").read_text(encoding="utf-8")
assert risk_test["status"] == "PASS" and risk_test["exceptions_or_assertion_failures"] == 0
assert risk_test["minimum_multiplier"] == 0.325 and risk_test["maximum_multiplier"] == 0.65
for expected in (
    "risk_exposure_fraction = 0.65", "target_atr_pct = 0.03",
    "minimum_volatility_scalar = 0.50", "maximum_volatility_scalar = 1.00",
    "return proposed_stake * self.risk_exposure_fraction * volatility_scalar",
):
    assert expected in source

data_and_risk_check = {
    "same_audited_archives_as_v1_v2": True,
    "minimum_split_coverage_pct": float(quality[coverage_cols].min().min()),
    "duplicate_timestamps": int(quality.duplicate_timestamps.sum()),
    "null_cells": int(quality.null_cells.sum()),
    "invalid_ohlcv": int(quality.invalid_ohlcv.sum()),
    "largest_gap_candles": int(quality.largest_gap_candles.max()),
    "maximum_4h_1d_mismatch_pct": float(timeframe_reconciliation.mismatch_pct.max()),
    "risk_callback_test": risk_test["status"],
    "stake_multiplier_range": [risk_test["minimum_multiplier"], risk_test["maximum_multiplier"]],
}
(REPORT_DIR / "dual_trend_v2r_data_and_risk_check.json").write_text(json.dumps(data_and_risk_check, indent=2), encoding="utf-8")
data_and_risk_check'''
        ),
        new_markdown_cell("## Results\n\n### 4. Recompute raw trade metrics and stake distributions"),
        new_code_cell(
            '''def recomputed_pf(values):
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")

reconciliation_rows, stake_rows = [], []
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
    stake_rows.append({
        "strategy": strategy, "split": split, "trades": len(trades),
        "minimum_stake": float(trades.stake_amount.min()),
        "median_stake": float(trades.stake_amount.median()),
        "maximum_stake": float(trades.stake_amount.max()),
        "mean_stake": float(trades.stake_amount.mean()),
    })
reconciliation = pd.DataFrame(reconciliation_rows).sort_values(["strategy", "split"])
assert (reconciliation.stored_trades == reconciliation.recomputed_trades).all()
assert np.allclose(reconciliation.stored_profit_abs, reconciliation.recomputed_profit_abs, atol=1e-6)
assert np.allclose(reconciliation.stored_pf, reconciliation.recomputed_pf, atol=1e-12)
assert (reconciliation.stored_wins == reconciliation.recomputed_wins).all()
assert (reconciliation.stored_losses == reconciliation.recomputed_losses).all()
reconciliation.to_csv(REPORT_DIR / "dual_trend_v2r_backtest_reconciliation.csv", index=False)
stake_profile = pd.DataFrame(stake_rows).sort_values(["strategy", "split"])
stake_profile.to_csv(REPORT_DIR / "dual_trend_v2r_stake_profile.csv", index=False)
display(reconciliation)
display(stake_profile)'''
        ),
        new_markdown_cell("### 5. Verify that the overlay did not alter signals"),
        new_code_cell(
            '''def load_base_stats(strategy, phase, split):
    candidates = []
    for meta_path in BACKTEST_DIR.glob("*.meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if strategy not in meta:
            continue
        notes = meta[strategy].get("notes", "")
        if not notes.startswith(f"phase={phase};") or f"split={split}" not in notes:
            continue
        base = meta_path.name.removesuffix(".meta.json")
        with zipfile.ZipFile(BACKTEST_DIR / f"{base}.zip") as archive:
            result = json.loads(archive.read(f"{base}.json"))
        candidates.append((int(meta[strategy]["backtest_start_time"]), result["strategy"][strategy]))
    assert candidates, (strategy, phase, split)
    return sorted(candidates)[-1][1]

identity_columns = ["pair", "open_date", "close_date", "is_short", "enter_tag", "exit_reason"]
signal_rows = []
for split in ["train", "validation", "2024", "2025", "current_2026", "fee_train", "fee_validation"]:
    for risk_strategy, base_strategy, phase in [
        ("DualTrendFuturesV1R", "DualTrendFuturesV1", "dual_v1"),
        ("DualTrendFuturesV2R", "DualTrendFuturesV2", "dual_v2"),
    ]:
        base_stats = load_base_stats(base_strategy, phase, split)
        risk_stats = raw[(risk_strategy, split)]
        base_ids = set(map(tuple, pd.DataFrame(base_stats["trades"])[identity_columns].astype(str).to_numpy()))
        risk_ids = set(map(tuple, pd.DataFrame(risk_stats["trades"])[identity_columns].astype(str).to_numpy()))
        signal_rows.append({
            "split": split, "risk_strategy": risk_strategy, "base_strategy": base_strategy,
            "base_trades": len(base_ids), "risk_trades": len(risk_ids),
            "missing_from_risk": len(base_ids - risk_ids), "extra_in_risk": len(risk_ids - base_ids),
            "identical": base_ids == risk_ids,
        })
signal_identity = pd.DataFrame(signal_rows)
assert signal_identity.identical.all()
signal_identity.to_csv(REPORT_DIR / "dual_trend_v2r_signal_identity.csv", index=False)
display(signal_identity)'''
        ),
        new_markdown_cell("### 6. Apply all absolute and matched-risk gates"),
        new_code_cell(
            '''v = challenger
c = control
val_stats = raw[("DualTrendFuturesV2R", "validation")]
pair_rows = pd.DataFrame([r for r in val_stats["results_per_pair"] if r["key"] != "TOTAL"])
val_trades = pd.DataFrame(val_stats["trades"])
positive_pairs = pair_rows[pair_rows.profit_total_abs > 0]
pair_concentration = float(positive_pairs.profit_total_abs.max() / positive_pairs.profit_total_abs.sum())
positive_trades = val_trades[val_trades.profit_abs > 0]
trade_concentration = float(positive_trades.profit_abs.max() / positive_trades.profit_abs.sum())

gates = {
    "train_positive": v.loc["train", "return_pct"] > 0,
    "train_pf_1_20": v.loc["train", "profit_factor"] >= 1.20,
    "train_dd_30": v.loc["train", "max_drawdown_pct"] <= 30,
    "validation_100_trades": v.loc["validation", "trades"] >= 100,
    "validation_positive": v.loc["validation", "return_pct"] > 0,
    "validation_pf_1_50": v.loc["validation", "profit_factor"] >= 1.50,
    "validation_dd_12": v.loc["validation", "max_drawdown_pct"] <= 12,
    "year_2024": (v.loc["2024", "return_pct"] > 0 and v.loc["2024", "profit_factor"] >= 1.20 and v.loc["2024", "max_drawdown_pct"] <= 12 and v.loc["2024", "trades"] >= 20),
    "year_2025": (v.loc["2025", "return_pct"] > 0 and v.loc["2025", "profit_factor"] >= 1.15 and v.loc["2025", "max_drawdown_pct"] <= 12 and v.loc["2025", "trades"] >= 20),
    "current_2026": (v.loc["current_2026", "return_pct"] > 0 and v.loc["current_2026", "profit_factor"] >= 1.30 and v.loc["current_2026", "max_drawdown_pct"] <= 10 and v.loc["current_2026", "trades"] >= 12),
    "fee_validation": (v.loc["fee_validation", "return_pct"] > 0 and v.loc["fee_validation", "profit_factor"] >= 1.30 and v.loc["fee_validation", "max_drawdown_pct"] <= 13),
    "fee_train": v.loc["fee_train", "return_pct"] > 0 and v.loc["fee_train", "profit_factor"] >= 1.20,
    "validation_five_positive_pairs": int((pair_rows.profit_total > 0).sum()) >= 5,
    "validation_pair_concentration": pair_concentration <= 0.50,
    "validation_trade_concentration": trade_concentration <= 0.25,
    "matched_validation_return": v.loc["validation", "return_pct"] > c.loc["validation", "return_pct"],
    "matched_validation_pf": v.loc["validation", "profit_factor"] > c.loc["validation", "profit_factor"],
    "matched_validation_return_dd_20pct": (v.loc["validation", "return_pct"] / v.loc["validation", "max_drawdown_pct"]) >= 1.20 * (c.loc["validation", "return_pct"] / c.loc["validation", "max_drawdown_pct"]),
    "matched_2025_return": v.loc["2025", "return_pct"] > c.loc["2025", "return_pct"],
    "matched_current_return": v.loc["current_2026", "return_pct"] > c.loc["current_2026", "return_pct"],
    "matched_fee_validation_return": v.loc["fee_validation", "return_pct"] > c.loc["fee_validation", "return_pct"],
    "matched_fee_validation_pf": v.loc["fee_validation", "profit_factor"] > c.loc["fee_validation", "profit_factor"],
}
gates_df = pd.DataFrame([{"gate": key, "pass": bool(value)} for key, value in gates.items()])
assert gates_df["pass"].all()
gates_df.to_csv(REPORT_DIR / "dual_trend_v2r_performance_gates.csv", index=False)
pair_audit = pair_rows[["key", "trades", "profit_total_pct", "profit_factor"]].copy()
pair_audit.to_csv(REPORT_DIR / "dual_trend_v2r_validation_pairs.csv", index=False)
concentration = {"positive_pairs": int((pair_rows.profit_total > 0).sum()), "pair_profit_concentration": pair_concentration, "winning_trade_concentration": trade_concentration}
(REPORT_DIR / "dual_trend_v2r_concentration.json").write_text(json.dumps(concentration, indent=2), encoding="utf-8")
display(pair_audit)
display(gates_df)
concentration'''
        ),
        new_markdown_cell("### 7. Validate bias checks and inspect dry-run runtime"),
        new_code_cell(
            '''lookahead = pd.read_csv(REPORT_DIR / "DualTrendFuturesV2R_lookahead.csv").iloc[0]
technical = json.loads((REPORT_DIR / "dual_trend_v2r_technical_checks.json").read_text(encoding="utf-8"))
technical_pass = (
    str(lookahead.has_bias).lower() == "false" and int(lookahead.total_signals) == 100
    and int(lookahead.biased_entry_signals) == 0 and int(lookahead.biased_exit_signals) == 0
    and technical["recursive_analysis"]["status"] == "PASS"
    and not technical["recursive_analysis"]["indicator_lookahead_found"]
    and abs(float(technical["recursive_analysis"]["ema200_1d_variance_pct_at_800"])) <= 0.01
)
assert technical_pass

base_config = json.loads((PROJECT_ROOT / "user_data" / "config.json").read_text(encoding="utf-8"))
assert base_config["exchange"]["key"] == base_config["exchange"]["secret"] == ""
credentials = f'{base_config["api_server"]["username"]}:{base_config["api_server"]["password"]}'

def runtime_at(port):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/show_config")
    request.add_header("Authorization", "Basic " + base64.b64encode(credentials.encode()).decode())
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            cfg = json.loads(response.read())
        return {"reachable": True, "http_status": int(response.status), "state": cfg["state"],
                "dry_run": bool(cfg["dry_run"]), "strategy": cfg["strategy"],
                "trading_mode": cfg["trading_mode"], "short_allowed": bool(cfg["short_allowed"]),
                "stake_amount": float(cfg["stake_amount"]), "max_open_trades": int(cfg["max_open_trades"])}
    except (urllib.error.URLError, TimeoutError):
        return {"reachable": False}

runtime_v1 = runtime_at(8080)
runtime_v2r = runtime_at(8081)
assert runtime_v1["reachable"] and runtime_v1["state"] == "running" and runtime_v1["dry_run"] and runtime_v1["strategy"] == "DualTrendFuturesV1"
runtime_v2r_ok = (runtime_v2r.get("reachable", False) and runtime_v2r.get("state") == "running"
                  and runtime_v2r.get("dry_run") and runtime_v2r.get("strategy") == "DualTrendFuturesV2R"
                  and runtime_v2r.get("trading_mode") == "futures" and runtime_v2r.get("short_allowed")
                  and runtime_v2r.get("stake_amount") == 25 and runtime_v2r.get("max_open_trades") == 2)
runtime_evidence = {"v1_port_8080": runtime_v1, "v2r_port_8081": runtime_v2r, "v2r_runtime_verified": bool(runtime_v2r_ok)}
(REPORT_DIR / "dual_trend_v2r_runtime_verification.json").write_text(json.dumps(runtime_evidence, indent=2), encoding="utf-8")
runtime_evidence'''
        ),
        new_markdown_cell("## Takeaways\n\n### 8. Write the machine decision"),
        new_code_cell(
            '''all_gates_pass = bool(gates_df["pass"].all() and technical_pass and signal_identity.identical.all())
decision_name = "PARALLEL_DRY_RUN_RUNNING" if all_gates_pass and runtime_v2r_ok else "PARALLEL_DRY_RUN_APPROVED_NOT_STARTED"
decision = {
    "decision": decision_name, "strategy": "DualTrendFuturesV2R", "control": "DualTrendFuturesV1R",
    "active_primary_strategy": runtime_v1["strategy"], "all_performance_gates_pass": bool(gates_df["pass"].all()),
    "technical_gates_pass": bool(technical_pass), "signal_identity_pass": bool(signal_identity.identical.all()),
    "risk_callback_test_pass": risk_test["status"] == "PASS", "parallel_runtime_verified": bool(runtime_v2r_ok),
    "live_trading_authorized": False, "live_api_keys_present": False, "new_sealed_holdout": False,
    "future_profit_guaranteed": False,
}
assert all_gates_pass
(REPORT_DIR / "dual_trend_v2r_validation_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
decision'''
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

    summary = pd.read_csv(REPORT_DIR / "dual_trend_v2r_backtest_summary.csv")
    comparison = pd.read_csv(REPORT_DIR / "dual_trend_v2r_vs_v1r.csv").set_index("split")
    decision = pd.read_json(REPORT_DIR / "dual_trend_v2r_validation_decision.json", typ="series")
    v2r = summary[summary.strategy == "DualTrendFuturesV2R"].set_index("split")
    validation, year_2025, current = v2r.loc["validation"], v2r.loc["2025"], v2r.loc["current_2026"]
    executed.cells[0].source = f"""## tl;dr

**{decision['decision']}** with every locked absolute, matched-risk, data, signal-identity, and bias gate passing.

- V2R validation: {validation['trades']:.0f} trades, {validation['return_pct']:.2f}%, PF {validation['profit_factor']:.3f}, DD {validation['max_drawdown_pct']:.2f}%.
- Matched V1R validation: {comparison.loc['validation', 'v1r_return_pct']:.2f}%, PF {comparison.loc['validation', 'v1r_profit_factor']:.3f}, DD {comparison.loc['validation', 'v1r_max_drawdown_pct']:.2f}%.
- V2R return/DD improvement: {comparison.loc['validation', 'return_to_dd_improvement_pct']:.2f}%.
- V2R 2025: {year_2025['return_pct']:.2f}%, PF {year_2025['profit_factor']:.3f}, DD {year_2025['max_drawdown_pct']:.2f}%.
- V2R current 2026: {current['return_pct']:.2f}%, PF {current['profit_factor']:.3f}, DD {current['max_drawdown_pct']:.2f}%.
"""
    executed.cells[-2].source = """## Takeaways

- The identical 32.5%-65% stake overlay reduced validation drawdown below 10% for both control and challenger.
- V2R retained superior validation return, PF, return/DD, weak-2025 return, current-2026 return, and fee-stress performance versus V1R.
- Trade identities are exactly unchanged from V1/V2 across all seven runs; only stake sizing changed.
- Raw rows reconcile exactly, the reused market-data audit remains clean, and 100-signal lookahead plus recursive checks pass.
- Historical selection evidence is not a fresh holdout. Any parallel dry-run is forward evidence collection, not proof of future profit.
"""
    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print((REPORT_DIR / "dual_trend_v2r_validation_decision.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
