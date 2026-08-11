#!/usr/bin/env python3
"""Build a fail-closed qualification report without authorizing live trading."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def gate(name: str, passed: bool, actual: Any, requirement: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "actual": actual,
        "requirement": requirement,
    }


def runtime_check(bot: dict[str, Any], name: str) -> bool:
    checks = bot.get("runtime_validation", {}).get("checks", [])
    return any(item.get("name") == name and item.get("status") == "PASS" for item in checks)


def build_readiness(
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    stress: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    bots = snapshot.get("bots", {})
    bot_values = [bots.get(key, {}) for key in ("v1", "v2r")]
    continuity = snapshot.get("monitoring", {}).get("continuity", {})
    evidence_gates = [
        gate(
            "forward_review_decision",
            decision.get("decision") == "FORWARD_REVIEW_READY",
            decision.get("decision"),
            "FORWARD_REVIEW_READY",
        ),
        gate(
            "continuous_forward_evidence",
            continuity.get("pass") is True,
            {
                "status": continuity.get("status"),
                "coverage_ratio": continuity.get("coverage_ratio"),
                "validated_observation_days": continuity.get("validated_observation_days"),
            },
            "continuity pass",
        ),
        gate(
            "account_risk_inside_limits",
            all(bot.get("account_risk", {}).get("new_entries_allowed") is True for bot in bot_values),
            {
                key: bots.get(key, {}).get("account_risk", {}).get("new_entries_allowed")
                for key in ("v1", "v2r")
            },
            "true for both bots",
        ),
        gate(
            "execution_stress",
            stress.get("status") == "PASS",
            stress.get("status"),
            "PASS",
        ),
    ]
    safe_dry_run = all(bot.get("runtime", {}).get("dry_run") is True for bot in bot_values)
    credentials_absent = all(runtime_check(bot, "local_exchange_credentials_empty") for bot in bot_values)
    policy_unauthorized = policy.get("live_launch", {}).get("authorized") is False
    safety_gates = [
        gate("dry_run_enforced", safe_dry_run, safe_dry_run, True),
        gate("exchange_credentials_absent", credentials_absent, credentials_absent, True),
        gate("policy_live_launch_unauthorized", policy_unauthorized, policy.get("live_launch", {}).get("authorized"), False),
        gate("automatic_promotion_disabled", decision.get("auto_promotion_enabled") is False, decision.get("auto_promotion_enabled"), False),
    ]
    evidence_pass = all(item["status"] == "PASS" for item in evidence_gates)
    safety_pass = all(item["status"] == "PASS" for item in safety_gates)
    if not safety_pass:
        status = "SAFETY_BLOCK"
    elif evidence_pass:
        status = "READY_FOR_HUMAN_REVIEW"
    else:
        status = "EVIDENCE_INCOMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "snapshot_utc": snapshot.get("snapshot_utc"),
        "qualification_status": status,
        "selected_candidate": decision.get("selected_candidate"),
        "evidence_gates": evidence_gates,
        "safety_gates": safety_gates,
        "next_action": (
            "Human review may begin; live launch still requires a separate explicit authorization and micro-capital plan."
            if status == "READY_FOR_HUMAN_REVIEW"
            else "Continue credential-free dry-run qualification and resolve every failed evidence gate."
        ),
        "live_trading_authorized": False,
        "automatic_live_launch_available": False,
        "profit_guaranteed": False,
    }


def write_report(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", default="user_data/reports")
    parser.add_argument("--risk-policy", default="user_data/risk_policy.json")
    parser.add_argument("--output", default="user_data/reports/live_readiness.json")
    args = parser.parse_args()
    reports = Path(args.reports_dir)
    report = build_readiness(
        load_object(reports / "forward_monitor_latest.json"),
        load_object(reports / "forward_monitor_decision.json"),
        load_object(reports / "execution_stress_report.json"),
        load_object(Path(args.risk_policy)),
    )
    write_report(Path(args.output), report)
    print(json.dumps({"qualification_status": report["qualification_status"], "live_trading_authorized": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
