#!/usr/bin/env python3
"""Reconcile the frozen Liquid50 TRAIN artifact and enforce locked gates."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_liquid50_cycle1"
MANIFEST = REPORT / "research_freeze_manifest.json"
ARCHIVE = REPORT / "train.zip"
DECISION = REPORT / "train_decision.json"
SENSITIVE = {"api_key", "apikey", "jwt_secret_key", "key", "password", "secret", "secret_key", "token", "ws_token"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def close(left: float, right: float, tolerance: float = 1e-10) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def assert_redacted(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in SENSITIVE and item not in (None, "", "REDACTED"):
                raise ValueError(f"unredacted sensitive value at {path}.{key}")
            assert_redacted(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, f"{path}[{index}]")


def profit_factor(trades: list[dict]) -> float | None:
    gains = sum(max(float(trade["profit_abs"]), 0.0) for trade in trades)
    losses = -sum(min(float(trade["profit_abs"]), 0.0) for trade in trades)
    return gains / losses if losses > 0 else None


def grouped_metrics(trades: list[dict]) -> dict:
    absolute = sum(float(trade["profit_abs"]) for trade in trades)
    return {"trades": len(trades), "profit_abs_usdt": absolute, "profit_factor": profit_factor(trades)}


def main() -> int:
    if DECISION.exists():
        print(f"FINALIZE_BLOCKED: decision already exists: {DECISION}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("status") != "RESEARCH_FROZEN_BEFORE_PNL" or manifest.get("pnl_parsed") is not False:
            raise ValueError("invalid pre-PnL manifest")
        if manifest.get("candidate") != "ProfitMaxLiquid50V1" or manifest.get("baseline_fee_per_side") != 0.00075:
            raise ValueError("manifest candidate or fee mismatch")
        checked = 0
        for row in list(manifest["files"].values()) + manifest["data_files"]:
            path = ROOT / row["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != row["sha256"]:
                raise ValueError(f"frozen input mismatch: {row['path']}")
            checked += 1

        with zipfile.ZipFile(ARCHIVE) as archive:
            if archive.testzip() is not None:
                raise ValueError("TRAIN ZIP integrity failed")
            names = archive.namelist()
            results = [name for name in names if name.endswith(".json") and not name.endswith("_config.json")]
            configs = [name for name in names if name.endswith("_config.json")]
            sources = [name for name in names if name.endswith("_ProfitMaxLiquid50V1.py")]
            if len(results) != 1 or len(configs) != 1 or len(sources) != 1:
                raise ValueError("unexpected TRAIN ZIP member inventory")
            embedded_config = json.loads(archive.read(configs[0]))
            assert_redacted(embedded_config)
            expected_pairs = json.loads((REPORT / "universe_selection.json").read_text(encoding="utf-8"))
            expected_pairs = [row["freqtrade_pair"] for row in expected_pairs["selected"]]
            if (
                embedded_config.get("fee") != 0.00075
                or embedded_config.get("trading_mode") != "futures"
                or embedded_config.get("margin_mode") != "isolated"
                or embedded_config.get("max_open_trades") != 5
                or embedded_config.get("stake_amount") != 50
                or (embedded_config.get("exchange") or {}).get("pair_whitelist") != expected_pairs
            ):
                raise ValueError("embedded config execution contract mismatch")
            strategy_source = ROOT / "user_data/strategies/ProfitMaxLiquid50V1.py"
            if digest_bytes(archive.read(sources[0])) != digest(strategy_source):
                raise ValueError("embedded strategy source mismatch")
            raw_root = json.loads(archive.read(results[0]))

        if list(raw_root.get("strategy", {})) != ["ProfitMaxLiquid50V1"]:
            raise ValueError("unexpected result strategy")
        raw = raw_root["strategy"]["ProfitMaxLiquid50V1"]
        if (
            raw.get("timerange") != "20210101-20240101"
            or raw.get("backtest_start") != "2021-01-01 00:00:00"
            or raw.get("backtest_end") != "2024-01-01 00:00:00"
            or int(raw.get("backtest_days")) != 1095
        ):
            raise ValueError("TRAIN timerange mismatch")
        trades = raw.get("trades") or []
        if len(trades) != int(raw["total_trades"]):
            raise ValueError("trade-count reconciliation failed")
        total_abs = sum(float(trade["profit_abs"]) for trade in trades)
        independent_pf = profit_factor(trades)
        if not close(total_abs, float(raw["profit_total_abs"]), 1e-8):
            raise ValueError("absolute-profit reconciliation failed")
        if independent_pf is None or not close(independent_pf, float(raw["profit_factor"]), 1e-12):
            raise ValueError("profit-factor reconciliation failed")
        if any(float(trade["fee_open"]) != 0.00075 or float(trade["fee_close"]) != 0.00075 for trade in trades):
            raise ValueError("per-trade fee reconciliation failed")

        by_year: dict[int, list[dict]] = defaultdict(list)
        by_pair: dict[str, list[dict]] = defaultdict(list)
        by_side: dict[str, list[dict]] = defaultdict(list)
        for trade in trades:
            by_year[int(str(trade["close_date"])[:4])].append(trade)
            by_pair[str(trade["pair"])].append(trade)
            by_side["short" if trade["is_short"] else "long"].append(trade)
        years = {str(year): grouped_metrics(by_year[year]) for year in (2021, 2022, 2023)}
        pairs = {pair: grouped_metrics(rows) for pair, rows in sorted(by_pair.items())}
        sides = {side: grouped_metrics(by_side[side]) for side in ("long", "short")}
        positive_pairs = sum(row["profit_abs_usdt"] > 0 for row in pairs.values())
        positive_pair_profit = sum(max(row["profit_abs_usdt"], 0.0) for row in pairs.values())
        largest_positive_share = (
            max(max(row["profit_abs_usdt"], 0.0) for row in pairs.values()) / positive_pair_profit
            if positive_pair_profit > 0 else None
        )
        worst_pair_return = min(
            float(row["profit_total_pct"])
            for row in raw["results_per_pair"]
            if row["key"] != "TOTAL" and int(row["trades"]) > 0
        )
        return_pct = float(raw["profit_total"]) * 100.0
        drawdown_pct = float(raw["max_drawdown_account"]) * 100.0
        return_dd = return_pct / drawdown_pct if drawdown_pct > 0 else None
        trades_per_day = len(trades) / 1095.0
        gates = {
            "trades_1095_to_2190": 1095 <= len(trades) <= 2190,
            "frequency_1_to_2_per_day": 1.0 <= trades_per_day <= 2.0,
            "return_positive": return_pct > 0,
            "profit_factor_at_least_1_50": float(raw["profit_factor"]) >= 1.50,
            "wallet_drawdown_at_most_12_pct": drawdown_pct <= 12.0,
            "return_over_drawdown_at_least_2": return_dd is not None and return_dd >= 2.0,
            "each_train_year_positive": all(years[str(year)]["profit_abs_usdt"] > 0 for year in (2021, 2022, 2023)),
            "each_train_year_pf_at_least_1_10": all(
                years[str(year)]["profit_factor"] is not None and years[str(year)]["profit_factor"] >= 1.10
                for year in (2021, 2022, 2023)
            ),
            "at_least_35_pairs_traded": len(pairs) >= 35,
            "at_least_25_positive_pairs": positive_pairs >= 25,
            "worst_traded_pair_return_above_minus_3_pct": worst_pair_return > -3.0,
            "largest_positive_pair_share_at_most_20_pct": largest_positive_share is not None and largest_positive_share <= 0.20,
            "long_at_least_300_trades": sides["long"]["trades"] >= 300,
            "short_at_least_300_trades": sides["short"]["trades"] >= 300,
            "long_net_positive_and_pf_at_least_1_15": sides["long"]["profit_abs_usdt"] > 0 and (sides["long"]["profit_factor"] or 0) >= 1.15,
            "short_net_positive_and_pf_at_least_1_15": sides["short"]["profit_abs_usdt"] > 0 and (sides["short"]["profit_factor"] or 0) >= 1.15,
        }
        passed = all(gates.values())
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max_liquid50_cycle1",
            "status": "PASS" if passed else "FAIL",
            "decision": "UNLOCK_TECHNICAL_GATES" if passed else "KEEP_OFFLINE_RESEARCH",
            "validation_revealed": False,
            "live_trading_authorized": False,
            "profit_guaranteed": False,
            "fee_per_side": 0.00075,
            "minimum_roundtrip_fee": 0.0015,
            "metrics": {
                "trades": len(trades),
                "days": 1095,
                "trades_per_day": trades_per_day,
                "return_pct": return_pct,
                "profit_abs_usdt": total_abs,
                "profit_factor": float(raw["profit_factor"]),
                "wallet_max_drawdown_pct": drawdown_pct,
                "return_over_drawdown": return_dd,
                "wins": int(raw["wins"]),
                "draws": int(raw["draws"]),
                "losses": int(raw["losses"]),
                "pairs_traded": len(pairs),
                "positive_pairs": positive_pairs,
                "worst_traded_pair_return_pct": worst_pair_return,
                "largest_positive_pair_contribution_pct": largest_positive_share * 100.0 if largest_positive_share is not None else None,
            },
            "years": years,
            "sides": sides,
            "pairs": pairs,
            "gates": gates,
            "failed_gates": [name for name, value in gates.items() if not value],
            "freeze_manifest_sha256": digest(MANIFEST),
            "train_archive": {
                "path": ARCHIVE.relative_to(ROOT).as_posix(),
                "sha256": digest(ARCHIVE),
                "zip_integrity": "PASS",
                "config_redaction": "PASS",
                "source_reconciliation": "PASS",
                "trade_reconciliation": "PASS",
            },
            "frozen_inputs_reverified": checked,
            "evaluator": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": digest(Path(__file__).resolve())},
        }
        with DECISION.open("xb") as handle:
            handle.write((json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        print(json.dumps({"status": payload["status"], "decision": payload["decision"], "failed_gates": payload["failed_gates"], "sha256": digest(DECISION)}))
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"FINALIZE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
