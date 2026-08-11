from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import check_pro_day_v2_runtime as module


def completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["docker"], returncode, stdout=stdout, stderr="hidden")


class RuntimeCompatibilityTests(unittest.TestCase):
    def _runner(self, command, **kwargs):
        if command[1:3] == ["image", "inspect"]:
            return completed(
                json.dumps(
                    [
                        {
                            "RepoDigests": [f"freqtradeorg/freqtrade@{module.EXPECTED_DIGEST}"],
                            "Architecture": "amd64",
                            "Os": "linux",
                            "Config": {"User": "ftuser", "WorkingDir": "/freqtrade"},
                        }
                    ]
                )
            )
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        return completed(
            json.dumps(
                {
                    "freqtrade": "2026.7",
                    "lightgbm": "4.7.0",
                    "datasieve": True,
                    "model": "LightGBMRegressor",
                    "machine": "x86_64",
                    "python": "3.14.6",
                }
            )
        )

    def test_pass_report_is_no_pnl_and_networkless(self):
        report = module.validate_runtime(runner=self._runner)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["model_training_performed"])
        self.assertFalse(report["pnl_evaluated"])
        self.assertFalse(report["live_trading_authorized"])
        self.assertEqual(report["network_mode"], "none")

    def test_digest_mismatch_fails_status(self):
        def mismatch(command, **kwargs):
            if command[1:3] == ["image", "inspect"]:
                payload = [{"RepoDigests": [], "Architecture": "amd64", "Os": "linux", "Config": {"User": "ftuser", "WorkingDir": "/freqtrade"}}]
                return completed(json.dumps(payload))
            return self._runner(command, **kwargs)

        report = module.validate_runtime(runner=mismatch)
        self.assertEqual(report["status"], "TECHNICAL_BLOCKED")
        self.assertFalse(report["checks"]["repo_digest"])

    def test_subprocess_failure_does_not_echo_stderr(self):
        def failed(command, **kwargs):
            return completed("", returncode=1)

        with self.assertRaisesRegex(module.RuntimeCheckError, "exit=1"):
            module.validate_runtime(runner=failed)

    def test_atomic_report_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime.json"
            payload = module.validate_runtime(runner=self._runner)
            module._atomic_write(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
