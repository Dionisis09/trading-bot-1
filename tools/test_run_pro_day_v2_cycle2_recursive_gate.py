from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import run_pro_day_v2_cycle2_recursive_gate as gate


def good_probe() -> dict:
    columns = sorted(gate.FEATURES | gate.CANDIDATES | gate.SIGNALS | {"date", gate.TARGET})
    return {
        "candidate_counts": gate.COUNTS,
        "strategy_startup_candle_count": gate.QUALIFICATION_COUNT,
        "pair": gate.PAIR,
        "timerange": gate.TIMERANGE,
        "full_indicator_columns": columns,
        "recursive_variance_fraction": {
            "%-ret_5m_1": {"399": 0.00005},
            gate.TARGET: {"399": "NONFINITE"},
        },
        "indicator_only_lookahead_columns": [gate.TARGET],
    }


class RecursiveGateTests(unittest.TestCase):
    def test_target_only_lookahead_and_small_variance_pass(self) -> None:
        passed, failures, details = gate.evaluate_probe(good_probe())
        self.assertTrue(passed, failures)
        self.assertEqual(details["allowed_target_only_lookahead"], gate.TARGET)

    def test_signal_difference_fails(self) -> None:
        probe = good_probe()
        probe["recursive_variance_fraction"]["enter_long"] = {"399": "NONFINITE"}
        passed, failures, _ = gate.evaluate_probe(probe)
        self.assertFalse(passed)
        self.assertIn("entry/exit signal differences found", failures)

    def test_non_target_lookahead_fails(self) -> None:
        probe = good_probe()
        probe["indicator_only_lookahead_columns"].append("candidate_T1_long")
        passed, failures, _ = gate.evaluate_probe(probe)
        self.assertFalse(passed)
        self.assertIn("non-target indicator lookahead found", failures)

    def test_variance_above_locked_limit_fails(self) -> None:
        probe = good_probe()
        probe["recursive_variance_fraction"]["%-ret_5m_1"] = {"399": 0.0001001}
        passed, failures, _ = gate.evaluate_probe(probe)
        self.assertFalse(passed)
        self.assertIn("indicator variance exceeds 0.01% or is non-finite", failures)

    def test_inventory_is_deterministic_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "b").mkdir()
            (root / "b/two.bin").write_bytes(b"two")
            (root / "one.bin").write_bytes(b"one")
            first = gate.inventory(root)
            second = gate.inventory(root)
            self.assertEqual(first, second)
            self.assertEqual(first["file_count"], 2)
            self.assertEqual([row["path"] for row in first["files"]], ["b/two.bin", "one.bin"])

    def test_docker_command_uses_read_only_inputs_and_isolated_models(self) -> None:
        command = gate.build_command(gate.ROOT)
        rendered = " ".join(command).replace("\\", "/")
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertIn(":/freqtrade/user_data/models:rw", rendered)
        self.assertIn("--inside-container", command)


if __name__ == "__main__":
    unittest.main()
