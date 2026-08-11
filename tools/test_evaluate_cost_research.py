import unittest

import evaluate_cost_research as research


def make_row(strategy: str, split: str, scenario: str, *, trades: int = 25, pf: float = 1.5):
    return {
        "strategy": strategy,
        "split": split,
        "scenario": scenario,
        "trades": trades,
        "net_profit_usdt": 5.0,
        "profit_factor": pf,
        "realized_drawdown_pct": 1.0,
        "source_reconciled": True,
    }


def passing_rows(splits):
    rows = []
    for strategy in (research.INCUMBENT, *research.CANDIDATES):
        for split in splits:
            rows.append(make_row(strategy, split, "standard"))
            rows.append(make_row(strategy, split, "moderate"))
            rows.append(make_row(strategy, split, "severe"))
    return rows


class CostResearchTests(unittest.TestCase):
    def test_training_ranks_by_worst_year_severe_profit_factor(self):
        rows = passing_rows(research.TRAINING_SPLITS)
        for row in rows:
            if row["strategy"] == "CostRobustRoc10" and row["scenario"] == "severe":
                row["profit_factor"] = 2.0
        candidates, selected = research.training_selection(rows)
        self.assertEqual(selected, "CostRobustRoc10")
        self.assertTrue(all(item["eligible"] for item in candidates))

    def test_training_rejects_near_empty_candidate(self):
        rows = passing_rows(research.TRAINING_SPLITS)
        for row in rows:
            if row["strategy"] in research.CANDIDATES and row["split"] == "2023":
                row["trades"] = 16
        candidates, selected = research.training_selection(rows)
        self.assertIsNone(selected)
        self.assertTrue(all(not item["eligible"] for item in candidates))

    def test_validation_enforces_locked_cost_gates(self):
        selected = "CostRobustRoc10"
        rows = passing_rows(research.VALIDATION_SPLITS)
        result = research.validation_result(rows, selected, set(research.VALIDATION_SPLITS))
        self.assertEqual(result["status"], "PASS")
        for row in rows:
            if row["strategy"] == selected and row["split"] == "2025" and row["scenario"] == "severe":
                row["net_profit_usdt"] = -0.01
        result = research.validation_result(rows, selected, set(research.VALIDATION_SPLITS))
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
