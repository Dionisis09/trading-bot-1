"""TRAIN-only screen for a second/third-ranked breadth bonus."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from screen_profit_max_daily_cross_sectional import (
    FEE_PER_SIDE,
    MIN_PAIRS,
    TRAIN_END,
    TRAIN_START,
    _candidate_trades,
    _load_panel,
    _metrics,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"
OUTPUT = ROOT / "user_data/reports/profit_max_daily_cross_cycle4_screen/train_screen.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def bonus_trades(
    frames: dict[str, pd.DataFrame], rank_from_top: int, breadth_minimum: float
) -> pd.DataFrame:
    close = pd.concat({pair: frame["close"] for pair, frame in frames.items()}, axis=1, sort=True).sort_index()
    open_ = pd.concat({pair: frame["open"] for pair, frame in frames.items()}, axis=1, sort=True).reindex(close.index)
    known = close.shift(1)
    momentum = known / known.shift(42) - 1.0
    count = momentum.notna().sum(axis=1)
    breadth = (momentum > 0).sum(axis=1) / count.replace(0, pd.NA)
    btc30 = known["BTC"] / known["BTC"].shift(180) - 1.0
    exit_open = open_.shift(-2)
    rows = []
    dates = close.index[
        (close.index >= TRAIN_START)
        & (close.index < TRAIN_END)
        & (close.index.hour == 16)
        & (count >= MIN_PAIRS)
        & (breadth >= breadth_minimum)
        & (btc30 > 0)
    ]
    for date in dates:
        scores = momentum.loc[date].dropna().sort_values(ascending=False, kind="stable")
        pair = str(scores.index[rank_from_top - 1])
        entry = float(open_.at[date, pair])
        exit_price = float(exit_open.at[date, pair])
        if not (math.isfinite(entry) and math.isfinite(exit_price) and entry > 0 and exit_price > 0):
            continue
        gross = exit_price / entry - 1.0
        rows.append(
            {
                "date": date,
                "pair": pair,
                "side": 1,
                "gross_return": gross,
                "net_return": gross - 2.0 * FEE_PER_SIDE,
                "momentum": float(scores.iloc[rank_from_top - 1]),
                "btc_momentum": float(btc30.at[date]),
                "breadth": float(breadth.at[date]),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    frames, hashes = _load_panel(DATA)
    base = _candidate_trades(frames, 7, (0, 12), 8, "leader_long_btc30_positive")
    results = []
    for rank in (2, 3):
        for breadth_minimum in (0.70, 0.80, 0.90):
            bonus = bonus_trades(frames, rank, breadth_minimum)
            trades = pd.concat([base, bonus], ignore_index=True).sort_values("date")
            metrics = _metrics(trades)
            gates = {
            "frequency_1_to_2": 1.0 <= metrics["trades_per_day"] <= 2.0,
            "profit_factor_1_20": (metrics["profit_factor"] or 0) >= 1.20,
            "all_years_positive_pf_1_05": all(
                metrics["years"][year]["return_sum_pct"] > 0
                and (metrics["years"][year]["profit_factor"] or 0) >= 1.05
                for year in ("2021", "2022", "2023")
            ),
        }
            results.append(
                {
                "candidate": f"base_leader_bonus_rank{rank}_16_breadth{int(breadth_minimum * 100)}",
                "bonus_rank_from_top": rank,
                "bonus_breadth_minimum": breadth_minimum,
                "bonus_trade_count": len(bonus),
                "metrics": metrics,
                "gates": gates,
                "pass": all(gates.values()),
                }
            )
    results.sort(
        key=lambda row: (
            row["pass"],
            min((year["profit_factor"] or 0) for year in row["metrics"]["years"].values()),
            row["metrics"]["profit_factor"] or 0,
            -row["bonus_rank_from_top"],
        ),
        reverse=True,
    )
    payload = {
        "schema_version": "1.0",
        "scope": "TRAIN_ONLY_DIAGNOSTIC_NO_FREQTRADE_PNL",
        "timerange": "20210101-20240101",
        "fee_per_side": 0.00075,
        "validation_used_for_selection": False,
        "data_files": hashes,
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
