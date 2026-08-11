# Final Challenger - Locked Chandelier Tournament Plan

This plan was written before the first `DualTrendFuturesV3R` result. There is no
such thing as a universally ideal or guaranteed-profitable strategy. The goal
is narrower: test one final independently motivated exit hypothesis and retain
the strongest robust candidate under rules fixed in advance.

## Single fixed candidate

`DualTrendFuturesV3R` keeps every V2R entry, regime, indicator, risk-sizing,
protection, hard-stop, 1x leverage, pair, and timeframe rule. It changes only
the normal exit logic:

- Chandelier lookback: 22 closed 4h candles.
- ATR length: the existing 14 candles.
- ATR multiplier: 3.0.
- Long exit level: rolling highest high minus 3 x ATR.
- Short exit level: rolling lowest low plus 3 x ATR.
- Exit when the closed 4h price crosses the applicable Chandelier level or the
  unchanged daily EMA20 regime fails.
- Remove V2's fixed 10-candle channel and DMI/VWMA invalidation exits.
- Keep hard stop -10%, ATR/exposure stake multiplier 0.325-0.65, no DCA or
  martingale, and isolated 1x leverage.

The TradingView Chandelier Exit description defines the same local-extreme plus
ATR-multiple formula and describes its purpose as staying in a trend until a
potential significant reversal. There is one candidate and no parameter grid.

## Tournament matrix

Run incumbent `DualTrendFuturesV2R` and challenger `DualTrendFuturesV3R` under
identical research configuration and fees:

- Backcast: 2020-08-01 through 2021-01-01.
- Train: 2021-01-01 through 2024-01-01.
- Validation: 2024-01-01 through 2026-01-01.
- Calendar folds: 2021, 2022, 2023, 2024, 2025.
- Current partial fold: 2026-01-01 through 2026-08-01.
- Fee stress 0.15%/side on train and validation.
- Lookahead and recursive analysis for V3R.
- Deterministic 4-week circular block bootstrap on concatenated train and
  validation weekly wallet returns: 5,000 simulated five-year paths.

All historical periods have already been visible. This is robustness and model
selection evidence, not a fresh sealed holdout. The active credential-free V2R
forward dry-run remains untouched during the tournament.

## Absolute challenger gates

- Train: positive return, PF >= 1.20, DD <= 30%.
- Validation: at least 100 trades, positive return, PF >= 1.50, DD <= 12%.
- At least five of the six 2021-2026 folds positive; worst fold return > -5%;
  median fold PF >= 1.20.
- 2025: positive return, PF >= 1.15, DD <= 12%, at least 20 trades.
- Current 2026: positive return, PF >= 1.30, DD <= 10%, at least 12 trades.
- Fee validation: positive return, PF >= 1.30, DD <= 13%.
- Fee train: positive return and PF >= 1.20.
- Backcast: positive return, PF >= 1.00, DD <= 15%, at least 10 trades.
- At least five validation pairs positive; pair concentration <= 50%; winning
  trade concentration <= 25%.
- Lookahead/recursive checks pass at the existing limits.
- Bootstrap: fifth-percentile terminal return > 0% and 95th-percentile weekly
  max drawdown <= 35%.

## Incumbent-superiority gates

V3R replaces V2R only if every absolute gate passes and all of these hold:

- Validation return, PF, and return/max-DD are each at least as high as V2R;
  return/max-DD must be at least 10% higher.
- 2025 and current-2026 returns are at least as high as V2R.
- Fee-validation return/max-DD is at least as high as V2R.
- Train return/max-DD is no more than 10% below V2R.
- Positive-fold count and worst-fold return are no worse than V2R.
- Bootstrap fifth-percentile terminal return is no worse than V2R.

If any superiority gate fails, V3R is rejected and the system returns to the
incumbent V2R as the best research candidate. No failed limit will be relaxed.
Passing authorizes only a credential-free forward dry-run; live trading remains
out of scope and future profit is not guaranteed.
