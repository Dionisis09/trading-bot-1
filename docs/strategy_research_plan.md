# Binance Spot Strategy Research Plan

## Objective

Develop and validate a long-only BTC/USDC and ETH/USDC strategy for Binance Spot. The objective is robust capital growth with controlled drawdown, not maximum backtest profit.

## Pre-declared hypothesis

Crypto returns may exhibit time-series momentum. A long-only strategy should participate only when the 1-hour market regime is positive, then use a 15-minute trend-reclaim entry to avoid buying every short-lived price spike.

The first implementation will deliberately use a small number of conventional, fixed rules:

- 1h EMA trend regime and ADX strength filter.
- 15m EMA alignment and price reclaim.
- RSI range filter to avoid weak or severely extended entries.
- ATR percentage filter to reject abnormally quiet or unstable candles.
- Positive volume and rolling-volume confirmation.
- Fixed protective stop, delayed trailing stop, and explicit trend-failure exit.

No FreqAI, hyperopt, grid search, or holdout-driven parameter selection is allowed in V1.

## Data and fixed splits

- Source: Binance public Spot OHLCV through Freqtrade 2026.7 / CCXT 4.5.68.
- Base timeframe: 15m.
- Informative timeframe: 1h.
- Pairs: BTC/USDC and ETH/USDC.
- Fee assumption: 0.10% per side, selected by Freqtrade as the conservative lowest-tier Binance fee.
- Train/sanity window: `2024-04-01` to `2025-01-01` UTC.
- Validation window: `2025-01-01` to `2026-01-01` UTC.
- Final holdout: `2026-01-01` to `2026-08-01` UTC.

The historical discontinuity from `2022-09-29` to `2023-03-12` must never be crossed by a reported backtest.

## Portfolio assumptions for research

- Starting wallet: 1,000 USDC.
- Maximum simultaneous positions: 2.
- Research stake: `unlimited`, so available capital is divided across available slots.
- Long-only Spot; no leverage, margin, shorting, DCA, or position adjustment.
- Protections enabled during decision backtests.

The running dry-run bot keeps its separate conservative 25 USDC stake.

## Acceptance gates

The validation window must pass all gates before the final holdout is evaluated:

1. Freqtrade lookahead analysis reports no biased entries, exits, or indicators.
2. Recursive analysis shows no material indicator variance at the declared startup candle count.
3. At least 30 closed trades across the validation window.
4. Positive total return after the 0.10% per-side fee assumption.
5. Profit factor at least 1.10.
6. Maximum portfolio drawdown no greater than 15%.
7. No individual pair may have profit factor below 0.90.
8. Results must not depend on one single trade for the majority of total profit.

If validation passes, the untouched holdout must then have:

- Positive total return.
- Profit factor at least 1.00.
- Maximum portfolio drawdown no greater than 15%.
- No lookahead or recursive bias findings.

Passing these gates permits dry-run deployment only. It does not permit live trading.

## Stability checks after the fixed V1 result

- Adjacent EMA and RSI thresholds may be tested only as sensitivity checks.
- Results should degrade gradually rather than flip from strongly positive to strongly negative.
- The number of tested variants must be recorded.
- Holdout results must not be used to select a variant.

## Trial log

- Trial 1, `BinanceSpotTrendV1`: signal and risk thresholds were tested exactly
  as pre-declared. Recursive analysis found about 0.10% residual variation in
  the 1h EMA200 at a 400-candle warm-up, so `startup_candle_count` was raised to
  800. This validity correction was selected from indicator convergence only;
  no entry, exit, stop, or profit parameter changed.

## Evidence artifacts

- Data-quality notebook: `user_data/notebooks/binance_ohlcv_data_quality.ipynb`
- Data-quality tables: `user_data/reports/data_quality_*.csv`
- Backtest exports: `user_data/backtest_results/`
- Strategy source: `user_data/strategies/BinanceSpotTrendV1.py`

## Research basis

- Trend-following in cryptocurrencies is treated only as a testable hypothesis, not a guaranteed effect.
- Backtest overfitting risk is controlled by pre-declaration, chronological splits, a sealed holdout, low trial count, and explicit bias checks.
