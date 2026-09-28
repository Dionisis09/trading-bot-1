import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evaluate_profit_max_portfolio_train import (  # noqa: E402
    EXPECTED_CORE_PAIRS,
    evaluate,
    load,
    maximum_exposure,
    wallet_drawdown_pct,
)


def trade(pair, opened, closed, profit, stake=30.0):
    return {"pair": pair, "open_timestamp": opened, "close_timestamp": closed,
            "open_date": "2021-01-01 00:00:00+00:00", "close_date": "2021-01-01 04:00:00+00:00",
            "profit_abs": profit, "stake_amount": stake, "fee_open": 0.00075, "fee_close": 0.00075}


class PortfolioEvaluatorTests(unittest.TestCase):
    def _archive(self, folder: Path, *, max_open=2, fee=0.00075, stake=50):
        path = folder / "result.zip"
        row = trade("BTC/USDT:USDT", 1, 2, 1, 30)
        row["leverage"] = 1.0
        result = {"strategy": {"DualTrendFuturesV1": {
            "backtest_days": 1095, "timerange": "20210101-20240101",
            "total_trades": 1, "trades": [row],
        }}}
        config = {
            "dry_run_wallet": 1000.0, "trading_mode": "futures", "margin_mode": "isolated",
            "timeframe": "4h", "fee": fee, "stake_amount": stake,
            "max_open_trades": max_open,
            "exchange": {"key": "", "secret": "", "pair_whitelist": sorted(EXPECTED_CORE_PAIRS)},
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("result.json", json.dumps(result))
            archive.writestr("result_config.json", json.dumps(config))
        return path

    def test_exact_v1_overlap_is_removed(self):
        cross = {"trades": [trade("X", 1, 2, 1)] * 1095}
        v5 = {"trades": [trade("A", 3, 4, 1)]}
        v1 = {"trades": [trade("A", 3, 5, 9), trade("B", 6, 7, 1)] * 20}
        result = evaluate(cross, v5, v1)
        self.assertEqual(result["deduplication"]["v1_exact_v5_overlaps_removed"], 20)
        self.assertEqual(result["deduplication"]["v1_retained_trades"], 20)

    def test_wallet_drawdown_groups_same_timestamp(self):
        trades = [trade("A", 1, 3, -10), trade("B", 1, 3, 5), trade("C", 4, 5, 20)]
        self.assertEqual(wallet_drawdown_pct(trades), 0.5)

    def test_exposure_uses_half_open_intervals(self):
        trades = [trade("A", 1, 3, 1, 30), trade("B", 3, 4, 1, 40)]
        self.assertEqual(maximum_exposure(trades), (1, 40.0))

    def test_load_accepts_exact_embedded_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = load(self._archive(Path(temporary), max_open=1), "DualTrendFuturesV1", 1, 6)
        self.assertEqual(result["total_trades"], 1)

    def test_load_rejects_wrong_fee_or_slot_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(Path(temporary), max_open=2, fee=0.0005)
            with self.assertRaisesRegex(ValueError, "embedded config contract mismatch"):
                load(path, "DualTrendFuturesV1", 1, 6)


if __name__ == "__main__":
    unittest.main()
