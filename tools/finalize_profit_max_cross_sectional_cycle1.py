#!/usr/bin/env python3
"""Reconcile cross-sectional TRAIN and write its terminal decision."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_cross_sectional_cycle1"
MANIFEST, ARCHIVE, DECISION = REPORT / "research_freeze_manifest.json", REPORT / "train.zip", REPORT / "train_decision.json"
CANDIDATES = ["ProfitMaxCrossSectional7dNeutral", "ProfitMaxCrossSectional30dNeutral", "ProfitMaxCrossSectional7dRegime"]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def pf(rows: list[dict]) -> float | None:
    wins = sum(max(float(row["profit_abs"]), 0) for row in rows)
    losses = -sum(min(float(row["profit_abs"]), 0) for row in rows)
    return wins / losses if losses else None


def main() -> int:
    if DECISION.exists():
        print(f"FINALIZE_BLOCKED: decision exists: {DECISION}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("candidates") != CANDIDATES:
            raise ValueError("manifest mismatch")
        checked = 0
        for item in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / item["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                raise ValueError(f"frozen input drift: {item['path']}")
            checked += 1
        with zipfile.ZipFile(ARCHIVE) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity failed")
            result_names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
            if len(result_names) != 1:
                raise ValueError("result inventory mismatch")
            raw = json.loads(archive.read(result_names[0])).get("strategy", {})
        if list(raw) != CANDIDATES:
            raise ValueError("candidate order/inventory mismatch")
        results = {}
        for name in CANDIDATES:
            row = raw[name]
            trades = row.get("trades") or []
            independent = pf(trades)
            if len(trades) != int(row["total_trades"]) or independent is None or not math.isclose(independent, float(row["profit_factor"]), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"{name}: trade/PF reconciliation failed")
            if any(float(trade["fee_open"]) != 0.00075 or float(trade["fee_close"]) != 0.00075 for trade in trades):
                raise ValueError(f"{name}: fee mismatch")
            yearly: dict[str, list[dict]] = defaultdict(list)
            sides: dict[str, list[dict]] = defaultdict(list)
            for trade in trades:
                yearly[str(trade["close_date"])[:4]].append(trade)
                sides["short" if trade["is_short"] else "long"].append(trade)
            ret, dd = float(row["profit_total"]) * 100, float(row["max_drawdown_account"]) * 100
            rate = len(trades) / 1095
            gates = {"frequency_1_to_2": 1 <= rate <= 2, "return_positive": ret > 0,
                     "pf_gte_1_50": float(row["profit_factor"]) >= 1.5, "dd_lte_12": dd <= 12,
                     "return_dd_gte_2": dd > 0 and ret / dd >= 2,
                     "each_year_positive": all(sum(float(t["profit_abs"]) for t in yearly[str(y)]) > 0 for y in (2021, 2022, 2023)),
                     "each_year_pf_gte_1_10": all((pf(yearly[str(y)]) or 0) >= 1.1 for y in (2021, 2022, 2023))}
            results[name] = {"status": "PASS_CORE_STABILITY" if all(gates.values()) else "FAIL",
                             "metrics": {"trades": len(trades), "trades_per_day": rate, "return_pct": ret,
                                         "profit_factor": float(row["profit_factor"]), "wallet_max_drawdown_pct": dd,
                                         "long_trades": len(sides["long"]), "long_profit_abs_usdt": sum(float(t["profit_abs"]) for t in sides["long"]),
                                         "long_profit_factor": pf(sides["long"]), "short_trades": len(sides["short"]),
                                         "short_profit_abs_usdt": sum(float(t["profit_abs"]) for t in sides["short"]),
                                         "short_profit_factor": pf(sides["short"])},
                             "gates": gates, "failed_gates": [key for key, value in gates.items() if not value]}
        passers = [name for name, row in results.items() if row["status"] != "FAIL"]
        payload = {"schema_version": "1.0", "cycle": "profit_max_cross_sectional_cycle1",
                   "status": "FAIL" if not passers else "PARTIAL_PASS", "decision": "KEEP_OFFLINE_RESEARCH",
                   "validation_revealed": False, "live_trading_authorized": False, "profit_guaranteed": False,
                   "fee_per_side": 0.00075, "results": results, "passers": passers,
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
