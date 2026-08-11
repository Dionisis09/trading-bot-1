import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
if str(STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGY_DIR))

import ProfessionalRisk as professional_risk


class Wallets:
    def __init__(self, total: float = 1000.0) -> None:
        self.total = total

    def get_total_stake_amount(self) -> float:
        return self.total


class Guard(professional_risk.ProfessionalRiskMixin):
    def __init__(self, user_data_dir: Path) -> None:
        self.config = {"user_data_dir": user_data_dir}
        self.wallets = Wallets()


class ProfessionalRiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "risk_policy.json").write_text(
            json.dumps(
                {
                    "limits": {
                        "maximum_daily_realized_loss_pct": 2.0,
                        "maximum_weekly_realized_loss_pct": 5.0,
                        "maximum_wallet_drawdown_pct": 10.0,
                        "maximum_total_open_stake_pct": 20.0,
                        "maximum_open_trades": 2,
                    },
                    "live_launch": {"authorized": False},
                }
            ),
            encoding="utf-8",
        )
        self.environment = patch.dict(
            os.environ,
            {"PRO_RISK_POLICY_PATH": str(self.root / "risk_policy.json")},
        )
        self.environment.start()
        self.now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
        self.guard = Guard(self.root)
        self.guard.config["dry_run_wallet"] = 1000.0

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def evaluate(self, closed_profits, open_count=0, open_stake=0.0, amount=0.001, rate=50_000.0):
        trades = [
            SimpleNamespace(close_profit_abs=value, close_date_utc=self.now)
            for value in closed_profits
        ]
        with (
            patch.object(professional_risk.Trade, "get_trades_proxy", return_value=trades),
            patch.object(professional_risk.Trade, "get_open_trade_count", return_value=open_count),
            patch.object(professional_risk.Trade, "total_open_trades_stakes", return_value=open_stake),
        ):
            return self.guard.confirm_trade_entry(
                "BTC/USDT:USDT",
                "limit",
                amount,
                rate,
                "GTC",
                self.now,
                None,
                "long",
                leverage=1.0,
            )

    def test_allows_entry_inside_every_limit(self) -> None:
        self.assertTrue(self.evaluate([-5.0, 3.0], open_count=1, open_stake=25.0))

    def test_rejects_entry_at_daily_loss_limit(self) -> None:
        self.assertFalse(self.evaluate([-20.0]))

    def test_rejects_projected_exposure_above_limit(self) -> None:
        self.assertFalse(self.evaluate([], open_count=1, open_stake=175.0))

    def test_rejects_wallet_drawdown_above_limit(self) -> None:
        self.guard.wallets.total = 899.0
        self.assertFalse(self.evaluate([]))

    def test_missing_policy_fails_closed(self) -> None:
        (self.root / "risk_policy.json").unlink()
        self.guard._risk_policy_cache = None
        self.assertFalse(self.evaluate([]))


if __name__ == "__main__":
    unittest.main()
