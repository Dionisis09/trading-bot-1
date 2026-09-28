#!/usr/bin/env python3
"""Consolidate the frozen ensemble technical gates before validation."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle4"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    paths = {
        "train": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle2/train_decision.json",
        "stress": ROOT / "user_data/reports/profit_max_daily_v5_ensemble_cycle2/execution_stress.json",
        "parity": REPORT / "parity.json",
        "lookahead": REPORT / "daily_lookahead100.csv",
    }
    for path in paths.values():
        if not path.is_file():
            raise SystemExit(f"missing technical artifact: {path}")
    train = json.loads(paths["train"].read_text(encoding="utf-8"))
    stress = json.loads(paths["stress"].read_text(encoding="utf-8"))
    parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
    with paths["lookahead"].open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", "profitmax-recursive-cycle4"],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    logs = subprocess.run(
        ["docker", "logs", "profitmax-recursive-cycle4"], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    recursive_text = logs.stdout + logs.stderr
    lookahead_inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}} {{.Id}}", "profitmax-lookahead100"],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    lookahead_logs_result = subprocess.run(
        ["docker", "logs", "profitmax-lookahead100"], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    lookahead_text = lookahead_logs_result.stdout + lookahead_logs_result.stderr
    csv_clean = (
        len(rows) == 1
        and rows[0].get("has_bias") == "No"
        and rows[0].get("total_signals") == "100"
        and rows[0].get("biased_entry_signals") == "0"
        and rows[0].get("biased_exit_signals") == "0"
        and not (rows[0].get("biased_indicators") or "").strip()
    )
    retained_log_clean = (
        lookahead_inspect.startswith("exited 0 ")
        and "Found targeted trade amount = 100 signals." in lookahead_text
        and "ProfitMaxDailyCrossStop20AuditV2: no bias detected" in lookahead_text
        and "100/100 100%" in lookahead_text
    )
    gates = {
        "train_pass": train.get("status") == "PASS" and train.get("decision") == "UNLOCK_TECHNICAL_GATES",
        "exact_trade_parity": parity.get("status") == "PASS" and parity.get("exact_trade_rows") is True,
        "lookahead_100_clean": csv_clean or retained_log_clean,
        "recursive_clean": (
            inspect == "exited 0"
            and "No variance on indicator(s) found due to recursive formula." in recursive_text
            and "No lookahead bias on indicators found." in recursive_text
        ),
        "execution_stress_pass": stress.get("pass") is True,
    }
    passed = all(gates.values())
    payload = {
        "schema_version": "1.0", "cycle": "profit_max_daily_v5_ensemble_cycle4",
        "status": "PASS" if passed else "FAIL",
        "decision": "UNLOCK_VALIDATION_ONCE" if passed else "REJECT_CANDIDATE",
        "lookahead_evidence": {
            "csv_rows": len(rows),
            "csv_clean": csv_clean,
            "retained_log_clean": retained_log_clean,
            "container_state_id": lookahead_inspect,
            "container_log_sha256": hashlib.sha256(lookahead_text.encode("utf-8")).hexdigest(),
            "exporter_limitation": "Freqtrade 2026.7 wrote a header-only CSV despite an exit-0 100-signal clean terminal result",
        },
        "gates": gates, "validation_revealed": False, "live_trading_authorized": False,
        "artifacts": {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)} for name, path in paths.items()},
    }
    target = REPORT / "technical_decision_v2.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
