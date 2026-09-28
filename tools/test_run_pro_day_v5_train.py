from __future__ import annotations

import unittest

import run_pro_day_v5_train as train


class V5TrainTests(unittest.TestCase):
    def test_reconciliation_and_gate_math(self) -> None:
        trades = [
            {"profit_abs": 2.0, "pair": train.PAIRS[0], "enter_tag": "T1_long", "is_short": False},
            {"profit_abs": -1.0, "pair": train.PAIRS[1], "enter_tag": "R1_short", "is_short": True},
            {"profit_abs": 0.0, "pair": train.PAIRS[2], "enter_tag": "R1_long", "is_short": False},
        ]
        payload = {"trades": trades, "total_trades": 3, "profit_total_abs": 1.0,
                   "profit_factor": 2.0, "wins": 1, "losses": 1, "draws": 1}
        result = train.reconcile(payload)
        self.assertEqual(result["trade_count"], 3)
        self.assertEqual(result["profit_factor"], 2.0)
        self.assertEqual(result["long_count"], 2)

    def test_reconciliation_fails_on_source_mismatch(self) -> None:
        payload = {"trades": [{"profit_abs": 1.0}], "total_trades": 2,
                   "profit_total_abs": 1.0, "profit_factor": 1.0,
                   "wins": 1, "losses": 0, "draws": 0}
        with self.assertRaises(train.TrainError):
            train.reconcile(payload)

    def test_command_uses_staging_and_exact_timerange(self) -> None:
        rendered = " ".join(train.build_command(train.ROOT)).replace("\\", "/")
        self.assertIn("pro_day_v5_cycle1/train_staging", rendered)
        self.assertIn(train.TIMERANGE, rendered)
        self.assertIn(train.ARTIFACT.name, rendered)
        self.assertIn(":/freqtrade/user_data:ro", rendered)


if __name__ == "__main__":
    unittest.main()
