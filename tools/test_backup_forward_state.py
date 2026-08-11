import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import backup_forward_state as backup


class ForwardBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.user_data = self.root / "user_data"
        self.reports = self.user_data / "reports"
        self.dashboard = self.user_data / "dashboard"
        self.derivatives = self.user_data / "data" / "binance" / "derivatives"
        self.backups = self.user_data / "backups"
        self.state = self.reports / "forward_backup_state.json"
        self.reports.mkdir(parents=True)
        self.dashboard.mkdir(parents=True)
        self.derivatives.mkdir(parents=True)
        (self.reports / "forward_monitor_latest.json").write_text(
            '{"snapshot":"safe"}', encoding="utf-8"
        )
        (self.dashboard / "forward_dashboard.html").write_text(
            "<html>safe</html>", encoding="utf-8"
        )
        (self.derivatives / "BTCUSDT-5m-open_interest.csv").write_text(
            "timestamp_utc,open_interest\n2026-01-10T00:00:00.000Z,42\n",
            encoding="utf-8",
        )
        (self.user_data / "config.json").write_text(
            '{"password":"DO_NOT_BACK_UP_THIS_SECRET"}', encoding="utf-8"
        )
        for name in backup.DATABASE_NAMES:
            with closing(sqlite3.connect(self.user_data / name)) as database:
                database.execute("CREATE TABLE sample (value INTEGER)")
                database.execute("INSERT INTO sample VALUES (42)")
                database.commit()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_creates_consistent_secret_free_backup_and_skips_until_due(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)

        result = backup.run_backup_if_due(
            self.user_data, self.backups, self.state, now
        )

        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(result["restore_test"]["status"], "PASS")
        self.assertTrue(result["restore_test"]["temporary_restore_removed"])
        backup_dir = Path(result["backup_directory"])
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["sqlite_integrity_check"].values()), {"ok"})
        for name in backup.DATABASE_NAMES:
            with closing(sqlite3.connect(backup_dir / name)) as database:
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], 42)
        archive_path = backup_dir / "forward_evidence.zip"
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            content = b"".join(archive.read(name) for name in names)
        self.assertNotIn("config.json", names)
        self.assertIn(
            "data/binance/derivatives/BTCUSDT-5m-open_interest.csv", names
        )
        self.assertIn(
            "user_data/data/binance/derivatives/**", manifest["source_scope"]
        )
        self.assertNotIn(b"DO_NOT_BACK_UP_THIS_SECRET", content)
        self.assertFalse(any(path.name.startswith(".tmp-") for path in self.backups.iterdir()))

        second = backup.run_backup_if_due(
            self.user_data, self.backups, self.state, now + timedelta(hours=1)
        )
        self.assertEqual(second["status"], "NOT_DUE")
        self.assertEqual(second["verification"]["status"], "PASS")

    def test_missing_recent_backup_forces_a_new_verified_backup(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        first = backup.run_backup_if_due(
            self.user_data, self.backups, self.state, now
        )
        shutil.rmtree(Path(first["backup_directory"]))

        recovered = backup.run_backup_if_due(
            self.user_data, self.backups, self.state, now + timedelta(hours=1)
        )

        self.assertEqual(recovered["status"], "CREATED")
        self.assertTrue(recovered["previous_backup_invalid"])
        self.assertEqual(recovered["verification"]["status"], "PASS")
        self.assertTrue(Path(recovered["backup_directory"]).is_dir())

    def test_corrupt_recent_backup_forces_a_new_verified_backup(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        first = backup.run_backup_if_due(
            self.user_data, self.backups, self.state, now
        )
        evidence = Path(first["backup_directory"]) / "forward_evidence.zip"
        with evidence.open("ab") as handle:
            handle.write(b"corrupt")

        recovered = backup.run_backup_if_due(
            self.user_data, self.backups, self.state, now + timedelta(hours=1)
        )

        self.assertEqual(recovered["status"], "CREATED")
        self.assertTrue(recovered["previous_backup_invalid"])
        self.assertIn("mismatch", recovered["previous_backup_invalid_reason"])
        self.assertEqual(recovered["verification"]["status"], "PASS")

    def test_retention_keeps_two_newest_complete_backups(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for days_old in (50, 45, 40, 1):
            timestamp = now - timedelta(days=days_old)
            folder = self.backups / timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(
                json.dumps({"backup_utc": backup.iso_utc(timestamp)}), encoding="utf-8"
            )

        removed = backup.enforce_retention(self.backups, now, retention_days=35)

        self.assertEqual(len(removed), 2)
        remaining = backup.validated_backup_directories(self.backups)
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[-1][0], now - timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
