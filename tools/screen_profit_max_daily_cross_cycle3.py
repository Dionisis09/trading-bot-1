"""TRAIN-only screen of the two natural 8h UTC phases for Cycle 3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from screen_profit_max_daily_cross_sectional import _candidate_trades, _load_panel, _metrics


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data/data/binance/profit_max_liquid50_cycle1_source/futures"
OUTPUT = ROOT / "user_data/reports/profit_max_daily_cross_cycle3_screen/train_screen.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    frames, data_hashes = _load_panel(DATA)
    results = []
    for hours in ((0, 8, 16), (4, 12, 20)):
        trades = _candidate_trades(
            frames,
            momentum_days=7,
            decision_hours=hours,
            hold_hours=8,
            rule="leader_long_btc30_positive",
        )
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
                "candidate": "entry_hours_" + "_".join(map(str, hours)),
                "entry_hours_utc": list(hours),
                "signal_hours_utc": [int((hour - 4) % 24) for hour in hours],
                "metrics": metrics,
                "gates": gates,
                "pass": all(gates.values()),
            }
        )
    base = _candidate_trades(
        frames,
        momentum_days=7,
        decision_hours=(0, 12),
        hold_hours=8,
        rule="leader_long_btc30_positive",
    )
    for bonus_hour in (8, 16):
        bonus = _candidate_trades(
            frames,
            momentum_days=7,
            decision_hours=(bonus_hour,),
            hold_hours=8,
            rule="leader_long_btc30_positive",
        )
        bonus = bonus.loc[bonus["breadth"] >= 0.70]
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
                "candidate": f"base_0_12_bonus_{bonus_hour}_breadth70",
                "entry_hours_utc": [0, 12, bonus_hour],
                "signal_hours_utc": [20, 8, int((bonus_hour - 4) % 24)],
                "bonus_breadth_min": 0.70,
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
            row["candidate"],
        ),
        reverse=True,
    )
    payload = {
        "schema_version": "1.0",
        "scope": "TRAIN_ONLY_DIAGNOSTIC_NO_FREQTRADE_PNL",
        "timerange": "20210101-20240101",
        "fee_per_side": 0.00075,
        "validation_used_for_selection": False,
        "candidate_count": len(results),
        "parent_screen_sha256": digest(ROOT / "user_data/reports/profit_max_daily_cross_screening/train_screen.json"),
        "data_files": data_hashes,
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
