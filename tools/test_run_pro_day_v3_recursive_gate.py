from __future__ import annotations

import unittest

import run_pro_day_v3_recursive_gate as gate


def good_probe() -> dict:
    return {
        "candidate_counts": gate.COUNTS,
        "strategy_startup_candle_count": gate.QUALIFICATION_COUNT,
        "pair": gate.PAIR,
        "timerange": gate.TIMERANGE,
        "full_indicator_columns": sorted(gate.CANDIDATES | gate.SIGNALS | {"date"}),
        "recursive_variance_fraction": {"ema20": {"399": 0.00005}},
        "indicator_only_lookahead_columns": [],
    }


class RecursiveGateTests(unittest.TestCase):
    def test_small_variance_and_no_signal_difference_pass(self) -> None:
        passed, failures, _ = gate.evaluate(good_probe())
        self.assertTrue(passed, failures)

    def test_signal_difference_fails(self) -> None:
        probe = good_probe()
        probe["recursive_variance_fraction"]["enter_long"] = {"399": "NONFINITE"}
        self.assertFalse(gate.evaluate(probe)[0])

    def test_indicator_variance_above_limit_fails(self) -> None:
        probe = good_probe()
        probe["recursive_variance_fraction"]["ema20"] = {"399": 0.0001001}
        self.assertFalse(gate.evaluate(probe)[0])

    def test_any_indicator_lookahead_fails(self) -> None:
        probe = good_probe()
        probe["indicator_only_lookahead_columns"] = ["candidate_T1_long"]
        self.assertFalse(gate.evaluate(probe)[0])

    def test_missing_candidate_fails(self) -> None:
        probe = good_probe()
        probe["full_indicator_columns"].remove("candidate_R1_short")
        self.assertFalse(gate.evaluate(probe)[0])

    def test_command_is_offline_and_read_only(self) -> None:
        rendered = " ".join(gate.build_command(gate.ROOT)).replace("\\", "/")
        self.assertIn("--network none", rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertNotIn("models:rw", rendered)


if __name__ == "__main__":
    unittest.main()
