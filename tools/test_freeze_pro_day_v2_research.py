from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import freeze_pro_day_v2_research as module


class ProDayV2FreezeTests(unittest.TestCase):
    def test_real_inputs_pass_check_only_without_pnl(self):
        manifest, ledger = module.freeze_research(write_output=False)
        self.assertEqual(manifest["status"], "RESEARCH_FROZEN")
        self.assertFalse(manifest["pnl_parsed"])
        self.assertFalse(manifest["model_training_performed"])
        self.assertEqual(ledger["qualification_runs"], [])
        self.assertEqual(len(manifest["frozen_parameters"]["features"]), 19)

    def test_model_parameter_mutation_is_refused(self):
        path = module.PROJECT_ROOT / module.DEFAULT_CONFIG
        payload = module.load_json_object(path, "config")
        payload = copy.deepcopy(payload)
        payload["freqai"]["model_training_parameters"]["max_depth"] = 5
        with self.assertRaisesRegex(module.FreezeError, "model parameters"):
            module.validate_config(payload)

    def test_runtime_digest_mutation_is_refused(self):
        path = module.PROJECT_ROOT / module.DEFAULT_RUNTIME
        payload = module.load_json_object(path, "runtime")
        payload = copy.deepcopy(payload)
        payload["expected_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(module.FreezeError, "runtime digest"):
            module.validate_runtime(payload)

    def test_data_hash_mutation_is_refused(self):
        path = module.PROJECT_ROOT / module.DEFAULT_DATA_AUDIT
        payload = module.load_json_object(path, "audit")
        payload = copy.deepcopy(payload)
        payload["canonical_files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(module.FreezeError, "changed after data audit"):
            module.validate_data_audit(payload, module.PROJECT_ROOT)

    def test_exclusive_manifest_and_ledger_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "manifest.json"
            ledger = Path(temp_dir) / "ledger.json"
            module.freeze_research(
                output_path=output,
                ledger_path=ledger,
                write_output=True,
                require_technical_evidence=False,
            )
            self.assertTrue(output.is_file())
            self.assertTrue(ledger.is_file())
            with self.assertRaisesRegex(module.FreezeError, "already exists"):
                module.freeze_research(
                    output_path=output,
                    ledger_path=ledger,
                    write_output=True,
                    require_technical_evidence=False,
                )


if __name__ == "__main__":
    unittest.main()
