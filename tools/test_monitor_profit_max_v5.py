import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor_profit_max_v5 import build_report, healthcheck


class ProfitMaxMonitorTests(unittest.TestCase):
    def database(self, root: Path, rows=()):
        path = root / "trades.sqlite"
        connection = sqlite3.connect(path)
        connection.execute(
            "create table trades (id integer primary key, pair text, is_open integer, close_profit_abs real, "
            "open_date text, close_date text, strategy text, trading_mode text, leverage real, is_short integer)"
        )
        connection.executemany(
            "insert into trades(pair,is_open,close_profit_abs,open_date,close_date,strategy,trading_mode,leverage,is_short) values(?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit(); connection.close()
        return path

    def row(self, profit, is_short=False, pair="BTC/USDT:USDT", is_open=0):
        return (pair, is_open, profit, "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00" if not is_open else None, "ProfitMaxV5Asymmetric50", "futures", 1.0, int(is_short))

    def test_empty_database_is_evidence_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 2, 1, tzinfo=timezone.utc)
            report = build_report(self.database(Path(directory)), "ProfitMaxV5Asymmetric50", now - timedelta(days=1), 1000, now=now)
            self.assertEqual(report["qualification_status"], "EVIDENCE_INCOMPLETE")
            self.assertEqual(report["decision"], "CONTINUE_DRY_RUN")

    def test_complete_profitable_breadth_pass_requires_human(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [self.row(2 if i % 3 else -1, bool(i % 2), ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"][i % 3]) for i in range(30)]
            now = datetime(2026, 3, 1, tzinfo=timezone.utc)
            report = build_report(self.database(Path(directory), rows), "ProfitMaxV5Asymmetric50", now - timedelta(days=31), 1000, now=now)
            self.assertEqual(report["qualification_status"], "FORWARD_GATES_PASS_HUMAN_REVIEW_REQUIRED")
            self.assertFalse(report["live_trading_authorized"])

    def test_bad_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = list(self.row(1)); bad[6] = "spot"
            with self.assertRaises(Exception):
                build_report(self.database(Path(directory), [tuple(bad)]), "ProfitMaxV5Asymmetric50", datetime.now(timezone.utc) - timedelta(days=1), 1000)

    def test_healthcheck_accepts_fresh_safe_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            path.write_text(json.dumps({"schema_version":"1.0","generated_at_utc":now.isoformat(),"mode":"dry_run","qualification_status":"EVIDENCE_INCOMPLETE","decision":"CONTINUE_DRY_RUN","live_trading_authorized":False,"auto_promotion_enabled":False}))
            self.assertTrue(healthcheck(path, 60, now=now + timedelta(seconds=30)))
            self.assertFalse(healthcheck(path, 60, now=now + timedelta(seconds=61)))

    def test_healthcheck_rejects_fresh_monitor_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            path.write_text(json.dumps({"schema_version":"1.0","generated_at_utc":now.isoformat(),"mode":"dry_run","qualification_status":"MONITOR_ERROR","decision":"KEEP_DRY_RUN_RESEARCH","live_trading_authorized":False,"auto_promotion_enabled":False}))
            self.assertFalse(healthcheck(path, 60, now=now))


if __name__ == "__main__":
    unittest.main()
