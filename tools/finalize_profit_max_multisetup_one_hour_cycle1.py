#!/usr/bin/env python3
"""Fail-closed core-gate reconciliation for the 1h multi-setup TRAIN."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_multisetup_one_hour_cycle1"
MANIFEST, ARCHIVE, DECISION = REPORT / "research_freeze_manifest.json", REPORT / "train.zip", REPORT / "train_decision.json"
CANDIDATES = ["ProfitMaxOneHourPullback", "ProfitMaxOneHourBreakout", "ProfitMaxOneHourHybrid"]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    if DECISION.exists():
        print(f"FINALIZE_BLOCKED: decision exists: {DECISION}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("candidates") != CANDIDATES:
            raise ValueError("manifest mismatch")
        checked = 0
        for row in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / row["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != row["sha256"]:
                raise ValueError(f"frozen input drift: {row['path']}")
            checked += 1
        with zipfile.ZipFile(ARCHIVE) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity failed")
            result_names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
            if len(result_names) != 1:
                raise ValueError("result inventory mismatch")
            raw = json.loads(archive.read(result_names[0])).get("strategy", {})
        if list(raw) != CANDIDATES:
            raise ValueError("candidate inventory/order mismatch")
        results = {}
        for name in CANDIDATES:
            row = raw[name]
            trades = row.get("trades") or []
            if len(trades) != int(row["total_trades"]):
                raise ValueError(f"{name}: trade-count mismatch")
            profit_abs = sum(float(trade["profit_abs"]) for trade in trades)
            wins = sum(max(float(trade["profit_abs"]), 0.0) for trade in trades)
            losses = -sum(min(float(trade["profit_abs"]), 0.0) for trade in trades)
            independent_pf = wins / losses if losses else None
            if not math.isclose(profit_abs, float(row["profit_total_abs"]), rel_tol=1e-9, abs_tol=1e-8):
                raise ValueError(f"{name}: profit mismatch")
            if independent_pf is None or not math.isclose(independent_pf, float(row["profit_factor"]), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"{name}: PF mismatch")
            if any(float(trade["fee_open"]) != 0.00075 or float(trade["fee_close"]) != 0.00075 for trade in trades):
                raise ValueError(f"{name}: fee mismatch")
            ret = float(row["profit_total"]) * 100.0
            dd = float(row["max_drawdown_account"]) * 100.0
            rate = len(trades) / 1095.0
            gates = {"trades_1095_to_2190": 1095 <= len(trades) <= 2190,
                     "frequency_1_to_2_per_day": 1 <= rate <= 2, "return_positive": ret > 0,
                     "profit_factor_at_least_1_50": float(row["profit_factor"]) >= 1.50,
                     "wallet_drawdown_at_most_12_pct": dd <= 12,
                     "return_over_drawdown_at_least_2": dd > 0 and ret / dd >= 2}
            results[name] = {"status": "PASS_CORE" if all(gates.values()) else "FAIL",
                             "metrics": {"trades": len(trades), "trades_per_day": rate, "return_pct": ret,
                                         "profit_abs_usdt": profit_abs, "profit_factor": float(row["profit_factor"]),
                                         "wallet_max_drawdown_pct": dd, "long_trades": int(row["trade_count_long"]),
                                         "short_trades": int(row["trade_count_short"]),
                                         "long_return_pct": float(row["profit_total_long"]) * 100,
                                         "short_return_pct": float(row["profit_total_short"]) * 100},
                             "core_gates": gates, "failed_core_gates": [key for key, value in gates.items() if not value]}
        passers = [name for name, row in results.items() if row["status"] == "PASS_CORE"]
        payload = {"schema_version": "1.0", "cycle": "profit_max_multisetup_one_hour_cycle1",
                   "status": "FAIL" if not passers else "CORE_PASS_REQUIRES_REMAINING_GATES",
                   "decision": "KEEP_OFFLINE_RESEARCH" if not passers else "EVALUATE_REMAINING_TRAIN_GATES",
                   "validation_revealed": False, "live_trading_authorized": False, "profit_guaranteed": False,
                   "fee_per_side": 0.00075, "minimum_roundtrip_fee": 0.0015, "results": results,
                   "freeze_manifest_sha256": digest(MANIFEST), "frozen_inputs_reverified": checked,
                   "train_archive": {"path": ARCHIVE.relative_to(ROOT).as_posix(), "sha256": digest(ARCHIVE), "zip_integrity": "PASS"},
                   "evaluator_sha256": digest(Path(__file__).resolve())}
        with DECISION.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "sha256": digest(DECISION)}))
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
