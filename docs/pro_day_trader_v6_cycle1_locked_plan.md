# ProDayTraderV6 Cycle 1 — Locked research plan

Status: `LOCKED_BEFORE_FIRST_V6_PNL_RUN`. This cycle is research-only; it cannot authorize live trading.

## Why this is a new cycle

V5 TRAIN produced 597 trades, -5.563143597% return and PF 0.4024146066107644. Its vectorized exit combined R1 zero-cross and T1 trend-reversal conditions for every open trade, so setup semantics were not isolated. V6 makes one structural, predeclared change: it tests the trend/momentum hypothesis alone.

## Frozen candidate

- Strategy: `ProDayTraderV6`; 5m base with causal 15m/1h/4h informative candles.
- Universe: BTC/USDT:USDT, ETH/USDT:USDT, BNB/USDT:USDT; futures isolated; 1x; maximum two positions.
- Entries: inherited T1 only — 4h EMA20/EMA50 trend and EMA50 slope, matching 1h momentum with ADX >=18, matching 15m EMA20/EMA50, and a volume-confirmed 5m EMA20 recross.
- Exits: only the direction-matched completed-15m EMA20/EMA50 reversal, inherited causal profit-protection stop, static -4% emergency stop, and a 720-minute fail-safe. R1 signals and the 180-minute losing-trade cut cannot affect V6.
- Stake: inherited fixed sizing, 0.25% wallet risk against the 4% emergency stop (6.25% wallet maximum before other caps); leverage fixed at 1.
- No ML, hyperopt, grid search, LLM order input, order-flow entry signal, or post-result parameter edits.

## Fixed evidence sequence

1. Freeze plan/source/config/risk/data hashes before any V6 PnL.
2. Recursive analysis counts `[199,399,799,1599,2399]`; count 2399 must have zero signal differences, zero indicator-only lookahead differences, and <=0.01% variance for decision-critical indicators.
3. Lookahead analysis on 2024-01-01 through 2026-01-01 must analyze at least 100 signals and report zero false entry, false exit, and indicator bias. Its backtests are technical-only and PnL fields are not parsed.
4. One TRAIN run on 2022-01-01 through 2024-01-01. Pass requires >=120 trades, return >0, PF >=1.25, wallet-curve DD <=12%, and return/DD >=1.0.
5. TRAIN failure means `KEEP_OFFLINE_RESEARCH` and stops the cycle. Only a complete TRAIN pass may reveal validation (2024-01-01 through 2026-01-01), then current partial (2026-01-01 through 2026-08-01).
6. Only all gates passing can produce `APPROVE_SEPARATE_DRY_RUN`; never live approval.

## Frozen inputs

- Strategy SHA256: `1f70917dd14aa6fe7cec243ff3a2290759e138357ee25f288eb0ea7f499ad33c`
- Config SHA256: `d5ceaf71bd8c3582532cd710bc8396c96019fd8d37859da47a5829df728fc48d`
- Strategy tests SHA256: `11663caceb8688faf784b115771f107290593e8691c6d05a1ca0868205341f35`
- Canonical data audit SHA256: `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`
- Risk policy SHA256: `6a3e073fd08b21d645b0d4b4151022bef79adc610d8c130b36554a01e6f51e80`
- Runtime: `freqtradeorg/freqtrade@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.

