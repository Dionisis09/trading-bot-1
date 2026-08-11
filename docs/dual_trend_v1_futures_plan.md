# Binance Futures Dual Trend V1 - Locked Plan

This plan was written before downloading or backtesting the futures dataset.
It is a single-candidate extension intended to participate in both bullish and
bearish markets. Futures are materially riskier than spot; all work is dry-run,
uses 1x leverage, contains no API credentials, and does not authorize live
trading.

## Fixed strategy

The long side is the frozen V6 rule set. The short side is its exact mirror:

- Long daily regime: close > EMA200, EMA20 > EMA50 > EMA200, ROC63 > 0.
- Short daily regime: close < EMA200, EMA20 < EMA50 < EMA200, ROC63 < 0.
- Long entry: 4h break above the prior 30-candle high; short entry: break below
  the prior 30-candle low.
- Both require ADX > 18, ATR/close from 0.5% to 12%, volume above its 12-candle
  median, and directional RSI (52-82 long, 18-48 short).
- Exit on the opposite 10-candle channel or loss of the daily EMA20 regime.
- Hard stop -10%, 1x isolated leverage, no DCA, no ROI optimization, and no
  trailing stop.
- Startup history: 800 candles; the same portfolio protections as V6.

There is exactly one candidate and no parameter grid.

## Market universe and periods

Binance USDT-margined perpetual markets: BTC, ETH, BNB, XRP, ADA, and DOGE.
Use 4h base candles plus 1d informative candles and actual downloadable funding
and mark data where Freqtrade requires them.

- Train: 2021-01-01 through 2024-01-01.
- Validation: 2024-01-01 through 2026-01-01.
- Validation subwindows: calendar 2024 and calendar 2025.
- Current-regime evaluation: 2026-01-01 through 2026-08-01. This is not called
  sealed because the spot study already revealed a broad bearish regime.
- Untouched historical backcast holdout: 2020-08-01 through 2021-01-01. It is
  opened last and is independent of candidate PnL selection, but it precedes
  train chronologically and is weaker evidence than a future holdout.

## Qualification gates

- Train: positive return, PF >= 1.20.
- Validation: at least 100 trades, positive return, PF >= 1.20, DD <= 20%.
- Each of 2024 and 2025: positive return, PF >= 1.00, at least 20 trades.
- At least 4 of 6 pairs positive in validation; no pair loses more than 5% of
  starting equity; pair concentration <= 50%; trade concentration <= 25%.
- Train and validation positive with 0.15% fee per side.
- No lookahead bias and no material recursive variance at startup 800.
- Current 2026 evaluation: positive return, PF >= 1.00, at least 12 trades,
  DD <= 15%.
- Backcast holdout: positive return, PF >= 1.00, at least 10 trades, DD <= 15%.

Passing authorizes a small-stake Binance Futures dry-run only. It cannot prove
future profit and does not justify live leverage or live credentials.

