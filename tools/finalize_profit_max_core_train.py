#!/usr/bin/env python3
"""Generic fail-closed terminalizer when every frozen candidate fails core TRAIN gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--minimum-profit-factor", required=True, type=float)
    parser.add_argument("--maximum-drawdown-pct", required=True, type=float)
    parser.add_argument("--minimum-return-drawdown", required=True, type=float)
    args = parser.parse_args()
    report = (ROOT / args.report_dir).resolve()
    manifest_path, archive_path, decision_path = report / "research_freeze_manifest.json", report / "train.zip", report / "train_decision.json"
    if decision_path.exists():
        print(f"FINALIZE_BLOCKED: decision exists: {decision_path}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("pnl_parsed") is not False:
            raise ValueError("invalid pre-PnL manifest")
        candidates = manifest.get("candidates") or []
        if not candidates or len(set(candidates)) != len(candidates):
            raise ValueError("invalid frozen candidates")
        checked = 0
        for item in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / item["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                raise ValueError(f"frozen input drift: {item['path']}")
            checked += 1
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity failed")
            result_names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
            if len(result_names) != 1:
                raise ValueError("result inventory mismatch")
            raw = json.loads(archive.read(result_names[0])).get("strategy", {})
        if list(raw) != candidates:
            raise ValueError("candidate order/inventory mismatch")
        frequency = manifest["frequency_gate_trades_per_day"]
        results = {}
        for name in candidates:
            row = raw[name]
            trades = row.get("trades") or []
            gains = sum(max(float(trade["profit_abs"]), 0) for trade in trades)
            losses = -sum(min(float(trade["profit_abs"]), 0) for trade in trades)
            independent_pf = gains / losses if losses else None
            if len(trades) != int(row["total_trades"]) or independent_pf is None or not math.isclose(independent_pf, float(row["profit_factor"]), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"{name}: trade/PF reconciliation failed")
            if any(float(trade["fee_open"]) != manifest["baseline_fee_per_side"] or float(trade["fee_close"]) != manifest["baseline_fee_per_side"] for trade in trades):
                raise ValueError(f"{name}: fee mismatch")
            days = int(row["backtest_days"])
            rate = len(trades) / days
            ret, dd = float(row["profit_total"]) * 100, float(row["max_drawdown_account"]) * 100
            gates = {
                "frequency_in_locked_range": frequency["minimum"] <= rate <= frequency["maximum"],
                "return_positive": ret > 0,
                "profit_factor_at_least_locked_minimum": float(row["profit_factor"]) >= args.minimum_profit_factor,
                "wallet_drawdown_at_most_locked_maximum": dd <= args.maximum_drawdown_pct,
                "return_over_drawdown_at_least_locked_minimum": dd > 0 and ret / dd >= args.minimum_return_drawdown,
            }
            results[name] = {"status": "PASS_CORE" if all(gates.values()) else "FAIL",
                             "metrics": {"trades": len(trades), "days": days, "trades_per_day": rate,
                                         "return_pct": ret, "profit_factor": float(row["profit_factor"]),
                                         "wallet_max_drawdown_pct": dd,
                                         "long_trades": int(row["trade_count_long"]), "short_trades": int(row["trade_count_short"])},
                             "core_gates": gates, "failed_core_gates": [key for key, value in gates.items() if not value]}
        core_passers = [name for name, row in results.items() if row["status"] == "PASS_CORE"]
        if core_passers:
            raise ValueError(f"core passers require cycle-specific remaining gates: {core_passers}")
        payload = {"schema_version": "1.0", "cycle": manifest["cycle"], "status": "FAIL",
                   "decision": "KEEP_OFFLINE_RESEARCH", "validation_revealed": False,
                   "live_trading_authorized": False, "profit_guaranteed": False,
                   "fee_per_side": manifest["baseline_fee_per_side"],
                   "locked_core_thresholds": {"minimum_profit_factor": args.minimum_profit_factor,
                                              "maximum_drawdown_pct": args.maximum_drawdown_pct,
                                              "minimum_return_drawdown": args.minimum_return_drawdown},
                   "results": results, "freeze_manifest_sha256": digest(manifest_path),
                   "frozen_inputs_reverified": checked,
                   "train_archive": {"path": archive_path.relative_to(ROOT).as_posix(), "sha256": digest(archive_path), "zip_integrity": "PASS"},
                   "evaluator": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": digest(Path(__file__).resolve())}}
        with decision_path.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": "FAIL", "decision": "KEEP_OFFLINE_RESEARCH", "sha256": digest(decision_path)}))
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
