from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from evaluate_profit_max_daily_v5_weighted_continuous import DAYS, FEE, TIMERANGE, load


class WeightedContinuousEvaluatorTests(unittest.TestCase):
    def _archive(self, root: Path, *, fee_close: float = FEE) -> Path:
        path = root / "result.zip"
        strategy = "ProfitMaxDailyCrossStop20AuditV2"
        result = {
            "strategy": {
                strategy: {
                    "timerange": TIMERANGE,
                    "backtest_days": DAYS,
                    "total_trades": 1,
                    "trades": [{
                        "fee_open": FEE,
                        "fee_close": fee_close,
                        "leverage": 1.0,
                        "stake_amount": 20.0,
                        "profit_abs": 1.0,
                    }],
                }
            }
        }
        config = {
            "dry_run_wallet": 1000.0,
            "fee": FEE,
            "stake_amount": 20,
            "max_open_trades": 2,
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "timeframe": "4h",
            "exchange": {
                "key": "REDACTED",
                "secret": "",
                "pair_whitelist": [f"PAIR{i}/USDT:USDT" for i in range(50)],
            },
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("result.json", json.dumps(result))
            archive.writestr("result_config.json", json.dumps(config))
        return path

    def test_accepts_exact_locked_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            value = load(self._archive(Path(tmp)), "ProfitMaxDailyCrossStop20AuditV2", 50, 20)
        self.assertEqual(value["total_trades"], 1)

    def test_rejects_trade_fee_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._archive(Path(tmp), fee_close=0.0005)
            with self.assertRaisesRegex(ValueError, "fee/leverage mismatch"):
                load(path, "ProfitMaxDailyCrossStop20AuditV2", 50, 20)


if __name__ == "__main__":
    unittest.main()
