from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import finalize_profit_max_cagr15_technical as subject


class FinalizeProfitMaxCagr15TechnicalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = self.root / "report"
        self.report.mkdir()
        for relative in (
            "user_data/strategies/ProfitMaxCagr15V5.py",
            "user_data/config-profit-max-cagr15-cycle5.json",
            "user_data/risk_policy_profit_max_cagr15_cycle5.json",
            "docs/profit_max_cagr15_cycle5_locked_plan.md",
            "tools/evaluate_profit_max_cagr15_cycle5.py",
            "tools/finalize_profit_max_cagr15_user_objective.py",
            "tools/finalize_profit_max_cagr15_technical.py",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("frozen\n", encoding="utf-8")
        (self.report / "continuous.zip").write_bytes(b"zip")
        objective = {
            "status": "MEETS_RETROSPECTIVE_USER_OBJECTIVE",
            "objective_gates": {"cagr": True, "cost": True},
            "live_trading_authorized": False,
            "profit_guaranteed": False,
            "metrics": {"cagr_pct": 15.9, "wallet_drawdown_pct": 8.8},
            "severe_stress": {"cagr_pct": 15.2},
        }
        (self.report / "user_objective_decision.json").write_text(
            json.dumps(objective), encoding="utf-8"
        )
        (self.report / "recursive_btc.log").write_text(
            "ema200_1d 1599 0.000%\nNo lookahead bias on indicators found.\n",
            encoding="utf-8",
        )
        self._csv(self.report / "lookahead.csv", True, 30, 5, 0)
        for _, (filename, signals) in subject.PAIR_FILES.items():
            self._csv(self.report / filename, False, signals, 0, 0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _csv(path: Path, bias: bool, signals: int, entries: int, exits: int) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "filename", "strategy", "has_bias", "total_signals",
                    "biased_entry_signals", "biased_exit_signals", "biased_indicators",
                ],
            )
            writer.writeheader()
            writer.writerow({
                "filename": "ProfitMaxCagr15V5.py",
                "strategy": "ProfitMaxCagr15V5",
                "has_bias": str(bias),
                "total_signals": signals,
                "biased_entry_signals": entries,
                "biased_exit_signals": exits,
                "biased_indicators": "",
            })

    def test_clean_pair_isolated_and_recursive_evidence_passes(self) -> None:
        result = subject.build(self.report, self.root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["decision"], "APPROVE_ISOLATED_DRY_RUN_ONLY")
        self.assertEqual(result["pair_isolated_lookahead"]["total_signals"], 82)
        self.assertTrue(result["portfolio_wide_lookahead_diagnostic"]["has_bias"])
        self.assertFalse(result["live_trading_authorized"])

    def test_one_biased_pair_fails_closed(self) -> None:
        filename, signals = subject.PAIR_FILES["BTC/USDT:USDT"]
        self._csv(self.report / filename, True, signals, 1, 0)
        result = subject.build(self.report, self.root)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["decision"], "KEEP_OFFLINE_RESEARCH")


if __name__ == "__main__":
    unittest.main()
