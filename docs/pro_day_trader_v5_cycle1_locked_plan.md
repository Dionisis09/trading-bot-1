# ProDayTraderV5 Cycle 1 - Locked Causal Execution Plan

- Status `LOCKED_BEFORE_FIRST_V5_PNL_RUN` on 2026-08-16; no hyperopt/grid.
- V4 proved recursive convergence and clean indicators, but 3/120 entries and exits
  were path-dependent in official lookahead. No V4 performance PnL was parsed.
- V5 keeps V4 T1/R1 entries and 4h EMA20/EMA50 regime unchanged.
- Setup exits become vectorized: a long exits on either causal R1 zero-cross or T1
  15m EMA cross; short is symmetric. `custom_exit` retains only R1 60m, losing-trade
  180m, and absolute 720m time stops and never reads a dataframe.
- Stake sizing no longer reads a dataframe: wallet risk 0.25% divided by the frozen
  4% hard stop, capped at 10% exposure, exchange limits, and proposed stake.
- 5m execution, causal 15m/1h/4h, BTC/ETH/BNB perpetuals, isolated 1x, max two.
- Recursive qualification at 2399 requires <=0.01% fractional variance, zero signal
  differences, zero indicator-only lookahead. Lookahead then checks 120 signals over
  `20240101-20260101` with all setups/sides/pairs and zero bias.
- Only both passes unlock TRAIN `20220101-20240101`: >=120 trades, return>0,
  PF>=1.25, wallet DD<=12%, return/DD>=1.00. VALIDATION and CURRENT remain sealed
  behind sequential passes and retain all V4 breadth/stress gates.
- Any technical failure is `REJECT_PRO_DAY_TRADER_V5`; performance failure is
  `KEEP_OFFLINE_RESEARCH`; all gates can only `APPROVE_SEPARATE_DRY_RUN`.
- Strategy SHA256 `eaa5cd47f6750a697c1cf32400fd641347a0bd95c3a2e0e4de60c4e5528e0b9f`.
- Config SHA256 `c633792072936197ef565112c8374d592dd72259e5b3cbe1bf26ef809d1b72f8`.
- V4 recursive PASS SHA256 `436c6b45bf31ac0b955cda8b173be6d7c2ab1b14a97fa83f69bc4794c0f43850`.
- V4 lookahead bias report SHA256 `4c56a3861c64a0405c187381fdd35bf0d9f92d61f211c6b2c2a41e526b8b6ac2`.
- Canonical audit SHA256
  `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`.
- Runtime digest `sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.
- V1/V2R and live deployment remain untouched and unauthorized.
