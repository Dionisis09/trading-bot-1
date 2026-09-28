#!/usr/bin/env python3
"""Verify the frozen ML TRAIN artifact and write its terminal gate decision."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_intraday_ml_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"
ARCHIVE = REPORT / "train.zip"
MODELS = REPORT / "models"
DECISION = REPORT / "train_decision.json"
STRATEGY = "ProfitMaxIntradayMLV1"
SENSITIVE = {"api_key", "apikey", "jwt_secret_key", "key", "password", "secret", "secret_key", "token", "ws_token"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def redacted(value: object) -> bool:
    if isinstance(value, dict):
        return all((key.lower() not in SENSITIVE or item in (None, "", "REDACTED")) and redacted(item) for key, item in value.items())
    if isinstance(value, list):
        return all(redacted(item) for item in value)
    return True


def model_inventory() -> dict:
    rows = []
    total = 0
    for path in sorted(item for item in MODELS.rglob("*") if item.is_file() and not item.is_symlink()):
        size = path.stat().st_size
        total += size
        rows.append({"path": path.relative_to(MODELS).as_posix(), "bytes": size, "sha256": digest(path)})
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return {"file_count": len(rows), "total_bytes": total, "inventory_sha256": hashlib.sha256(encoded).hexdigest()}


def main() -> int:
    if DECISION.exists():
        print(f"FINALIZE_BLOCKED: decision already exists: {DECISION}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_MODEL_AND_PNL" or manifest.get("candidate") != STRATEGY:
            raise ValueError("freeze contract mismatch")
        checked = 0
        for item in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / item["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                raise ValueError(f"frozen input mismatch: {item['path']}")
            checked += 1
        with zipfile.ZipFile(ARCHIVE) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity failed")
            names = archive.namelist()
            results = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            configs = [name for name in names if name.endswith("_config.json")]
            sources = [name for name in names if name.endswith(f"_{STRATEGY}.py")]
            if len(results) != 1 or len(configs) != 1 or len(sources) != 1:
                raise ValueError("archive member contract mismatch")
            config = json.loads(archive.read(configs[0]))
            if not redacted(config) or config.get("fee") != 0.00075 or config.get("freqaimodel") != "LightGBMRegressor":
                raise ValueError("embedded config/redaction mismatch")
            source_hash = hashlib.sha256(archive.read(sources[0])).hexdigest()
            if source_hash != digest(ROOT / "user_data/strategies/ProfitMaxIntradayMLV1.py"):
                raise ValueError("embedded strategy mismatch")
            raw = json.loads(archive.read(results[0]))["strategy"][STRATEGY]
        trades = raw["trades"]
        if len(trades) != raw["total_trades"] or not math.isclose(sum(float(row["profit_abs"]) for row in trades), float(raw["profit_total_abs"]), abs_tol=1e-7):
            raise ValueError("trade/profit reconciliation failed")
        pair_rows = [row for row in raw["results_per_pair"] if row["key"] != "TOTAL"]
        pair_counts = {row["key"]: int(row["trades"]) for row in pair_rows}
        pair_returns = {row["key"]: float(row["profit_total_pct"]) for row in pair_rows}
        return_pct = float(raw["profit_total"]) * 100.0
        dd_pct = float(raw["max_drawdown_account"]) * 100.0
        frequency = len(trades) / 730.0
        gates = {
            "trade_count_730_to_1460": 730 <= len(trades) <= 1460,
            "frequency_1_to_2_per_day": 1.0 <= frequency <= 2.0,
            "return_positive": return_pct > 0.0,
            "profit_factor_at_least_1_15": float(raw["profit_factor"]) >= 1.15,
            "wallet_drawdown_at_most_10_pct": dd_pct <= 10.0,
            "return_over_drawdown_at_least_0_75": dd_pct > 0.0 and return_pct / dd_pct >= 0.75,
            "every_pair_at_least_60_trades": len(pair_counts) == 6 and min(pair_counts.values()) >= 60,
            "at_least_four_positive_pairs": sum(value > 0.0 for value in pair_returns.values()) >= 4,
            "worst_pair_return_above_minus_2_pct": min(pair_returns.values()) > -2.0,
        }
        passed = all(gates.values())
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_intraday_ml_cycle1",
            "status": "PASS" if passed else "FAIL",
            "decision": "UNLOCK_TECHNICAL_GATES" if passed else "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": False,
            "live_trading_authorized": False,
            "profit_guaranteed": False,
            "fee_per_side": 0.00075,
            "freeze_manifest_sha256": digest(MANIFEST),
            "train_archive_sha256": digest(ARCHIVE),
            "frozen_inputs_reverified": checked,
            "model_inventory": model_inventory(),
            "result": {
                "trades": len(trades),
                "trades_per_day": frequency,
                "return_pct": return_pct,
                "profit_abs_usdt": float(raw["profit_total_abs"]),
                "profit_factor": float(raw["profit_factor"]),
                "wallet_max_drawdown_pct": dd_pct,
                "positive_pairs": sum(value > 0.0 for value in pair_returns.values()),
                "worst_pair_return_pct": min(pair_returns.values()),
                "pair_trade_counts": pair_counts,
                "pair_returns_pct": pair_returns,
                "gates": gates,
                "failed_gates": [key for key, value in gates.items() if not value],
            },
        }
        with DECISION.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "sha256": digest(DECISION)}))
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
