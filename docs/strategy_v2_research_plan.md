# Binance Spot Breakout V2 - Pre-declared Research Plan

## Why a second structural trial exists

`BinanceSpotTrendV1` failed both train and validation. Its trailing exits were
profitable, but frequent trend-reclaim entries followed by small trend-failure
losses produced negative expectancy. V2 changes the entry/exit structure rather
than optimizing a collection of nearby thresholds.

## Fixed V2 hypothesis

A 12-hour Donchian price breakout may provide stronger confirmation than an
intraday EMA reclaim. Entries are allowed only inside the same positive 1-hour
trend regime. A 12-hour breakout entry is paired with a 6-hour channel exit,
plus a slower 1-hour regime-failure exit.

The fixed rules for Trial 2 are:

- 1h close above EMA200, EMA50 above EMA200, and ADX above 20.
- 15m close crossing above the prior 96-candle high.
- 15m RSI strictly between 55 and 80.
- ATR percentage strictly between 0.20% and 5.00%.
- Current volume above the prior 24-candle median.
- Exit below the prior 48-candle low or when the 1h close falls below EMA50.
- Hard stop at -7%; trailing activates at +6% and trails 2.5% below price.
- The same cooldown, stoploss guard, and max-drawdown protections as V1.
- `startup_candle_count = 800`, selected from V1's indicator-convergence test.

No other V2 variant will be tested before its train and validation results are
recorded. This is Trial 2 of the research sequence.

## Data, splits, and gates

V2 uses the same Binance Spot BTC/USDC and ETH/USDC data, 0.10% per-side fee,
1,000 USDC research wallet, two maximum positions, chronological splits, and
acceptance gates declared in `docs/strategy_research_plan.md`.

The final `2026-01-01` to `2026-08-01` holdout remains sealed unless V2 passes
every validation gate. Passing can authorize dry-run only, never live trading.

