from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import evaluate_pro_day_trader as evaluator


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _record(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": evaluator.sha256_file(path),
    }


def _trade(
    opened: str,
    profit: float,
    *,
    pair: str = evaluator.PAIRS[0],
    short: bool = False,
) -> dict[str, object]:
    open_time = evaluator.parse_utc(opened, "fixture.open")
    close_time = open_time + timedelta(hours=1)
    if short:
        tag = "breakout_retest_short_r2l2s1t2p1_total8"
    else:
        tag = "trend_pullback_long_r2l1s1t2p1_total7"
    return {
        "pair": pair,
        "open_timestamp": int(open_time.timestamp() * 1000),
        "close_timestamp": int(close_time.timestamp() * 1000),
        "profit_abs": profit,
        "profit_ratio": profit / 100.0,
        "is_short": short,
        "is_open": False,
        "enter_tag": tag,
        "amount": 1.0,
        "open_rate": 100.0,
        "close_rate": 101.0,
        "funding_fees": 0.0,
        "leverage": 1.0,
    }


def _pf(profits: list[float]) -> float | None:
    gross_positive = math.fsum(value for value in profits if value > 0)
    gross_loss = abs(math.fsum(value for value in profits if value < 0))
    # Freqtrade's serialized source sentinel is 0.0 when gross loss is zero.
    return gross_positive / gross_loss if gross_loss else 0.0


def _pair_row(pair: str, trades: list[dict[str, object]], starting: float) -> dict[str, object]:
    profits = [float(trade["profit_abs"]) for trade in trades]
    return {
        "key": pair,
        "trades": len(trades),
        "wins": sum(value > 0 for value in profits),
        "losses": sum(value < 0 for value in profits),
        "draws": sum(value == 0 for value in profits),
        "profit_total_abs": math.fsum(profits),
        "profit_total": math.fsum(profits) / starting,
        "profit_factor": _pf(profits),
    }


def _strategy_payload(label: str, trades: list[dict[str, object]]) -> dict[str, object]:
    starting = 1000.0
    profits = [float(trade["profit_abs"]) for trade in trades]
    pair_rows = [
        _pair_row(pair, [trade for trade in trades if trade["pair"] == pair], starting)
        for pair in evaluator.PAIRS
    ]
    return {
        "strategy_name": evaluator.STRATEGY,
        "timerange": evaluator.EXPECTED_TIMERANGES[label],
        "timeframe": "5m",
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "max_open_trades": 2,
        "enable_protections": True,
        "pairlist": list(evaluator.PAIRS),
        "starting_balance": starting,
        "total_trades": len(trades),
        "wins": sum(value > 0 for value in profits),
        "losses": sum(value < 0 for value in profits),
        "draws": sum(value == 0 for value in profits),
        "trade_count_long": sum(not bool(trade["is_short"]) for trade in trades),
        "trade_count_short": sum(bool(trade["is_short"]) for trade in trades),
        "profit_total_abs": math.fsum(profits),
        "profit_total": math.fsum(profits) / starting,
        "profit_factor": _pf(profits),
        "profit_total_long_abs": math.fsum(
            float(trade["profit_abs"]) for trade in trades if not bool(trade["is_short"])
        ),
        "profit_total_short_abs": math.fsum(
            float(trade["profit_abs"]) for trade in trades if bool(trade["is_short"])
        ),
        "max_drawdown_account": 0.02,
        "results_per_pair": pair_rows,
        "rejected_signals": 17,
        "trades": trades,
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.strategy_source = b"class ProDayTraderV1:\n    pass\n"
        self.config = {
            "dry_run": True,
            "dry_run_wallet": 1000,
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "stake_currency": "USDT",
            "stake_amount": "unlimited",
            "max_open_trades": 2,
            "timeframe": "5m",
            "fee": 0.0005,
            "exchange": {
                "name": "binance",
                "key": "",
                "secret": "",
                "pair_whitelist": list(evaluator.PAIRS),
                "pair_blacklist": [],
            },
            "pairlists": [{"method": "StaticPairList"}],
        }
        self.plan = root / "docs" / "pro_day_trader_v1_locked_plan.md"
        self.strategy = root / "user_data" / "strategies" / "ProDayTraderV1.py"
        self.config_path = root / "user_data" / "config-pro-day-research.json"
        self.risk = root / "docs" / "risk.md"
        self.audit = root / "user_data" / "reports" / "pro_day" / "data_quality.json"
        for path in (self.plan, self.strategy, self.risk):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text("locked plan\n", encoding="utf-8")
        self.strategy.write_bytes(self.strategy_source)
        self.risk.write_text("locked risk\n", encoding="utf-8")
        _write_json(self.config_path, self.config)
        _write_json(self.audit, {"status": "PASS"})
        self.data_records = self._data_files()
        self.artifact_paths, self.artifact_records = self._artifacts()
        self.manifest = root / "user_data" / "reports" / "pro_day" / "manifest.json"
        self.payload = self._manifest_payload()
        _write_json(self.manifest, self.payload)

    def _data_files(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        data_root = self.root / "user_data" / "data" / "binance" / "futures"
        for pair in evaluator.PAIRS:
            for timeframe in evaluator.TIMEFRAMES:
                safe_pair = pair.replace("/", "_").replace(":", "_")
                path = data_root / f"{safe_pair}-{timeframe}.feather"
                path.parent.mkdir(parents=True, exist_ok=True)
                if pair == "BTC/USDT:USDT" and timeframe == "4h":
                    dates = pd.date_range("2020-01-01", "2026-08-02", freq="4h", tz="UTC")
                    close = pd.Series([100.0 + index * 0.01 for index in range(len(dates))])
                    pd.DataFrame({
                        "date": dates,
                        "open": close - 0.05,
                        "high": close + 0.10,
                        "low": close - 0.10,
                        "close": close,
                        "volume": 1.0,
                    }).to_feather(path)
                else:
                    path.write_bytes(b"fixture-verified-by-hash")
                record = _record(self.root, path)
                record.update({"pair": pair, "timeframe": timeframe})
                records.append(record)
        return records

    def _wallet_bytes(self) -> bytes:
        dates = pd.date_range("2021-01-01", "2026-08-01", freq="7D", tz="UTC")
        balances = [1000.0 + (index % 17) * 0.25 for index in range(len(dates))]
        buffer = io.BytesIO()
        pd.DataFrame({
            "date": dates,
            "currency": "USDT",
            "total_quote": balances,
        }).to_feather(buffer)
        return buffer.getvalue()

    def _artifact(self, label: str, trades: list[dict[str, object]]) -> tuple[Path, dict[str, object]]:
        path = self.root / "artifacts" / f"{label}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        result_name = f"{label}.json"
        config_name = f"{label}_config.json"
        strategy_name = f"{label}_{evaluator.STRATEGY}.py"
        result_bytes = json.dumps(
            {"strategy": {evaluator.STRATEGY: _strategy_payload(label, trades)}},
            sort_keys=True,
        ).encode()
        config_bytes = json.dumps(self.config, sort_keys=True).encode()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(result_name, result_bytes)
            bundle.writestr(config_name, config_bytes)
            bundle.writestr(strategy_name, self.strategy_source)
            if label == "canonical":
                bundle.writestr(f"{label}_{evaluator.STRATEGY}_wallet.feather", self._wallet_bytes())
        record: dict[str, object] = {
            **_record(self.root, path),
            "status": "READY",
            "sanitized": True,
            "members": {
                "result": {"filename": result_name, "sha256": evaluator.sha256_bytes(result_bytes)},
                "config": {"filename": config_name, "sha256": evaluator.sha256_bytes(config_bytes)},
                "strategy": {"filename": strategy_name, "sha256": evaluator.sha256_bytes(self.strategy_source)},
            },
        }
        return path, record

    def _artifacts(self) -> tuple[dict[str, Path], dict[str, dict[str, object]]]:
        split_trades = {
            "train": [_trade("2022-06-01T00:00:00Z", 10.0)],
            "validation": [_trade("2024-06-01T00:00:00Z", -2.0, pair=evaluator.PAIRS[1], short=True)],
            "current_partial": [_trade("2026-06-01T00:00:00Z", 8.0, pair=evaluator.PAIRS[2])],
        }
        split_trades["canonical"] = [
            *split_trades["train"], *split_trades["validation"], *split_trades["current_partial"]
        ]
        paths: dict[str, Path] = {}
        records: dict[str, dict[str, object]] = {}
        for label in evaluator.ARTIFACT_LABELS:
            paths[label], records[label] = self._artifact(label, split_trades[label])
        return paths, records

    def _manifest_payload(self) -> dict[str, object]:
        inputs = {
            "plan": _record(self.root, self.plan),
            "strategy": _record(self.root, self.strategy),
            "research_config": _record(self.root, self.config_path),
            "risk_policy": _record(self.root, self.risk),
            "data_audit": _record(self.root, self.audit),
        }
        return {
            "schema_version": "1.0",
            "status": "RESEARCH_FROZEN",
            "candidate": evaluator.STRATEGY,
            "qualification_state": "ARTIFACTS_SANITIZED",
            "pnl_parsed": False,
            "live_trading_authorized": False,
            "inputs": inputs,
            "data_files": self.data_records,
            "artifacts": self.artifact_records,
            "qualification_evidence": {
                "lookahead": {
                    "baseline_signals": 100,
                    "has_bias": False,
                    "biased_entry_signals": 0,
                    "biased_exit_signals": 0,
                    "biased_indicators": 0,
                    "represented_sides": ["long", "short"],
                    "represented_setups": list(evaluator.SETUPS),
                },
                "recursive": {
                    "candidate_counts": list(evaluator.RECURSIVE_COUNTS),
                    "startup_candle_count": evaluator.STARTUP_CANDLE_COUNT,
                    "signal_differences": 0,
                    "indicator_variance_pct": {"ema_200": 0.005, "adx": 0.0},
                },
            },
        }

    def rewrite_manifest(self) -> None:
        _write_json(self.manifest, self.payload)


class StrictParsingTests(unittest.TestCase):
    def test_finite_number_rejects_bool_string_nan_and_infinity(self) -> None:
        for value in (True, "1.0", float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(evaluator.EvaluationError):
                evaluator.finite_number(value, "value")
        self.assertEqual(evaluator.finite_number(1.25, "value"), 1.25)

    def test_json_rejects_duplicate_keys_and_nonfinite_constants(self) -> None:
        with self.assertRaises(evaluator.EvaluationError):
            evaluator.load_json_bytes(b'{"x":1,"x":2}', "duplicate")
        with self.assertRaises(evaluator.EvaluationError):
            evaluator.load_json_bytes(b'{"x":NaN}', "nan")

    def test_explanatory_tag_must_match_side_scores_and_one_x(self) -> None:
        raw = _trade("2024-01-01T00:00:00Z", 1.0)
        raw["leverage"] = 2.0
        with self.assertRaisesRegex(evaluator.EvaluationError, "1x"):
            evaluator.parse_trade(raw, 0)
        raw = _trade("2024-01-01T00:00:00Z", 1.0)
        raw["enter_tag"] = "trend_pullback_short_r2l2s1t2p1_total8"
        with self.assertRaisesRegex(evaluator.EvaluationError, "disagrees"):
            evaluator.parse_trade(raw, 0)


class RegimeAndStressTests(unittest.TestCase):
    def test_regime_assignment_uses_last_closed_candle_at_entry(self) -> None:
        base = evaluator.parse_trade(_trade("2024-01-01T07:59:59Z", 1.0), 0)
        available = [
            datetime(2024, 1, 1, 4, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 8, tzinfo=timezone.utc),
        ]
        before = evaluator.assign_regimes([base], available, ["bull", "bear"])[0]
        at_close = evaluator.assign_regimes(
            [replace(base, open_time=datetime(2024, 1, 1, 8, tzinfo=timezone.utc))],
            available,
            ["bull", "bear"],
        )[0]
        self.assertEqual(before.regime, "bull")
        self.assertEqual(at_close.regime, "bear")

    def test_stress_is_incremental_round_trip_and_funding_cost(self) -> None:
        raw = _trade("2024-01-01T00:00:00Z", 10.0)
        raw["funding_fees"] = -2.0
        trade = evaluator.parse_trade(raw, 0)
        stressed = evaluator.stress_profit(trade, evaluator.STRESS_SCENARIOS["moderate"])
        expected = 10.0 - (7.0 / 10_000 * 201.0) - (2.0 / 10_000 * 100.0) - 1.0
        self.assertAlmostEqual(stressed, expected, places=12)

    def test_realized_drawdown_is_peak_relative_not_start_wallet_alias(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        value = evaluator.realized_drawdown_pct(
            [(start, 100.0), (start + timedelta(days=1), -55.0)], 1000.0
        )
        self.assertAlmostEqual(value, 5.0)


class ManifestArchiveIntegrationTests(unittest.TestCase):
    def test_valid_hashed_sanitized_fixture_is_technical_pass_but_performance_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            report = evaluator.build_report(fixture.manifest, fixture.root.resolve(), fixture.artifact_paths)
        self.assertTrue(report["technical_validation"]["passed"])
        self.assertEqual(report["decision"], "KEEP_OFFLINE_RESEARCH")
        scopes = {row["scope"] for row in report["metrics"]}
        self.assertTrue({"overall", "period", "year", "quarter", "pair", "direction", "setup", "regime", "stress"}.issubset(scopes))
        overall = next(row for row in report["metrics"] if row["scope"] == "overall")
        self.assertEqual(overall["source_max_drawdown_account_pct"], 2.0)
        self.assertNotEqual(
            overall["source_max_drawdown_account_pct"],
            overall["realized_closed_trade_drawdown_pct"],
        )
        serialized = json.dumps(report, allow_nan=False, sort_keys=True)
        self.assertNotIn("mtime", serialized.lower())
        self.assertNotIn("generated_at", serialized.lower())

    def test_locked_gates_and_decision_can_reach_approve_only_when_every_section_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            report = evaluator.build_report(fixture.manifest, fixture.root.resolve(), fixture.artifact_paths)
        rows = [dict(row) for row in report["metrics"]]
        for row in rows:
            row.update({
                "trades": 1000,
                "net_profit_abs": 100.0,
                "return_pct": 10.0,
                "profit_factor": 2.0,
                "realized_closed_trade_drawdown_pct": 1.0,
                "return_to_drawdown": 10.0,
            })
            if row.get("source_max_drawdown_account_pct") is not None:
                row["source_max_drawdown_account_pct"] = 1.0
            if row.get("continuous_wallet_drawdown_pct") is not None:
                row["continuous_wallet_drawdown_pct"] = 1.0
        gates = evaluator.evaluate_locked_gates(rows, {
            "positive_pairs": 3,
            "largest_positive_pair_contribution": 0.40,
            "largest_winning_trade_contribution": 0.01,
        })
        self.assertTrue(all(gate["passed"] for gate in gates))
        sections = {
            section: all(gate["passed"] for gate in gates if gate["section"] == section)
            for section in ("train", "validation", "current", "stability", "regime", "stress")
        }
        self.assertEqual(evaluator.locked_decision(True, sections), "APPROVE_SEPARATE_DRY_RUN")
        sections["stress"] = False
        self.assertEqual(evaluator.locked_decision(True, sections), "KEEP_OFFLINE_RESEARCH")
        self.assertEqual(evaluator.locked_decision(False, sections), "REJECT_PRO_DAY_TRADER")

    def test_missing_bias_and_recursion_evidence_forces_technical_reject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.payload.pop("qualification_evidence")
            fixture.rewrite_manifest()
            report = evaluator.build_report(fixture.manifest, fixture.root.resolve(), fixture.artifact_paths)
        self.assertFalse(report["technical_validation"]["passed"])
        self.assertEqual(report["decision"], "REJECT_PRO_DAY_TRADER")

    def test_manifest_planned_record_without_hash_is_rejected_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            record = fixture.payload["artifacts"]["canonical"]  # type: ignore[index]
            record["status"] = "PLANNED_NOT_RUN"
            record["sha256"] = None
            fixture.rewrite_manifest()
            with self.assertRaisesRegex(evaluator.EvaluationError, "PLANNED_NOT_RUN"):
                evaluator.build_report(fixture.manifest, fixture.root.resolve(), fixture.artifact_paths)

    def test_zip_hash_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            with fixture.artifact_paths["canonical"].open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaisesRegex(evaluator.EvaluationError, "ZIP SHA256 mismatch"):
                evaluator.build_report(fixture.manifest, fixture.root.resolve(), fixture.artifact_paths)

    def test_raw_sensitive_config_is_rejected_even_when_manifest_hashes_match(self) -> None:
        config = {"exchange": {"key": "raw-secret"}}
        with self.assertRaisesRegex(evaluator.EvaluationError, "non-redacted sensitive"):
            evaluator.assert_sanitized(config)

    def test_member_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            record = fixture.payload["artifacts"]["validation"]  # type: ignore[index]
            record["members"]["result"]["sha256"] = "0" * 64  # type: ignore[index]
            fixture.rewrite_manifest()
            with self.assertRaisesRegex(evaluator.EvaluationError, "result member SHA256 mismatch"):
                evaluator.build_report(fixture.manifest, fixture.root.resolve(), fixture.artifact_paths)

    def test_register_artifact_sanitizes_hashes_and_atomically_updates_planned_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            label = "validation"
            path = fixture.artifact_paths[label]
            with zipfile.ZipFile(path, "r") as source:
                members = {name: source.read(name) for name in source.namelist()}
            config_name = next(name for name in members if name.endswith("_config.json"))
            raw_config = dict(fixture.config)
            raw_config["exchange"] = dict(raw_config["exchange"])
            raw_config["exchange"]["key"] = "must-not-survive"
            members[config_name] = json.dumps(raw_config, sort_keys=True).encode()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
                for name, payload in members.items():
                    target.writestr(name, payload)
            fixture.payload["artifacts"][label] = {  # type: ignore[index]
                "path": path.relative_to(fixture.root).as_posix(),
                "filename": path.name,
                "sha256": None,
                "status": "PLANNED_NOT_RUN",
            }
            fixture.payload["qualification_state"] = "NOT_STARTED_NO_PNL_PARSED"
            fixture.rewrite_manifest()

            exit_code = evaluator.main([
                "register-artifact",
                "--workspace", str(fixture.root),
                "--manifest", str(fixture.manifest),
                "--artifact", f"{label}={path}",
            ])
            first_manifest = fixture.manifest.read_bytes()
            repeated = evaluator.register_artifact(
                fixture.manifest,
                fixture.root.resolve(),
                label,
                path.resolve(),
            )
            self.assertEqual(first_manifest, fixture.manifest.read_bytes())
            updated = json.loads(first_manifest)
            record = updated["artifacts"][label]
            self.assertEqual(record["status"], "READY")
            self.assertTrue(record["sanitized"])
            self.assertEqual(record["sha256"], evaluator.sha256_file(path))
            self.assertEqual(set(record["members"]), {"result", "config", "strategy"})
            with zipfile.ZipFile(path) as bundle:
                sanitized = json.loads(bundle.read(config_name))
            self.assertEqual(sanitized["exchange"]["key"], evaluator.REDACTION)
            self.assertEqual(exit_code, 0)
            self.assertTrue(repeated["idempotent"])

    def test_cli_writes_deterministic_json_and_csv_on_keep_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            json_output = fixture.root / "out" / "decision.json"
            csv_output = fixture.root / "out" / "metrics.csv"
            arguments = [
                "--workspace", str(fixture.root),
                "--manifest", str(fixture.manifest),
                *sum((["--artifact", f"{label}={path}"] for label, path in fixture.artifact_paths.items()), []),
                "--json-output", str(json_output),
                "--csv-output", str(csv_output),
            ]
            exit_code = evaluator.main(arguments)
            first_json = json_output.read_bytes()
            first_csv = csv_output.read_bytes()
            second_exit = evaluator.main(arguments)
            self.assertEqual(first_json, json_output.read_bytes())
            self.assertEqual(first_csv, csv_output.read_bytes())
        self.assertEqual(exit_code, 3)
        self.assertEqual(second_exit, 3)


if __name__ == "__main__":
    unittest.main()
