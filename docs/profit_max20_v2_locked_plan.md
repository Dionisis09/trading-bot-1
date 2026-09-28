# ProfitMax20 V2 - locked retrospective research plan

V1 failed its locked rolling-five-year frequency and severe-cost CAGR gates.
V2 is a separate cycle and does not overwrite V1 or change any active bot.

The primary interval is `[2021-08-01, 2026-08-01)` and the secondary interval
is `[2021-01-01, 2026-01-01)`. Both use a 1,000 USDT aggregate wallet,
Binance isolated USDT futures, 0.075% fee per side, recorded funding, and
next-candle Freqtrade execution.

The alpha sleeve keeps the qualified long-only swing signal, uses fixed 3.76x
leverage and a `-0.376` leveraged stop, preserving the approximate 10%
underlying price stop. It keeps one position and the 20% margin guard.

The activity sleeve uses the same causal 50-pair, seven-day cross-sectional
momentum and 30-day BTC risk gate as the audited daily strategy. It selects the
top two ranks at 08:00 and 20:00 UTC, holds for eight hours, uses 1x leverage,
6 USDT per position, and allows two positions. This changes only breadth, not
the data timing or market regime gate.

The rolling five-year result must satisfy:

- at least 1.00 closed trade per calendar day on average;
- CAGR at least 20% at the exact configured fee;
- CAGR at least 20% with another 0.10% cost on entry and exit;
- profit factor at least 1.50 in baseline and severe cost cases;
- realized wallet drawdown at most 20% in both cost cases;
- concurrent margin at most 25% and concurrent notional at most 75%;
- no represented calendar segment worse than -2% of the wallet and at least
  four positive calendar segments;
- exact reconciliation and secret-free archives.

All history has already been observed. A full pass is retrospective robustness
evidence only and may authorize only a separate credential-free isolated
dry-run. Live trading and automatic promotion remain disabled.
