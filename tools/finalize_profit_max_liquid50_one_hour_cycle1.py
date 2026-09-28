#!/usr/bin/env python3
"""Reconcile all frozen 1h TRAIN candidates and enforce the locked gates."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_liquid50_one_hour_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"
ARCHIVE = REPORT / "train.zip"
DECISION = REPORT / "train_decision.json"
CANDIDATES = ["ProfitMaxLiquid50OneHour30", "ProfitMaxLiquid50OneHour60", "ProfitMaxLiquid50OneHour120"]
SENSITIVE = {"api_key", "apikey", "jwt_secret_key", "key", "password", "secret", "secret_key", "token", "ws_token"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def assert_redacted(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in SENSITIVE and item not in (None, "", "REDACTED"):
                raise ValueError(f"unredacted sensitive value at {path}.{key}")
            assert_redacted(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, f"{path}[{index}]")


def pf(trades: list[dict]) -> float | None:
    wins = sum(max(float(row["profit_abs"]), 0.0) for row in trades)
    losses = -sum(min(float(row["profit_abs"]), 0.0) for row in trades)
    return wins / losses if losses > 0 else None


def group(trades: list[dict]) -> dict:
    return {"trades": len(trades), "profit_abs_usdt": sum(float(row["profit_abs"]) for row in trades), "profit_factor": pf(trades)}


def evaluate(name: str, raw: dict) -> dict:
    if raw.get("timerange") != "20210101-20240101" or raw.get("backtest_days") != 1095:
        raise ValueError(f"{name}: timerange mismatch")
    trades = raw.get("trades") or []
    if len(trades) != int(raw["total_trades"]):
        raise ValueError(f"{name}: trade-count mismatch")
    profit_abs = sum(float(row["profit_abs"]) for row in trades)
    independent_pf = pf(trades)
    if not math.isclose(profit_abs, float(raw["profit_total_abs"]), rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError(f"{name}: profit mismatch")
    if independent_pf is None or not math.isclose(independent_pf, float(raw["profit_factor"]), rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"{name}: PF mismatch")
    if any(float(row["fee_open"]) != 0.00075 or float(row["fee_close"]) != 0.00075 for row in trades):
        raise ValueError(f"{name}: fee mismatch")
    by_year: dict[int, list[dict]] = defaultdict(list)
    by_pair: dict[str, list[dict]] = defaultdict(list)
    by_side: dict[str, list[dict]] = defaultdict(list)
    for row in trades:
        by_year[int(str(row["close_date"])[:4])].append(row)
        by_pair[str(row["pair"])].append(row)
        by_side["short" if row["is_short"] else "long"].append(row)
    years = {str(year): group(by_year[year]) for year in (2021, 2022, 2023)}
    pairs = {pair: group(rows) for pair, rows in sorted(by_pair.items())}
    sides = {side: group(by_side[side]) for side in ("long", "short")}
    positive_pairs = sum(row["profit_abs_usdt"] > 0 for row in pairs.values())
    positive_sum = sum(max(row["profit_abs_usdt"], 0.0) for row in pairs.values())
    largest_share = max(max(row["profit_abs_usdt"], 0.0) for row in pairs.values()) / positive_sum if positive_sum > 0 else None
    worst_pair_return = min(
        float(row["profit_total_pct"]) for row in raw["results_per_pair"]
        if row["key"] != "TOTAL" and int(row["trades"]) > 0
    )
    return_pct = float(raw["profit_total"]) * 100.0
    drawdown_pct = float(raw["max_drawdown_account"]) * 100.0
    return_dd = return_pct / drawdown_pct if drawdown_pct > 0 else None
    rate = len(trades) / 1095.0
    gates = {
        "trades_1095_to_2190": 1095 <= len(trades) <= 2190,
        "frequency_1_to_2_per_day": 1.0 <= rate <= 2.0,
        "return_positive": return_pct > 0,
        "profit_factor_at_least_1_50": float(raw["profit_factor"]) >= 1.50,
        "wallet_drawdown_at_most_12_pct": drawdown_pct <= 12.0,
        "return_over_drawdown_at_least_2": return_dd is not None and return_dd >= 2.0,
        "each_train_year_positive": all(years[str(year)]["profit_abs_usdt"] > 0 for year in (2021, 2022, 2023)),
        "each_train_year_pf_at_least_1_10": all((years[str(year)]["profit_factor"] or 0) >= 1.10 for year in (2021, 2022, 2023)),
        "at_least_35_pairs_traded": len(pairs) >= 35,
        "at_least_25_positive_pairs": positive_pairs >= 25,
        "worst_traded_pair_return_above_minus_3_pct": worst_pair_return > -3.0,
        "largest_positive_pair_share_at_most_20_pct": largest_share is not None and largest_share <= 0.20,
        "long_at_least_300_trades": sides["long"]["trades"] >= 300,
        "short_at_least_300_trades": sides["short"]["trades"] >= 300,
        "long_net_positive_and_pf_at_least_1_15": sides["long"]["profit_abs_usdt"] > 0 and (sides["long"]["profit_factor"] or 0) >= 1.15,
        "short_net_positive_and_pf_at_least_1_15": sides["short"]["profit_abs_usdt"] > 0 and (sides["short"]["profit_factor"] or 0) >= 1.15,
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "metrics": {"trades": len(trades), "days": 1095, "trades_per_day": rate,
                    "return_pct": return_pct, "profit_abs_usdt": profit_abs,
                    "profit_factor": float(raw["profit_factor"]), "wallet_max_drawdown_pct": drawdown_pct,
                    "return_over_drawdown": return_dd, "pairs_traded": len(pairs),
                    "positive_pairs": positive_pairs, "worst_traded_pair_return_pct": worst_pair_return,
                    "largest_positive_pair_contribution_pct": largest_share * 100.0 if largest_share is not None else None},
        "years": years, "sides": sides, "pairs": pairs, "gates": gates,
        "failed_gates": [key for key, passed in gates.items() if not passed],
    }


def main() -> int:
    if DECISION.exists():
        print(f"FINALIZE_BLOCKED: decision already exists: {DECISION}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("candidates") != CANDIDATES:
            raise ValueError("manifest contract mismatch")
        checked = 0
        for row in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / row["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != row["sha256"]:
                raise ValueError(f"frozen input mismatch: {row['path']}")
            checked += 1
        with zipfile.ZipFile(ARCHIVE) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity failed")
            names = archive.namelist()
            result_names = [x for x in names if x.endswith(".json") and not x.endswith("_config.json")]
            config_names = [x for x in names if x.endswith("_config.json")]
            if len(result_names) != 1 or len(config_names) != 1:
                raise ValueError("unexpected ZIP JSON inventory")
            embedded = json.loads(archive.read(config_names[0]))
            assert_redacted(embedded)
            if embedded.get("fee") != 0.00075 or embedded.get("timeframe") != "1h" or embedded.get("max_open_trades") != 5:
                raise ValueError("embedded config mismatch")
            source = (ROOT / "user_data/strategies/ProfitMaxLiquid50OneHour.py").read_bytes()
            for candidate in CANDIDATES:
                members = [x for x in names if x.endswith(f"_{candidate}.py")]
                if len(members) != 1 or sha_bytes(archive.read(members[0])) != sha_bytes(source):
                    raise ValueError(f"embedded source mismatch: {candidate}")
            raw = json.loads(archive.read(result_names[0]))
        if list(raw.get("strategy", {})) != CANDIDATES:
            raise ValueError("candidate result order/inventory mismatch")
        results = {name: evaluate(name, raw["strategy"][name]) for name in CANDIDATES}
        passers = [name for name in CANDIDATES if results[name]["status"] == "PASS"]
        passers.sort(key=lambda name: (-(results[name]["metrics"]["return_over_drawdown"] or -math.inf),
                                       -results[name]["metrics"]["profit_factor"],
                                       results[name]["metrics"]["wallet_max_drawdown_pct"], name))
        payload = {
            "schema_version": "1.0", "cycle": "profit_max_liquid50_one_hour_cycle1",
            "status": "PASS" if passers else "FAIL",
            "decision": "UNLOCK_TECHNICAL_GATES" if passers else "KEEP_OFFLINE_RESEARCH",
            "winner": passers[0] if passers else None, "passers": passers,
            "validation_revealed": False, "live_trading_authorized": False, "profit_guaranteed": False,
            "fee_per_side": 0.00075, "minimum_roundtrip_fee": 0.0015,
            "results": results, "freeze_manifest_sha256": digest(MANIFEST),
            "train_archive": {"path": ARCHIVE.relative_to(ROOT).as_posix(), "sha256": digest(ARCHIVE),
                              "zip_integrity": "PASS", "config_redaction": "PASS",
                              "source_reconciliation": "PASS", "trade_reconciliation": "PASS"},
            "frozen_inputs_reverified": checked,
            "evaluator": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": digest(Path(__file__).resolve())},
        }
        with DECISION.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "winner": payload["winner"], "sha256": digest(DECISION)}))
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
