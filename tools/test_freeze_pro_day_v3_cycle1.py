from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import freeze_pro_day_v3_cycle1 as freeze


ROOT = Path(__file__).resolve().parents[1]


class FreezeProDayV3Tests(unittest.TestCase):
    def test_current_plan_and_config_validate(self) -> None:
        freeze.validate_plan(ROOT / freeze.PLAN)
        freeze.validate_config(json.loads((ROOT / freeze.CONFIG).read_text(encoding="utf-8")))

    def test_freqai_or_live_authorization_is_rejected(self) -> None:
        config = json.loads((ROOT / freeze.CONFIG).read_text(encoding="utf-8"))
        config["freqai"] = {}
        with self.assertRaises(freeze.FreezeError):
            freeze.validate_config(config)
        config = json.loads((ROOT / freeze.CONFIG).read_text(encoding="utf-8"))
        config["pro_day_v3_research"]["live_trading_authorized"] = True
        with self.assertRaises(freeze.FreezeError):
            freeze.validate_config(config)

    def test_data_hash_mutation_is_rejected(self) -> None:
        audit = json.loads((ROOT / freeze.AUDIT).read_text(encoding="utf-8"))
        changed = copy.deepcopy(audit)
        changed["canonical_files"][0]["sha256"] = "0" * 64
        with self.assertRaises(freeze.FreezeError):
            freeze.validate_data(changed, ROOT)


if __name__ == "__main__":
    unittest.main()
