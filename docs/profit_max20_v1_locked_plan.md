# ProfitMax20 V1 - locked retrospective research plan

This cycle tests a new two-sleeve portfolio without changing or stopping any
active bot. All available history has already been seen, so every result is
retrospective robustness evidence and never a profit guarantee or live-trading
authorization.

The primary period is the exact rolling five years `[2021-08-01, 2026-08-01)`.
The secondary period is the five complete calendar years `[2021-01-01,
2026-01-01)`. Both use a 1,000 USDT aggregate wallet, Binance USDT isolated
futures, 0.075% fee per side, recorded funding, and next-candle Freqtrade
execution.

The alpha sleeve is `ProfitMaxCagr20V1`: the qualified long-only V5 signal is
unchanged, leverage is fixed at 3.5x, proposed margin is 300 USDT, the existing
ATR sizing keeps individual margin at or below 20% of the wallet, and one
position is allowed. The stop is `-0.35`, preserving the same approximate 10%
underlying price distance used by the 2.5x baseline.

The activity sleeve is `ProfitMaxDailyCrossBreadthBonus`: the already declared
50-pair cross-sectional breadth candidate, 4h execution, 1x, 10 USDT stake and
two positions. It supplies broad market participation; it is not allowed to
change the swing sleeve's signals or leverage.

The locked portfolio must satisfy all of these gates on the rolling five-year
period:

- at least 1.00 closed trade per calendar day on average;
- CAGR at least 20% at the exact Binance fee;
- CAGR at least 20% after an additional 0.10% cost per entry side and exit side;
- profit factor at least 1.50 under baseline and severe costs;
- realized wallet drawdown at most 20% under baseline and severe costs;
- maximum concurrent margin at most 25% and notional at most 75%;
- positive net profit in every represented calendar year;
- exact trade/accounting reconciliation and secret-free archives.

The component source/config hashes are frozen before parsing PnL. A failure
keeps the candidate offline. A complete pass can authorize only a separate,
credential-free isolated dry-run; automatic promotion and live trading remain
disabled.
