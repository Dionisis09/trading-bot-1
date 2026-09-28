#!/usr/bin/env python3
"""Freeze, run, reconcile, and select the fixed 15m TRAIN tournament."""

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

import freeze_pro_day_v3_cycle1 as base


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "freqtradeorg/freqtrade@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643"
PLAN = Path("docs/pro_swing_tournament_1h_cycle3_locked_plan.md")
STRATEGY = Path("user_data/strategies/ProSwingTournament1h.py")
CONFIG = Path("user_data/config-pro-swing-tournament-1h-cycle3.json")
TESTS = Path("tools/test_pro_swing_tournament_1h.py")
AUDIT = Path("user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json")
RISK = Path("user_data/risk_policy.json")
RUNNER = Path("tools/run_pro_swing_tournament_1h.py")
REPORT_DIR = Path("user_data/reports/pro_swing_tournament_1h_cycle3")
MANIFEST = REPORT_DIR / "research_freeze_manifest.json"
LEDGER = REPORT_DIR / "trial_ledger.json"
OUTPUT = REPORT_DIR / "train_tournament.json"
STAGING = REPORT_DIR / "train_staging"
ARTIFACT = Path("user_data/backtest_results/pro-swing-tournament-1h-cycle3-train.zip")
TIMERANGE = "20220101-20240101"
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"]
CANDIDATES = [
    "ProSwingCore1h", "ProSwingSlow1h", "ProSwingSelective1h", "ProSwingStrongTrend1h",
]
HASHES = {
    STRATEGY: "f87333d0135a4da026e8908e0102102110404dc760e5590e4427346c7dbfec82",
    CONFIG: "a634d92284a22ac1da9b6098a0b9d97da73bc858d96a8c5bdfac94e6465a8ff3",
    TESTS: "9460eafffbe740102ec72766aed1d2dbd647c8a4c3ecdaad4ab1febfacbcc66d",
    AUDIT: "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772",
    RISK: "6a3e073fd08b21d645b0d4b4151022bef79adc610d8c130b36554a01e6f51e80",
}


class TournamentError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TournamentError(f"invalid JSON object: {path}")
    return value


def write(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if exclusive:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise TournamentError(f"refusing to overwrite {path}") from exc
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def freeze(root: Path) -> dict[str, Any]:
    paths = [PLAN, STRATEGY, CONFIG, TESTS, AUDIT, RISK, RUNNER]
    for relative in paths:
        if not (root / relative).is_file():
            raise TournamentError(f"missing frozen input: {relative}")
    for relative, expected in HASHES.items():
        if sha256(root / relative) != expected:
            raise TournamentError(f"hash mismatch: {relative}")
    config = load(root / CONFIG)
    if config.get("strategy") != CANDIDATES[0] or config.get("dry_run") is not True:
        raise TournamentError("research config differs")
    if config.get("trading_mode") != "futures" or config.get("margin_mode") != "isolated":
        raise TournamentError("research futures mode differs")
    if config.get("pro_swing_research", {}).get("status") != "LOCKED_BEFORE_TOURNAMENT_TRAIN":
        raise TournamentError("config is not locked")
    if "freqai" in config or "freqaimodel" in config:
        raise TournamentError("ML is forbidden in tournament cycle 1")
    audit = load(root / AUDIT)
    data_files = base.validate_data(audit, root)
    if (root / ARTIFACT).exists() or (root / OUTPUT).exists():
        raise TournamentError("TRAIN output already exists")
    if (root / REPORT_DIR).exists() and any((root / REPORT_DIR).iterdir()):
        raise TournamentError("tournament report directory is not empty")
    descriptors = {
        str(relative).replace("\\", "/"): {"sha256": sha256(root / relative), "size_bytes": (root / relative).stat().st_size}
        for relative in paths
    }
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0", "status": "RESEARCH_FROZEN",
        "cycle": "pro_swing_tournament_1h_cycle3", "locked_at_utc": now,
        "candidates": CANDIDATES, "files": descriptors, "data_files": data_files,
        "train_timerange": TIMERANGE, "validation_timerange": "20240101-20260101",
        "selection_rule": "highest_return_among_all_train_gates_pass_tie_pf_then_lower_dd",
        "artifact": {"path": str(ARTIFACT).replace("\\", "/"), "status": "PLANNED_NOT_RUN"},
        "pnl_parsed": False, "validation_revealed": False, "live_trading_authorized": False,
    }
    ledger = {
        "schema_version": "1.0", "cycle": manifest["cycle"], "created_at_utc": now,
        "candidate_trials": CANDIDATES, "trial_count": len(CANDIDATES),
        "train_runs": 0, "validation_runs": 0, "pnl_parsed": False,
        "post_result_edits_allowed": False, "live_trading_authorized": False,
    }
    write(root / LEDGER, ledger, exclusive=True)
    try:
        write(root / MANIFEST, manifest, exclusive=True)
    except Exception:
        (root / LEDGER).unlink(missing_ok=True)
        raise
    return manifest


def validate_frozen(root: Path) -> tuple[dict[str, Any], str]:
    manifest = load(root / MANIFEST)
    if manifest.get("status") != "RESEARCH_FROZEN" or manifest.get("candidates") != CANDIDATES:
        raise TournamentError("manifest differs")
    if manifest.get("pnl_parsed") is not False or manifest.get("validation_revealed") is not False:
        raise TournamentError("manifest crossed evidence boundary")
    for relative, row in manifest.get("files", {}).items():
        path = root / relative
        if not path.is_file() or sha256(path) != row.get("sha256"):
            raise TournamentError(f"frozen file changed: {relative}")
    if (root / ARTIFACT).exists() or (root / OUTPUT).exists():
        raise TournamentError("TRAIN output already exists")
    if (root / STAGING).exists() and any((root / STAGING).iterdir()):
        raise TournamentError("TRAIN staging is not empty")
    return manifest, sha256(root / MANIFEST)


def build_command(root: Path) -> list[str]:
    return [
        "docker", "run", "--rm",
        "-v", f"{(root / 'user_data').resolve()}:/freqtrade/user_data:ro",
        "-v", f"{(root / 'user_data/data/binance/pro_day_v2_canonical').resolve()}:/canonical/futures:ro",
        "-v", f"{(root / STAGING).resolve()}:/freqtrade/user_data/backtest_results:rw",
        "--entrypoint", "freqtrade", IMAGE, "backtesting",
        "--config", "/freqtrade/user_data/config-pro-swing-tournament-1h-cycle3.json",
        "--userdir", "/freqtrade/user_data", "--strategy-list", *CANDIDATES,
        "--datadir", "/canonical", "--timerange", TIMERANGE,
        "--pairs", *PAIRS, "--export", "trades", "--cache", "none", "--no-color",
    ]


def resolve_receipt(staging: Path) -> tuple[Path, Path, Path]:
    receipt = staging / ".last_result.json"
    value = load(receipt)
    filename = value.get("latest_backtest")
    if set(value) != {"latest_backtest"} or not isinstance(filename, str) or Path(filename).name != filename:
        raise TournamentError("invalid Freqtrade receipt")
    archive = staging / filename
    metadata = staging / f"{Path(filename).stem}.meta.json"
    if not archive.is_file() or not metadata.is_file():
        raise TournamentError("receipt files missing")
    if sorted(path.name for path in staging.glob("*.zip")) != [archive.name]:
        raise TournamentError("ambiguous staged ZIP inventory")
    return receipt, archive, metadata


def reconcile(payload: Mapping[str, Any]) -> dict[str, Any]:
    trades = payload.get("trades")
    if not isinstance(trades, list):
        raise TournamentError("trades missing")
    profits = [float(row["profit_abs"]) for row in trades]
    gains = sum(value for value in profits if value > 0)
    losses = -sum(value for value in profits if value < 0)
    pf = gains / losses if losses > 0 else None
    if len(trades) != int(payload.get("total_trades", -1)):
        raise TournamentError("trade count mismatch")
    if abs(sum(profits) - float(payload.get("profit_total_abs"))) > 1e-6:
        raise TournamentError("profit mismatch")
    if pf is None or abs(pf - float(payload.get("profit_factor"))) > 1e-12:
        raise TournamentError("PF mismatch")
    return {
        "trade_count": len(trades), "profit_abs": sum(profits), "profit_factor": pf,
        "long_count": sum(not bool(row.get("is_short")) for row in trades),
        "short_count": sum(bool(row.get("is_short")) for row in trades),
        "pair_counts": {pair: sum(row.get("pair") == pair for row in trades) for pair in PAIRS},
    }


def evaluate_strategy(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    reconciliation = reconcile(payload)
    ret = float(payload.get("profit_total")); pf = float(payload.get("profit_factor"))
    dd = float(payload.get("max_drawdown_account"))
    if any(not math.isfinite(value) for value in (ret, pf, dd)) or dd < 0:
        raise TournamentError(f"non-finite metrics: {name}")
    return_dd = ret / dd if dd > 0 else (math.inf if ret > 0 else None)
    gates = {
        "trades_gte_60": reconciliation["trade_count"] >= 60,
        "return_positive": ret > 0, "profit_factor_gte_1_15": pf >= 1.15,
        "wallet_drawdown_lte_15pct": dd <= 0.15,
        "return_to_drawdown_gte_0_50": return_dd is not None and return_dd >= 0.50,
    }
    return {
        "strategy": name, "status": "PASS" if all(gates.values()) else "FAIL", "gates": gates,
        "metrics": {"trades": reconciliation["trade_count"], "return_pct": ret * 100,
                    "profit_factor": pf, "wallet_drawdown_pct": dd * 100,
                    "return_to_drawdown": return_dd,
                    "starting_balance": float(payload.get("starting_balance")),
                    "final_balance": float(payload.get("final_balance"))},
        "reconciliation": reconciliation,
    }


def parse_archive(path: Path, expected_source_hash: str) -> list[dict[str, Any]]:
    expected_suffixes = {f"_{name}.py" for name in CANDIDATES}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise TournamentError("corrupt tournament ZIP")
        result_names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        source_names = [name for name in archive.namelist() if any(name.endswith(suffix) for suffix in expected_suffixes)]
        if len(result_names) != 1 or len(source_names) != len(CANDIDATES):
            raise TournamentError("ambiguous tournament archive inventory")
        if any(hashlib.sha256(archive.read(name)).hexdigest() != expected_source_hash for name in source_names):
            raise TournamentError("embedded tournament source differs")
        result = json.loads(archive.read(result_names[0]))
    strategies = result.get("strategy", {})
    if set(strategies) != set(CANDIDATES):
        raise TournamentError("result candidate inventory differs")
    rows = []
    for name in CANDIDATES:
        payload = strategies[name]
        if payload.get("timerange") != TIMERANGE or payload.get("timeframe") != "1h" or payload.get("pairlist") != PAIRS:
            raise TournamentError(f"result contract differs: {name}")
        rows.append(evaluate_strategy(name, payload))
    return rows


def run(root: Path, timeout: int) -> dict[str, Any]:
    manifest, manifest_hash = validate_frozen(root)
    staging = root / STAGING; staging.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(build_command(root), cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode:
        raise TournamentError(f"tournament backtest exit {result.returncode}")
    receipt, staged, metadata = resolve_receipt(staging)
    pre_sanitize_hash = sha256(staged)
    sanitizer = subprocess.run([sys.executable, str(root / "tools/sanitize_backtest_archive.py"), str(staged)],
                               cwd=root, capture_output=True, text=True, timeout=120, check=False)
    if sanitizer.returncode:
        raise TournamentError("archive sanitizer failed")
    rows = parse_archive(staged, manifest["files"][str(STRATEGY).replace("\\", "/")]["sha256"])
    passed = [row for row in rows if row["status"] == "PASS"]
    passed.sort(key=lambda row: (-row["metrics"]["return_pct"], -row["metrics"]["profit_factor"], row["metrics"]["wallet_drawdown_pct"]))
    winner = passed[0]["strategy"] if passed else None
    final = root / ARTIFACT; final.parent.mkdir(parents=True, exist_ok=True); os.replace(staged, final)
    report = {
        "schema_version": "1.0", "status": "PASS" if winner else "FAIL",
        "decision": "CONTINUE_WINNER_TO_TECHNICAL_GATES" if winner else "KEEP_OFFLINE_RESEARCH",
        "cycle": "pro_swing_tournament_1h_cycle3", "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": manifest_hash, "winner": winner, "candidate_results": rows,
        "artifact": {"path": str(ARTIFACT).replace("\\", "/"), "sha256": sha256(final),
                     "pre_sanitize_sha256": pre_sanitize_hash, "size_bytes": final.stat().st_size,
                     "selected_by": "exact_isolated_freqtrade_receipt", "sanitized": True},
        "receipt_sha256": sha256(receipt), "metadata_sha256": sha256(metadata),
        "captured_output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        "train_runs": 1, "candidate_trials": len(CANDIDATES), "validation_revealed": False,
        "pnl_parsed": True, "live_trading_authorized": False,
    }
    write(root / OUTPUT, report, exclusive=True)
    ledger = load(root / LEDGER); ledger["train_runs"] = 1; ledger["pnl_parsed"] = True
    ledger["winner"] = winner; ledger["report_sha256"] = sha256(root / OUTPUT); write(root / LEDGER, ledger)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args(argv); root = args.workspace.resolve()
    try:
        report = freeze(root) if args.freeze else run(root, args.timeout_seconds)
        if args.freeze:
            print(json.dumps({"status": report["status"], "pnl_parsed": False})); return 0
        print(json.dumps({"status": report["status"], "decision": report["decision"], "winner": report["winner"],
                          "results": {row["strategy"]: row["metrics"] for row in report["candidate_results"]}}))
        return 0 if report["status"] == "PASS" else 2
    except (TournamentError, base.FreezeError, OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "TOURNAMENT_BLOCKED", "error": str(exc)})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
