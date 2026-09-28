from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProSwingTournament1h import ProSwingCore1h, ProSwingSelective1h, ProSwingSlow1h, ProSwingStrongTrend1h  # noqa: E402


class ProSwingTournamentTests(unittest.TestCase):
    def test_four_predeclared_variants(self) -> None:
        self.assertEqual((ProSwingCore1h.entry_window, ProSwingCore1h.exit_window, ProSwingCore1h.confluence_minimum, ProSwingCore1h.adx_minimum), (30, 10, 3, 20.0))
        self.assertEqual((ProSwingSlow1h.entry_window, ProSwingSlow1h.exit_window), (55, 20))
        self.assertEqual(ProSwingSelective1h.confluence_minimum, 4)
        self.assertEqual(ProSwingStrongTrend1h.adx_minimum, 25.0)

    def test_all_are_1h_callback_free_and_one_x(self) -> None:
        for candidate in (ProSwingCore1h, ProSwingSlow1h, ProSwingSelective1h, ProSwingStrongTrend1h):
            self.assertEqual(candidate.timeframe, "1h")
            self.assertFalse(candidate.use_custom_stoploss)


if __name__ == "__main__":
    unittest.main()

