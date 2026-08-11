# Binance Major Trend Portfolio V3 - Locked Research Plan

## Objective and meaning of profitable

Build a functional Binance Spot dry-run bot whose selected strategy has positive
net return after the modeled 0.10% fee on both entry and exit in chronological
train, validation, and one untouched final holdout. A profitable backtest does
not guarantee future profit.

## Fixed market universe

The universe was locked before downloading or backtesting the new USDT data:

- BTC/USDT
- ETH/USDT
- BNB/USDT
- SOL/USDT
- XRP/USDT
- ADA/USDT
- DOGE/USDT
- LINK/USDT
- LTC/USDT
- AVAX/USDT

All ten were verified as currently active Binance Spot markets on 2026-08-03.
They were selected as liquid, long-lived majors rather than from strategy PnL.
This introduces survivorship bias because today's universe is applied to
history; the limitation must remain visible in the final conclusion.

## Data and chronological splits

- Base timeframe: 4h.
- Informative timeframe: 1d.
- Download window: 2020-01-01 through 2026-08-03 UTC.
- Train: `2021-01-01` to `2024-01-01` UTC.
- Validation: `2024-01-01` to `2026-01-01` UTC.
- Final holdout: `2026-01-01` to `2026-08-01` UTC.
- Starting research wallet: 10,000 USDT.
- Maximum simultaneous positions: 4.
- Stake: `unlimited`, divided across available slots.
- Spot long-only; no leverage, shorting, margin, DCA, or position adjustment.

## Trial budget fixed before results

At most four structural variants may be compared on train and validation. This
is a deliberately small model-selection budget, not hyperopt or a large grid.
Every tried variant and result must be retained.

1. `MajorTrendV3A`: daily EMA200 bull regime, 30/15 Donchian entry/exit.
2. `MajorTrendV3B`: daily EMA200 bull regime, 42/21 Donchian entry/exit.
3. `MajorTrendV3C`: daily EMA100 bull regime, 30/15 Donchian entry/exit.
4. `MajorTrendV3D`: daily EMA200 bull regime, 20/10 Donchian entry/exit.

Shared fixed rules:

- Daily close above the regime EMA and daily EMA50 above the regime EMA.
- 4h close breaks above the prior Donchian entry channel.
- 4h ADX above 18, RSI between 52 and 82, ATR/close between 0.5% and 12%.
- Positive volume above the trailing 12-candle median.
- Exit below the prior Donchian exit channel or daily close below EMA50.
- Hard stop at -12%; no ROI or trailing-profit optimization.
- Cooldown, stoploss guard, and max-drawdown protections enabled.

## Train and validation qualification

A variant may become the single holdout candidate only if:

- Train return is positive and train profit factor is at least 1.05.
- Validation has at least 100 closed trades.
- Validation return is positive after fees.
- Validation profit factor is at least 1.10.
- Validation maximum drawdown is no greater than 20%.
- At least 6 of 10 pairs have positive validation return.
- No pair has validation profit factor below 0.75.
- No single pair contributes more than 50% of total positive pair profit.
- No single winning trade contributes more than 25% of total positive trade profit.
- Adjacent variants do not all collapse, so the result is not a single brittle setting.

If multiple variants qualify, select the one with the highest minimum of train
and validation profit factor, then lower validation drawdown as tie-breaker.
No holdout result may influence selection.

## Technical and holdout gates

Before the holdout is opened, the selected candidate must show:

- No lookahead-biased entries, exits, or indicators.
- No material recursive indicator variance at the declared startup candles.
- Positive result under fee sensitivity at 0.15% per side.

The one-time holdout must then have positive return, profit factor at least
1.00, maximum drawdown no greater than 15%, and at least 20 closed trades.

Passing authorizes dry-run only. Live keys and live trading remain out of scope.

