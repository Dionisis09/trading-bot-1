#!/usr/bin/env python3
"""Freeze, backtest, sanitize, and evaluate the isolated ProfitMax20 V2 portfolio."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import run_profit_max20_v1 as common


ROOT = common.ROOT
REPORT_DIR = Path("user_data/reports/profit_max20_v2")
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
DECISION = REPORT_DIR / "decision.json"
PERIODS = common.PERIODS
SOURCE_FILES = (
    Path("docs/profit_max20_v2_locked_plan.md"),
    Path("tools/run_profit_max20_v1.py"),
    Path("tools/run_profit_max20_v2.py"),
    Path("tools/test_profit_max20_v2.py"),
    Path("user_data/config-profit-max-cagr20-v2.json"),
    Path("user_data/config-profit-max-liquid50-cycle1.json"),
    Path("user_data/config-profit-max20-daily-v2-overlay.json"),
    Path("user_data/risk_policy_profit_max_cagr20_v2.json"),
    Path("user_data/strategies/ProfitMaxCagr20V2.py"),
    Path("user_data/strategies/ProfitMaxCagr20V1.py"),
    Path("user_data/strategies/ProfitMaxCagr15V5.py"),
    Path("user_data/strategies/ProfitMaxCagr15V4.py"),
    Path("user_data/strategies/ProfitMaxCagr15V3.py"),
    Path("user_data/strategies/ProfitMaxCagr15V2.py"),
    Path("user_data/strategies/ProfitMaxSwingV5.py"),
    Path("user_data/strategies/ProfitMaxDailyTop2ActivityV1.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectionalAuditV2.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectionalAudit.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectionalV2.py"),
    Path("user_data/strategies/ProfitMaxDailyCrossSectional.py"),
    Path("user_data/strategies/ProfitMaxCrossSectional.py"),
    Path("user_data/strategies/DualTrendFuturesV1.py"),
    Path("user_data/strategies/DualTrendFuturesV2.py"),
    Path("user_data/strategies/DualTrendFuturesRisk.py"),
    Path("user_data/strategies/ProfessionalRisk.py"),
)


def validate_contracts() -> None:
    swing = common.read_json(ROOT / "user_data/config-profit-max-cagr20-v2.json")
    daily = common.read_json(ROOT / "user_data/config-profit-max-liquid50-cycle1.json")
    overlay = common.read_json(ROOT / "user_data/config-profit-max20-daily-v2-overlay.json")
    policy = common.read_json(ROOT / "user_data/risk_policy_profit_max_cagr20_v2.json")
    if swing.get("dry_run") is not True or daily.get("dry_run") is not True:
        raise common.CycleError("both configs must remain dry-run")
    for config in (swing, daily):
        if config.get("exchange", {}).get("key") or config.get("exchange", {}).get("secret"):
            raise common.CycleError("research config contains credentials")
    research = swing.get("profit_max_research", {})
    daily_research = overlay.get("profit_max_research", {})
    if research.get("status") != "LOCKED_BEFORE_PNL" or daily_research.get("status") != "LOCKED_BEFORE_PNL":
        raise common.CycleError("candidate is not locked before PnL")
    if research.get("leverage") != 3.76 or swing.get("max_open_trades") != 1 or swing.get("stake_amount") != 300:
        raise common.CycleError("swing sizing contract mismatch")
    if daily_research.get("rank_count") != 2 or overlay.get("max_open_trades") != 2 or overlay.get("stake_amount") != 6:
        raise common.CycleError("activity sizing contract mismatch")
    if swing.get("fee") != common.BASE_FEE or overlay.get("fee") != common.BASE_FEE:
        raise common.CycleError("fee contract mismatch")
    if policy.get("live_launch", {}).get("authorized") is not False:
        raise common.CycleError("live launch must remain unauthorized")


def freeze() -> dict[str, Any]:
    if (ROOT / REPORT_DIR).exists():
        raise common.CycleError("V2 report directory already exists")
    validate_contracts()
    paths = [*SOURCE_FILES, *common.data_files(ROOT)]
    missing = [path.as_posix() for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise common.CycleError(f"missing frozen inputs: {missing}")
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max20_v2",
        "status": "RESEARCH_FROZEN",
        "locked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pnl_parsed": False,
        "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
        "live_trading_authorized": False,
        "files": {
            path.as_posix(): {
                "sha256": common.sha256(ROOT / path),
                "size_bytes": (ROOT / path).stat().st_size,
            }
            for path in paths
        },
    }
    common.write_json(ROOT / MANIFEST, payload, exclusive=True)
    return payload


def verify_freeze() -> None:
    manifest = common.read_json(ROOT / MANIFEST)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("pnl_parsed") is not False:
        raise common.CycleError("invalid V2 freeze manifest")
    for relative, evidence in manifest.get("files", {}).items():
        path = ROOT / relative
        if not path.is_file() or common.sha256(path) != evidence.get("sha256"):
            raise common.CycleError(f"frozen input changed: {relative}")


def backtest(label: str, timerange: str, strategy: str, configs: Iterable[Path], datadir: Path, timeout: int) -> dict[str, Any]:
    final = ROOT / REPORT_DIR / f"{label}.zip"
    if final.exists():
        raise common.CycleError(f"refusing to overwrite {final}")
    with tempfile.TemporaryDirectory(prefix=f"{label}-", dir=ROOT / REPORT_DIR) as temporary:
        staging = Path(temporary)
        command = [
            "docker", "run", "--rm",
            "-v", f"{(ROOT / 'user_data').resolve()}:/freqtrade/user_data:ro",
            "-v", f"{staging.resolve()}:/freqtrade/user_data/backtest_results:rw",
            "--entrypoint", "freqtrade", common.IMAGE, "backtesting",
        ]
        for config in configs:
            command.extend(("--config", f"/freqtrade/{config.as_posix()}"))
        command.extend((
            "--userdir", "/freqtrade/user_data", "--strategy", strategy,
            "--datadir", f"/freqtrade/{datadir.as_posix()}",
            "--timerange", timerange, "--export", "trades",
            "--cache", "none", "--no-color",
        ))
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
        if result.returncode:
            tail = ((result.stdout or "") + "\n" + (result.stderr or ""))[-3000:]
            raise common.CycleError(f"{label} backtest exit {result.returncode}: {tail}")
        receipt = common.read_json(staging / ".last_result.json")
        filename = receipt.get("latest_backtest")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise common.CycleError(f"invalid receipt: {label}")
        archive = staging / filename
        sanitized = subprocess.run(
            [sys.executable, str(ROOT / "tools/sanitize_backtest_archive.py"), str(archive)],
            cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
        )
        if sanitized.returncode:
            raise common.CycleError(f"sanitizer failed: {label}: {sanitized.stderr[-1000:]}")
        os.replace(archive, final)
    return {
        "path": final.relative_to(ROOT).as_posix(),
        "sha256": common.sha256(final),
        "size_bytes": final.stat().st_size,
        "command_sha256": hashlib.sha256("\0".join(command).encode()).hexdigest(),
        "stdout_stderr_sha256": hashlib.sha256(
            ((result.stdout or "") + "\n" + (result.stderr or "")).encode()
        ).hexdigest(),
    }


def evaluate_period(label: str, timerange: str, days: int) -> dict[str, Any]:
    swing, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_swing.zip", "ProfitMaxCagr20V2", timerange, days, 3.76
    )
    daily, _ = common.load_archive(
        ROOT / REPORT_DIR / f"{label}_daily.zip", "ProfitMaxDailyTop2ActivityV1", timerange, days, 1.0
    )
    combined = [dict(trade, portfolio_component="swing") for trade in swing]
    combined.extend(dict(trade, portfolio_component="daily") for trade in daily)
    baseline = common.metrics(combined, days, 0.0)
    severe = common.metrics(combined, days, common.SEVERE_EXTRA_COST_PER_SIDE)
    exposure = common.maximum_exposure(combined)
    baseline_years = baseline["year_profit_usdt"]
    severe_years = severe["year_profit_usdt"]
    gates = {
        "trades_per_day_gte_1": baseline["trades_per_day"] >= 1.0,
        "baseline_cagr_gte_20": baseline["cagr_pct"] >= 20.0,
        "severe_cagr_gte_20": severe["cagr_pct"] >= 20.0,
        "baseline_profit_factor_gte_1_50": baseline["profit_factor"] >= 1.50,
        "severe_profit_factor_gte_1_50": severe["profit_factor"] >= 1.50,
        "baseline_drawdown_lte_20": baseline["realized_drawdown_pct"] <= 20.0,
        "severe_drawdown_lte_20": severe["realized_drawdown_pct"] <= 20.0,
        "maximum_margin_lte_25pct": exposure["maximum_concurrent_margin_usdt"] <= common.WALLET * 0.25 + 1e-9,
        "maximum_notional_lte_75pct": exposure["maximum_concurrent_notional_usdt"] <= common.WALLET * 0.75 + 1e-9,
        "no_baseline_segment_below_minus_2pct": all(value >= -20.0 for value in baseline_years.values()),
        "no_severe_segment_below_minus_2pct": all(value >= -20.0 for value in severe_years.values()),
        "at_least_four_positive_baseline_segments": sum(value > 0 for value in baseline_years.values()) >= 4,
        "at_least_four_positive_severe_segments": sum(value > 0 for value in severe_years.values()) >= 4,
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "timerange": timerange,
        "baseline": baseline,
        "severe_cost": severe,
        "exposure": exposure,
        "components": {
            "swing": common.metrics(swing, days, 0.0),
            "daily": common.metrics(daily, days, 0.0),
        },
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    try:
        manifest = freeze()
        verify_freeze()
        artifacts: dict[str, Any] = {}
        for label, (timerange, _) in PERIODS.items():
            artifacts[f"{label}_swing"] = backtest(
                f"{label}_swing", timerange, "ProfitMaxCagr20V2",
                (Path("user_data/config-profit-max-cagr20-v2.json"),),
                Path("user_data/data/binance"), args.timeout,
            )
            artifacts[f"{label}_daily"] = backtest(
                f"{label}_daily", timerange, "ProfitMaxDailyTop2ActivityV1",
                (
                    Path("user_data/config-profit-max-liquid50-cycle1.json"),
                    Path("user_data/config-profit-max20-daily-v2-overlay.json"),
                ),
                Path("user_data/data/binance/profit_max_liquid50_cycle1_source"), args.timeout,
            )
        verify_freeze()
        results = {
            label: evaluate_period(label, timerange, days)
            for label, (timerange, days) in PERIODS.items()
        }
        primary_pass = results["rolling_five_year"]["status"] == "PASS"
        payload = {
            "schema_version": "1.0",
            "cycle": "profit_max20_v2",
            "status": "PASS" if primary_pass else "FAIL",
            "decision": "APPROVE_CREDENTIAL_FREE_ISOLATED_DRY_RUN_ONLY" if primary_pass else "KEEP_OFFLINE_RESEARCH",
            "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "primary_period": "rolling_five_year",
            "history_status": "FULLY_SEEN_RETROSPECTIVE_NOT_HOLDOUT",
            "profit_guaranteed": False,
            "live_trading_authorized": False,
            "automatic_promotion_authorized": False,
            "freeze_manifest_sha256": common.sha256(ROOT / MANIFEST),
            "frozen_file_count": len(manifest["files"]),
            "results": results,
            "artifacts": artifacts,
        }
        common.write_json(ROOT / DECISION, payload, exclusive=True)
        print(json.dumps({
            "status": payload["status"], "decision": payload["decision"],
            "rolling": results["rolling_five_year"],
            "calendar": results["calendar_five_year"],
        }, indent=2, allow_nan=False))
        return 0 if primary_pass else 2
    except Exception as exc:
        print(f"PROFIT_MAX20_V2_BLOCKED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
