import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data/strategies"))

from ProfitMaxCrossSectionalFourHour import (  # noqa: E402
    ProfitMaxCrossSectionalTopTwo4h,
    ProfitMaxCrossSectionalTopTwo4hPositive,
)


class ProfitMaxCrossSectionalFourHourTests(unittest.TestCase):
    def test_contract_and_exact_four_hour_exit(self):
        strategy = object.__new__(ProfitMaxCrossSectionalTopTwo4h)
        self.assertEqual((strategy.momentum_candles, strategy.top_n, strategy.hold_hours), (180, 2, 4))
        opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trade = SimpleNamespace(open_date_utc=opened)
        self.assertIsNone(strategy.custom_exit("BTC/USDT:USDT", trade, opened + timedelta(hours=3), 1, 0))
        self.assertEqual(
            strategy.custom_exit("BTC/USDT:USDT", trade, opened + timedelta(hours=4), 1, 0),
            "fixed_4h_rebalance",
        )

    def test_positive_filter_uses_only_trailing_completed_prices(self):
        strategy = object.__new__(ProfitMaxCrossSectionalTopTwo4hPositive)
        strategy._rank_cache = pd.DataFrame(
            {
                "rank_count": [50.0, 50.0],
                "btc_bull": [True, True],
                "rank::BTC/USDT:USDT": [50.0, 50.0],
            },
            index=pd.to_datetime(["2026-01-01 00:00", "2026-01-01 04:00"], utc=True),
        )
        dates = pd.date_range("2025-12-02", periods=182, freq="4h", tz="UTC")
        close = [100.0] * 181 + [101.0]
        frame = pd.DataFrame(
            {"date": dates, "open": close, "high": close, "low": close, "close": close, "volume": 1.0}
        )
        # The formula is explicit and has no future shift or global normalization.
        result = strategy.populate_indicators(frame, {"pair": "BTC/USDT:USDT"})
        expected = result["close"] / result["close"].shift(180) - 1.0
        pd.testing.assert_series_equal(result["absolute_momentum_30d"], expected, check_names=False)


if __name__ == "__main__":
    unittest.main()
