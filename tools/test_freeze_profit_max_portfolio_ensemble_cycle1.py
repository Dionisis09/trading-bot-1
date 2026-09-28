import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from freeze_profit_max_portfolio_ensemble_cycle1 import validate_archive  # noqa: E402


class PortfolioFreezeTests(unittest.TestCase):
    def _archive(self, config_overrides=None):
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "cross.zip"
        config = {
            "dry_run_wallet": 1000, "trading_mode": "futures", "margin_mode": "isolated",
            "timeframe": "4h", "fee": 0.00075, "stake_amount": 50, "max_open_trades": 2,
            "exchange": {"key": "", "secret": "", "pair_whitelist": [f"P{i}" for i in range(50)]},
        }
        config.update(config_overrides or {})
        result = {"strategy": {"ProfitMaxCrossSectionalTopTwo8h": {
            "timerange": "20210101-20240101", "backtest_days": 1095, "total_trades": 936,
        }}}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("result.json", json.dumps(result))
            archive.writestr("result_config.json", json.dumps(config))
        return temporary, path

    def test_accepts_exact_cross_contract(self):
        temporary, path = self._archive()
        try:
            validate_archive(path)
        finally:
            temporary.cleanup()

    def test_rejects_embedded_credential(self):
        temporary, path = self._archive({"exchange": {
            "key": "secret", "secret": "", "pair_whitelist": [f"P{i}" for i in range(50)]
        }})
        try:
            with self.assertRaisesRegex(ValueError, "contract mismatch"):
                validate_archive(path)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
