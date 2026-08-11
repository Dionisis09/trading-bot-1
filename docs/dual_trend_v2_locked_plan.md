# DualTrendFuturesV2 - Locked Challenger Plan

This document was written before the first V2 backtest. V2 is a challenger to
the already running V1 dry-run; it does not replace V1 unless every gate below
passes. No live keys, live orders, leverage increase, DCA, or martingale are in
scope.

## Fixed hypothesis

Keep the V1 daily 1d regime, 4h 30-candle breakout, RSI/ATR filters, 10-candle
channel exit, hard -10% stop, protections, and isolated 1x leverage. Add one
fixed, interpretable 4h confluence model inspired by commonly used TradingView
analysis concepts:

1. Directional movement: +DI > -DI for longs, mirrored for shorts.
2. Trend strength: ADX >= 25 and rising from the previous closed candle.
3. Participation: quote relative volume >= 1.10 versus the previous ten closed
   4h candles. The current candle is excluded from the comparison average.
4. Volume-weighted price location: close beyond VWMA20 and VWMA20 beyond SMA20,
   mirrored for shorts.

The entry must satisfy at least three of the four confirmations, plus ADX > 20,
the unchanged daily regime/breakout/RSI/ATR rules, and positive volume. This is
a confluence score, not a claim that software reproduces human cognition.

Add one fixed early-invalidation exit: an opposing DMI direction confirmed by
a close crossing the VWMA20. The unchanged V1 channel/daily-regime exits remain.

There is exactly one V2 candidate and no parameter search. All indicators use
closed candles. Relative volume uses `close * volume` so crypto contracts with
different nominal token prices are compared in approximate quote-volume terms.

## Fixed test matrix

Same six Binance USDT perpetual markets and same downloaded 4h/1d/funding/mark
data as V1:

- Train: 2021-01-01 through 2024-01-01.
- Validation: 2024-01-01 through 2026-01-01.
- Calendar folds: 2024 and 2025.
- Current regime: 2026-01-01 through 2026-08-01.
- Fee stress: 0.15% per side on train and validation.
- Lookahead analysis and recursive analysis at startup 800.

These periods have already been inspected during V1 development, so they are
walk-forward-style comparisons but are not a new sealed holdout. The first
genuinely new evidence after code freeze must come from parallel dry-run.

## Qualification gates

V2 can enter a parallel challenger dry-run only if all of these pass:

- Train: positive return and PF >= 1.20.
- Validation: at least 100 trades, positive return, PF >= 1.50, DD <= 12%.
- 2024: positive return, PF >= 1.20, at least 20 trades.
- Weak-regime 2025: return > V1's +2.64%, PF >= 1.15, DD <= V1's 12.69%, at
  least 20 trades.
- Current 2026: positive return, PF >= 1.30, DD <= 12%, at least 12 trades.
- Validation with 0.15% fee per side: positive return and PF >= 1.30.
- At least five of six pairs positive in validation; pair profit concentration
  <= 50%; winning-trade concentration <= 25%.
- Zero lookahead-biased entries/exits/indicators and no material recursive
  variance at startup 800.

Even a full pass authorizes only a separate small-stake dry-run. Replacing V1
would require future forward evidence; profitability is never guaranteed.
