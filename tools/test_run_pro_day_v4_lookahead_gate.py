from __future__ import annotations

import unittest

import run_pro_day_v4_lookahead_gate as gate


def good_probe() -> dict:
    return {
        "analyzed_signals": 120, "has_bias": False,
        "false_entry_signals": 0, "false_exit_signals": 0, "false_indicators": [],
        "full_trade_count": 200,
        "full_trade_tag_counts": {tag: 10 for tag in gate.REQUIRED_TAGS},
        "full_trade_pair_counts": {pair: 20 for pair in gate.PAIRS},
        "public_market_metadata_used": True, "private_api_used": False,
    }


class V4LookaheadGateTests(unittest.TestCase):
    def test_clean_representative_probe_passes(self) -> None:
        passed, failures, _ = gate.evaluate(good_probe())
        self.assertTrue(passed, failures)

    def test_bias_low_sample_or_missing_representation_fails(self) -> None:
        for mutate in (
            lambda row: row.update(analyzed_signals=99),
            lambda row: row.update(has_bias=True),
            lambda row: row["full_trade_tag_counts"].update(R1_short=0),
            lambda row: row["full_trade_pair_counts"].update({gate.PAIRS[2]: 0}),
        ):
            probe = good_probe()
            mutate(probe)
            self.assertFalse(gate.evaluate(probe)[0])

    def test_transport_and_mounts_are_bounded(self) -> None:
        rendered = " ".join(gate.build_command(gate.ROOT)).replace("\\", "/")
        self.assertNotIn("--network none", rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertNotIn("models:rw", rendered)


if __name__ == "__main__":
    unittest.main()
