# DualTrendFuturesV2 - Pro-Style Confluence Experiment

## Decision

`CHALLENGER_REJECTED_KEEP_V1_RUNNING`

The fixed V2 experiment produced materially better recent-period return and
profit factor than V1, but it failed the two locked drawdown gates. It was not
deployed, no parallel V2 container was started, and the existing
`DualTrendFuturesV1` dry-run remains active on port 8080. Live trading remains
unauthorized and no Binance API keys are present.

## What was added

V2 kept the V1 1d regime, 4h breakout, RSI/ATR filters, 10-candle channel exit,
hard -10% stop, portfolio protections, and isolated 1x leverage. Its entry
required at least three of four closed-candle confirmations:

1. DMI direction (+DI/-DI).
2. ADX >= 25 and rising.
3. Quote relative volume >= 1.10 versus the previous ten 4h candles.
4. Close/VWMA20/SMA20 directional alignment.

It also added an opposing-DMI plus VWMA-cross invalidation exit. These are
interpretable confluence rules inspired by common chart-analysis workflows;
they do not reproduce or simulate a human trader's mind.

The indicator meanings and implementation choices were checked against the
official TradingView documentation for [ADX and DMI](https://www.tradingview.com/support/solutions/43000589099-average-directional-index-adx/),
[multi-timeframe analysis](https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/),
[relative volume](https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/),
and [VWMA](https://www.tradingview.com/support/solutions/43000592293-volume-weighted-moving-average-vwma/).

## V1 versus V2

All figures below use the same six Binance USDT perpetual markets, downloaded
4h/1d/funding/mark archives, 10,000 USDT starting wallet, unlimited research
stake, four maximum positions, protections, and 1x leverage.

| Window | V1 return / PF / DD | V2 return / PF / DD | Return change |
|---|---:|---:|---:|
| Train 2021-2023 | +254.20% / 1.514 / 29.02% | +228.67% / 1.552 / 27.25% | -25.53 pp |
| Validation 2024-2025 | +45.04% / 1.390 / 13.07% | +74.74% / 1.737 / 14.69% | +29.69 pp |
| 2024 | +41.23% / 1.781 / 12.75% | +58.09% / 2.247 / 13.27% | +16.86 pp |
| 2025 | +2.64% / 1.060 / 12.69% | +10.53% / 1.303 / 14.68% | +7.88 pp |
| Current 2026-01/08 | +10.71% / 1.462 / 10.07% | +14.77% / 1.812 / 7.04% | +4.07 pp |
| Train, 0.15% fee/side | +222.70% / 1.451 / 31.38% | +200.53% / 1.483 / 29.61% | -22.17 pp |
| Validation, 0.15% fee/side | +35.73% / 1.307 / 14.14% | +64.63% / 1.628 / 15.63% | +28.89 pp |

V2 validation contained 128 trades (80 long, 48 short). All six pairs were
profitable. Pair-profit concentration was 41.02%, and the largest winning trade
represented 13.47% of total winning-trade profit; both passed their limits.

## Locked-gate result

V2 passed 15 of 17 performance gates. The two failures were:

- Validation drawdown 14.69% versus the locked maximum 12%.
- 2025 drawdown 14.68% versus V1's locked comparison ceiling 12.69%.

The limits were not relaxed after seeing the result. Because every gate was
required, V2 was rejected for deployment despite its stronger validation
return and PF.

## Technical and data validation

- Raw trade rows reconcile exactly with Freqtrade trade count, absolute profit,
  PF, wins, and losses for all seven V2 runs.
- The same audited futures data used for V1 retains 100% coverage of the declared
  periods, no duplicates/nulls/invalid OHLCV/gaps, and only the already-recorded
  isolated 4h-to-1d mismatch days below 0.2%.
- Freqtrade lookahead analysis: 100 signals, zero biased entries, zero biased
  exits, and no biased indicators.
- Recursive analysis at startup 800: EMA200 1d variance -0.005%, below the
  pre-declared 0.01% materiality limit.
- The executed notebook has 15 cells, six executed code cells, and zero errors.
- Runtime re-check: `DualTrendFuturesV1` is still running in futures dry-run;
  V2 was never activated.

## Interpretation and next experiment

The result supports the signal-confluence hypothesis but does not support
immediate replacement of V1. Historical periods were already visible during
V1 research, so this is comparative selection evidence rather than a new
sealed holdout. Unlimited-stake compounding also differs from the deployed
25-USDT fixed stake.

If development continues, the clean next experiment is a separately locked
risk overlay around the unchanged V2 signals: volatility-normalized position
sizing and a portfolio exposure budget. It should be evaluated against V1 at
matched risk, then require genuinely new parallel dry-run evidence. Indicator
threshold tuning on the same periods should be avoided.

## Reproducible artifacts

- Locked plan: `docs/dual_trend_v2_locked_plan.md`
- Strategy: `user_data/strategies/DualTrendFuturesV2.py`
- Executed notebook: `user_data/notebooks/dual_trend_v2_validation.ipynb`
- Summary: `user_data/reports/dual_trend_v2_backtest_summary.csv`
- V1 comparison: `user_data/reports/dual_trend_v2_vs_v1.csv`
- Raw-row reconciliation: `user_data/reports/dual_trend_v2_backtest_reconciliation.csv`
- Gate matrix: `user_data/reports/dual_trend_v2_performance_gates.csv`
- Pair audit: `user_data/reports/dual_trend_v2_validation_pairs.csv`
- Lookahead result: `user_data/reports/DualTrendFuturesV2_lookahead.csv`
- Machine decision: `user_data/reports/dual_trend_v2_validation_decision.json`
