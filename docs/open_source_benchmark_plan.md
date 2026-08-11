# Open-source Strategy Benchmark Plan

## Source and scope

- Repository: `freqtrade/freqtrade-strategies`
- Pinned commit reviewed: `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4`
- Source is mounted read-only from a temporary checkout; benchmark code is not
  modified or silently optimized.
- The repository itself warns that its strategies are educational, many were
  hyperoptimized, and results depend on exchange, pairs, timeframe, and period.

NostalgiaForInfinity was reviewed but excluded from this two-pair benchmark. Its
own documented operating assumptions recommend 40-80 pairs and 6-12 open
trades, which is materially different from this BTC/USDC + ETH/USDC project.

## Pre-declared benchmark set

Exactly three distinct ready-made strategies will be tested before results are
compared:

1. `Bandtastic` on 15m: Bollinger-band mean reversion with hyperoptimized
   defaults.
2. `SwingHighToSky` on 15m: CCI/RSI oscillator strategy with hyperoptimized
   defaults.
3. `Supertrend` on 1h: multi-Supertrend direction strategy with hyperoptimized
   defaults. Its own source warns that the indicator implementation has not
   been validated against an authoritative reference.

No defaults will be changed. This is a benchmark of available code, not a
search across its parameter spaces.

## Common evaluation conditions

- Binance Spot BTC/USDC and ETH/USDC.
- 1,000 USDC starting wallet, unlimited research stake, maximum two positions.
- Freqtrade worst-case Binance fee selection: 0.10% per entry and exit side.
- The same cooldown, stoploss guard, and max-drawdown portfolio overlay used by
  the custom trials. Freqtrade 2026.7 requires these protections in a strategy,
  so transparent wrapper subclasses add only the overlay; vendor signals and
  risk/ROI defaults remain unchanged.
- Train: `2024-04-01` to `2025-01-01` UTC.
- Validation: `2025-01-01` to `2026-01-01` UTC.
- Holdout: remains sealed unless a benchmark passes every gate in
  `docs/strategy_research_plan.md`.
- Lookahead and recursive analysis will run only for a benchmark that first
  passes the performance and trade-count gates.
