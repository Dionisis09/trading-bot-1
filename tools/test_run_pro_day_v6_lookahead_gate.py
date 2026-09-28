from __future__ import annotations

import unittest

import run_pro_day_v6_lookahead_gate as runner


class V6LookaheadTests(unittest.TestCase):
    def test_paths_and_transport_are_isolated(self) -> None:
        self.assertIn("pro_day_v6_cycle1", str(runner.gate.MANIFEST))
        rendered = " ".join(runner.build_command(runner.ROOT)).replace("\\", "/")
        self.assertIn(":/freqtrade/user_data:ro", rendered)
        self.assertIn(":/canonical/futures:ro", rendered)
        self.assertNotIn("--network none", rendered)

    def test_exact_market_orderbook_override_is_present(self) -> None:
        source = (runner.ROOT / runner.gate.RUNNER).read_text(encoding="utf-8")
        self.assertIn('{"price_side": "other", "use_order_book": True}', source)


if __name__ == "__main__":
    unittest.main()
