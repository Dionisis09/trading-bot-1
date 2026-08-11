# Locked Forward-Monitoring Plan

## Purpose and safety boundary

This plan was locked before the first automated monitoring snapshot. It compares
the active `DualTrendFuturesV1` control with the selected
`DualTrendFuturesV2R` candidate using new, credential-free Binance Futures
dry-run evidence.

The monitor is read-only. It uses only Freqtrade `GET` endpoints and cannot
start, stop, enter, exit, delete, or modify trades. A passing result means only
`FORWARD_REVIEW_READY`; it never enables live trading, adds exchange
credentials, or automatically replaces V1.

## Runtime and evidence contract

- Control API: `freqtrade:8080` inside Compose (`127.0.0.1:8080` on the host).
- Candidate API: `freqtrade-v2r:8080` inside Compose (`127.0.0.1:8081` on the host).
- Snapshot cadence: immediately at monitor startup and every 4 hours.
- Monitoring epoch: the first successful installation run, persisted in
  `forward_monitor_state.json` and never reset by a normal restart.
- Official Freqtrade read endpoints: `/ping`, `/show_config`, `/profit`,
  `/count`, and paginated `/trades?limit=500&offset=...`.
- Starting wallet for normalized metrics: the configured 1,000 USDT dry-run
  wallet for each bot.

The Freqtrade REST API documents a maximum of 500 trades per `/trades` call,
so the monitor must paginate until `total_trades` is exhausted.

## Recomputed metrics

The monitor independently recomputes all decision metrics from closed trades:

- net and gross profit in USDT;
- wins, losses, breakeven trades, and win rate;
- profit factor;
- average and median trade profit ratio;
- return as a percentage of the configured starting wallet;
- chronological maximum drawdown as a percentage of the starting wallet;
- return/max-drawdown ratio;
- pair breadth and long/short counts.

The API-reported closed count, closed profit, wins, losses, and profit factor
are reconciled against the recomputation. Empty samples produce `null` for
undefined metrics such as profit factor; they are never represented as
infinity or treated as a pass.

## Data-quality and runtime gates

Every bot must satisfy all of the following:

- API reachable and response schema valid;
- runtime is `dry_run=true`, `trading_mode=futures`, isolated margin, running,
  and short-capable;
- runtime strategy matches the expected V1 or V2R class;
- local Binance key and secret remain empty;
- no duplicate trade IDs;
- all closed trades contain ID, pair, close time, absolute profit, and profit
  ratio;
- API and recomputed closed-trade statistics reconcile within numeric
  tolerance.

## Forward-review gates

These thresholds are fixed before collecting the first snapshot. All must pass:

1. At least 30 calendar days have elapsed since the monitoring epoch.
2. V1 has at least 30 closed trades.
3. V2R has at least 30 closed trades.
4. V2R traded at least 4 distinct pairs.
5. V2R net profit is positive.
6. V2R profit factor is at least 1.20.
7. V2R maximum drawdown is no more than 10% of its starting wallet.
8. V2R return/max-drawdown is positive and defined.
9. V2R profit factor is no more than 0.10 below V1.
10. V2R return/max-drawdown is at least as high as V1.
11. All runtime and data-quality gates pass for both bots.

Thirty trades is a minimum review threshold, not statistical proof. If the
strategy trades slowly, the observation period continues beyond 30 days until
both minimum trade counts are reached.

## Decision states

- `MONITORING_ERROR`: an API, schema, safety, or evidence-integrity failure
  prevents a valid decision.
- `INSUFFICIENT_FORWARD_SAMPLE`: fewer than 30 days or 30 closed trades per bot.
- `FORWARD_GATES_FAILED_KEEP_RUNNING`: the sample is large enough, but at least
  one performance or breadth gate failed.
- `FORWARD_REVIEW_READY`: every locked gate passed and a human review may begin.

For every state, `live_trading_authorized=false` and
`auto_promotion_enabled=false`.

## Artifacts

- `user_data/reports/forward_monitor_latest.json`: latest complete snapshot.
- `user_data/reports/forward_monitor_decision.json`: current gate decision.
- `user_data/reports/forward_monitor_history.csv`: append-only bot-level trend.
- `user_data/reports/forward_monitor_state.json`: persistent monitoring epoch.

Historical backtests and forward dry-runs are simulations, not a guarantee of
future profit. Futures and short exposure can lose capital quickly.
