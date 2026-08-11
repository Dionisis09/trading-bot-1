from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from sanitize_backtest_archive import REDACTION, sanitize_archive


class SanitizeBacktestArchiveTests(unittest.TestCase):
    def test_redacts_config_secrets_and_preserves_trade_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "result.zip"
            trade_payload = b'{"strategy":{"Demo":{"profit_total_abs":1.0}}}'
            config = {
                "exchange": {"key": "private", "secret": "private", "empty": ""},
                "api_server": {"password": "private", "jwt_secret_key": "private"},
                "nested": [{"token": "private"}],
            }
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("result.json", trade_payload)
                bundle.writestr("result_config.json", json.dumps(config))

            result = sanitize_archive(archive)
            self.assertEqual(result["zip_integrity"], "PASS")
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(bundle.read("result.json"), trade_payload)
                cleaned = json.loads(bundle.read("result_config.json"))
            self.assertEqual(cleaned["exchange"]["key"], REDACTION)
            self.assertEqual(cleaned["api_server"]["jwt_secret_key"], REDACTION)
            self.assertEqual(cleaned["nested"][0]["token"], REDACTION)


if __name__ == "__main__":
    unittest.main()
