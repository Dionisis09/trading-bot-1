# Cost-Robust Challenger - Locked Research Plan

## Status and evidence boundary

This plan is locked before the candidate backtests.  It does not authorize a
strategy change or live trading.  The active `DualTrendFuturesV2R` dry-run must
remain unchanged while this research runs.

All available historical periods have already been inspected during earlier
research.  Therefore neither the 2021-2023 selection set nor the 2024-current
validation set is a fresh sealed holdout.  Any winner is only an offline
challenger for later forward testing, not proof of future profitability.

## Motivation

The incumbent V2R is historically profitable overall, but its 2022 trades fail
the adverse execution-cost gate.  The failure is concentrated in late-2022
short trades.  Pair removal is prohibited because BNB and DOGE, the weak 2022
pairs, were profitable under severe costs in other training years.  A prior
4-of-4 confluence candidate was also worse and will not be retested.

## Fixed candidate matrix

Every candidate keeps the incumbent's universe, 4h timeframe, daily regime,
3-of-4 confluence, exits, protections, isolated 1x leverage, hard stop, and
ATR/exposure sizing.  Filters are direction-symmetric and pair-independent.

1. `CostRobustRoc5`: require absolute daily ROC63 above 5% in trade direction.
2. `CostRobustRoc10`: require absolute daily ROC63 above 10%.
3. `CostRobustEma1`: require EMA20/EMA50 directional separation of at least 1%
   of daily close.
4. `CostRobustAtr1`: raise minimum 4h ATR from 0.5% to 1% of price.
5. `CostRobustBreakout50`: replace the 30-candle breakout with 50 candles.
6. `CostRobustRoc5Ema1`: combine only the fixed 5% ROC and 1% EMA filters.

No thresholds, pairs, exits, or risk parameters may be changed after seeing
the results.  No seventh candidate may be introduced in this research cycle.

## Selection sequence and gates

Candidate selection uses the individual 2021, 2022, and 2023 windows with the
same archived Binance futures data and 0.05% backtest fee per side as the
incumbent.  For each year, deterministic moderate and severe cost scenarios
are applied to raw exported trades.

A candidate is eligible only if:

- source totals exactly reconcile with its exported trades;
- every 2021, 2022, and 2023 moderate scenario has positive net profit,
  profit factor at least 1.10, and realized drawdown at most 15%;
- every corresponding severe scenario has positive net profit, profit factor
  at least 1.00, and realized drawdown at most 20%;
- it has at least 20 trades in every training year, to avoid a trivial
  near-empty pass;
- aggregate standard-cost training profit remains positive.

Eligible candidates are ranked by the lowest yearly severe profit factor,
then aggregate severe net profit.  Only the top candidate is evaluated on the
fixed 2024, 2025, and current-2026 windows.  It must pass the same per-year
cost gates and retain at least 20 trades in 2024 and 2025.  Current 2026 is a
partial year, so its trade count is reported but has no minimum.

If no candidate passes training, or if the single selected candidate fails
validation, the decision is `RETAIN_V2R`.  Validation failure does not trigger
another candidate or threshold search.  Even a full pass produces
`OFFLINE_CHALLENGER_ONLY`; replacement requires a new forward comparison.
