#!/usr/bin/env python3
"""Require exact trade-stream parity between parent and audit variant."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


FIELDS = (
    "pair", "is_short", "open_timestamp", "close_timestamp", "open_rate", "close_rate",
    "stake_amount", "profit_abs", "profit_ratio", "fee_open", "fee_close", "exit_reason",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, strategy: str) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        if archive.testzip() is not None or len(names) != 1:
            raise ValueError("archive integrity/inventory failure")
        return json.loads(archive.read(names[0]))["strategy"][strategy]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parent = load(args.parent, "ProfitMaxDailyCrossStop20")
    audit = load(args.audit, "ProfitMaxDailyCrossStop20Audit")
    parent_rows = [tuple(trade.get(field) for field in FIELDS) for trade in parent["trades"]]
    audit_rows = [tuple(trade.get(field) for field in FIELDS) for trade in audit["trades"]]
    metrics = ("total_trades", "profit_total_abs", "profit_factor", "max_drawdown_account", "trades_per_day")
    differences = [key for key in metrics if parent.get(key) != audit.get(key)]
    passed = parent_rows == audit_rows and not differences
    payload = {
        "schema_version": "1.0", "status": "PASS" if passed else "FAIL",
        "exact_trade_rows": parent_rows == audit_rows, "metric_differences": differences,
        "parent_trades": len(parent_rows), "audit_trades": len(audit_rows),
        "parent_sha256": digest(args.parent), "audit_sha256": digest(args.audit),
        "validation_revealed": False, "live_trading_authorized": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

