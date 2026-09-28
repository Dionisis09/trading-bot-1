from __future__ import annotations

import unittest

import run_pro_day_v4_cycle2_lookahead_gate as gate


class Cycle2LookaheadTests(unittest.TestCase):
    def test_retry_paths_are_isolated(self) -> None:
        self.assertIn("pro_day_v4_cycle2", str(gate.gate.MANIFEST))
        self.assertIn("pro_day_v4_cycle2", str(gate.gate.OUTPUT))

    def test_transport_keeps_inputs_read_only_and_allows_public_metadata(self) -> None:
        rendered = " ".join(gate.build_command(gate.ROOT)).replace("\\", "/")
        self.assertNotIn("--network none", rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)

    def test_source_contains_exact_transient_market_compatibility_override(self) -> None:
        source = (gate.ROOT / gate.gate.RUNNER).read_text(encoding="utf-8")
        self.assertIn('{"price_side": "other", "use_order_book": False}', source)
        self.assertIn('"transient_order_book_pricing": False', source)


if __name__ == "__main__":
    unittest.main()
