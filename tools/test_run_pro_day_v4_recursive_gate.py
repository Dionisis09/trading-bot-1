from __future__ import annotations

import unittest

import run_pro_day_v3_recursive_gate as base
import run_pro_day_v4_recursive_gate as gate


def good_probe() -> dict:
    return {
        "candidate_counts": base.COUNTS,
        "strategy_startup_candle_count": 2399,
        "pair": base.PAIR,
        "timerange": base.TIMERANGE,
        "full_indicator_columns": sorted(base.CANDIDATES | {"date"}),
        "recursive_variance_fraction": {"trend_gap_atr_4h": {"2399": 0.00005}},
        "indicator_only_lookahead_columns": [],
    }


class V4RecursiveGateTests(unittest.TestCase):
    def test_converged_probe_passes_without_signal_columns_in_indicator_frame(self) -> None:
        passed, failures, _ = gate.evaluate(good_probe())
        self.assertTrue(passed, failures)

    def test_variance_signal_and_lookahead_fail_closed(self) -> None:
        probe = good_probe()
        probe["recursive_variance_fraction"]["trend_gap_atr_4h"] = {"2399": 0.0001001}
        self.assertFalse(gate.evaluate(probe)[0])
        probe = good_probe()
        probe["recursive_variance_fraction"]["enter_long"] = {"2399": "NONFINITE"}
        self.assertFalse(gate.evaluate(probe)[0])
        probe = good_probe()
        probe["indicator_only_lookahead_columns"] = ["trend_long_4h"]
        self.assertFalse(gate.evaluate(probe)[0])

    def test_public_metadata_transport_and_read_only_inputs(self) -> None:
        rendered = " ".join(gate.build_command(gate.ROOT)).replace("\\", "/")
        self.assertNotIn("--network none", rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertNotIn("models:rw", rendered)


if __name__ == "__main__":
    unittest.main()
