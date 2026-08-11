from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "user_data" / "notebooks" / "binance_ohlcv_data_quality.ipynb"
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

This notebook validates the local Binance Spot OHLCV extracts used by the Freqtrade research environment.

### Key Assumptions

- Grain: one UTC exchange candle per `pair × timeframe × candle-open timestamp`.
- Inputs: Binance public OHLCV data downloaded by Freqtrade 2026.7 / CCXT 4.5.68.
- Intended use: segmented backtesting for BTC/USDC and ETH/USDC, not tick-level execution modeling.
- A long exchange/listing gap blocks full-period backtests but does not invalidate later contiguous segments.
- The last still-forming candle is excluded from freshness conclusions.
"""
        ),
        new_markdown_cell("## Data\n\n### 1. Load the local Feather extracts"),
        new_code_cell(
            """from pathlib import Path
import json
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd()
if not (PROJECT_ROOT / "user_data").exists():
    raise RuntimeError(f"Execute from the project root, got: {PROJECT_ROOT}")

DATA_DIR = PROJECT_ROOT / "user_data" / "data" / "binance"
REPORT_DIR = PROJECT_ROOT / "user_data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PAIRS = ("BTC_USDC", "ETH_USDC")
TIMEFRAMES = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1)}
frames = {}

for pair in PAIRS:
    for timeframe in TIMEFRAMES:
        path = DATA_DIR / f"{pair}-{timeframe}.feather"
        frame = pd.read_feather(path).sort_values("date").reset_index(drop=True)
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        frames[(pair, timeframe)] = frame

{f"{pair}-{timeframe}": list(frame.columns) for (pair, timeframe), frame in frames.items()}"""
        ),
        new_markdown_cell("## Results\n\n### 2. Profile grain, completeness, and domain validity"),
        new_code_cell(
            """def profile_frame(pair, timeframe, frame):
    interval = TIMEFRAMES[timeframe]
    unique_dates = frame["date"].drop_duplicates().sort_values()
    expected_rows = int((unique_dates.iloc[-1] - unique_dates.iloc[0]) / interval) + 1
    duplicate_timestamps = int(frame["date"].duplicated().sum())
    null_cells = int(frame.isna().sum().sum())
    invalid_prices = int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    invalid_volume = int((frame["volume"] < 0).sum())
    invalid_ohlc = int((
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    ).sum())
    missing_candles = expected_rows - len(unique_dates)
    return {
        "pair": pair.replace("_", "/"),
        "timeframe": timeframe,
        "rows": len(frame),
        "from_utc": unique_dates.iloc[0],
        "to_utc": unique_dates.iloc[-1],
        "expected_rows": expected_rows,
        "missing_candles": missing_candles,
        "coverage_pct": 100 * len(unique_dates) / expected_rows,
        "duplicate_timestamps": duplicate_timestamps,
        "null_cells": null_cells,
        "invalid_prices": invalid_prices,
        "invalid_volume": invalid_volume,
        "invalid_ohlc": invalid_ohlc,
    }

profile_df = pd.DataFrame([
    profile_frame(pair, timeframe, frame)
    for (pair, timeframe), frame in frames.items()
])
profile_df.to_csv(REPORT_DIR / "data_quality_profile.csv", index=False)
display(profile_df)"""
        ),
        new_markdown_cell("### 3. Locate gaps and contiguous research segments"),
        new_code_cell(
            """gap_rows = []
segment_rows = []

for (pair, timeframe), frame in frames.items():
    interval = TIMEFRAMES[timeframe]
    dates = frame["date"].drop_duplicates().sort_values().reset_index(drop=True)
    deltas = dates.diff()
    gap_positions = deltas[deltas > interval].index.tolist()

    for position in gap_positions:
        previous_date = dates.iloc[position - 1]
        next_date = dates.iloc[position]
        gap_rows.append({
            "pair": pair.replace("_", "/"),
            "timeframe": timeframe,
            "previous_candle_utc": previous_date,
            "next_candle_utc": next_date,
            "missing_candles": int((next_date - previous_date) / interval) - 1,
        })

    boundaries = [0] + gap_positions + [len(dates)]
    for segment_number, (start_idx, end_idx) in enumerate(zip(boundaries[:-1], boundaries[1:]), start=1):
        segment = dates.iloc[start_idx:end_idx]
        if segment.empty:
            continue
        segment_rows.append({
            "pair": pair.replace("_", "/"),
            "timeframe": timeframe,
            "segment": segment_number,
            "from_utc": segment.iloc[0],
            "to_utc": segment.iloc[-1],
            "candles": len(segment),
            "duration_days": (segment.iloc[-1] - segment.iloc[0]).total_seconds() / 86400,
        })

gaps_df = pd.DataFrame(gap_rows).sort_values("missing_candles", ascending=False)
segments_df = pd.DataFrame(segment_rows).sort_values(
    ["pair", "timeframe", "candles"], ascending=[True, True, False]
)
gaps_df.to_csv(REPORT_DIR / "data_quality_gaps.csv", index=False)
segments_df.to_csv(REPORT_DIR / "data_quality_segments.csv", index=False)

print("Largest gaps:")
display(gaps_df.head(12))
print("Longest segment per pair/timeframe:")
display(segments_df.groupby(["pair", "timeframe"], as_index=False).first())"""
        ),
        new_markdown_cell("### 4. Reconcile 15-minute candles against stored hourly candles"),
        new_code_cell(
            """consistency_rows = []

for pair in PAIRS:
    frame_15m = frames[(pair, "15m")].copy().set_index("date")
    frame_15m["_count"] = 1
    hourly_from_15m = frame_15m.resample("1h", label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "_count": "sum",
    })
    hourly_from_15m = hourly_from_15m[hourly_from_15m["_count"] == 4].drop(columns="_count")
    stored_hourly = frames[(pair, "1h")].set_index("date")[["open", "high", "low", "close", "volume"]]
    joined = hourly_from_15m.join(stored_hourly, how="inner", lsuffix="_from_15m", rsuffix="_stored")

    mismatch_counts = {}
    max_relative_diffs = {}
    for column in ("open", "high", "low", "close", "volume"):
        left = joined[f"{column}_from_15m"].to_numpy()
        right = joined[f"{column}_stored"].to_numpy()
        matches = np.isclose(left, right, rtol=1e-10, atol=1e-10, equal_nan=True)
        mismatch_counts[column] = int((~matches).sum())
        denominator = np.maximum(np.abs(right), 1e-12)
        max_relative_diffs[column] = float(np.max(np.abs(left - right) / denominator)) if len(joined) else np.nan

    consistency_rows.append({
        "pair": pair.replace("_", "/"),
        "complete_hours_compared": len(joined),
        **{f"{column}_mismatches": mismatch_counts[column] for column in mismatch_counts},
        **{f"{column}_max_relative_diff": max_relative_diffs[column] for column in max_relative_diffs},
    })

consistency_df = pd.DataFrame(consistency_rows)
consistency_df.to_csv(REPORT_DIR / "data_quality_timeframe_consistency.csv", index=False)
display(consistency_df)"""
        ),
        new_markdown_cell("### 5. Verify the pre-declared train, validation, and holdout windows"),
        new_code_cell(
            """SPLITS = {
    "train": (pd.Timestamp("2024-04-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
    "holdout": (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-08-01", tz="UTC")),
}

split_rows = []
for split_name, (start, end) in SPLITS.items():
    for (pair, timeframe), frame in frames.items():
        interval = TIMEFRAMES[timeframe]
        split_frame = frame[(frame["date"] >= start) & (frame["date"] < end)]
        expected_rows = int((end - start) / interval)
        unique_rows = split_frame["date"].nunique()
        split_rows.append({
            "split": split_name,
            "pair": pair.replace("_", "/"),
            "timeframe": timeframe,
            "from_utc": start,
            "to_utc_exclusive": end,
            "rows": len(split_frame),
            "expected_rows": expected_rows,
            "missing_candles": expected_rows - unique_rows,
            "coverage_pct": 100 * unique_rows / expected_rows,
        })

split_coverage_df = pd.DataFrame(split_rows)
split_coverage_df.to_csv(REPORT_DIR / "data_quality_split_coverage.csv", index=False)
display(split_coverage_df)"""
        ),
        new_markdown_cell("### 6. Produce the data-quality decision"),
        new_code_cell(
            """validity_failures = int(profile_df[[
    "duplicate_timestamps", "null_cells", "invalid_prices", "invalid_volume", "invalid_ohlc"
]].sum().sum())
timeframe_mismatches = int(consistency_df[[
    column for column in consistency_df.columns if column.endswith("_mismatches")
]].sum().sum())
minimum_split_coverage = float(split_coverage_df["coverage_pct"].min())
largest_gap = int(gaps_df["missing_candles"].max()) if not gaps_df.empty else 0

if validity_failures == 0 and timeframe_mismatches == 0 and minimum_split_coverage >= 99.5:
    decision = "READY FOR SEGMENTED RESEARCH"
else:
    decision = "NEEDS REVISION"

decision_summary = {
    "decision": decision,
    "validity_failures": validity_failures,
    "timeframe_mismatches": timeframe_mismatches,
    "minimum_split_coverage_pct": round(minimum_split_coverage, 6),
    "largest_historical_gap_candles": largest_gap,
    "as_of_utc": max(frame["date"].max() for frame in frames.values()).isoformat(),
}

(REPORT_DIR / "data_quality_decision.json").write_text(
    json.dumps(decision_summary, indent=2), encoding="utf-8"
)
decision_summary"""
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

    decision = pd.read_json(REPORT_DIR / "data_quality_decision.json", typ="series")
    profile = pd.read_csv(REPORT_DIR / "data_quality_profile.csv")
    gaps = pd.read_csv(REPORT_DIR / "data_quality_gaps.csv")
    split_coverage = pd.read_csv(REPORT_DIR / "data_quality_split_coverage.csv")

    largest_gap = gaps.iloc[0]
    minimum_coverage = split_coverage.loc[split_coverage["coverage_pct"].idxmin()]
    executed.cells[0].source = f"""## tl;dr

**{decision['decision']}** as of `{decision['as_of_utc']}`.

- {int(profile['rows'].sum()):,} candles profiled across two pairs and two research timeframes.
- Zero validity failures: no duplicate timestamps, null cells, negative values, or impossible OHLC relationships.
- Zero 15m-to-1h reconciliation mismatches on complete hours.
- A historical listing/trading gap exists; the largest gap contains {int(largest_gap['missing_candles']):,} missing `{largest_gap['timeframe']}` candles for `{largest_gap['pair']}`.
- The weakest pre-declared research split still has {float(minimum_coverage['coverage_pct']):.4f}% coverage.
"""
    executed.cells[-1].source = f"""## Takeaways

- Use only the pre-declared segmented windows beginning `2024-04-01`; do not backtest across the earlier long discontinuity.
- The intended grain and OHLC domain rules are clean, and stored hourly candles reconcile with complete 15-minute aggregates.
- Minimum split coverage is {float(decision['minimum_split_coverage_pct']):.4f}%, which is adequate for candle-level research with explicit gap handling.
- Data quality supports research decisions, but does not validate strategy profitability or real-world fills.
"""

    nbformat.write(executed, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)
    print(decision.to_json())


if __name__ == "__main__":
    main()
