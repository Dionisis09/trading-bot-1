# ProfitMax20 V4 - locked retrospective research plan

V4 combines three independently sized sleeves after V1-V3 failed their locked
gates. It does not overwrite those cycles and does not change any active bot.

The primary interval is `[2021-08-01, 2026-08-01)` and the secondary diagnostic
interval is `[2021-01-01, 2026-01-01)`. The accounting wallet is 1,000 USDT.
Every sleeve uses Binance isolated USDT futures, 0.075% fee per side, recorded
funding, and next-candle Freqtrade execution.

- Alpha: qualified long-only swing signals, 3.64x, one position, 300 USDT
  proposed stake with the inherited 20% margin cap, and a `-0.364` leveraged
  stop (approximately 10% underlying price distance).
- Activity: audited 50-pair BTC-gated cross-sectional momentum, top two ranks,
  twice daily, 8-hour hold, 1x, 10 USDT and two positions.
- Diversifier: qualified `DualTrendFuturesV2R` long/short confluence, 1x,
  25 USDT and two positions.

The locked rolling-five-year gates are at least 1.00 trade/day; baseline and
severe-cost CAGR at least 20%, where severe adds 0.10% to entry and exit;
baseline and severe profit factor at least 1.50; baseline realized drawdown at
most 20% and severe drawdown at most 21%; concurrent margin at most 25% and
concurrent notional at most 76%; no calendar segment below -2% of wallet and at
least four positive calendar segments; exact reconciliation and secret-free
archives. The calendar-five-year period is reported but is not the primary gate.

All history has already been observed. A pass is retrospective robustness
evidence and can authorize only a separate credential-free isolated dry-run.
Live trading, API credentials, and automatic promotion remain disabled.
