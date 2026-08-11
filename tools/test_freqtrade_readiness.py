import base64
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import check_freqtrade_ready as readiness


class Response:
    def __init__(self, payload):
        self.body = BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body.read()


class FreqtradeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Path(self.temporary.name) / "config.json"
        self.config.write_text(
            json.dumps({"api_server": {"username": "user", "password": "secret"}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_requires_completed_bot_loop(self):
        with patch.object(readiness.urllib.request, "urlopen", return_value=Response({})):
            self.assertFalse(readiness.check_ready(self.config, "http://bot", 1.0))

    def test_uses_auth_and_accepts_last_process(self):
        def open_request(request, timeout):
            expected = base64.b64encode(b"user:secret").decode("ascii")
            self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
            self.assertEqual(timeout, 1.0)
            return Response({"last_process": "2026-08-10T00:00:00Z"})

        with patch.object(readiness.urllib.request, "urlopen", side_effect=open_request):
            self.assertTrue(readiness.check_ready(self.config, "http://bot", 1.0))


if __name__ == "__main__":
    unittest.main()
