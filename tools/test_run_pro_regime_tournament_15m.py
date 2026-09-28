from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import run_pro_regime_tournament_15m as tournament


class TournamentRunnerTests(unittest.TestCase):
    def test_reconciliation_and_gate_math(self) -> None:
        trades = [
            {"profit_abs": 2.0, "is_short": False, "pair": tournament.PAIRS[0]},
            {"profit_abs": -1.0, "is_short": True, "pair": tournament.PAIRS[1]},
        ]
        payload = {"trades": trades, "total_trades": 2, "profit_total_abs": 1.0,
                   "profit_factor": 2.0, "profit_total": 0.01, "max_drawdown_account": 0.005,
                   "starting_balance": 1000.0, "final_balance": 1010.0}
        row = tournament.evaluate_strategy("fixed", payload)
        self.assertEqual(row["metrics"]["return_to_drawdown"], 2.0)
        self.assertFalse(row["gates"]["trades_gte_80"])

    def test_receipt_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            (staging / ".last_result.json").write_text(json.dumps({"latest_backtest": "../bad.zip"}), encoding="utf-8")
            with self.assertRaises(tournament.TournamentError):
                tournament.resolve_receipt(staging)

    def test_command_is_exact_five_candidate_train(self) -> None:
        command = tournament.build_command(tournament.ROOT)
        rendered = " ".join(command).replace("\\", "/")
        self.assertEqual(len(tournament.CANDIDATES), 4)
        for candidate in tournament.CANDIDATES:
            self.assertIn(candidate, command)
        self.assertIn(tournament.TIMERANGE, command)
        self.assertIn("pro_regime_tournament_15m_cycle2/train_staging", rendered)


if __name__ == "__main__":
    unittest.main()
