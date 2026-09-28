from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import freeze_pro_day_v2_cycle2 as cycle2


class Cycle2FreezeTests(unittest.TestCase):
    def test_real_config_has_only_locked_cycle2_changes(self) -> None:
        config = cycle2.base.load_json_object(cycle2.ROOT / cycle2.CONFIG, "Cycle 2")
        base_config = cycle2.base.load_json_object(cycle2.ROOT / cycle2.BASE_CONFIG, "base")
        params = cycle2.validate_config(config, base_config)
        self.assertEqual(params["identifier"], cycle2.IDENTIFIER)
        self.assertEqual(params["purge_old_models"], 0)
        self.assertEqual(params["recursive_startup_counts"], cycle2.COUNTS)

    def test_model_capacity_mutation_is_rejected(self) -> None:
        config = cycle2.base.load_json_object(cycle2.ROOT / cycle2.CONFIG, "Cycle 2")
        base_config = cycle2.base.load_json_object(cycle2.ROOT / cycle2.BASE_CONFIG, "base")
        changed = copy.deepcopy(config)
        changed["freqai"]["model_training_parameters"]["max_depth"] = 5
        with self.assertRaises(cycle2.base.FreezeError):
            cycle2.validate_config(changed, base_config)

    def test_real_plan_and_inherited_hashes_validate(self) -> None:
        paths = {
            "plan": cycle2.ROOT / cycle2.PLAN,
            "base_plan": cycle2.ROOT / cycle2.BASE_PLAN,
            "strategy": cycle2.ROOT / cycle2.STRATEGY,
            "cycle1_decision": cycle2.ROOT / cycle2.CYCLE1_DECISION,
            "data_audit": cycle2.ROOT / cycle2.DATA_AUDIT,
            "runtime_compatibility": cycle2.ROOT / cycle2.RUNTIME,
        }
        cycle2.validate_plan(paths)

    def test_technical_evidence_is_fail_closed(self) -> None:
        valid = {
            "schema_version": "1.0",
            "status": "PASS",
            "candidate": "ProDayTraderV2",
            "cycle": cycle2.CYCLE,
            "total_tests": 33,
            "cycle1_terminal_decision": "PASS_NO_PNL",
            "model_training_performed": False,
            "backtest_performed": False,
            "pnl_evaluated": False,
            "live_trading_authorized": False,
        }
        cycle2.validate_technical(valid)
        invalid = dict(valid)
        invalid["pnl_evaluated"] = True
        with self.assertRaises(cycle2.base.FreezeError):
            cycle2.validate_technical(invalid)

    def test_exclusive_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            cycle2.base._write_exclusive(path, {"status": "first"})
            with self.assertRaises(cycle2.base.FreezeError):
                cycle2.base._write_exclusive(path, {"status": "second"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "first")


if __name__ == "__main__":
    unittest.main()
