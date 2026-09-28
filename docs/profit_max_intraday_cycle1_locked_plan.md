# ProfitMax Intraday Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_DATA_DOWNLOAD_AND_PNL`. Research only. This cycle cannot authorize live trading.

## Objective

Build a separate causal intraday challenger that closes an average of **1.0 to 2.0 trades per UTC calendar day** across the complete portfolio while remaining profitable after realistic futures costs. Frequency is a hard qualification gate, not a target that may be relaxed after results. The active 4h V1, V2R and ProfitMaxV5 dry-runs remain unchanged.

All historical periods have already been seen in prior research. TRAIN and VALIDATION below are robustness splits, not a sealed holdout and not a profit guarantee.

## Fixed market and execution contract

- Candidate family: `ProfitMaxIntradayV1`.
- Universe: exactly BTC/USDT:USDT, ETH/USDT:USDT, BNB/USDT:USDT, XRP/USDT:USDT, ADA/USDT:USDT and DOGE/USDT:USDT. No pair may be removed after PnL is observed.
- Base timeframe: 15m. Informative timeframes: 1h and 4h.
- UTC closed candles only. A signal calculated from candle `t` may fill no earlier than the next 15m open.
- Binance USDT-margined futures, isolated margin, 1x leverage, dry-run wallet 1,000 USDT, stake 75 USDT, at most three concurrent positions.
- Fee: **7.5 bps (0.075%) per executed order/side**, therefore 15 bps minimum entry+exit round-trip, plus recorded funding. No DCA, martingale, position adjustment or leverage increase.
- Canonical OHLCV source: native 15m futures candles. Complete UTC bins are deterministically aggregated from 15m into 1h and 4h; native higher-timeframe candles are not used for decisions.
- Required coverage: every pair has continuous 15m data for each evaluated split, no duplicates/null/non-finite/invalid OHLCV, at least 99.95% coverage and no undocumented gap longer than three base candles. Failure is `DATA_BLOCKED` before PnL.

## Frozen splits

- TRAIN: 2022-01-01 through 2024-01-01, exactly 730 UTC days.
- VALIDATION: 2024-01-01 through 2026-01-01, exactly 731 UTC days; revealed once only after a complete TRAIN pass and technical pass.
- CURRENT_PARTIAL: 2026-01-01 through 2026-08-01, diagnostic only after VALIDATION passes.
- Continuous diagnostic: 2022-01-01 through 2026-08-01.

## Exactly three predeclared candidates

All candidates share causal EMA20/EMA50, ATR14, ADX14, RSI14, previous-channel and previous-volume indicators. Higher-timeframe data is merged at its actual close availability.

The exact shared long regime is `trend_long_4h`, `ema_gap_atr_4h >= 0.35`, `ema20_1h > ema50_1h`, `momentum24_1h > 0` and `ADX14_1h >= 22`; short is exactly mirrored. No threshold is train-derived.

1. `ProfitMaxIntradayReclaim15m`: within the shared regime, long requires previous close <= previous EMA20, current close > current EMA20, previous RSI14 <=45, current RSI14 >45 and current volume >0.9 times the prior-20-candle median; short is mirrored with RSI55. 
2. `ProfitMaxIntradayBreakout15m`: within the shared regime, long requires close above the previous 32-candle high, current volume >1.25 times the prior-20 median and `ADX14_1h > ADX14_1h.shift(4)`; short is mirrored below the previous channel low.
3. `ProfitMaxIntradayHybrid15m`: fixed union of the exact reclaim and breakout signals, preserving an immutable setup tag for attribution. Concurrent duplicate long/short signals on one candle are forbidden.

The common fixed exit policy is opposite 15m EMA20/EMA50 loss or opposite 1h regime, `-1.8%` hard stop, no trailing stop, and a time-decaying ROI schedule of 2.4% at entry, 1.2% after 4 hours, 0.5% after 12 hours and 0% after 24 hours. Cooldown is four 15m candles after a close.

No other candidate, threshold, indicator, side policy, pair policy, hyperopt, grid search, ML, FreqAI or LLM order decision may be added in this cycle after the first PnL run.

## TRAIN gates

Every gate is mandatory:

- Mean portfolio frequency from closed trades: `1.0 <= trades / 730 <= 2.0` per day.
- At least 730 and at most 1,460 closed trades.
- Return > 0, profit factor >= 1.20, wallet-curve maximum drawdown <= 12%, return/drawdown >= 1.0.
- Long and short each at least 150 trades, each net positive and each PF >= 1.05.
- Every pair at least 60 trades; at least four of six pairs net positive; no pair return below -2%.
- At least 18 of 24 TRAIN months positive; worst month return > -2%.
- Largest winning-trade share of total positive profit <= 15%.

The winner is the complete passer with the highest profit factor; ties use higher return/drawdown and then lower drawdown. No complete passer ends the cycle `KEEP_OFFLINE_RESEARCH`.

## Technical gates before VALIDATION

- Strategy/config/data/risk/runtime hashes frozen before the first PnL run.
- Freqtrade strategy discovery and config validation pass in pinned Freqtrade 2026.7.
- Official lookahead analysis: no biased entry, exit or decision-critical indicator.
- Recursive/prefix convergence: zero signal differences and <=0.01% absolute variance for decision-critical columns at the first passing fixed startup count among `[799,1599,3199,6399,12799]`.
- Exact source/config/result reconciliation and explicit artifact filenames; never select an artifact by mtime.

## VALIDATION gates

- Mean portfolio frequency `1.0 <= trades / 731 <= 2.0` per day and each validation year between 0.75 and 2.25 trades/day.
- Return > 0, PF >= 1.25, wallet DD <= 10%, return/DD >= 1.25.
- Both 2024 and 2025 positive with PF >= 1.10.
- Long and short each at least 150 trades, net positive and PF >= 1.05.
- Every pair at least 60 trades; at least four of six pairs net positive; no pair return below -2%.
- At least 18 of 24 months positive; worst month return > -2%.

## Cost stress and decision

- Moderate stress above the 7.5-bps baseline: +2 fee bps/side, +5 slippage bps/side, +2 one-way latency bps and funding x1.5. Require return >0, PF >=1.15 and DD <=12%.
- Severe stress above the 7.5-bps baseline: +10 fee bps/side, +15 slippage bps/side, +5 one-way latency bps and funding x3. Require return >0, PF >=1.05 and DD <=15%.
- Data/technical/source/bias failure: `REJECT_PROFIT_MAX_INTRADAY`.
- Valid artifacts but performance or frequency failure: `KEEP_OFFLINE_RESEARCH`.
- Only a complete pass: `APPROVE_SEPARATE_DRY_RUN`, never live trading.
