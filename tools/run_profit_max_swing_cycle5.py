#!/usr/bin/env python3
"""Freeze and execute the bounded Profit-Max Swing Cycle 5 tournament."""

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
PLAN = Path("docs/profit_max_swing_cycle5_locked_plan.md")
STRATEGY = Path("user_data/strategies/ProfitMaxSwingV5.py")
BASE_STRATEGY = Path("user_data/strategies/DualTrendFuturesV2.py")
RISK_STRATEGY = Path("user_data/strategies/DualTrendFuturesRisk.py")
PROFESSIONAL_RISK = Path("user_data/strategies/ProfessionalRisk.py")
CONFIG = Path("user_data/config-profit-max-swing-cycle5.json")
RISK_POLICY = Path("user_data/risk_policy.json")
TESTS = Path("tools/test_profit_max_swing_v5.py")
RUNNER_TESTS = Path("tools/test_run_profit_max_swing_cycle5.py")
RUNNER = Path("tools/run_profit_max_swing_cycle5.py")
REPORT_DIR = Path("user_data/reports/profit_max_swing_cycle5")
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
OUTPUT = REPORT_DIR / "tournament.json"
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"]
CANDIDATES = ["DualTrendFuturesV2R", "ProfitMaxV5Asymmetric50", "ProfitMaxV5SelectiveShort", "ProfitMaxV5Balanced", "ProfitMaxV5LongOnly"]
ELIGIBLE = set(CANDIDATES[:-1])
SPLITS = {"train": "20210101-20240101", "validation": "20240101-20260101", "current_partial": "20260101-20260801"}
DATA_FILES = [Path(f"user_data/data/binance/futures/{pair}_USDT_USDT-{tf}-futures.feather") for pair in ("BTC", "ETH", "BNB", "XRP", "ADA", "DOGE") for tf in ("4h", "1d")]


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


def write_json(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise CycleError(f"refusing to overwrite {path}") from exc
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def frozen_inputs() -> list[Path]:
    return [PLAN, STRATEGY, BASE_STRATEGY, RISK_STRATEGY, PROFESSIONAL_RISK, CONFIG, RISK_POLICY, TESTS, RUNNER_TESTS, RUNNER, *DATA_FILES]


def freeze(root: Path) -> dict[str, Any]:
    if (root / REPORT_DIR).exists() and any((root / REPORT_DIR).iterdir()):
        raise CycleError("cycle report directory is not empty")
    inputs = frozen_inputs()
    for relative in inputs:
        if not (root / relative).is_file():
            raise CycleError(f"missing input: {relative}")
    config = read_json(root / CONFIG)
    research = config.get("profit_max_research", {})
    if config.get("dry_run") is not True or research.get("status") != "LOCKED_BEFORE_PNL":
        raise CycleError("research config is not locked dry-run")
    if config.get("exchange", {}).get("key") or config.get("exchange", {}).get("secret"):
        raise CycleError("research config contains credentials")
    artifacts = {label: str(REPORT_DIR / f"{label}.zip").replace("\\", "/") for label in (*SPLITS, "continuous")}
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_swing_cycle5", "status": "RESEARCH_FROZEN",
        "locked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidates": CANDIDATES, "eligible_candidates": sorted(ELIGIBLE), "splits": SPLITS,
        "files": {str(path).replace("\\", "/"): {"sha256": sha256(root / path), "size_bytes": (root / path).stat().st_size} for path in inputs},
        "planned_artifacts": artifacts, "pnl_parsed": False, "validation_revealed": False,
        "live_trading_authorized": False,
    }
    write_json(root / MANIFEST, payload, exclusive=True)
    return payload


def validate_frozen(root: Path) -> dict[str, Any]:
    manifest = read_json(root / MANIFEST)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("candidates") != CANDIDATES:
        raise CycleError("freeze manifest differs")
    if manifest.get("pnl_parsed") is not False or manifest.get("validation_revealed") is not False:
        raise CycleError("freeze evidence boundary crossed")
    for relative, row in manifest.get("files", {}).items():
        if not (root / relative).is_file() or sha256(root / relative) != row.get("sha256"):
            raise CycleError(f"frozen file changed: {relative}")
    if (root / OUTPUT).exists():
        raise CycleError("output already exists")
    return manifest


def metrics(name: str, payload: Mapping[str, Any], split: str) -> dict[str, Any]:
    trades = payload.get("trades")
    if not isinstance(trades, list):
        raise CycleError(f"trades missing: {name}/{split}")
    profits = [float(row["profit_abs"]) for row in trades]
    gains = sum(value for value in profits if value > 0)
    losses = -sum(value for value in profits if value < 0)
    pf = gains / losses if losses else math.inf
    reported_pf = float(payload["profit_factor"])
    if len(trades) != int(payload["total_trades"]) or abs(sum(profits) - float(payload["profit_total_abs"])) > 1e-6:
        raise CycleError(f"reconciliation failed: {name}/{split}")
    if math.isfinite(pf) and abs(pf - reported_pf) > 1e-12:
        raise CycleError(f"PF reconciliation failed: {name}/{split}")
    ret = float(payload["profit_total"]); dd = float(payload["max_drawdown_account"])
    values = (ret, reported_pf, dd)
    if any(not math.isfinite(value) for value in values) or dd < 0:
        raise CycleError(f"invalid metric: {name}/{split}")
    by_year: dict[str, float] = {}
    for trade in trades:
        year = str(trade["open_date"])[:4]
        by_year[year] = by_year.get(year, 0.0) + float(trade["profit_abs"])
    return {
        "strategy": name, "split": split, "trades": len(trades),
        "long_trades": sum(not bool(row.get("is_short")) for row in trades),
        "short_trades": sum(bool(row.get("is_short")) for row in trades),
        "profit_abs_usdt": sum(profits), "return_pct": ret * 100, "profit_factor": reported_pf,
        "wallet_drawdown_pct": dd * 100,
        "return_to_drawdown": ret / dd if dd > 0 else (999.0 if ret > 0 else 0.0),
        "year_profit_abs_usdt": dict(sorted(by_year.items())),
    }


def gates(row: Mapping[str, Any], split: str) -> dict[str, bool]:
    if row["strategy"] not in ELIGIBLE:
        return {"eligible": False}
    if split == "train":
        return {
            "eligible": True, "trades_gte_100": row["trades"] >= 100,
            "return_positive": row["return_pct"] > 0, "pf_gte_1_30": row["profit_factor"] >= 1.30,
            "dd_lte_12": row["wallet_drawdown_pct"] <= 12, "return_dd_gte_1_5": row["return_to_drawdown"] >= 1.5,
            "long_gte_25": row["long_trades"] >= 25, "short_gte_25": row["short_trades"] >= 25,
        }
    if split == "validation":
        years = row["year_profit_abs_usdt"]
        return {
            "eligible": True, "trades_gte_70": row["trades"] >= 70,
            "return_positive": row["return_pct"] > 0, "pf_gte_1_25": row["profit_factor"] >= 1.25,
            "dd_lte_10": row["wallet_drawdown_pct"] <= 10, "return_dd_gte_1_5": row["return_to_drawdown"] >= 1.5,
            "long_gte_20": row["long_trades"] >= 20, "short_gte_20": row["short_trades"] >= 20,
            "year_2024_positive": years.get("2024", 0.0) > 0, "year_2025_positive": years.get("2025", 0.0) > 0,
        }
    return {"diagnostic_only": True}


def row_passes(row: Mapping[str, Any], split: str) -> bool:
    result = gates(row, split)
    return bool(result) and all(result.values())


def select_winner(train_rows: Sequence[Mapping[str, Any]], validation_rows: Sequence[Mapping[str, Any]]) -> str | None:
    train_pass = {row["strategy"] for row in train_rows if row_passes(row, "train")}
    passed = [row for row in validation_rows if row["strategy"] in train_pass and row_passes(row, "validation")]
    passed.sort(key=lambda row: (-row["return_to_drawdown"], -row["profit_factor"], row["wallet_drawdown_pct"], row["strategy"]))
    return str(passed[0]["strategy"]) if passed else None


def backtest(root: Path, label: str, timerange: str, candidates: Sequence[str], timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    staging = root / REPORT_DIR / f"{label}_staging"
    staging.mkdir(parents=True, exist_ok=False)
    command = [
        "docker", "run", "--rm", "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{staging.resolve()}:/freqtrade/user_data/backtest_results:rw", "--entrypoint", "freqtrade", IMAGE,
        "backtesting", "--config", "/freqtrade/user_data/config-profit-max-swing-cycle5.json", "--userdir", "/freqtrade/user_data",
        "--strategy-list", *candidates, "--datadir", "/freqtrade/user_data/data/binance", "--timerange", timerange,
        "--pairs", *PAIRS, "--export", "trades", "--cache", "none", "--no-color",
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if result.returncode:
        raise CycleError(f"{label} backtest exit {result.returncode}: {(result.stderr or '')[-500:]}")
    receipt = read_json(staging / ".last_result.json")
    filename = receipt.get("latest_backtest")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise CycleError(f"invalid receipt: {label}")
    archive = staging / filename
    sanitizer = subprocess.run([sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(archive)], cwd=root, capture_output=True, text=True, timeout=120, check=False)
    if sanitizer.returncode:
        raise CycleError(f"sanitizer failed: {label}")
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip():
            raise CycleError(f"corrupt archive: {label}")
        result_names = [name for name in zipped.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        if len(result_names) != 1:
            raise CycleError(f"ambiguous archive: {label}")
        payload = json.loads(zipped.read(result_names[0]))
    strategies = payload.get("strategy", {})
    if set(strategies) != set(candidates):
        raise CycleError(f"candidate inventory differs: {label}")
    rows = [metrics(name, strategies[name], label) for name in candidates]
    final = root / REPORT_DIR / f"{label}.zip"
    os.replace(archive, final)
    evidence = {
        "path": str(final.relative_to(root)).replace("\\", "/"), "sha256": sha256(final), "size_bytes": final.stat().st_size,
        "timerange": timerange, "candidates": list(candidates),
        "stdout_stderr_sha256": hashlib.sha256(((result.stdout or "") + "\n" + (result.stderr or "")).encode()).hexdigest(),
    }
    return rows, evidence


def run(root: Path, timeout: int) -> dict[str, Any]:
    manifest = validate_frozen(root)
    train_rows, train_artifact = backtest(root, "train", SPLITS["train"], CANDIDATES, timeout)
    if not any(row_passes(row, "train") for row in train_rows):
        raise CycleError("no eligible TRAIN pass; validation remains hidden")
    validation_rows, validation_artifact = backtest(root, "validation", SPLITS["validation"], CANDIDATES, timeout)
    winner = select_winner(train_rows, validation_rows)
    if winner is None:
        raise CycleError("no eligible validation pass")
    current_rows, current_artifact = backtest(root, "current_partial", SPLITS["current_partial"], CANDIDATES, timeout)
    continuous_candidates = ["DualTrendFuturesV2R"] if winner == "DualTrendFuturesV2R" else ["DualTrendFuturesV2R", winner]
    continuous_rows, continuous_artifact = backtest(root, "continuous", "20210101-20260801", continuous_candidates, timeout)
    for row in train_rows: row["gates"] = gates(row, "train"); row["status"] = "PASS" if row_passes(row, "train") else "DIAGNOSTIC" if row["strategy"] not in ELIGIBLE else "FAIL"
    for row in validation_rows: row["gates"] = gates(row, "validation"); row["status"] = "PASS" if row_passes(row, "validation") else "DIAGNOSTIC" if row["strategy"] not in ELIGIBLE else "FAIL"
    report = {
        "schema_version": "1.0", "cycle": "profit_max_swing_cycle5", "status": "PASS",
        "decision": "WINNER_REQUIRES_COST_AND_TECHNICAL_GATES", "winner": winner,
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "freeze_manifest_sha256": sha256(root / MANIFEST), "validation_revealed": True, "pnl_parsed": True,
        "live_trading_authorized": False, "profit_guaranteed": False,
        "results": {"train": train_rows, "validation": validation_rows, "current_partial": current_rows, "continuous": continuous_rows},
        "artifacts": {"train": train_artifact, "validation": validation_artifact, "current_partial": current_artifact, "continuous": continuous_artifact},
        "evidence_boundary": "All historical periods were already seen; this is robustness evidence, not a sealed holdout or a profit guarantee.",
    }
    write_json(root / OUTPUT, report, exclusive=True)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args(argv)
    try:
        payload = freeze(args.workspace.resolve()) if args.freeze else run(args.workspace.resolve(), args.timeout_seconds)
        print(json.dumps({"status": payload["status"], "winner": payload.get("winner"), "pnl_parsed": payload.get("pnl_parsed")}, sort_keys=True))
        return 0
    except (CycleError, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "CYCLE_BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
