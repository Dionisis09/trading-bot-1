from __future__ import annotations

import unittest

import run_pro_day_v4_cycle3_lookahead_gate as runner


class Cycle3LookaheadTests(unittest.TestCase):
    def test_cycle3_paths_are_isolated(self) -> None:
        self.assertIn("pro_day_v4_cycle3", str(runner.gate.MANIFEST))
        self.assertIn("pro_day_v4_cycle3", str(runner.gate.OUTPUT))

    def test_exact_binance_market_compatibility_override_is_frozen(self) -> None:
        source = (runner.ROOT / runner.gate.RUNNER).read_text(encoding="utf-8")
        self.assertIn('{"price_side": "other", "use_order_book": True}', source)
        self.assertIn('"transient_order_book_pricing": True', source)

    def test_inputs_are_read_only_and_public_metadata_is_available(self) -> None:
        rendered = " ".join(runner.build_command(runner.ROOT)).replace("\\", "/")
        self.assertNotIn("--network none", rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)


if __name__ == "__main__":
    unittest.main()
