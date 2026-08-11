# Binance Major Trend Portfolio V4 - Locked Research Plan

This plan was fixed after the V3 rejection and before any V4 backtest. The
sealed 2026 holdout remains unopened. V4 is a second, explicitly disclosed
research round, so its train/validation performance is model-selection evidence,
not final out-of-sample evidence.

## Hypothesis

V3 caught long-term trends but allowed breakouts while shorter daily momentum
was already deteriorating. V4 requires a fully aligned daily trend and exits on
loss of the daily EMA20. The intent is to reduce persistent losses in weak
individual assets without selecting or excluding symbols from observed PnL.

The fixed ten-pair universe, 4h/1d data, 10,000 USDT research wallet, four
maximum positions, 0.10% fee per side, protections, and chronological splits
remain exactly as specified in `strategy_v3_portfolio_plan.md`.

## Fixed V4 trial budget

Exactly four variants may be compared:

1. `MajorTrendV4A`: 63-day positive ROC, 30/15 Donchian channels.
2. `MajorTrendV4B`: 63-day positive ROC, 30/10 Donchian channels.
3. `MajorTrendV4C`: 126-day positive ROC, 30/15 Donchian channels.
4. `MajorTrendV4D`: 63-day positive ROC, 42/21 Donchian channels.

Shared rules:

- Daily close above EMA200 and EMA20 above EMA50 above EMA200.
- Positive daily ROC over the declared momentum window.
- 4h Donchian breakout, ADX above 18, RSI from 52 to 82, ATR/close from 0.5%
  to 12%, and volume above its trailing 12-candle median.
- Exit below the prior Donchian exit channel or daily close below EMA20.
- Hard stop at -10%; no ROI or trailing-profit optimization.
- The same cooldown, stoploss guard, and portfolio drawdown protections as V3.

## Qualification gates

A single candidate may advance only if:

- Train return is positive and train PF is at least 1.05.
- Validation has at least 80 closed trades, positive net return, PF at least
  1.10, and maximum drawdown no greater than 20%.
- At least 6 of 10 pairs have positive validation return.
- For a pair with at least 10 validation trades, PF is at least 0.75.
- A sparse pair with fewer than 10 validation trades does not lose more than
  8% of starting equity cumulatively.
- No pair contributes more than 50% of total positive pair profit and no single
  trade contributes more than 25% of total positive trade profit.
- Adjacent variants do not all collapse.

The V3 pair-PF gate was replaced prospectively for V4 because PF from only four
to eight trades is not a stable estimate. This change does not retroactively
approve V3. If multiple V4 variants qualify, choose the highest minimum of train
and validation PF, then the lower validation drawdown.

## Technical and sealed-holdout gates

Before opening the holdout, the chosen candidate must pass lookahead analysis,
recursive-indicator analysis, and remain profitable at a 0.15% fee per side.
The one-time holdout must have at least 20 trades, positive net return, PF at
least 1.00, and maximum drawdown no greater than 15%.

Passing these gates authorizes dry-run operation only. It is not a promise of
future profit and does not authorize live API keys or live orders.

