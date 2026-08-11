import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import monitor_forward_dry_runs as monitor


def closed_trade(
    trade_id: int,
    profit_abs: float,
    profit_ratio: float,
    close_date: str,
    pair: str = "BTC/USDT:USDT",
    is_short: bool = False,
) -> dict:
    return {
        "trade_id": trade_id,
        "is_open": False,
        "pair": pair,
        "close_date": close_date,
        "profit_abs": profit_abs,
        "profit_ratio": profit_ratio,
        "is_short": is_short,
    }


class TradeMetricTests(unittest.TestCase):
    def test_empty_sample_has_no_infinite_or_fake_profit_factor(self) -> None:
        metrics, quality = monitor.compute_trade_metrics([], 1000.0)

        self.assertEqual(metrics["closed_trades"], 0)
        self.assertIsNone(metrics["profit_factor"])
        self.assertIsNone(metrics["win_rate"])
        self.assertIsNone(metrics["return_to_drawdown"])
        self.assertEqual(metrics["return_pct_of_start_wallet"], 0.0)
        self.assertTrue(quality["pass"] if "pass" in quality else quality["required_fields_pass"])

    def test_recomputes_profit_factor_and_chronological_drawdown(self) -> None:
        trades = [
            closed_trade(1, 10.0, 0.10, "2026-01-01T00:00:00Z"),
            closed_trade(2, -5.0, -0.05, "2026-01-02T00:00:00Z", is_short=True),
            closed_trade(3, 2.0, 0.02, "2026-01-03T00:00:00Z", "ETH/USDT:USDT"),
        ]

        metrics, quality = monitor.compute_trade_metrics(trades, 1000.0)

        self.assertEqual(metrics["wins"], 2)
        self.assertEqual(metrics["losses"], 1)
        self.assertAlmostEqual(metrics["net_profit_abs"], 7.0)
        self.assertAlmostEqual(metrics["profit_factor"], 2.4)
        self.assertAlmostEqual(metrics["max_drawdown_abs"], 5.0)
        self.assertAlmostEqual(metrics["max_drawdown_pct_of_start_wallet"], 0.5)
        self.assertAlmostEqual(metrics["return_to_drawdown"], 1.4)
        self.assertEqual(metrics["distinct_pairs"], 2)
        self.assertEqual(metrics["long_trades"], 2)
        self.assertEqual(metrics["short_trades"], 1)
        self.assertTrue(quality["duplicates_pass"])
        self.assertTrue(quality["required_fields_pass"])

    def test_detects_duplicate_ids_and_missing_required_values(self) -> None:
        trades = [
            closed_trade(7, 1.0, 0.01, "2026-01-01T00:00:00Z"),
            {
                "trade_id": 7,
                "is_open": False,
                "pair": "",
                "close_date": None,
                "profit_abs": None,
                "profit_ratio": None,
            },
        ]

        _, quality = monitor.compute_trade_metrics(trades, 1000.0)

        self.assertEqual(quality["duplicate_trade_ids"], ["7"])
        self.assertFalse(quality["duplicates_pass"])
        self.assertFalse(quality["required_fields_pass"])
        self.assertEqual(quality["missing_required_values"]["pair"], 1)
        self.assertEqual(quality["missing_required_values"]["close_time"], 1)
        self.assertEqual(quality["missing_required_values"]["profit_abs"], 1)

    def test_reconciles_api_summary(self) -> None:
        trades = [
            closed_trade(1, 10.0, 0.10, "2026-01-01T00:00:00Z"),
            closed_trade(2, -5.0, -0.05, "2026-01-02T00:00:00Z"),
        ]
        metrics, _ = monitor.compute_trade_metrics(trades, 1000.0)
        api = {
            "trade_count": 2,
            "closed_trade_count": 2,
            "winning_trades": 1,
            "losing_trades": 1,
            "profit_closed_coin": 5.0,
            "profit_factor": 2.0,
        }

        reconciliation = monitor.reconcile_profit_api(api, metrics)

        self.assertTrue(reconciliation["pass"])

    def test_api_reconciliation_counts_breakeven_as_freqtrade_win(self) -> None:
        trades = [
            closed_trade(1, 0.0, 0.0, "2026-01-01T00:00:00Z"),
            closed_trade(2, -1.0, -0.01, "2026-01-02T00:00:00Z"),
        ]
        metrics, _ = monitor.compute_trade_metrics(trades, 1000.0)
        api = {
            "trade_count": 2,
            "closed_trade_count": 2,
            "winning_trades": 1,
            "losing_trades": 1,
            "profit_closed_coin": -1.0,
            "profit_factor": 0.0,
        }

        reconciliation = monitor.reconcile_profit_api(api, metrics)

        self.assertEqual(metrics["breakeven"], 1)
        self.assertTrue(reconciliation["pass"])


class ApiPaginationTests(unittest.TestCase):
    def test_fetches_all_pages_using_total_trades(self) -> None:
        first = {"trades": [{"trade_id": i} for i in range(500)], "total_trades": 501}
        second = {"trades": [{"trade_id": 500}], "total_trades": 501}
        with patch.object(monitor, "api_get_json", side_effect=[first, second]) as mocked:
            trades, total = monitor.fetch_all_trades("http://bot", "user", "secret", 1.0)

        self.assertEqual(total, 501)
        self.assertEqual(len(trades), 501)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(mocked.call_args_list[1].args[-1]["offset"], 500)


class CollectBotTests(unittest.TestCase):
    def test_complete_collection_returns_validated_bot_record(self) -> None:
        observed_at = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
        runtime = {
            "dry_run": True,
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "short_allowed": True,
            "strategy": "Strategy",
            "state": "RUNNING",
            "timeframe": "4h",
        }
        profit = {
            "trade_count": 0,
            "closed_trade_count": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "profit_closed_coin": 0.0,
        }
        expected = {
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "strategy": "Strategy",
            "state": "RUNNING",
            "credential_free": True,
            "starting_wallet": 1000.0,
            "pair_whitelist": ["BTC/USDT:USDT"],
            "stake_amount": 25.0,
        }
        risk_policy = {
            "policy_id": "test",
            "limits": {
                "maximum_daily_realized_loss_pct": 2.0,
                "maximum_weekly_realized_loss_pct": 5.0,
                "maximum_wallet_drawdown_pct": 10.0,
                "maximum_total_open_stake_pct": 20.0,
                "maximum_open_trades": 2,
            },
        }
        market = {
            "all_pairs_fresh": True,
            "maximum_candle_close_age_seconds": 3600.0,
            "pairs_checked": 1,
        }
        with (
            patch.object(
                monitor,
                "api_get_json",
                side_effect=[
                    {"status": "pong"},
                    runtime,
                    {"last_process": observed_at.isoformat(), "bot_start": "start"},
                    profit,
                    {"current": 0},
                ],
            ),
            patch.object(monitor, "fetch_market_data_freshness", return_value=market),
            patch.object(monitor, "fetch_all_trades", return_value=([], 0)),
        ):
            result = monitor.collect_bot(
                "v1",
                "http://bot",
                expected,
                "user",
                "password",
                1.0,
                observed_at,
                risk_policy,
            )

        self.assertEqual(result["status"], "OK")
        self.assertTrue(result["runtime_validation"]["pass"])
        self.assertTrue(result["data_quality"]["pass"])
        self.assertEqual(result["market_data_freshness"]["pairs_checked"], 1)
        self.assertTrue(result["account_risk"]["new_entries_allowed"])


def bot_for_decision(
    *,
    closed: int,
    pairs: int,
    net: float,
    profit_factor: float | None,
    drawdown: float,
    return_to_drawdown: float | None,
    integrity: bool = True,
) -> dict:
    return {
        "status": "OK",
        "runtime_validation": {"pass": integrity},
        "data_quality": {"pass": integrity},
        "metrics": {
            "closed_trades": closed,
            "distinct_pairs": pairs,
            "net_profit_abs": net,
            "profit_factor": profit_factor,
            "max_drawdown_pct_of_start_wallet": drawdown,
            "return_to_drawdown": return_to_drawdown,
        },
    }


class DecisionTests(unittest.TestCase):
    def snapshot(self, days: float, v1: dict, v2r: dict) -> dict:
        return {
            "snapshot_utc": "2026-01-31T00:00:00Z",
            "monitoring": {"elapsed_days": days},
            "bots": {"v1": v1, "v2r": v2r},
        }

    def test_insufficient_sample_never_passes(self) -> None:
        empty = bot_for_decision(
            closed=0,
            pairs=0,
            net=0.0,
            profit_factor=None,
            drawdown=0.0,
            return_to_drawdown=None,
        )
        decision = monitor.make_decision(self.snapshot(0.0, empty, empty))

        self.assertEqual(decision["decision"], "INSUFFICIENT_FORWARD_SAMPLE")
        self.assertFalse(decision["live_trading_authorized"])
        self.assertFalse(decision["auto_promotion_enabled"])

    def test_ready_only_when_every_locked_gate_passes(self) -> None:
        v1 = bot_for_decision(
            closed=32,
            pairs=5,
            net=35.0,
            profit_factor=1.50,
            drawdown=4.0,
            return_to_drawdown=1.0,
        )
        v2r = bot_for_decision(
            closed=31,
            pairs=4,
            net=40.0,
            profit_factor=1.45,
            drawdown=3.0,
            return_to_drawdown=1.2,
        )
        decision = monitor.make_decision(self.snapshot(31.0, v1, v2r))

        self.assertEqual(decision["decision"], "FORWARD_REVIEW_READY")
        self.assertTrue(all(gate["status"] == "PASS" for gate in decision["performance_gates"]))
        self.assertFalse(decision["live_trading_authorized"])

    def test_integrity_failure_is_monitoring_error(self) -> None:
        v1 = bot_for_decision(
            closed=31,
            pairs=4,
            net=10.0,
            profit_factor=1.3,
            drawdown=3.0,
            return_to_drawdown=1.0,
            integrity=False,
        )
        v2r = bot_for_decision(
            closed=31,
            pairs=4,
            net=10.0,
            profit_factor=1.3,
            drawdown=3.0,
            return_to_drawdown=1.0,
        )
        decision = monitor.make_decision(self.snapshot(31.0, v1, v2r))

        self.assertEqual(decision["decision"], "MONITORING_ERROR")

    def test_performance_failure_keeps_monitoring(self) -> None:
        v1 = bot_for_decision(
            closed=31,
            pairs=4,
            net=10.0,
            profit_factor=1.5,
            drawdown=3.0,
            return_to_drawdown=1.2,
        )
        v2r = bot_for_decision(
            closed=31,
            pairs=4,
            net=-1.0,
            profit_factor=0.9,
            drawdown=3.0,
            return_to_drawdown=-0.1,
        )
        decision = monitor.make_decision(self.snapshot(31.0, v1, v2r))

        self.assertEqual(decision["decision"], "FORWARD_GATES_FAILED_KEEP_RUNNING")

    def test_account_risk_breach_blocks_before_sample_review(self) -> None:
        v1 = bot_for_decision(
            closed=0,
            pairs=0,
            net=0.0,
            profit_factor=None,
            drawdown=0.0,
            return_to_drawdown=None,
        )
        v2r = dict(v1)
        v1["account_risk"] = {"new_entries_allowed": True}
        v2r["account_risk"] = {"new_entries_allowed": False}
        decision = monitor.make_decision(self.snapshot(0.0, v1, v2r))

        self.assertEqual(decision["decision"], "RISK_LIMIT_BREACH")
        self.assertFalse(decision["live_trading_authorized"])


class AlertTests(unittest.TestCase):
    def snapshot(self, timestamp: str, v1_closed: int, v2r_closed: int, drawdown: float) -> dict:
        v1 = bot_for_decision(
            closed=v1_closed,
            pairs=1,
            net=0.0,
            profit_factor=None,
            drawdown=0.0,
            return_to_drawdown=None,
        )
        v2r = bot_for_decision(
            closed=v2r_closed,
            pairs=1,
            net=0.0,
            profit_factor=None,
            drawdown=drawdown,
            return_to_drawdown=None,
        )
        return {"snapshot_utc": timestamp, "bots": {"v1": v1, "v2r": v2r}}

    def test_initializes_once_and_deduplicates_same_snapshot(self) -> None:
        snapshot = self.snapshot("2026-01-01T00:00:00Z", 0, 0, 0.0)
        decision = {"decision": "INSUFFICIENT_FORWARD_SAMPLE"}

        alerts, state = monitor.evaluate_alerts(snapshot, decision, {})
        duplicate_alerts, duplicate_state = monitor.evaluate_alerts(snapshot, decision, state)

        self.assertEqual(
            [item["event_type"] for item in alerts],
            ["MONITOR_BASELINE", "DAILY_FORWARD_SUMMARY"],
        )
        self.assertEqual(duplicate_alerts, [])
        self.assertEqual(duplicate_state, state)

    def test_new_trade_and_drawdown_warning_emit_on_transition(self) -> None:
        previous = {
            "last_snapshot_utc": "2026-01-01T00:00:00Z",
            "last_decision": "INSUFFICIENT_FORWARD_SAMPLE",
            "closed_trades": {"v1": 1, "v2r": 1},
            "active": {
                "monitoring_error": False,
                "v2r_drawdown_warning": False,
                "v2r_drawdown_critical": False,
            },
        }
        snapshot = self.snapshot("2026-01-02T00:00:00Z", 1, 2, 8.5)

        alerts, state = monitor.evaluate_alerts(
            snapshot, {"decision": "INSUFFICIENT_FORWARD_SAMPLE"}, previous
        )

        event_types = {item["event_type"] for item in alerts}
        self.assertEqual(
            event_types,
            {
                "NEW_CLOSED_TRADES",
                "V2R_DRAWDOWN_WARNING",
                "DAILY_FORWARD_SUMMARY",
            },
        )
        self.assertTrue(state["active"]["v2r_drawdown_warning"])

    def test_daily_summary_emits_once_per_utc_day(self) -> None:
        snapshot = self.snapshot("2026-01-02T04:00:00Z", 1, 1, 0.0)
        previous = {
            "last_snapshot_utc": "2026-01-02T00:00:00Z",
            "last_daily_summary_date": "2026-01-02",
            "last_decision": "INSUFFICIENT_FORWARD_SAMPLE",
            "closed_trades": {"v1": 1, "v2r": 1},
            "active": {},
        }

        same_day, state = monitor.evaluate_alerts(
            snapshot, {"decision": "INSUFFICIENT_FORWARD_SAMPLE"}, previous
        )
        next_day_snapshot = self.snapshot("2026-01-03T00:00:00Z", 1, 1, 0.0)
        next_day, next_state = monitor.evaluate_alerts(
            next_day_snapshot, {"decision": "INSUFFICIENT_FORWARD_SAMPLE"}, state
        )

        self.assertNotIn("DAILY_FORWARD_SUMMARY", {item["event_type"] for item in same_day})
        self.assertIn("DAILY_FORWARD_SUMMARY", {item["event_type"] for item in next_day})
        self.assertEqual(next_state["last_daily_summary_date"], "2026-01-03")

    def test_unconfigured_webhook_is_local_only(self) -> None:
        delivery = monitor.deliver_alert_webhook(
            None,
            "2026-01-01T00:00:00Z",
            [
                monitor.alert_event(
                    "2026-01-01T00:00:00Z", "INFO", "TEST", "Test alert"
                )
            ],
            1.0,
        )

        self.assertEqual(delivery, {"status": "LOCAL_ONLY", "delivered": 0})

    def test_ntfy_webhook_uses_readable_push_message(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        alert = monitor.alert_event(
            "2026-01-01T00:00:00Z",
            "CRITICAL",
            "TEST_ALERT",
            "Fail-closed test alert",
        )
        with patch.object(
            monitor.urllib.request, "urlopen", return_value=FakeResponse()
        ) as urlopen:
            delivery = monitor.deliver_alert_webhook(
                "https://ntfy.sh/private-random-topic",
                "2026-01-01T00:00:00Z",
                [alert],
                1.0,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(delivery["status"], "DELIVERED")
        self.assertEqual(request.get_header("Content-type"), "text/plain; charset=utf-8")
        self.assertEqual(request.get_header("X-priority"), "max")
        self.assertIn(b"TEST_ALERT", request.data)
        self.assertNotIn(b"private-random-topic", request.data)

    def test_webhook_rejects_non_https_url_without_network(self) -> None:
        with patch.object(monitor.urllib.request, "urlopen") as urlopen:
            delivery = monitor.deliver_alert_webhook(
                "http://example.invalid/topic",
                "2026-01-01T00:00:00Z",
                [
                    monitor.alert_event(
                        "2026-01-01T00:00:00Z", "INFO", "TEST", "Test alert"
                    )
                ],
                1.0,
            )

        self.assertEqual(delivery["error"], "InvalidWebhookUrl")
        urlopen.assert_not_called()

    def test_ntfy_webhook_rejects_overlong_topic_without_network(self) -> None:
        with patch.object(monitor.urllib.request, "urlopen") as urlopen:
            delivery = monitor.deliver_alert_webhook(
                "https://ntfy.sh/" + "a" * 65,
                "2026-01-01T00:00:00Z",
                [
                    monitor.alert_event(
                        "2026-01-01T00:00:00Z", "INFO", "TEST", "Test alert"
                    )
                ],
                1.0,
            )

        self.assertEqual(delivery["error"], "InvalidNtfyTopic")
        urlopen.assert_not_called()


class ContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.bot_starts = {
            "v1": "2026-01-01T00:00:00Z",
            "v2r": "2026-01-01T00:00:00Z",
        }

    def test_manual_snapshot_cannot_start_or_inflate_coverage(self) -> None:
        state, metrics, events = monitor.update_continuity(
            None,
            self.started,
            scheduled=False,
            eligible=True,
            bot_starts=self.bot_starts,
        )

        self.assertIsNone(state)
        self.assertEqual(metrics["status"], "WAITING_FOR_SCHEDULED_VALID_BASELINE")
        self.assertEqual(metrics["observed_valid_slots"], 0)
        self.assertEqual(events, [])

    def test_scheduled_slots_compute_coverage_without_duplicate_inflation(self) -> None:
        state, metrics, _ = monitor.update_continuity(
            None,
            self.started,
            scheduled=True,
            eligible=True,
            bot_starts=self.bot_starts,
        )
        state, _, _ = monitor.update_continuity(
            state,
            self.started + timedelta(hours=1),
            scheduled=True,
            eligible=True,
            bot_starts=self.bot_starts,
        )
        state, metrics, _ = monitor.update_continuity(
            state,
            self.started + timedelta(hours=8),
            scheduled=True,
            eligible=True,
            bot_starts=self.bot_starts,
        )

        self.assertEqual(metrics["expected_slots"], 3)
        self.assertEqual(metrics["observed_valid_slots"], 2)
        self.assertAlmostEqual(metrics["coverage_ratio"], 2 / 3)
        self.assertEqual(metrics["status"], "DEGRADED_COVERAGE")

    def test_gap_above_eight_hours_resets_validated_segment(self) -> None:
        state, _, _ = monitor.update_continuity(
            None,
            self.started,
            scheduled=True,
            eligible=True,
            bot_starts=self.bot_starts,
        )
        state, metrics, events = monitor.update_continuity(
            state,
            self.started + timedelta(hours=8, seconds=1),
            scheduled=True,
            eligible=True,
            bot_starts=self.bot_starts,
        )

        self.assertEqual(metrics["major_gap_count"], 1)
        self.assertEqual(metrics["observed_valid_slots"], 1)
        self.assertEqual(metrics["validated_observation_days"], 0.0)
        self.assertEqual(events[0]["event_type"], "CONTINUITY_SEGMENT_RESET")

    def test_bot_start_change_is_counted_as_restart(self) -> None:
        state, _, _ = monitor.update_continuity(
            None,
            self.started,
            scheduled=True,
            eligible=True,
            bot_starts=self.bot_starts,
        )
        changed = {**self.bot_starts, "v2r": "2026-01-01T01:00:00Z"}
        _, metrics, events = monitor.update_continuity(
            state,
            self.started + timedelta(hours=4),
            scheduled=True,
            eligible=True,
            bot_starts=changed,
        )

        self.assertEqual(metrics["bot_restart_counts"]["v2r"], 1)
        self.assertEqual(events[0]["event_type"], "BOT_RESTART_DETECTED")


class SafetyTests(unittest.TestCase):
    def test_exchange_credentials_are_checked_without_being_returned(self) -> None:
        base = {
            "exchange": {"key": "", "secret": ""},
            "dry_run_wallet": 1000,
            "stake_currency": "USDT",
        }
        override = {"exchange": {"pair_whitelist": ["BTC/USDT:USDT"]}}

        expected = monitor.expected_bot_config(base, override, "Strategy")

        self.assertTrue(expected["credential_free"])
        self.assertNotIn("key", expected)
        self.assertNotIn("secret", expected)


class MainLoopTests(unittest.TestCase):
    def test_collection_error_retries_before_normal_cadence(self) -> None:
        snapshot = {"snapshot_utc": "2026-01-01T00:00:00Z", "errors": [{"bot": "v1"}]}
        decision = {"decision": "MONITORING_ERROR"}
        with (
            patch.object(monitor, "run_snapshot", return_value=(snapshot, decision)),
            patch.object(monitor.time, "sleep", side_effect=SystemExit("stop")) as sleeper,
            self.assertRaises(SystemExit),
        ):
            monitor.main(
                [
                    "--loop-seconds",
                    "14400",
                    "--error-retry-seconds",
                    "60",
                ]
            )
        sleeper.assert_called_once_with(60)


if __name__ == "__main__":
    unittest.main()
