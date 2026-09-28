from __future__ import annotations

import unittest

import run_pro_day_v3_recursive_gate as base
import run_pro_day_v6_recursive_gate as gate


class V6RecursiveTests(unittest.TestCase):
    def test_clean_probe_passes_and_variance_fails(self) -> None:
        probe = {"candidate_counts": base.COUNTS, "strategy_startup_candle_count": 2399,
                 "full_indicator_columns": sorted(base.CANDIDATES),
                 "recursive_variance_fraction": {"ema50_4h": {"2399": 0.00001}},
                 "indicator_only_lookahead_columns": []}
        self.assertTrue(gate.evaluate(probe)[0])
        probe["recursive_variance_fraction"]["ema50_4h"] = {"2399": 0.001}
        self.assertFalse(gate.evaluate(probe)[0])

    def test_command_uses_read_only_inputs_and_public_metadata(self) -> None:
        rendered = " ".join(gate.build_command(gate.ROOT)).replace("\\", "/")
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertNotIn("--network none", rendered)


if __name__ == "__main__":
    unittest.main()
