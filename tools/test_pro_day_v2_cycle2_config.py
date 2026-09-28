from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = ROOT / "user_data/config-pro-day-v2-research.json"
CYCLE2_CONFIG = ROOT / "user_data/config-pro-day-v2-cycle2-research.json"
ADDENDUM = ROOT / "docs/pro_day_trader_v2_cycle2_locked_plan.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path.name} root is not an object")
    return value


class ProDayV2Cycle2ConfigTests(unittest.TestCase):
    def test_only_declared_cycle2_config_fields_changed(self) -> None:
        base = load(BASE_CONFIG)
        cycle2 = load(CYCLE2_CONFIG)
        normalized = copy.deepcopy(cycle2)
        normalized["bot_name"] = base["bot_name"]
        normalized["freqai"]["identifier"] = base["freqai"]["identifier"]
        normalized["freqai"]["purge_old_models"] = base["freqai"]["purge_old_models"]
        normalized["pro_day_v2_research"] = base["pro_day_v2_research"]
        self.assertEqual(normalized, base)

    def test_cycle2_namespace_and_technical_controls_are_exact(self) -> None:
        config = load(CYCLE2_CONFIG)
        self.assertEqual(config["bot_name"], "pro-day-trader-v2-cycle2-research")
        self.assertEqual(
            config["freqai"]["identifier"],
            "proday-v2-cycle2-canonical5m-lgbm-20260811",
        )
        self.assertEqual(config["freqai"]["purge_old_models"], 0)
        meta = config["pro_day_v2_research"]
        self.assertEqual(meta["cycle"], "pro_day_v2_cycle2")
        self.assertEqual(meta["recursive_startup_counts"], [199, 399, 799, 1599, 2399])
        self.assertEqual(meta["canonical_container_datadir"], "/canonical")
        self.assertEqual(meta["canonical_futures_mount"], "/canonical/futures")
        self.assertIs(meta["retain_all_fold_models_for_audit"], True)
        self.assertIs(meta["live_trading_authorized"], False)

    def test_inherited_file_hashes_match_the_addendum(self) -> None:
        text = ADDENDUM.read_text(encoding="utf-8")
        expected = {
            ROOT / "docs/pro_day_trader_v2_locked_plan.md":
                "707793fc95cc99f9663e354ed5ddae90cfb753a48e773d46ac1759d11bc11e6d",
            ROOT / "user_data/strategies/ProDayTraderV2.py":
                "6041f416e4c951b83b5f9cef5438319fd4f24d1d296eb37fd499415a00e47f45",
            ROOT / "user_data/reports/pro_day_v2_cycle1/canonical_data_audit.json":
                "f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772",
            ROOT / "user_data/reports/pro_day_v2_cycle1/runtime_compatibility.json":
                "155dbfe16892d5d4616ee1186d29678ea2baaab51cb84ea1673caaa7ed22ca1b",
            ROOT / "user_data/reports/pro_day_v2_cycle1/final_decision.json":
                "fdac3459fb940617371fb772ec5819e8254dc0a53d3ca0c78134f793c2b87dc9",
        }
        for path, digest in expected.items():
            self.assertEqual(sha256(path), digest, path.name)
            self.assertIn(digest, text)

    def test_locked_strategy_and_model_capacity_are_unchanged(self) -> None:
        base = load(BASE_CONFIG)
        cycle2 = load(CYCLE2_CONFIG)
        self.assertEqual(
            cycle2["freqai"]["feature_parameters"],
            base["freqai"]["feature_parameters"],
        )
        self.assertEqual(
            cycle2["freqai"]["data_split_parameters"],
            base["freqai"]["data_split_parameters"],
        )
        self.assertEqual(
            cycle2["freqai"]["model_training_parameters"],
            base["freqai"]["model_training_parameters"],
        )
        self.assertEqual(
            sha256(ROOT / "user_data/strategies/ProDayTraderV2.py"),
            "6041f416e4c951b83b5f9cef5438319fd4f24d1d296eb37fd499415a00e47f45",
        )


if __name__ == "__main__":
    unittest.main()
