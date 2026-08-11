#!/usr/bin/env python3
"""Reconcile the newest production-profile backtest artifact for each locked split."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SPLITS = {
    ("2021-01-01", "2022-01-01"): "2021",
    ("2022-01-01", "2023-01-01"): "2022",
    ("2023-01-01", "2024-01-01"): "2023",
    ("2024-01-01", "2025-01-01"): "2024",
    ("2025-01-01", "2026-01-01"): "2025",
    ("2026-01-01", "2026-08-01"): "current_2026",
    ("2024-01-01", "2026-01-01"): "validation",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_result(archive: Path, strategy: str) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_path = archive.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(archive) as bundle:
        result_names = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(result_names) != 1:
            raise ValueError(f"Expected one result JSON in {archive}")
        result = json.loads(bundle.read(result_names[0]))
    return meta[strategy], result["strategy"][strategy]


def select_latest(directory: Path, prefix: str, strategy: str) -> dict[str, Path]:
    selected: dict[str, Path] = {}
    for archive in directory.glob(f"{prefix}-*.zip"):
        try:
            meta, _ = load_result(archive, strategy)
        except (OSError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
            continue
        start = datetime.fromtimestamp(meta["backtest_start_ts"], timezone.utc).date().isoformat()
        end = datetime.fromtimestamp(meta["backtest_end_ts"], timezone.utc).date().isoformat()
        split = SPLITS.get((start, end))
        if split is None:
            continue
        if split not in selected or archive.stat().st_mtime_ns > selected[split].stat().st_mtime_ns:
            selected[split] = archive
    missing = sorted(set(SPLITS.values()) - set(selected))
    if missing:
        raise ValueError(f"Missing production-profile backtests: {', '.join(missing)}")
    return selected


def build_summary(directory: Path, prefix: str, strategy: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = select_latest(directory, prefix, strategy)
    rows = []
    for split in ("validation", "2021", "2022", "2023", "2024", "2025", "current_2026"):
        archive = selected[split]
        _, result = load_result(archive, strategy)
        trades = result.get("trades", [])
        fee = trades[0].get("fee_open") if trades else 0.0005
        rows.append(
            {
                "artifact": archive.name,
                "strategy": strategy,
                "split": split,
                "starting_wallet_usdt": 1000.0,
                "stake_amount_usdt": 25.0,
                "max_open_trades": 2,
                "fee_per_side": fee,
                "trades": result.get("total_trades"),
                "long_trades": result.get("trade_count_long"),
                "short_trades": result.get("trade_count_short"),
                "return_pct": float(result.get("profit_total", 0.0)) * 100.0,
                "profit_abs_usdt": result.get("profit_total_abs"),
                "profit_factor": result.get("profit_factor"),
                "max_drawdown_pct": float(result.get("max_drawdown_account", 0.0)) * 100.0,
                "market_change_pct": float(result.get("market_change", 0.0)) * 100.0,
            }
        )
    root = Path(__file__).resolve().parents[1]
    evidence_files = [
        root / "user_data/strategies/ProfessionalRisk.py",
        root / "user_data/strategies/DualTrendFuturesV1.py",
        root / "user_data/strategies/DualTrendFuturesV2.py",
        root / "user_data/strategies/DualTrendFuturesRisk.py",
        root / "user_data/risk_policy.json",
        root / "user_data/config-dual-futures-v2r-dry-run.json",
    ]
    manifest = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "strategy": strategy,
        "profile": {
            "starting_wallet_usdt": 1000.0,
            "stake_amount_usdt": 25.0,
            "max_open_trades": 2,
            "fee_per_side": 0.0005,
            "protections_enabled": True,
            "leverage": 1.0,
            "margin_mode": "isolated",
        },
        "source_hashes": {
            str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in evidence_files
        },
        "artifacts": [
            {
                "split": row["split"],
                "file": row["artifact"],
                "sha256": sha256(directory / row["artifact"]),
            }
            for row in rows
        ],
        "live_trading_authorized": False,
    }
    return rows, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest-dir", default="user_data/backtest_results")
    parser.add_argument("--prefix", default="professional_live_profile")
    parser.add_argument("--strategy", default="DualTrendFuturesV2R")
    parser.add_argument("--summary", default="user_data/reports/professional_risk_backtest_summary.csv")
    parser.add_argument("--manifest", default="user_data/reports/professional_risk_backtest_manifest.json")
    args = parser.parse_args()
    rows, manifest = build_summary(Path(args.backtest_dir), args.prefix, args.strategy)
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    Path(args.manifest).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "summary": args.summary, "manifest": args.manifest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
