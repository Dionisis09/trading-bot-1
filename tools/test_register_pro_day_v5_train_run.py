from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import register_pro_day_v5_train_run as register


class RegisterTrainTests(unittest.TestCase):
    def test_exact_receipt_inventory_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / register.train.STAGING
            staging.mkdir(parents=True)
            (staging / ".last_result.json").write_text(
                json.dumps({"latest_backtest": "backtest-result-fixed.zip"}), encoding="utf-8"
            )
            (staging / "backtest-result-fixed.zip").write_bytes(b"zip")
            (staging / "backtest-result-fixed.meta.json").write_text("{}", encoding="utf-8")
            _, archive, meta = register.resolve_receipt(root)
            self.assertEqual(archive.name, "backtest-result-fixed.zip")
            self.assertEqual(meta.name, "backtest-result-fixed.meta.json")

    def test_extra_zip_or_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / register.train.STAGING
            staging.mkdir(parents=True)
            (staging / ".last_result.json").write_text(
                json.dumps({"latest_backtest": "../bad.zip"}), encoding="utf-8"
            )
            with self.assertRaises(register.train.TrainError):
                register.resolve_receipt(root)


if __name__ == "__main__":
    unittest.main()
