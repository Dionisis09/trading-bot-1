#!/usr/bin/env python3
"""Verify Cycle 3's frozen TRAIN artifact and write a terminal decision."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_intraday_cycle3"
MANIFEST_PATH = REPORT / "research_freeze_manifest.json"
ARCHIVE_PATH = REPORT / "train.zip"
DECISION_PATH = REPORT / "train_decision.json"
CANDIDATES = [
    "ProfitMaxIntradayShortProfitOnly15m",
    "ProfitMaxIntradayShortBreakEven15m",
    "ProfitMaxIntradayShortProfitOnlyBreakEven15m",
]
SENSITIVE = {"api_key", "apikey", "jwt_secret_key", "key", "password", "secret", "secret_key", "token", "ws_token"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def assert_redacted(value: object, location: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if key.lower() in SENSITIVE and item not in (None, "", "REDACTED"):
                raise ValueError(f"unredacted secret at {child}")
            assert_redacted(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, f"{location}[{index}]")


def main() -> int:
    if DECISION_PATH.exists():
        print(f"FINALIZE_BLOCKED: decision already exists: {DECISION_PATH}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("candidates") != CANDIDATES:
            raise ValueError("freeze manifest contract mismatch")
        checked = 0
        for item in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / item["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                raise ValueError(f"frozen input mismatch: {item['path']}")
            checked += 1
        with zipfile.ZipFile(ARCHIVE_PATH) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity failed")
            names = archive.namelist()
            results = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            configs = [name for name in names if name.endswith("_config.json")]
            if len(results) != 1 or len(configs) != 1:
                raise ValueError("unexpected result/config member count")
            config = json.loads(archive.read(configs[0]))
            assert_redacted(config)
            if config.get("fee") != 0.00075 or config.get("trading_mode") != "futures" or config.get("margin_mode") != "isolated":
                raise ValueError("embedded execution contract mismatch")
            source_hash = hashlib.sha256((ROOT / "user_data/strategies/ProfitMaxIntradayV3.py").read_bytes()).hexdigest()
            for candidate in CANDIDATES:
                member = [name for name in names if name.endswith(f"_{candidate}.py")]
                if len(member) != 1 or hashlib.sha256(archive.read(member[0])).hexdigest() != source_hash:
                    raise ValueError(f"embedded source mismatch: {candidate}")
            raw = json.loads(archive.read(results[0]))["strategy"]
        if list(raw) != CANDIDATES:
            raise ValueError("candidate result list mismatch")
        starts = {value["backtest_start"] for value in raw.values()}
        ends = {value["backtest_end"] for value in raw.values()}
        if starts != {"2022-01-01 00:00:00"} or ends != {"2024-01-01 00:00:00"}:
            raise ValueError("TRAIN timerange mismatch")
        days = (datetime.fromisoformat(next(iter(ends))) - datetime.fromisoformat(next(iter(starts)))).days
        summaries = {}
        for name in CANDIDATES:
            value = raw[name]
            trades = value["trades"]
            if len(trades) != value["total_trades"]:
                raise ValueError(f"trade count mismatch: {name}")
            if not math.isclose(sum(float(row["profit_abs"]) for row in trades), float(value["profit_total_abs"]), rel_tol=1e-9, abs_tol=1e-7):
                raise ValueError(f"profit mismatch: {name}")
            pair_rows = [row for row in value["results_per_pair"] if row["key"] != "TOTAL"]
            pair_counts = {row["key"]: int(row["trades"]) for row in pair_rows}
            pair_returns = {row["key"]: float(row["profit_total_pct"]) for row in pair_rows}
            return_pct = float(value["profit_total"]) * 100.0
            dd_pct = float(value["max_drawdown_account"]) * 100.0
            frequency = len(trades) / days
            gates = {
                "trade_count_730_to_1460": 730 <= len(trades) <= 1460,
                "frequency_1_to_2_per_day": 1.0 <= frequency <= 2.0,
                "return_positive": return_pct > 0,
                "profit_factor_at_least_1_15": float(value["profit_factor"]) >= 1.15,
                "wallet_drawdown_at_most_10_pct": dd_pct <= 10.0,
                "return_over_drawdown_at_least_0_75": dd_pct > 0 and return_pct / dd_pct >= 0.75,
                "every_pair_at_least_60_trades": len(pair_counts) == 6 and min(pair_counts.values()) >= 60,
                "at_least_four_positive_pairs": sum(item > 0 for item in pair_returns.values()) >= 4,
                "worst_pair_return_above_minus_2_pct": min(pair_returns.values()) > -2.0,
            }
            summaries[name] = {
                "status": "PASS" if all(gates.values()) else "FAIL",
                "trades": len(trades),
                "trades_per_day": frequency,
                "return_pct": return_pct,
                "profit_abs_usdt": float(value["profit_total_abs"]),
                "profit_factor": float(value["profit_factor"]),
                "wallet_max_drawdown_pct": dd_pct,
                "positive_pairs": sum(item > 0 for item in pair_returns.values()),
                "worst_pair_return_pct": min(pair_returns.values()),
                "gates": gates,
                "failed_gates": [key for key, passed in gates.items() if not passed],
            }
        passers = [name for name, value in summaries.items() if value["status"] == "PASS"]
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_intraday_cycle3",
            "status": "PASS" if passers else "FAIL",
            "decision": "UNLOCK_TECHNICAL_GATES" if passers else "KEEP_OFFLINE_RESEARCH",
            "deterministic_exit_tuning_closed": not passers,
            "validation_revealed": False,
            "live_trading_authorized": False,
            "profit_guaranteed": False,
            "fee_per_side": 0.00075,
            "minimum_roundtrip_fee": 0.0015,
            "freeze_manifest_sha256": digest(MANIFEST_PATH),
            "train_archive_sha256": digest(ARCHIVE_PATH),
            "frozen_inputs_reverified": checked,
            "passers": passers,
            "results": summaries,
        }
        with DECISION_PATH.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "passers": passers, "sha256": digest(DECISION_PATH)}))
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
