# ProDayTraderV4 Cycle 1 - Locked Live-Feasible 5m Research Plan

## Objective and evidence boundary

- Status: `LOCKED_BEFORE_FIRST_V4_PNL_RUN` on 2026-08-16.
- One deterministic candidate, no hyperopt/grid or post-result parameter edits.
- V3 Cycle 1 failed only because public metadata was network-blocked. V3 Cycle 2
  then proved zero indicator-only lookahead and zero signal differences but failed
  the locked 399-candle convergence gate for the 4h EMA200 state.
- Neither V3 cycle ran a backtest, parsed PnL, or trained a model.

## Frozen technique

- T1 trend continuation and R1 flat-regime mean reversion remain unchanged.
- The 4h regime changes from EMA50/EMA200 to EMA20/EMA50. Long requires EMA20>EMA50
  and rising EMA50; short is symmetric. This is a pre-PnL feasibility change because
  Binance/Freqtrade live startup is bounded to roughly 2,499 base candles, while a
  4h EMA200 needs roughly 9,600 5m candles. EMA20/EMA50 fits the locked 2,399 startup.
- Base 5m, causal 15m/1h/4h merges, next-5m-open fills, closed candles only.
- BTC/ETH/BNB USDT perpetuals, isolated 1x, maximum two positions, inherited risk
  sizing/stops/protections. No ML, LLM, order flow, OI, news, or leverage increase.

## Technical gates

- Pinned Freqtrade 2026.7 standard image digest:
  `sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.
- Recursive counts `[199, 399, 799, 1599, 2399]`; qualification count 2399.
  Every reported decision-critical indicator at 2399 must have absolute fractional
  variance <=0.0001 (0.01%), with zero entry/exit signal differences and zero
  indicator-only lookahead differences.
- Only a recursive pass unlocks all-pair lookahead over `20240101-20260101` with
  minimum 100 and target 120 analyzed trades. Any ambiguity fails closed.

## Sequential performance gates

- TRAIN `[20220101-20240101)`: >=120 trades, return>0, PF>=1.25, wallet DD<=12%,
  return/DD>=1.00. Only a pass unlocks VALIDATION.
- VALIDATION `[20240101-20260101)`: >=120 trades, return>0, PF>=1.35, DD<=10%,
  return/DD>=1.20, plus the pair/side/setup/year/quarter breadth gates frozen in V3.
- CURRENT `[20260101-20260801)`: >=20 trades, return>=0, PF>=1.10, DD<=8%.
- Baseline includes 5 bps/side plus recorded funding. Moderate/severe fee, slippage,
  latency and funding stresses remain identical to the V3 plan.
- A technical failure is `REJECT_PRO_DAY_TRADER_V4`; a valid performance failure is
  `KEEP_OFFLINE_RESEARCH`; every gate passing can only `APPROVE_SEPARATE_DRY_RUN`.
  Live trading, automatic promotion, and profit guarantees remain forbidden.

## Frozen evidence

- Strategy SHA256:
  `ecca8f37bf162bd6f1e9d8d0bb6ccc06910e3c65ab95c9b4a06ba8cd99c1fcea`.
- Config SHA256:
  `307fa8d43b0356b28a7b0e451c57cc59ad35b969bb1a0351e3d23c8f9d666c26`.
- Canonical data audit SHA256:
  `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`.
- V3 Cycle 1 manifest SHA256:
  `83b2e4f79d5e3ade690621faf374574f1d3d480f8c138e3c76aa642193a69ba9`.
- V3 Cycle 2 manifest SHA256:
  `f0dd6a265a9aff832a5d9f2349bce08bb8b216859c92d441df81fd0f8703d570`.
- V3 Cycle 2 recursive report SHA256:
  `9f2e95aa83d78c00aa9707e01853b62b707a41d864e8ef222aa03bac6d7dfc30`.
- Explicit artifacts: `prodayv4-cycle1-train.zip`, `-validation.zip`,
  `-current-partial.zip`, and `-canonical.zip`; no mtime/latest selection.
- V1/V2R, Compose, databases, ports, monitoring, and VPS deployment stay untouched.
