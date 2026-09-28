from __future__ import annotations

import unittest

import run_pro_day_v3_cycle2_recursive_gate as cycle2
import run_pro_day_v3_recursive_gate as gate


class Cycle2RunnerTests(unittest.TestCase):
    def test_transport_allows_public_metadata_without_private_credentials(self) -> None:
        rendered = " ".join(cycle2.build_command(cycle2.ROOT)).replace("\\", "/")
        self.assertNotIn("--network none", rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertNotIn("models:rw", rendered)

    def test_cycle2_paths_are_isolated(self) -> None:
        self.assertIn("pro_day_v3_cycle2", str(gate.MANIFEST))
        self.assertIn("pro_day_v3_cycle2", str(gate.OUTPUT))
        self.assertIn("cycle2", str(gate.RUNNER))


if __name__ == "__main__":
    unittest.main()
