import json
import tempfile
import unittest
from pathlib import Path

import freeze_pro_day_research as freeze


class ProDayResearchFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir(parents=True)
        (self.root / "user_data" / "strategies").mkdir(parents=True)
        (self.root / "user_data" / "reports" / "pro_day").mkdir(parents=True)
        (self.root / "user_data" / "data" / "binance" / "futures").mkdir(parents=True)
        (self.root / "user_data" / "backtest_results").mkdir(parents=True)

        self.plan = self.root / freeze.DEFAULT_PLAN
        self.strategy = self.root / freeze.DEFAULT_STRATEGY
        self.config = self.root / freeze.DEFAULT_CONFIG
        self.risk = self.root / freeze.DEFAULT_RISK_POLICY
        self.audit = self.root / freeze.DEFAULT_DATA_QUALITY
        self.output = self.root / freeze.DEFAULT_OUTPUT

        self.plan.write_text(
            "\n".join(
                (
                    "# ProDayTraderV1 locked plan",
                    "LOCKED_BEFORE_FIRST_PRO_DAY_PNL_RUN",
                    "DATA_BLOCKED before PnL",
                    "TRAIN starts 2021-01-01",
                    "canonical ends 2026-08-01",
                )
            ),
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
        self.valid_config = {
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "dry_run": True,
            "max_open_trades": 2,
            "stake_currency": "USDT",
            "stake_amount": "unlimited",
            "dry_run_wallet": 1000,
            "timeframe": "5m",
            "fee": 0.0005,
            "exchange": {
                "pair_whitelist": list(freeze.PAIRS),
                "pair_blacklist": [],
            },
            "pro_day_research": {
                "informative_timeframes": list(freeze.INFORMATIVE_TIMEFRAMES),
                "timerange": freeze.CANONICAL_TIMERANGE,
                "leverage": 1.0,
            },
        }
        self.config.write_text(json.dumps(self.valid_config), encoding="utf-8")
        self.risk.write_text(
            json.dumps(
                {
                    "limits": dict(freeze.EXPECTED_RISK_LIMITS),
                    "live_launch": {
                        "authorized": False,
                        "requires_human_authorization": True,
                        "requires_trade_only_api_key": True,
                        "requires_withdrawals_disabled": True,
                        "maximum_leverage": 1.0,
                        "margin_mode": "isolated",
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.root / "docker-compose.yml").write_text(
            "services:\n  freqtrade:\n"
            "    image: freqtradeorg/freqtrade:2026.7@sha256:"
            + "a" * 64
            + "\n",
            encoding="utf-8",
        )
        self.data_paths: dict[tuple[str, str], Path] = {}
        rows = []
        for pair in freeze.PAIRS:
            for timeframe in freeze.TIMEFRAMES:
                filename = f"{pair.split('/')[0]}_USDT_USDT-{timeframe}-futures.feather"
                path = self.root / "user_data" / "data" / "binance" / "futures" / filename
                path.write_bytes(f"native:{pair}:{timeframe}".encode("utf-8"))
                self.data_paths[(pair, timeframe)] = path
                item = freeze.descriptor(path, self.root)
                rows.append(
                    {
                        "pair": pair,
                        "timeframe": timeframe,
                        **item,
                        "exists": True,
                        "status": "PASS",
                    }
                )
        self.valid_audit = {
            "schema_version": "1.0",
            "status": "PASS",
            "decision": "READY_FOR_RESEARCH_FREEZE",
            "pnl_evaluated": False,
            "live_trading_authorized": False,
            "expected_pairs": list(freeze.PAIRS),
            "expected_timeframes": list(freeze.TIMEFRAMES),
            "thresholds": {
                "minimum_coverage_pct": 99.95,
                "maximum_undocumented_gap_candles": 3,
                "maximum_mismatch_days_pct": 0.20,
                "reconciliation_relative_tolerance": 1e-9,
                "reconciliation_absolute_tolerance": 1e-8,
            },
            "data_files": rows,
        }
        self.audit.write_text(json.dumps(self.valid_audit), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _freeze(self, *, write_output: bool = False) -> dict:
        return freeze.freeze_research(
            project_root=self.root,
            lock_time_utc="2026-08-11T10:00:00Z",
            write_output=write_output,
        )

    def test_creates_hashed_pre_pnl_manifest_with_explicit_planned_artifacts(self) -> None:
        # Existing garbage result files must not be opened or parsed by the freeze.
        for relative in freeze.DEFAULT_ARTIFACTS.values():
            (self.root / relative).write_bytes(b"not a ZIP and not PnL evidence")

        manifest = self._freeze(write_output=True)

        self.assertEqual(manifest["status"], "RESEARCH_FROZEN")
        self.assertEqual(manifest["qualification_state"], "NOT_STARTED_NO_PNL_PARSED")
        self.assertFalse(manifest["pnl_parsed"])
        self.assertFalse(manifest["live_trading_authorized"])
        self.assertEqual(set(manifest["files"]), {"plan", "strategy", "config", "risk_policy", "data_quality"})
        self.assertEqual(
            manifest["files"]["strategy"]["sha256"],
            manifest["inputs"]["strategy"]["sha256"],
        )
        self.assertEqual(len(manifest["data_files"]), 12)
        self.assertEqual(set(manifest["artifacts"]), set(freeze.ARTIFACT_KEYS))
        for artifact in manifest["artifacts"].values():
            self.assertEqual(artifact["status"], "PLANNED_NOT_RUN")
            self.assertIsNone(artifact["sha256"])
            self.assertTrue(artifact["filename"].endswith(".zip"))
        stored = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(stored, manifest)

    def test_refuses_to_overwrite_immutable_manifest(self) -> None:
        self._freeze(write_output=True)

        with self.assertRaisesRegex(freeze.FreezeError, "overwrite immutable"):
            self._freeze(write_output=True)

    def test_refuses_failed_or_stale_data_audit(self) -> None:
        failed = dict(self.valid_audit)
        failed["status"] = "DATA_BLOCKED"
        failed["decision"] = "DATA_BLOCKED"
        self.audit.write_text(json.dumps(failed), encoding="utf-8")
        with self.assertRaisesRegex(freeze.FreezeError, "not PASS"):
            self._freeze()

        self.audit.write_text(json.dumps(self.valid_audit), encoding="utf-8")
        self.data_paths[(freeze.PAIRS[0], "4h")].write_bytes(b"changed after audit")
        with self.assertRaisesRegex(freeze.FreezeError, "changed after"):
            self._freeze()

    def test_refuses_secret_bearing_or_semantically_unlocked_config(self) -> None:
        secret_config = json.loads(json.dumps(self.valid_config))
        # Freqtrade calls the API-key field simply ``exchange.key``; it must be
        # rejected even without a simultaneously populated ``secret`` field.
        secret_config["exchange"]["key"] = "MUST_NOT_APPEAR_IN_ERROR"
        self.config.write_text(json.dumps(secret_config), encoding="utf-8")
        with self.assertRaises(freeze.FreezeError) as context:
            self._freeze()
        self.assertIn("exchange credential fields", str(context.exception))
        self.assertNotIn("MUST_NOT_APPEAR", str(context.exception))

        unlocked = json.loads(json.dumps(self.valid_config))
        unlocked["exchange"]["pair_whitelist"].pop()
        self.config.write_text(json.dumps(unlocked), encoding="utf-8")
        with self.assertRaisesRegex(freeze.FreezeError, "exact locked 3-pair universe"):
            self._freeze()


if __name__ == "__main__":
    unittest.main()
