#!/usr/bin/env python3
"""TRAIN-only candidate meta-label screening with expanding OOS predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor


ROOT = Path(__file__).resolve().parents[1]
STRATEGY = "ProfitMaxIntradayShortBase15m"
FEE = 0.00075


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_trades(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"ZIP integrity failed: {path}")
        result_name = next(name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json"))
        config_name = next(name for name in archive.namelist() if name.endswith("_config.json"))
        payload = json.loads(archive.read(result_name))["strategy"][STRATEGY]
        config = json.loads(archive.read(config_name))
    if config.get("fee") != FEE or config.get("trading_mode") != "futures" or config.get("margin_mode") != "isolated":
        raise ValueError(f"execution contract mismatch: {path}")
    frame = pd.DataFrame(payload["trades"])
    if len(frame) != payload["total_trades"] or not (frame["fee_open"] == FEE).all() or not (frame["fee_close"] == FEE).all():
        raise ValueError(f"trade reconciliation failed: {path}")
    frame["open_date"] = pd.to_datetime(frame["open_date"], utc=True)
    frame["signal_date"] = frame["open_date"] - pd.Timedelta(minutes=15)
    frame["year"] = frame["open_date"].dt.year
    return frame


def candle_features(path: Path) -> pd.DataFrame:
    frame = pd.read_feather(path, columns=["date", "open", "high", "low", "close", "volume"])
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    close = pd.to_numeric(frame["close"], errors="coerce")
    log_close = np.log(close.where(close > 0))
    ret1 = log_close.diff()
    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    previous_close = close.shift(1)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous_close).abs(),
        (frame["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = true_range.rolling(14, min_periods=14).mean()
    high_prev32 = frame["high"].rolling(32, min_periods=32).max().shift(1)
    low_prev32 = frame["low"].rolling(32, min_periods=32).min().shift(1)
    volume_prev20 = frame["volume"].rolling(20, min_periods=20).median().shift(1)
    result = pd.DataFrame({
        "date": frame["date"],
        "ret1": ret1,
        "ret4": log_close.diff(4),
        "ret16": log_close.diff(16),
        "ema_gap_atr": (ema20 - ema50) / atr14,
        "channel_position": (close - low_prev32) / (high_prev32 - low_prev32),
        "breakdown_atr": (low_prev32 - close) / atr14,
        "log_volume_ratio": np.log((frame["volume"] / volume_prev20).where(lambda value: value > 0)),
        "atr_close": atr14 / close,
        "realized_vol96": np.sqrt(ret1.pow(2).rolling(96, min_periods=96).sum()),
    })
    return result.replace([np.inf, -np.inf], np.nan)


def attach_features(trades: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    btc = candle_features(data_dir / "BTC_USDT_USDT-15m-futures.feather").rename(columns={
        "ret4": "btc_ret4", "ret16": "btc_ret16", "ema_gap_atr": "btc_ema_gap_atr", "realized_vol96": "btc_realized_vol96"
    })[["date", "btc_ret4", "btc_ret16", "btc_ema_gap_atr", "btc_realized_vol96"]]
    pieces = []
    for pair, group in trades.groupby("pair", sort=True):
        symbol = pair.split("/")[0]
        features = candle_features(data_dir / f"{symbol}_USDT_USDT-15m-futures.feather")
        features = features.merge(btc, on="date", how="left", validate="one_to_one")
        current = group.merge(features, left_on="signal_date", right_on="date", how="left", validate="one_to_one")
        current["relative_ret16"] = current["ret16"] - current["btc_ret16"]
        pieces.append(current)
    result = pd.concat(pieces, ignore_index=True)
    return result


def metrics(frame: pd.DataFrame) -> dict:
    gains = frame.loc[frame["profit_abs"] > 0, "profit_abs"].sum()
    losses = -frame.loc[frame["profit_abs"] < 0, "profit_abs"].sum()
    return {
        "trades": int(len(frame)),
        "trades_per_day": float(len(frame) / 730.0),
        "profit_usdt": float(frame["profit_abs"].sum()),
        "profit_factor": float(gains / losses) if losses else None,
        "positive_pairs": int((frame.groupby("pair")["profit_abs"].sum() > 0).sum()),
        "years": {
            str(year): {
                "trades": int(len(group)),
                "profit_usdt": float(group["profit_abs"].sum()),
                "profit_factor": float(group.loc[group["profit_abs"] > 0, "profit_abs"].sum() / -group.loc[group["profit_abs"] < 0, "profit_abs"].sum()) if (group["profit_abs"] < 0).any() else None,
            }
            for year, group in frame.groupby("year")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", required=True)
    parser.add_argument("--oos", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    history_path = (ROOT / args.history).resolve()
    oos_path = (ROOT / args.oos).resolve()
    data_dir = (ROOT / args.data_dir).resolve()
    output = (ROOT / args.output).resolve()
    if output.exists():
        raise FileExistsError(output)

    trades = pd.concat([load_trades(history_path), load_trades(oos_path)], ignore_index=True)
    frame = attach_features(trades, data_dir)
    numeric = [
        "ret1", "ret4", "ret16", "ema_gap_atr", "channel_position", "breakdown_atr",
        "log_volume_ratio", "atr_close", "realized_vol96", "btc_ret4", "btc_ret16",
        "btc_ema_gap_atr", "btc_realized_vol96", "relative_ret16",
    ]
    pair_columns = sorted(frame["pair"].unique())
    pair_feature_names = {pair: f"pair_{pair.split('/')[0].lower()}" for pair in pair_columns}
    encoded = pd.DataFrame({
        name: frame["pair"].eq(pair).astype(float)
        for pair, name in pair_feature_names.items()
    })
    matrix = pd.concat([frame[numeric].reset_index(drop=True), encoded.reset_index(drop=True)], axis=1)
    if matrix.isna().any().any():
        raise ValueError("feature mapping contains NaN")
    predictions = pd.Series(np.nan, index=frame.index, dtype=float)
    folds = []
    for year in (2022, 2023):
        train_mask = frame["year"] < year
        test_mask = frame["year"] == year
        model = LGBMRegressor(
            n_estimators=200, learning_rate=0.03, num_leaves=15, max_depth=4,
            min_child_samples=100, subsample=1.0, colsample_bytree=1.0,
            reg_alpha=0.0, reg_lambda=1.0, n_jobs=2, deterministic=True,
            force_col_wise=True, random_state=20260817, verbosity=-1,
        )
        model.fit(matrix.loc[train_mask], frame.loc[train_mask, "profit_ratio"])
        predictions.loc[test_mask] = model.predict(matrix.loc[test_mask])
        folds.append({"test_year": year, "train_rows": int(train_mask.sum()), "test_rows": int(test_mask.sum())})
    oos = frame.loc[frame["year"].isin([2022, 2023])].copy()
    oos["prediction"] = predictions.loc[oos.index]
    if oos["prediction"].isna().any():
        raise ValueError("OOS prediction missing")
    ranked = oos.sort_values("prediction", ascending=False)
    annual_top365 = pd.concat([
        group.sort_values("prediction", ascending=False).head(min(365, len(group)))
        for _, group in oos.groupby("year")
    ], ignore_index=True)
    payload = {
        "schema_version": "1.0",
        "status": "POST_FAILURE_SCREENING_ONLY",
        "qualification_evidence": False,
        "live_trading_authorized": False,
        "fee_per_side": FEE,
        "features": numeric + list(pair_feature_names.values()),
        "folds": folds,
        "all_oos": metrics(oos),
        "top_730_global_noncausal_diagnostic": metrics(ranked.head(730)),
        "top_365_per_year_noncausal_diagnostic": metrics(annual_top365),
        "caveat": "Trade-level screening ignores changed concurrency and uses ex-post fixed-count ranking; it cannot authorize a strategy or threshold.",
        "inputs": {
            "history": {"path": history_path.relative_to(ROOT).as_posix(), "sha256": digest(history_path)},
            "oos": {"path": oos_path.relative_to(ROOT).as_posix(), "sha256": digest(oos_path)},
            "data_dir": data_dir.relative_to(ROOT).as_posix(),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps({"status": payload["status"], "top730": payload["top_730_global_noncausal_diagnostic"], "sha256": digest(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
