# ProfitMax Intraday ML Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_ML_PNL`. Research only; live trading unauthorized.

The deterministic lineage is closed after three bounded TRAIN cycles. Its strongest signal, `ProfitMaxIntradayShortBase15m`, achieved the required frequency (904 trades, 1.238/day), low wallet drawdown (5.46%) and PF 0.983 after the user's exact 0.075% fee per side, but was not profitable. This cycle tests one materially different hypothesis: a small causal LightGBM regressor may veto low-quality occurrences of that exact short signal. It cannot create a trade, change direction, increase stake or leverage, or alter exits.

Runtime is the official amd64 FreqAI image pinned exactly to `freqtradeorg/freqtrade:2026.7_freqai@sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000`. Universe remains BTC, ETH, BNB, XRP, ADA and DOGE USD-M perpetual futures. Main timeframe is 15m; 1h and 4h are informative. Canonical source is exact public Binance 15m data from 2020-12-01 through 2026-08-02, with complete-bin UTC aggregation. Isolated futures, 1x leverage, 75 USDT stake, max three open trades, and fee 0.00075 per side are unchanged.

Exactly one model candidate is allowed: `ProfitMaxIntradayMLV1`, using the exact Cycle-2 ShortBase entry and exit policy. Prediction must be present with `do_predict == 1` and strictly positive; missing, stale, invalid or non-positive prediction vetoes the trade.

The regression label is calculated for every completed 15m row: enter at `open[t+1]`, exit at `open[t+17]` (four hours), short-side log return minus the locked 0.0015 round-trip fee. No same-candle fill is allowed. The label is not a strategy exit and cannot change the ShortBase exit policy.

Only these 15 numeric features are permitted, all calculated from the current or earlier completed candles: 15m log returns over 1/4/16 bars, EMA20-EMA50 divided by ATR14, prior-32 channel position, downside breakout distance divided by ATR14, RSI14, ADX14, log volume versus prior-20 median, ATR14/close, 24h realized volatility, 1h EMA gap/ATR, 1h ADX14, 1h 24-period momentum, and 4h EMA gap/ATR. Higher-timeframe values become available only at their close. No wallet, PnL, orderflow, OI, funding, raw price, LLM output or automatic feature expansion is a model input.

Walk-forward contract: model history starts 2021-01-01; TRAIN OOS is 2022-01-01 through 2024-01-01. FreqAI uses the preceding 365 days, retrains every 30-day backtest window, never shuffles, uses no internal random holdout, and buffers at least 17 base candles. LightGBM capacity and seeds are fixed in config. Model files use a unique identifier and an isolated empty directory. No cached model or prediction may be reused.

TRAIN gates remain 730–1,460 trades (1–2/day), return >0, PF >=1.15, wallet DD <=10%, return/DD >=0.75, every pair >=60 trades, at least four positive pairs, and worst pair return >-2%. Highest priority is a complete gate pass, not in-sample prediction accuracy. Validation 2024–2025 remains inaccessible unless TRAIN and technical/source gates pass. No threshold tuning, feature edit, pair deletion, second model, hyperopt or LLM decision is permitted after the first ML PnL run.

Any data/runtime/source/causality failure rejects the cycle before PnL. Any valid TRAIN performance failure yields `KEEP_OFFLINE_RESEARCH`. Only a complete TRAIN pass can unlock lookahead/recursive reconciliation and one-time validation. Nothing here authorizes live trading or guarantees profit.
