#!/usr/bin/env python3
"""Freeze, backtest, sanitize, and evaluate the isolated ProfitMax20 V1 portfolio."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
REPORT_DIR = Path("user_data/reports/profit_max20_v1")
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DECISION = REPORT_DIR / "decision.json"
PERIODS = {
    "rolling_five_year": ("20210801-20260801", 1826),
    "calendar_five_year": ("20210101-20260101", 1826),
}
BASE_FEE = 0.00075
SEVERE_EXTRA_COST_PER_SIDE = 0.001
WALLET = 1000.0
YEAR_DAYS = 365.2425
SWING_PAIRS = ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE")

SOURCE_FILES = (
    Path("docs/profit_max20_v1_locked_plan.md"),
    Path("tools/run_profit_max20_v1.py"),
    Path("tools/test_profit_max_cagr20_v1.py"),
    Path("user_data/config-profit-max-cagr20-v1.json"),
    Path("user_data/config-profit-max-liquid50-cycle1.json"),
    Path("user_data/config-profit-max20-daily-v1-overlay.json"),
    Path("user_data/risk_policy_profit_max_cagr20_v1.json"),
    Path("user_data/strategies/ProfitMaxCagr20V1.py"),
    Path("user_data/strategies/ProfitMaxCagr15V5.py"),
    Path("user_data/strategies/ProfitMaxCagr15V4.py"),
    Path("user_data/strategies/ProfitMaxCagr15V3.py"),
    Path("user_data/strategies/ProfitMaxCagr15V2.py"),
    Path("user_data/strategies/ProfitMaxSwingV5.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectionalV3.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectionalV2.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectional.py"),
    Path("user_data/strategies/ProfitMaxCrossSectional.py"),
    Path("user_data/strategies/DualTrendFuturesV1.py"),
    Path("user_data/strategies/DualTrendFuturesV2.py"),
    Path("user_data/strategies/DualTrendFuturesRisk.py"),
    Path("user_data/strategies/ProfessionalRisk.py"),
)


class CycleError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CycleError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any], *, exclusive: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def data_files(root: Path) -> list[Path]:
    result: list[Path] = []
    swing = Path("user_data/data/binance/futures")
    for pair in SWING_PAIRS:
        for suffix in ("4h-futures", "1d-futures", "1h-funding_rate", "1h-mark"):
            result.append(swing / f"{pair}_USDT_USDT-{suffix}.feather")
    daily = Path("user_data/data/binance/profit_max_liquid50_cycle1_source/futures")
    daily_config = read_json(root / "user_data/config-profit-max-liquid50-cycle1.json")
    for pair in daily_config["exchange"]["pair_whitelist"]:
        symbol = pair.split("/")[0]
        for suffix in ("4h-futures", "1d-futures", "1h-funding_rate", "1h-mark"):
            result.append(daily / f"{symbol}_USDT_USDT-{suffix}.feather")
    return result


def validate_contracts(root: Path) -> None:
    swing = read_json(root / "user_data/config-profit-max-cagr20-v1.json")
    daily = read_json(root / "user_data/config-profit-max-liquid50-cycle1.json")
    overlay = read_json(root / "user_data/config-profit-max20-daily-v1-overlay.json")
    policy = read_json(root / "user_data/risk_policy_profit_max_cagr20_v1.json")
    if swing.get("dry_run") is not True or daily.get("dry_run") is not True:
        raise CycleError("both research configs must be dry-run")
    for config in (swing, daily):
        exchange = config.get("exchange", {})
        if exchange.get("key") or exchange.get("secret"):
            raise CycleError("credentials found in research config")
    research = swing.get("profit_max_research", {})
    overlay_research = overlay.get("profit_max_research", {})
    if research.get("status") != "LOCKED_BEFORE_PNL" or overlay_research.get("status") != "LOCKED_BEFORE_PNL":
        raise CycleError("candidate is not locked before PnL")
    if research.get("leverage") != 3.5 or swing.get("stake_amount") != 300 or swing.get("max_open_trades") != 1:
        raise CycleError("swing sizing contract mismatch")
    if overlay_research.get("leverage") != 1 or overlay.get("stake_amount") != 10 or overlay.get("max_open_trades") != 2:
        raise CycleError("daily sizing contract mismatch")
    if swing.get("fee") != BASE_FEE or overlay.get("fee") != BASE_FEE:
        raise CycleError("fee contract mismatch")
    if policy.get("live_launch", {}).get("authorized") is not False:
        raise CycleError("live launch must remain unauthorized")


def freeze(root: Path) -> dict[str, Any]:
    if (root / REPORT_DIR).exists():
        raise CycleError("cycle report directory already exists")
    validate_contracts(root)
    paths = [*SOURCE_FILES, *data_files(root)]
    missing = [path.as_posix() for path in paths if not (root / path).is_file()]
    if missing:
        raise CycleError(f"missing frozen inputs: {missing}")
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max20_v1",
        "status": "RESEARCH_FROZEN",
        "locked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pnl_parsed": False,
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
        "live_trading_authorized": False,
        "files": {
            path.as_posix(): {
                "sha256": sha256(root / path),
                "size_bytes": (root / path).stat().st_size,
            }
            for path in paths
        },
    }
    write_json(root / MANIFEST, payload, exclusive=True)
    return payload


def verify_freeze(root: Path) -> dict[str, Any]:
    manifest = read_json(root / MANIFEST)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("pnl_parsed") is not False:
        raise CycleError("invalid freeze manifest")
    for relative, evidence in manifest.get("files", {}).items():
        path = root / relative
        if not path.is_file() or sha256(path) != evidence.get("sha256"):
            raise CycleError(f"frozen input changed: {relative}")
    return manifest


def run_backtest(
    root: Path,
    *,
    label: str,
    timerange: str,
    strategy: str,
    configs: Iterable[Path],
    datadir: Path,
    timeout: int,
) -> dict[str, Any]:
    final = root / REPORT_DIR / f"{label}.zip"
    if final.exists():
        raise CycleError(f"refusing to overwrite {final}")
    with tempfile.TemporaryDirectory(prefix=f"{label}-", dir=root / REPORT_DIR) as temporary:
        staging = Path(temporary)
        command = [
            "docker", "run", "--rm",
            "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
            "-v", f"{staging.resolve()}:/freqtrade/user_data/backtest_results:rw",
            "--entrypoint", "freqtrade", IMAGE, "backtesting",
        ]
        for config in configs:
            command.extend(("--config", f"/freqtrade/{config.as_posix()}"))
        command.extend((
            "--userdir", "/freqtrade/user_data",
            "--strategy", strategy,
            "--datadir", f"/freqtrade/{datadir.as_posix()}",
            "--timerange", timerange,
            "--export", "trades", "--cache", "none", "--no-color",
        ))
        result = subprocess.run(
            command, cwd=root, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
        if result.returncode:
            tail = ((result.stdout or "") + "\n" + (result.stderr or ""))[-3000:]
            raise CycleError(f"{label} backtest exit {result.returncode}: {tail}")
        receipt = read_json(staging / ".last_result.json")
        filename = receipt.get("latest_backtest")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise CycleError(f"invalid backtest receipt: {label}")
        archive = staging / filename
        sanitize = subprocess.run(
            [sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(archive)],
            cwd=root, capture_output=True, text=True, timeout=120, check=False,
        )
        if sanitize.returncode:
            raise CycleError(f"archive sanitizer failed: {label}: {sanitize.stderr[-1000:]}")
        os.replace(archive, final)
    return {
        "path": final.relative_to(root).as_posix(),
        "sha256": sha256(final),
        "size_bytes": final.stat().st_size,
        "command_sha256": hashlib.sha256("\0".join(command).encode()).hexdigest(),
        "stdout_stderr_sha256": hashlib.sha256(
            ((result.stdout or "") + "\n" + (result.stderr or "")).encode()
        ).hexdigest(),
    }


def load_archive(path: Path, strategy: str, timerange: str, days: int, leverage: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise CycleError(f"ZIP integrity failure: {path}")
        result_names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        config_names = [name for name in archive.namelist() if name.endswith("_config.json")]
        if len(result_names) != 1 or len(config_names) != 1:
            raise CycleError(f"ambiguous archive members: {path}")
        payload = json.loads(archive.read(result_names[0]))
        config = json.loads(archive.read(config_names[0]))
    result = payload.get("strategy", {}).get(strategy)
    if not isinstance(result, dict):
        raise CycleError(f"strategy missing from archive: {strategy}")
    trades = result.get("trades")
    if not isinstance(trades, list):
        raise CycleError(f"trades missing: {strategy}")
    if result.get("timerange") != timerange or int(result.get("backtest_days")) != days:
        raise CycleError(f"timerange mismatch: {strategy}")
    if config.get("dry_run_wallet") != WALLET or config.get("fee") != BASE_FEE:
        raise CycleError(f"wallet/fee mismatch: {strategy}")
    if config.get("exchange", {}).get("key") not in (None, "", "REDACTED"):
        raise CycleError("API key remains in sanitized archive")
    if config.get("exchange", {}).get("secret") not in (None, "", "REDACTED"):
        raise CycleError("API secret remains in sanitized archive")
    if any(float(trade.get("fee_open")) != BASE_FEE or float(trade.get("fee_close")) != BASE_FEE for trade in trades):
        raise CycleError(f"trade fee mismatch: {strategy}")
    if any(float(trade.get("leverage")) != leverage for trade in trades):
        raise CycleError(f"leverage mismatch: {strategy}")
    reported = float(result.get("profit_total_abs"))
    recomputed = sum(float(trade["profit_abs"]) for trade in trades)
    if abs(reported - recomputed) > 1e-6:
        raise CycleError(f"profit reconciliation mismatch: {strategy}")
    return trades, result


def cagr(profit: float, days: int) -> float:
    multiple = 1.0 + profit / WALLET
    return -100.0 if multiple <= 0 else (multiple ** (YEAR_DAYS / days) - 1.0) * 100.0


def profit_factor(profits: Iterable[float]) -> float:
    values = list(profits)
    wins = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses <= 0:
        raise CycleError("finite loss sample required for profit factor")
    return wins / losses


def realized_drawdown_pct(trades: list[dict[str, Any]], profits: list[float]) -> float:
    by_close: dict[int, float] = defaultdict(float)
    for trade, profit in zip(trades, profits, strict=True):
        by_close[int(trade["close_timestamp"])] += profit
    equity = peak = WALLET
    maximum = 0.0
    for timestamp in sorted(by_close):
        equity += by_close[timestamp]
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / WALLET * 100.0)
    return maximum


def maximum_exposure(trades: list[dict[str, Any]]) -> dict[str, float | int]:
    events: list[tuple[int, int, float, float, int]] = []
    for trade in trades:
        margin = float(trade["stake_amount"])
        notional = margin * float(trade["leverage"])
        events.append((int(trade["open_timestamp"]), 1, margin, notional, 1))
        events.append((int(trade["close_timestamp"]), 0, -margin, -notional, -1))
    margin = notional = 0.0
    positions = 0
    maximum_margin = maximum_notional = 0.0
    maximum_positions = 0
    for _, _, margin_change, notional_change, position_change in sorted(events):
        margin += margin_change
        notional += notional_change
        positions += position_change
        maximum_margin = max(maximum_margin, margin)
        maximum_notional = max(maximum_notional, notional)
        maximum_positions = max(maximum_positions, positions)
    return {
        "maximum_concurrent_positions": maximum_positions,
        "maximum_concurrent_margin_usdt": maximum_margin,
        "maximum_concurrent_notional_usdt": maximum_notional,
    }


def metrics(trades: list[dict[str, Any]], days: int, extra_per_side: float) -> dict[str, Any]:
    profits: list[float] = []
    years: dict[str, float] = defaultdict(float)
    for trade in trades:
        profit = float(trade["profit_abs"])
        if extra_per_side:
            amount = float(trade["amount"])
            profit -= extra_per_side * amount * (float(trade["open_rate"]) + float(trade["close_rate"]))
        profits.append(profit)
        years[str(trade["close_date"])[:4]] += profit
    total = sum(profits)
    return {
        "extra_cost_per_side": extra_per_side,
        "trades": len(trades),
        "days": days,
        "trades_per_day": len(trades) / days,
        "profit_usdt": total,
        "return_pct": total / WALLET * 100.0,
        "cagr_pct": cagr(total, days),
        "profit_factor": profit_factor(profits),
        "realized_drawdown_pct": realized_drawdown_pct(trades, profits),
        "year_profit_usdt": dict(sorted(years.items())),
    }


def evaluate_period(root: Path, label: str, timerange: str, days: int) -> dict[str, Any]:
    swing, _ = load_archive(root / REPORT_DIR / f"{label}_swing.zip", "ProfitMaxCagr20V1", timerange, days, 3.5)
    daily, _ = load_archive(root / REPORT_DIR / f"{label}_daily.zip", "ProfitMaxDailyCrossBreadthBonus", timerange, days, 1.0)
    combined = [dict(trade, portfolio_component="swing") for trade in swing]
    combined.extend(dict(trade, portfolio_component="daily") for trade in daily)
    baseline = metrics(combined, days, 0.0)
    severe = metrics(combined, days, SEVERE_EXTRA_COST_PER_SIDE)
    exposure = maximum_exposure(combined)
    years = baseline["year_profit_usdt"]
    severe_years = severe["year_profit_usdt"]
    gates = {
        "trades_per_day_gte_1": baseline["trades_per_day"] >= 1.0,
        "baseline_cagr_gte_20": baseline["cagr_pct"] >= 20.0,
        "severe_cagr_gte_20": severe["cagr_pct"] >= 20.0,
        "baseline_profit_factor_gte_1_50": baseline["profit_factor"] >= 1.50,
        "severe_profit_factor_gte_1_50": severe["profit_factor"] >= 1.50,
        "baseline_drawdown_lte_20": baseline["realized_drawdown_pct"] <= 20.0,
        "severe_drawdown_lte_20": severe["realized_drawdown_pct"] <= 20.0,
        "maximum_margin_lte_25pct": exposure["maximum_concurrent_margin_usdt"] <= WALLET * 0.25 + 1e-9,
        "maximum_notional_lte_75pct": exposure["maximum_concurrent_notional_usdt"] <= WALLET * 0.75 + 1e-9,
        "all_represented_years_positive": all(value > 0 for value in years.values()),
        "all_represented_years_positive_severe": all(value > 0 for value in severe_years.values()),
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "timerange": timerange,
        "baseline": baseline,
        "severe_cost": severe,
        "exposure": exposure,
        "components": {
            "swing": metrics(swing, days, 0.0),
            "daily": metrics(daily, days, 0.0),
        },
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    try:
        manifest = freeze(ROOT)
        verify_freeze(ROOT)
        artifacts: dict[str, Any] = {}
        for label, (timerange, _) in PERIODS.items():
            artifacts[f"{label}_swing"] = run_backtest(
                ROOT, label=f"{label}_swing", timerange=timerange,
                strategy="ProfitMaxCagr20V1",
                configs=(Path("user_data/config-profit-max-cagr20-v1.json"),),
                datadir=Path("user_data/data/binance"), timeout=args.timeout,
            )
            artifacts[f"{label}_daily"] = run_backtest(
                ROOT, label=f"{label}_daily", timerange=timerange,
                strategy="ProfitMaxDailyCrossBreadthBonus",
                configs=(
                    Path("user_data/config-profit-max-liquid50-cycle1.json"),
                    Path("user_data/config-profit-max20-daily-v1-overlay.json"),
                ),
                datadir=Path("user_data/data/binance/profit_max_liquid50_cycle1_source"),
                timeout=args.timeout,
            )
        verify_freeze(ROOT)
        results = {
            label: evaluate_period(ROOT, label, timerange, days)
            for label, (timerange, days) in PERIODS.items()
        }
        primary_pass = results["rolling_five_year"]["status"] == "PASS"
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max20_v1",
            "status": "PASS" if primary_pass else "FAIL",
            "decision": "APPROVE_CREDENTIAL_FREE_ISOLATED_DRY_RUN_ONLY" if primary_pass else "KEEP_OFFLINE_RESEARCH",
            "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "primary_period": "rolling_five_year",
            "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
            "profit_guaranteed": False,
            "live_trading_authorized": False,
            "automatic_promotion_authorized": False,
            "freeze_manifest_sha256": sha256(ROOT / MANIFEST),
            "frozen_file_count": len(manifest["files"]),
            "results": results,
            "artifacts": artifacts,
        }
        write_json(ROOT / DECISION, payload, exclusive=True)
        print(json.dumps({
            "status": payload["status"],
            "decision": payload["decision"],
            "rolling": results["rolling_five_year"],
            "calendar": results["calendar_five_year"],
        }, indent=2, allow_nan=False))
        return 0 if primary_pass else 2
    except Exception as exc:
        print(f"PROFIT_MAX20_V1_BLOCKED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
