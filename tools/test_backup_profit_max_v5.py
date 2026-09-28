import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_profit_max_v5 import create_backup, healthcheck


class ProfitMaxBackupTests(unittest.TestCase):
    def database(self, root: Path) -> Path:
        path = root / "source.sqlite"
        connection = sqlite3.connect(path); connection.execute("create table sample(value integer)"); connection.execute("insert into sample values(1)"); connection.commit(); connection.close()
        return path

    def test_backup_is_consistent_and_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "out"; now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            record = create_backup(self.database(root), output, 35, now=now)
            self.assertEqual(record["integrity_check"], "ok")
            self.assertTrue(healthcheck(output, 100, now=now + timedelta(seconds=50)))

    def test_tampered_backup_is_unhealthy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "out"; now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            record = create_backup(self.database(root), output, 35, now=now)
            with (output / record["database"]).open("ab") as handle: handle.write(b"tamper")
            self.assertFalse(healthcheck(output, 100, now=now))

    def test_refuses_same_timestamp_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "out"; source = self.database(root); now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            create_backup(source, output, 35, now=now)
            with self.assertRaises(RuntimeError): create_backup(source, output, 35, now=now)


if __name__ == "__main__":
    unittest.main()
