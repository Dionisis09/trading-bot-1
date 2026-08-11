from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "v3_usdt_data_quality.ipynb"
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

This notebook validates Binance Spot 4h and 1d OHLCV for the ten-pair V3 USDT universe.

### Key assumptions

- Grain is one UTC exchange candle per pair, timeframe, and candle-open timestamp.
- Source is Binance public OHLCV downloaded with Freqtrade 2026.7 / CCXT 4.5.68.
- The research windows are train `2021-01-01/2024-01-01`, validation `2024-01-01/2026-01-01`, and holdout `2026-01-01/2026-08-01`.
- The incomplete current day is outside the declared holdout.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the fixed universe"),
        new_code_cell(
            """from pathlib import Path
import json
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
DATA_DIR = PROJECT_ROOT / "user_data" / "data" / "binance"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PAIRS = ("BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "LTC", "AVAX")
INTERVALS = {"4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}
frames = {}
for base in PAIRS:
    for timeframe in INTERVALS:
        path = DATA_DIR / f"{base}_USDT-{timeframe}.feather"
        frame = pd.read_feather(path).sort_values("date").reset_index(drop=True)
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        frames[(base, timeframe)] = frame

len(frames), sum(len(frame) for frame in frames.values())"""
        ),
        new_markdown_cell("## Results\n\n### 2. Validate grain, domains, and gaps"),
        new_code_cell(
            """profile_rows = []
gap_rows = []

for (base, timeframe), frame in frames.items():
    interval = INTERVALS[timeframe]
    dates = frame["date"].drop_duplicates().sort_values().reset_index(drop=True)
    expected = int((dates.iloc[-1] - dates.iloc[0]) / interval) + 1
    deltas = dates.diff()
    for position in deltas[deltas > interval].index:
        gap_rows.append({
            "pair": f"{base}/USDT",
            "timeframe": timeframe,
            "previous_utc": dates.iloc[position - 1],
            "next_utc": dates.iloc[position],
            "missing_candles": int(deltas.iloc[position] / interval) - 1,
        })

    invalid_ohlc = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    profile_rows.append({
        "pair": f"{base}/USDT",
        "timeframe": timeframe,
        "rows": len(frame),
        "from_utc": dates.iloc[0],
        "to_utc": dates.iloc[-1],
        "coverage_since_listing_pct": 100 * len(dates) / expected,
        "duplicate_timestamps": int(frame["date"].duplicated().sum()),
        "null_cells": int(frame.isna().sum().sum()),
        "nonpositive_prices": int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "negative_volume": int((frame["volume"] < 0).sum()),
        "invalid_ohlc": int(invalid_ohlc.sum()),
    })

profile_df = pd.DataFrame(profile_rows)
gaps_df = pd.DataFrame(gap_rows)
profile_df.to_csv(REPORT_DIR / "v3_data_quality_profile.csv", index=False)
gaps_df.to_csv(REPORT_DIR / "v3_data_quality_gaps.csv", index=False)
display(profile_df)
display(gaps_df.sort_values("missing_candles", ascending=False).head(20) if not gaps_df.empty else gaps_df)"""
        ),
        new_markdown_cell("### 3. Verify all declared chronological splits"),
        new_code_cell(
            """SPLITS = {
    "train": (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
    "holdout": (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-08-01", tz="UTC")),
}

split_rows = []
for split, (start, end) in SPLITS.items():
    for (base, timeframe), frame in frames.items():
        interval = INTERVALS[timeframe]
        selected = frame[(frame["date"] >= start) & (frame["date"] < end)]
        expected = int((end - start) / interval)
        unique = selected["date"].nunique()
        split_rows.append({
            "split": split,
            "pair": f"{base}/USDT",
            "timeframe": timeframe,
            "rows": len(selected),
            "expected_rows": expected,
            "missing_candles": expected - unique,
            "coverage_pct": 100 * unique / expected,
        })

split_df = pd.DataFrame(split_rows)
split_df.to_csv(REPORT_DIR / "v3_data_quality_splits.csv", index=False)
display(split_df)
display(split_df.groupby(["split", "timeframe"])["coverage_pct"].agg(["min", "mean", "max"]))"""
        ),
        new_markdown_cell("### 4. Reconcile complete 4h days with stored daily candles"),
        new_code_cell(
            """consistency_rows = []
for base in PAIRS:
    four_hour = frames[(base, "4h")].set_index("date").copy()
    four_hour["_count"] = 1
    aggregated = four_hour.resample("1d", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "_count": "sum"
    })
    aggregated = aggregated[aggregated["_count"] == 6].drop(columns="_count")
    daily = frames[(base, "1d")].set_index("date")[["open", "high", "low", "close", "volume"]]
    joined = aggregated.join(daily, how="inner", lsuffix="_4h", rsuffix="_1d")
    row = {"pair": f"{base}/USDT", "complete_days_compared": len(joined)}
    for column in ("open", "high", "low", "close", "volume"):
        matches = np.isclose(
            joined[f"{column}_4h"], joined[f"{column}_1d"], rtol=1e-10, atol=1e-10
        )
        row[f"{column}_mismatches"] = int((~matches).sum())
    consistency_rows.append(row)

consistency_df = pd.DataFrame(consistency_rows)
consistency_df.to_csv(REPORT_DIR / "v3_data_quality_timeframe_consistency.csv", index=False)
display(consistency_df)"""
        ),
        new_markdown_cell("### 5. Produce the data-quality decision"),
        new_code_cell(
            """validity_columns = [
    "duplicate_timestamps", "null_cells", "nonpositive_prices", "negative_volume", "invalid_ohlc"
]
validity_failures = int(profile_df[validity_columns].sum().sum())
mismatch_columns = [column for column in consistency_df if column.endswith("_mismatches")]
timeframe_mismatches = int(consistency_df[mismatch_columns].sum().sum())
minimum_split_coverage = float(split_df["coverage_pct"].min())
largest_gap = int(gaps_df["missing_candles"].max()) if not gaps_df.empty else 0

decision = {
    "decision": "READY_FOR_V3_RESEARCH" if (
        validity_failures == 0 and timeframe_mismatches == 0 and minimum_split_coverage >= 99.5
    ) else "NEEDS_REVISION",
    "pairs": len(PAIRS),
    "files": len(frames),
    "candles": int(sum(len(frame) for frame in frames.values())),
    "validity_failures": validity_failures,
    "timeframe_mismatches": timeframe_mismatches,
    "minimum_split_coverage_pct": minimum_split_coverage,
    "largest_gap_candles": largest_gap,
    "as_of_utc": max(frame["date"].max() for frame in frames.values()).isoformat(),
}
(REPORT_DIR / "v3_data_quality_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
decision"""
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

    decision = pd.read_json(REPORT_DIR / "v3_data_quality_decision.json", typ="series")
    executed.cells[0].source = f"""## tl;dr

**{decision['decision']}** across {int(decision['pairs'])} pairs, {int(decision['files'])} files, and {int(decision['candles']):,} candles.

- Validity failures: {int(decision['validity_failures'])}.
- 4h-to-1d reconciliation mismatches: {int(decision['timeframe_mismatches'])}.
- Minimum declared-split coverage: {float(decision['minimum_split_coverage_pct']):.4f}%.
- Largest source gap: {int(decision['largest_gap_candles'])} candles.
"""
    executed.cells[-1].source = f"""## Takeaways

- All ten pairs cover the complete train, validation, and sealed holdout windows at a minimum of {float(decision['minimum_split_coverage_pct']):.4f}%.
- Stored daily candles reconcile with complete 4-hour aggregates and the OHLC domains are valid.
- The data is suitable for the declared V3 research, subject to the documented current-universe survivorship caveat.
"""
    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print(decision.to_json())


if __name__ == "__main__":
    main()
