# ProfitMax20 V5 - locked retrospective research plan

V4 passed every rolling gate except severe-cost CAGR, scoring 19.9217% versus
the required 20%. V5 is the minimal separate refinement: the swing leverage
moves from 3.64x to 3.66x and the leveraged stop from `-0.364` to `-0.366`,
preserving the approximate 10% underlying price stop. No other signal, stake,
pair, fee, timeframe, activity, or diversifier setting changes.

The primary interval is `[2021-08-01, 2026-08-01)`; `[2021-01-01, 2026-01-01)`
is a secondary diagnostic. The aggregate wallet is 1,000 USDT. All sleeves use
Binance isolated USDT futures, 0.075% fee per side, recorded funding, and
next-candle Freqtrade execution.

- Swing: qualified long-only confluence, 3.66x, one position, 20% margin cap.
- Activity: audited 50-pair BTC-gated top-two momentum, twice daily, 8-hour
  hold, 1x, 10 USDT and two positions.
- Diversifier: qualified V2R long/short confluence, 1x, 25 USDT and two
  positions.

The rolling gates remain unchanged from V4: at least 1.00 trade/day; baseline
and extra-0.10%-per-side CAGR at least 20%; profit factor at least 1.50 in both;
baseline drawdown at most 20% and severe drawdown at most 21%; concurrent
margin at most 25% and notional at most 76%; no calendar segment below -2% and
at least four positive segments; exact reconciliation and sanitized archives.

All history was observed before this cycle. Passing is retrospective evidence,
not a future-profit guarantee. Only a separate credential-free isolated dry-run
may follow; live trading and automatic promotion remain disabled.
