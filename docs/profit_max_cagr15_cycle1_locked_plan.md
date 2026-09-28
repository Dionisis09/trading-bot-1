# ProfitMax CAGR15 Cycle 1 — Locked Research Plan

Locked before any Cycle 1 PnL run. This cycle uses already-seen historical data and
therefore provides retrospective robustness evidence only. It cannot guarantee future
profit and cannot authorize live trading.

## Objective and fixed candidate

- Candidate: `ProfitMaxCagr15V1`.
- Signal and exit logic: exactly inherited from the already technically qualified
  `ProfitMaxV5Asymmetric50`; this cycle does not tune indicators or entry thresholds.
- Exchange model: Binance USD-M futures, isolated margin, leverage 1x.
- Universe: BTC, ETH, BNB, XRP, ADA and DOGE USDT perpetuals.
- Base timeframe: 4h.
- Initial wallet: 1,000 USDT.
- Configured stake: 350 USDT, passed through the existing ATR exposure overlay
  (`0.65 * volatility_scalar`, scalar fixed to `[0.50, 1.00]`).
- Shorts retain the existing fixed 0.50 stake multiplier.
- Maximum open trades: 2.
- Baseline fee: exactly 0.075% per side; recorded funding is included by Freqtrade.
- Continuous timerange: `20210101-20260801` (2,038 days).
- There is no trade-frequency gate.

The candidate and stake are fixed before the result. No alternate stake, signal patch,
pair deletion or side deletion may be selected after seeing Cycle 1 PnL.

## Baseline gates

All must pass:

1. Exact fee fields on every trade: `0.00075` open and close.
2. CAGR >= 15.0%, computed from the Freqtrade initial wallet and final absolute profit.
3. Profit factor >= 2.00.
4. Freqtrade wallet-curve maximum drawdown <= 12.0%.
5. Return / drawdown >= 10.0.
6. Every full calendar year 2021–2025 has net profit > 0.
7. Partial 2026 through 2026-08-01 has return > -2.0%.
8. Both long and short trades are present.
9. Observed peak concurrent stake <= 50% of initial wallet.

## Locked cost stress

The same raw trades and order prices are used. Extra costs are applied to entry and
exit notionals without repricing outcomes.

- Moderate: additional 0.05% per side; CAGR >= 13%, PF >= 1.70, realized DD <= 15%.
- Severe: additional 0.10% per side; CAGR >= 10%, PF >= 1.40, realized DD <= 18%.

## Technical evidence and decision

The candidate adds no indicator, signal, exit or callback logic. It inherits the source
that passed pair-isolated lookahead analysis and recursive analysis in
`user_data/reports/profit_max_swing_cycle5/technical_qualification.json`. Cycle 1 must
record and hash that evidence plus the new plan, strategy, config and result archive.

- Any source/config/data/fee/reconciliation failure: `REJECT_CAGR15_CYCLE1`.
- Technically valid but any performance/risk/stress gate failure:
  `KEEP_OFFLINE_RESEARCH`.
- Every gate pass: `APPROVE_ISOLATED_DRY_RUN_ONLY`.
- Live trading remains unauthorized in every outcome.
