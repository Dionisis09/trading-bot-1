#!/usr/bin/env python3
"""Reuse exact parity logic for the V2 audit class name."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare_profit_max_daily_audit_parity import FIELDS, digest, load


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parent = load(args.parent, "ProfitMaxDailyCrossStop20")
    audit = load(args.audit, "ProfitMaxDailyCrossStop20AuditV2")
    left = [tuple(trade.get(field) for field in FIELDS) for trade in parent["trades"]]
    right = [tuple(trade.get(field) for field in FIELDS) for trade in audit["trades"]]
    metrics = ("total_trades", "profit_total_abs", "profit_factor", "max_drawdown_account", "trades_per_day")
    differences = [key for key in metrics if parent.get(key) != audit.get(key)]
    passed = left == right and not differences
    payload = {
        "schema_version": "1.0", "status": "PASS" if passed else "FAIL",
        "exact_trade_rows": left == right, "metric_differences": differences,
        "parent_trades": len(left), "audit_trades": len(right),
        "parent_sha256": digest(args.parent), "audit_sha256": digest(args.audit),
        "validation_revealed": False, "live_trading_authorized": False,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

