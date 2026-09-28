"""TRAIN-only screen for a causal daily cross-sectional momentum family.

This is a diagnostic pre-PnL screen, not a Freqtrade qualification run.  It
uses the frozen 50-pair 4h dataset, information available at the preceding
4h close, exact fixed entry/exit opens, and a 0.075% fee on each side.
Validation/current dates are deliberately excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


TRAIN_START = pd.Timestamp("2021-01-01T00:00:00Z")
TRAIN_END = pd.Timestamp("2024-01-01T00:00:00Z")
FEE_PER_SIDE = 0.00075
MIN_PAIRS = 35


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pair_from_filename(path: Path) -> str:
    return path.name.removesuffix("-4h-futures.feather").replace("_USDT_USDT", "")


def _load_panel(data_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    files = sorted(data_dir.glob("*-4h-futures.feather"))
    if len(files) != 50:
        raise ValueError(f"expected exactly 50 4h files, found {len(files)}")
    frames: dict[str, pd.DataFrame] = {}
    hashes: dict[str, str] = {}
    for path in files:
        pair = _pair_from_filename(path)
        frame = pd.read_feather(path, columns=["date", "open", "close"])
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        frame = frame.drop_duplicates("date").set_index("date").sort_index()
        frames[pair] = frame.astype(float)
        hashes[path.name] = _sha256(path)
    if "BTC" not in frames:
        raise ValueError("BTC reference series is missing")
    return frames, hashes


def _metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "trades_per_day": 0.0, "return_sum_pct": 0.0, "profit_factor": None}
    pnl = trades["net_return"].to_numpy(float)
    wins = float(pnl[pnl > 0].sum())
    losses = float(-pnl[pnl < 0].sum())
    pf = wins / losses if losses > 0 else None
    days = (TRAIN_END - TRAIN_START).total_seconds() / 86400.0
    by_year = {}
    for year, group in trades.groupby(trades["date"].dt.year):
        ypnl = group["net_return"].to_numpy(float)
        ywins = float(ypnl[ypnl > 0].sum())
        ylosses = float(-ypnl[ypnl < 0].sum())
        by_year[str(int(year))] = {
            "trades": int(len(group)),
            "return_sum_pct": float(ypnl.sum() * 100.0),
            "profit_factor": ywins / ylosses if ylosses > 0 else None,
        }
    return {
        "trades": int(len(trades)),
        "trades_per_day": float(len(trades) / days),
        "return_sum_pct": float(pnl.sum() * 100.0),
        "profit_factor": pf,
        "long_trades": int((trades["side"] == 1).sum()),
        "short_trades": int((trades["side"] == -1).sum()),
        "positive_trade_rate": float((pnl > 0).mean()),
        "years": by_year,
    }


def _candidate_trades(
    frames: dict[str, pd.DataFrame],
    momentum_days: int,
    decision_hours: tuple[int, ...],
    hold_hours: int,
    rule: str,
) -> pd.DataFrame:
    close = pd.concat({pair: frame["close"] for pair, frame in frames.items()}, axis=1).sort_index()
    open_ = pd.concat({pair: frame["open"] for pair, frame in frames.items()}, axis=1).reindex(close.index)
    candles = momentum_days * 6
    known_close = close.shift(1)
    momentum = known_close / known_close.shift(candles) - 1.0
    btc_momentum = momentum["BTC"]
    btc_momentum_30d = known_close["BTC"] / known_close["BTC"].shift(30 * 6) - 1.0
    breadth = (momentum > 0).sum(axis=1) / momentum.notna().sum(axis=1).replace(0, np.nan)
    count = momentum.notna().sum(axis=1)
    exit_open = open_.shift(-(hold_hours // 4))
    rows: list[dict] = []
    eligible_dates = close.index[
        (close.index >= TRAIN_START)
        & (close.index < TRAIN_END)
        & close.index.hour.isin(decision_hours)
        & (count >= MIN_PAIRS)
    ]
    for date in eligible_dates:
        scores = momentum.loc[date].dropna()
        if len(scores) < MIN_PAIRS:
            continue
        leader = str(scores.idxmax())
        laggard = str(scores.idxmin())
        if rule == "leader_long":
            pair, side = leader, 1
        elif rule == "btc_regime":
            pair, side = (leader, 1) if btc_momentum.loc[date] >= 0 else (laggard, -1)
        elif rule == "breadth_regime":
            pair, side = (leader, 1) if breadth.loc[date] >= 0.5 else (laggard, -1)
        elif rule == "leader_long_btc30_positive":
            if btc_momentum_30d.loc[date] < 0:
                continue
            pair, side = leader, 1
        elif rule == "leader_long_breadth50":
            if breadth.loc[date] < 0.5:
                continue
            pair, side = leader, 1
        else:
            raise ValueError(f"unknown rule: {rule}")
        entry = float(open_.at[date, pair])
        exit_price = float(exit_open.at[date, pair])
        if not (math.isfinite(entry) and math.isfinite(exit_price) and entry > 0 and exit_price > 0):
            continue
        gross = side * (exit_price / entry - 1.0)
        rows.append(
            {
                "date": date,
                "pair": pair,
                "side": side,
                "gross_return": gross,
                "net_return": gross - 2.0 * FEE_PER_SIDE,
                "momentum": float(scores[pair]),
                "btc_momentum": float(btc_momentum.loc[date]),
                "breadth": float(breadth.loc[date]),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("user_data/data/binance/profit_max_liquid50_cycle1_source/futures"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("user_data/reports/profit_max_daily_cross_screening/train_screen.json"),
    )
    args = parser.parse_args()
    frames, hashes = _load_panel(args.data_dir)
    specs = []
    for momentum_days in (7, 14):
        for decision_hours in ((0,), (0, 12)):
            for hold_hours in (4, 8, 12):
                for rule in (
                    "leader_long",
                    "btc_regime",
                    "breadth_regime",
                    "leader_long_btc30_positive",
                    "leader_long_breadth50",
                ):
                    specs.append((momentum_days, decision_hours, hold_hours, rule))
    results = []
    for momentum_days, decision_hours, hold_hours, rule in specs:
        trades = _candidate_trades(frames, momentum_days, decision_hours, hold_hours, rule)
        metrics = _metrics(trades)
        annual_pass = all(
            year in metrics.get("years", {})
            and metrics["years"][year]["return_sum_pct"] > 0
            and (metrics["years"][year]["profit_factor"] or 0) >= 1.05
            for year in ("2021", "2022", "2023")
        )
        frequency_pass = 1.0 <= metrics["trades_per_day"] <= 2.0
        quality_pass = (metrics["profit_factor"] or 0) >= 1.20
        results.append(
            {
                "candidate": f"mom{momentum_days}d_{'-'.join(map(str, decision_hours))}_{hold_hours}h_{rule}",
                "momentum_days": momentum_days,
                "decision_hours_utc": list(decision_hours),
                "hold_hours": hold_hours,
                "rule": rule,
                "metrics": metrics,
                "diagnostic_pass": bool(annual_pass and frequency_pass and quality_pass),
                "gates": {
                    "all_train_years_positive_pf_1_05": annual_pass,
                    "frequency_1_to_2_per_day": frequency_pass,
                    "overall_pf_1_20": quality_pass,
                },
            }
        )
    results.sort(
        key=lambda row: (
            row["diagnostic_pass"],
            min((year["profit_factor"] or 0) for year in row["metrics"]["years"].values()),
            row["metrics"]["profit_factor"] or 0,
        ),
        reverse=True,
    )
    payload = {
        "schema_version": "1.0",
        "scope": "TRAIN_ONLY_DIAGNOSTIC_NO_FREQTRADE_PNL",
        "timerange": "20210101-20240101",
        "fee_per_side": FEE_PER_SIDE,
        "validation_used_for_selection": False,
        "live_trading_authorized": False,
        "candidate_count": len(results),
        "data_files": hashes,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "top": results[:10]}, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
