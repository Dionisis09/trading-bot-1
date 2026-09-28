from __future__ import annotations

import unittest

import register_pro_swing_tournament_1h as register


class RegisterTournamentTests(unittest.TestCase):
    def test_expected_source_member_suffixes_are_unique(self) -> None:
        suffixes = {f"_{name}.py" for name in register.tournament.CANDIDATES}
        self.assertEqual(len(suffixes), 4)

    def test_selection_order_is_return_then_pf_then_drawdown(self) -> None:
        rows = [
            {"strategy": "a", "status": "PASS", "metrics": {"return_pct": 2.0, "profit_factor": 1.3, "wallet_drawdown_pct": 4.0}},
            {"strategy": "b", "status": "PASS", "metrics": {"return_pct": 3.0, "profit_factor": 1.2, "wallet_drawdown_pct": 6.0}},
        ]
        rows.sort(key=lambda row: (-row["metrics"]["return_pct"], -row["metrics"]["profit_factor"], row["metrics"]["wallet_drawdown_pct"]))
        self.assertEqual(rows[0]["strategy"], "b")


if __name__ == "__main__":
    unittest.main()

