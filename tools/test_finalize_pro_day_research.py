from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import finalize_pro_day_research as finalizer


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


class BlockedFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.audit = root / finalizer.EXPECTED_PATHS["audit"]
        self.plan = root / finalizer.EXPECTED_PATHS["plan"]
        self.strategy = root / finalizer.EXPECTED_PATHS["strategy"]
        self.config = root / finalizer.EXPECTED_PATHS["config"]
        self.risk = root / finalizer.EXPECTED_PATHS["risk_policy"]
        self.output = root / finalizer.DEFAULT_OUTPUT
        for path in (self.plan, self.strategy):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text(
            "# ProDayTraderV1\nLOCKED_BEFORE_FIRST_PRO_DAY_PNL_RUN\n"
            "DATA_BLOCKED before PnL\n2021-01-01 through 2026-08-01\n",
            encoding="utf-8",
        )
        self.strategy.write_text(
            """class ProDayTraderV1:
    timeframe = "5m"
    can_short = True
    position_adjustment_enable = False
    startup_candle_count = 3199

    def informative_pairs(self):
        return ["15m", "1h", "4h"]

    def leverage(self, *args, **kwargs):
        return 1.0
""",
            encoding="utf-8",
        )
        self.config_payload = {
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "dry_run": True,
            "max_open_trades": 2,
            "stake_currency": "USDT",
            "stake_amount": 100,
            "dry_run_wallet": 1000,
            "timeframe": "5m",
            "fee": 0.0005,
            "exchange": {
                "pair_whitelist": list(finalizer.PAIRS),
                "pair_blacklist": [],
                "key": "",
                "secret": "",
            },
            "pro_day_research": {
                "informative_timeframes": ["15m", "1h", "4h"],
                "timerange": "20210101-20260801",
                "leverage": 1.0,
            },
        }
        _json(self.config, self.config_payload)
        _json(self.risk, {
            "limits": {
                "maximum_daily_realized_loss_pct": 2.0,
                "maximum_weekly_realized_loss_pct": 5.0,
                "maximum_wallet_drawdown_pct": 10.0,
                "maximum_total_open_stake_pct": 20.0,
                "maximum_open_trades": 2,
            },
            "live_launch": {
                "authorized": False,
                "requires_human_authorization": True,
                "requires_trade_only_api_key": True,
                "requires_withdrawals_disabled": True,
                "maximum_leverage": 1.0,
                "margin_mode": "isolated",
            },
        })
        self.data_paths: dict[tuple[str, str], Path] = {}
        data_rows = []
        for pair in finalizer.PAIRS:
            for timeframe in finalizer.TIMEFRAMES:
                path = (
                    root / "user_data" / "data" / "binance" / "futures"
                    / f"{finalizer.PAIR_STEMS[pair]}-{timeframe}-futures.feather"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"native:{pair}:{timeframe}".encode())
                self.data_paths[(pair, timeframe)] = path
                data_rows.append({
                    "pair": pair,
                    "timeframe": timeframe,
                    "path": path.relative_to(root).as_posix(),
                    "filename": path.name,
                    "exists": True,
                    "bytes": path.stat().st_size,
                    "sha256": finalizer.sha256_file(path),
                    "status": "PASS",
                })
        split_rows = [
            {"split": split, "pair": pair, "timeframe": timeframe, "status": "PASS"}
            for split in finalizer.SPLITS
            for pair in finalizer.PAIRS
            for timeframe in finalizer.TIMEFRAMES
        ]
        reconciliation_rows = [
            {
                "split": split,
                "pair": pair,
                "timeframe": timeframe,
                "status": (
                    "FAIL"
                    if (split, pair, timeframe) == ("TRAIN", finalizer.PAIRS[0], "15m")
                    else "PASS"
                ),
            }
            for split in finalizer.SPLITS
            for pair in finalizer.PAIRS
            for timeframe in finalizer.INFORMATIVE_TIMEFRAMES
        ]
        self.audit_payload = {
            "schema_version": "1.0",
            "status": "DATA_BLOCKED",
            "decision": "DATA_BLOCKED",
            "candidate": finalizer.CANDIDATE,
            "pnl_evaluated": False,
            "live_trading_authorized": False,
            "required_file_count": 12,
            "expected_pairs": list(finalizer.PAIRS),
            "expected_timeframes": list(finalizer.TIMEFRAMES),
            "thresholds": dict(finalizer.EXPECTED_THRESHOLDS),
            "windows": finalizer.EXPECTED_WINDOWS,
            "data_files": data_rows,
            "split_checks": split_rows,
            "reconciliation_checks": reconciliation_rows,
            "failures": [{
                "severity": "CRITICAL",
                "code": "TIMEFRAME_RECONCILIATION_FAILED",
                "split": "TRAIN",
                "pair": finalizer.PAIRS[0],
                "timeframe": "15m",
                "detail": "mismatch_days_pct=0.25, compared_days=100",
            }],
            "summary": {
                "files_passed": 12,
                "files_total": 12,
                "split_checks_passed": 36,
                "split_checks_total": 36,
                "reconciliation_checks_passed": 26,
                "reconciliation_checks_total": 27,
                "failure_count": 1,
            },
        }
        self.rewrite_audit()

    def rewrite_audit(self) -> None:
        _json(self.audit, self.audit_payload)

    def build(self) -> dict:
        return finalizer.build_final_decision(
            root=self.root,
            audit_path=self.audit,
            plan_path=self.plan,
            strategy_path=self.strategy,
            config_path=self.config,
            risk_policy_path=self.risk,
            output_path=self.output,
        )


class FinalizeProDayResearchTests(unittest.TestCase):
    def test_writes_deterministic_terminal_rejection_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            decision = fixture.build()
            created = finalizer.write_terminal_decision(fixture.output, decision)
            first = fixture.output.read_bytes()
            repeated = finalizer.write_terminal_decision(fixture.output, fixture.build())
            self.assertEqual(first, fixture.output.read_bytes())
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(decision["decision"], "REJECT_PRO_DAY_TRADER")
        self.assertEqual(decision["performance_status"], "NOT_RUN_BY_LOCKED_DATA_GATE")
        self.assertFalse(decision["pnl_evaluated"])
        self.assertFalse(decision["live_trading_authorized"])
        self.assertFalse(decision["dry_run_deployment_authorized"])
        self.assertEqual(decision["data_gate"]["critical_failure_count"], 1)
        encoded = finalizer.encoded_json(decision).decode()
        self.assertNotIn("mtime", encoded.lower())
        self.assertNotIn("generated_at", encoded.lower())

    def test_cli_creates_only_the_locked_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            exit_code = finalizer.main([
                "--project-root", str(fixture.root),
                "--audit", str(fixture.audit),
                "--plan", str(fixture.plan),
                "--strategy", str(fixture.strategy),
                "--config", str(fixture.config),
                "--risk-policy", str(fixture.risk),
            ])
            stored = json.loads(fixture.output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(stored["research_status"], "TERMINAL_DATA_BLOCKED")
        self.assertFalse(stored["deployment_performed"])

    def test_rejects_stale_or_tampered_data_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            fixture.data_paths[(finalizer.PAIRS[0], "4h")].write_bytes(b"changed after audit")
            with self.assertRaisesRegex(finalizer.FinalizeError, "Stale or tampered audit hash"):
                fixture.build()

    def test_rejects_invalid_hash_schema_and_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            fixture.audit_payload["data_files"][0]["sha256"] = "not-a-hash"
            fixture.rewrite_audit()
            with self.assertRaisesRegex(finalizer.FinalizeError, "sha256 is invalid"):
                fixture.build()
            fixture.audit.write_text('{"status":"DATA_BLOCKED","status":"PASS"}', encoding="utf-8")
            with self.assertRaisesRegex(finalizer.FinalizeError, "duplicate key"):
                finalizer.load_json_object(fixture.audit, "audit")

    def test_requires_data_blocked_no_pnl_and_critical_failures(self) -> None:
        mutations = (
            ("status", "PASS", "terminal DATA_BLOCKED"),
            ("pnl_evaluated", True, "pnl_evaluated=false"),
        )
        for key, value, message in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                fixture = BlockedFixture(Path(directory))
                fixture.audit_payload[key] = value
                fixture.rewrite_audit()
                with self.assertRaisesRegex(finalizer.FinalizeError, message):
                    fixture.build()
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            fixture.audit_payload["failures"] = []
            fixture.audit_payload["summary"]["failure_count"] = 0
            fixture.rewrite_audit()
            with self.assertRaisesRegex(finalizer.FinalizeError, "critical failures"):
                fixture.build()

    def test_rejects_inconsistent_summary_or_failure_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            fixture.audit_payload["summary"]["reconciliation_checks_passed"] = 27
            fixture.rewrite_audit()
            with self.assertRaisesRegex(finalizer.FinalizeError, "summary.reconciliation_checks_passed"):
                fixture.build()
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            fixture.audit_payload["reconciliation_checks"][0]["status"] = "PASS"
            fixture.rewrite_audit()
            with self.assertRaisesRegex(finalizer.FinalizeError, "matching failed reconciliation"):
                fixture.build()

    def test_rejects_existing_freeze_manifest_or_proday_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            manifest = fixture.root / "user_data" / "reports" / "pro_day" / "research_freeze_manifest.json"
            _json(manifest, {"status": "RESEARCH_FROZEN"})
            with self.assertRaisesRegex(finalizer.FinalizeError, "manifest exists"):
                fixture.build()
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            artifact = fixture.root / "user_data" / "backtest_results" / "pro_day_train.zip"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"not-opened-pnl-evidence")
            with self.assertRaisesRegex(finalizer.FinalizeError, "backtest ZIP exists"):
                fixture.build()

    def test_rejects_semantically_tampered_locked_input_and_divergent_terminal_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            fixture.config_payload["dry_run"] = False
            _json(fixture.config, fixture.config_payload)
            with self.assertRaisesRegex(finalizer.FinalizeError, "semantic validation failed"):
                fixture.build()
        with tempfile.TemporaryDirectory() as directory:
            fixture = BlockedFixture(Path(directory))
            decision = fixture.build()
            fixture.output.parent.mkdir(parents=True, exist_ok=True)
            fixture.output.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(finalizer.FinalizeError, "refusing to overwrite"):
                finalizer.write_terminal_decision(fixture.output, decision)


if __name__ == "__main__":
    unittest.main()
