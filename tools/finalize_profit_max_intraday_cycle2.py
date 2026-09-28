#!/usr/bin/env python3
"""Verify the frozen Cycle 2 TRAIN artifact and write its terminal decision."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "user_data/reports/profit_max_intraday_cycle2"
MANIFEST_PATH = REPORT_DIR / "research_freeze_manifest.json"
ARCHIVE_PATH = REPORT_DIR / "train.zip"
DECISION_PATH = REPORT_DIR / "train_decision.json"
EXPECTED = [
    "ProfitMaxIntradayShortTight15m",
    "ProfitMaxIntradayShortBase15m",
    "ProfitMaxIntradayAsymmetric15m",
]
SENSITIVE_KEYS = {"api_key", "apikey", "jwt_secret_key", "key", "password", "secret", "secret_key", "token", "ws_token"}


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def assert_redacted(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key.lower() in SENSITIVE_KEYS and item not in (None, "", "REDACTED"):
                raise ValueError(f"unredacted sensitive value at {child}")
            assert_redacted(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, f"{path}[{index}]")


def close_enough(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def verify_frozen_inputs(manifest: dict) -> int:
    checked = 0
    for item in list(manifest["files"].values()) + manifest["data_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
            raise ValueError(f"frozen input mismatch: {item['path']}")
        checked += 1
    return checked


def candidate_result(name: str, result: dict, days: int) -> dict:
    trades = result.get("trades") or []
    if len(trades) != result.get("total_trades"):
        raise ValueError(f"trade-count reconciliation failed for {name}")
    profit_abs = sum(float(trade["profit_abs"]) for trade in trades)
    if not close_enough(profit_abs, float(result["profit_total_abs"]), tolerance=1e-7):
        raise ValueError(f"absolute-profit reconciliation failed for {name}")
    gross_win = sum(max(float(trade["profit_abs"]), 0.0) for trade in trades)
    gross_loss = -sum(min(float(trade["profit_abs"]), 0.0) for trade in trades)
    independent_pf = gross_win / gross_loss if gross_loss else math.inf
    if not close_enough(independent_pf, float(result["profit_factor"]), tolerance=1e-12):
        raise ValueError(f"profit-factor reconciliation failed for {name}")

    pair_rows = [row for row in result["results_per_pair"] if row["key"] != "TOTAL"]
    pair_counts = {row["key"]: int(row["trades"]) for row in pair_rows}
    pair_returns = {row["key"]: float(row["profit_total_pct"]) for row in pair_rows}
    return_pct = float(result["profit_total"]) * 100.0
    drawdown_pct = float(result["max_drawdown_account"]) * 100.0
    return_dd = return_pct / drawdown_pct if drawdown_pct > 0 else None
    trades_per_day = len(trades) / days
    positive_pairs = sum(value > 0 for value in pair_returns.values())
    gates = {
        "trade_count_730_to_1460": 730 <= len(trades) <= 1460,
        "frequency_1_to_2_per_day": 1.0 <= trades_per_day <= 2.0,
        "return_positive": return_pct > 0,
        "profit_factor_at_least_1_15": float(result["profit_factor"]) >= 1.15,
        "wallet_drawdown_at_most_10_pct": drawdown_pct <= 10.0,
        "return_over_drawdown_at_least_0_75": return_dd is not None and return_dd >= 0.75,
        "every_pair_at_least_60_trades": len(pair_counts) == 6 and min(pair_counts.values()) >= 60,
        "at_least_four_positive_pairs": positive_pairs >= 4,
        "worst_pair_return_above_minus_2_pct": min(pair_returns.values()) > -2.0,
    }
    if name == "ProfitMaxIntradayAsymmetric15m":
        gates.update(
            {
                "at_least_100_long_trades": int(result["trade_count_long"]) >= 100,
                "long_side_positive": float(result["profit_total_long"]) > 0,
                "short_side_positive": float(result["profit_total_short"]) > 0,
            }
        )
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "trades": len(trades),
        "days": days,
        "trades_per_day": trades_per_day,
        "return_pct": return_pct,
        "profit_abs_usdt": float(result["profit_total_abs"]),
        "profit_factor": float(result["profit_factor"]),
        "wallet_max_drawdown_pct": drawdown_pct,
        "return_over_drawdown": return_dd,
        "wins": int(result["wins"]),
        "draws": int(result["draws"]),
        "losses": int(result["losses"]),
        "long_trades": int(result["trade_count_long"]),
        "short_trades": int(result["trade_count_short"]),
        "long_return_pct": float(result["profit_total_long"]) * 100.0,
        "short_return_pct": float(result["profit_total_short"]) * 100.0,
        "positive_pairs": positive_pairs,
        "pair_trade_counts": pair_counts,
        "pair_returns_pct": pair_returns,
        "gates": gates,
        "failed_gates": [key for key, passed in gates.items() if not passed],
    }


def main() -> int:
    if DECISION_PATH.exists():
        print(f"FINALIZE_BLOCKED: decision already exists: {DECISION_PATH}", file=sys.stderr)
        return 3
    if not MANIFEST_PATH.is_file() or not ARCHIVE_PATH.is_file():
        print("FINALIZE_BLOCKED: manifest or TRAIN archive missing", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("pnl_parsed") is not False:
            raise ValueError("invalid pre-PnL freeze state")
        if manifest.get("candidates") != EXPECTED:
            raise ValueError("candidate list differs from frozen plan")
        frozen_inputs_checked = verify_frozen_inputs(manifest)
        with zipfile.ZipFile(ARCHIVE_PATH) as archive:
            if archive.testzip() is not None:
                raise ValueError("TRAIN ZIP integrity failed")
            names = archive.namelist()
            result_names = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            config_names = [name for name in names if name.endswith("_config.json")]
            if len(result_names) != 1 or len(config_names) != 1:
                raise ValueError("TRAIN ZIP must contain exactly one result and config JSON")
            config = json.loads(archive.read(config_names[0]))
            assert_redacted(config)
            if config.get("fee") != 0.00075 or config.get("trading_mode") != "futures" or config.get("margin_mode") != "isolated":
                raise ValueError("embedded config execution contract mismatch")
            source = (ROOT / "user_data/strategies/ProfitMaxIntradayV2.py").read_bytes()
            for candidate in EXPECTED:
                members = [name for name in names if name.endswith(f"_{candidate}.py")]
                if len(members) != 1 or digest_bytes(archive.read(members[0])) != digest_bytes(source):
                    raise ValueError(f"embedded strategy source mismatch for {candidate}")
            raw = json.loads(archive.read(result_names[0]))
        if list(raw.get("strategy", {}).keys()) != EXPECTED:
            raise ValueError("result strategies are missing, reordered, or unexpected")
        starts = {value["backtest_start"] for value in raw["strategy"].values()}
        ends = {value["backtest_end"] for value in raw["strategy"].values()}
        if starts != {"2022-01-01 00:00:00"} or ends != {"2024-01-01 00:00:00"}:
            raise ValueError("TRAIN timerange mismatch")
        days = (datetime.fromisoformat(next(iter(ends))) - datetime.fromisoformat(next(iter(starts)))).days
        results = {name: candidate_result(name, raw["strategy"][name], days) for name in EXPECTED}
        passers = [name for name, result in results.items() if result["status"] == "PASS"]
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_intraday_cycle2",
            "status": "PASS" if passers else "FAIL",
            "decision": "UNLOCK_TECHNICAL_GATES" if passers else "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": False,
            "live_trading_authorized": False,
            "profit_guaranteed": False,
            "fee_per_side": 0.00075,
            "minimum_roundtrip_fee": 0.0015,
            "freeze_manifest_sha256": digest(MANIFEST_PATH),
            "train_archive": {
                "path": ARCHIVE_PATH.relative_to(ROOT).as_posix(),
                "sha256": digest(ARCHIVE_PATH),
                "zip_integrity": "PASS",
                "config_redaction": "PASS",
                "embedded_strategy_reconciliation": "PASS",
            },
            "frozen_inputs_reverified": frozen_inputs_checked,
            "passers": passers,
            "results": results,
        }
        encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        with DECISION_PATH.open("xb") as handle:
            handle.write(encoded)
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "passers": passers, "sha256": digest(DECISION_PATH)}))
        return 0
    except (KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
