"""Fail-closed account-level entry guard for the locked dry-run strategies."""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from freqtrade.persistence import Trade


logger = logging.getLogger(__name__)


class ProfessionalRiskMixin:
    """Reject new entries when account-level loss or exposure limits are breached."""

    _risk_policy_cache: dict[str, Any] | None = None
    _risk_policy_mtime_ns: int | None = None
    _risk_policy_cached_path: Path | None = None

    def _risk_policy_path(self) -> Path:
        configured = os.environ.get("PRO_RISK_POLICY_PATH")
        if configured:
            return Path(configured)
        user_data_dir = self.config.get("user_data_dir", "user_data")
        return Path(user_data_dir) / "risk_policy.json"

    def _risk_policy(self) -> dict[str, Any]:
        path = self._risk_policy_path()
        metadata = path.stat()
        if (
            self._risk_policy_cache is None
            or self._risk_policy_cached_path != path
            or self._risk_policy_mtime_ns != metadata.st_mtime_ns
        ):
            value = json.loads(path.read_text(encoding="utf-8"))
            limits = value.get("limits")
            if not isinstance(limits, dict):
                raise ValueError("risk policy has no limits object")
            required_positive = (
                "maximum_daily_realized_loss_pct",
                "maximum_weekly_realized_loss_pct",
                "maximum_wallet_drawdown_pct",
                "maximum_total_open_stake_pct",
                "maximum_open_trades",
            )
            for key in required_positive:
                number = limits.get(key)
                if isinstance(number, bool) or not isinstance(number, (int, float)) or number <= 0:
                    raise ValueError(f"risk policy limit {key} must be positive")
            if value.get("live_launch", {}).get("authorized") is not False:
                raise ValueError("risk policy must remain fail-closed during qualification")
            self._risk_policy_cache = value
            self._risk_policy_mtime_ns = metadata.st_mtime_ns
            self._risk_policy_cached_path = path
        return self._risk_policy_cache

    @staticmethod
    def _closed_profit_since(since: datetime) -> float:
        profit = 0.0
        for trade in Trade.get_trades_proxy(is_open=False, close_date=since):
            value = getattr(trade, "close_profit_abs", None)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                profit += float(value)
        return profit

    @staticmethod
    def _maximum_closed_wallet_drawdown_pct(starting_wallet: float) -> float:
        records: list[tuple[datetime, float]] = []
        for trade in Trade.get_trades_proxy(is_open=False):
            profit = getattr(trade, "close_profit_abs", None)
            if isinstance(profit, bool) or not isinstance(profit, (int, float)) or not math.isfinite(profit):
                raise ValueError("closed trade profit is unavailable")
            closed_at = getattr(trade, "close_date_utc", None) or getattr(trade, "close_date", None)
            if isinstance(closed_at, str):
                closed_at = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            if not isinstance(closed_at, datetime):
                raise ValueError("closed trade timestamp is unavailable")
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=timezone.utc)
            records.append((closed_at.astimezone(timezone.utc), float(profit)))
        equity = starting_wallet
        peak = starting_wallet
        maximum_drawdown_pct = 0.0
        for _, profit in sorted(records, key=lambda item: item[0]):
            equity += profit
            peak = max(peak, equity)
            maximum_drawdown_pct = max(
                maximum_drawdown_pct,
                max(0.0, peak - equity) / starting_wallet * 100.0,
            )
        return maximum_drawdown_pct

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> bool:
        """Allow an entry only when every locked account guardrail passes."""

        try:
            policy = self._risk_policy()
            limits = policy["limits"]
            now = current_time
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            else:
                now = now.astimezone(timezone.utc)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = day_start - timedelta(days=day_start.weekday())
            wallet = float(self.wallets.get_total_stake_amount())
            if not math.isfinite(wallet) or wallet <= 0:
                raise ValueError("wallet total is unavailable")
            starting_wallet = float(self.config.get("dry_run_wallet"))
            if not math.isfinite(starting_wallet) or starting_wallet <= 0:
                raise ValueError("starting wallet is unavailable")
            daily_loss_pct = max(0.0, -self._closed_profit_since(day_start)) / starting_wallet * 100.0
            weekly_loss_pct = max(0.0, -self._closed_profit_since(week_start)) / starting_wallet * 100.0
            wallet_drawdown_pct = max(
                self._maximum_closed_wallet_drawdown_pct(starting_wallet),
                max(0.0, starting_wallet - wallet) / starting_wallet * 100.0,
            )
            open_count = int(Trade.get_open_trade_count())
            open_stake = float(Trade.total_open_trades_stakes())
            proposed_stake = abs(float(amount) * float(rate))
            leverage = float(kwargs.get("leverage", 1.0) or 1.0)
            if leverage > 0:
                proposed_stake /= leverage
            projected_open_stake_pct = (open_stake + proposed_stake) / wallet * 100.0
            allowed = (
                daily_loss_pct < float(limits["maximum_daily_realized_loss_pct"])
                and weekly_loss_pct < float(limits["maximum_weekly_realized_loss_pct"])
                and wallet_drawdown_pct
                <= float(limits["maximum_wallet_drawdown_pct"])
                and open_count < int(limits["maximum_open_trades"])
                and projected_open_stake_pct
                <= float(limits["maximum_total_open_stake_pct"])
            )
        except Exception as exc:
            logger.error("Professional risk guard failed closed for %s: %s", pair, exc)
            return False
        if not allowed:
            logger.warning(
                "Professional risk guard rejected %s %s: daily_loss=%.3f%% weekly_loss=%.3f%% wallet_drawdown=%.3f%% projected_open_stake=%.3f%% open_trades=%d",
                side,
                pair,
                daily_loss_pct,
                weekly_loss_pct,
                wallet_drawdown_pct,
                projected_open_stake_pct,
                open_count,
            )
        return allowed
