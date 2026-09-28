# ProDayTraderV3 Cycle 1 — Locked Deterministic 5m Research Plan

## Status and objective

- Status: `LOCKED_BEFORE_FIRST_V3_PNL_RUN` on 2026-08-16.
- Candidate: `ProDayTraderV3`; one candidate, no parameter sweep or hyperopt.
- Objective: maximize robust net return after fees, slippage, latency, and funding,
  subject to the inherited drawdown, breadth, stability, and causal-data gates.
- This cycle follows a pre-PnL technical rejection of ProDayTraderV2. No Cycle 2
  TRAIN, VALIDATION, CURRENT, return, profit factor, or drawdown was run or seen.
- V1/V2R, their databases, Compose services, ports, monitoring, and VPS state remain
  unchanged. This plan can authorize at most a separate third dry-run, never live.

## Frozen design

- Base execution timeframe: 5m. Informative timeframes: 15m, 1h, and 4h.
- Universe: BTC/USDT:USDT, ETH/USDT:USDT, and BNB/USDT:USDT futures.
- Isolated margin, leverage 1x, maximum two positions, next-5m-open execution.
- T1 trend continuation and R1 flat-regime mean reversion are inherited exactly
  from `ProDayTraderV2`. Risk sizing, -4% emergency stop, setup exits, time stops,
  protections, and 0.25% wallet risk budget are inherited unchanged.
- Machine learning is disabled in the order path. No prediction may create, veto,
  reverse, size, stop, or exit a Cycle 1 trade. A later cycle may collect ML shadow
  predictions only after this deterministic candidate has independent evidence.
- Canonical inputs are the already audited 5m source and complete UTC-derived
  15m/1h/4h files under `user_data/data/binance/pro_day_v2_canonical/`.
- Native Binance higher-timeframe files, order flow, OI, taker ratios, LLM output,
  and news are excluded from entries and qualification.

## Splits and execution costs

- TRAIN OOS: `[2022-01-01, 2024-01-01)`.
- VALIDATION OOS: `[2024-01-01, 2026-01-01)`; revealed only after TRAIN passes.
- CURRENT_PARTIAL: `[2026-01-01, 2026-08-01)`; revealed only after prior passes.
- Continuous replay: `[2022-01-01, 2026-08-01)`.
- Baseline fee: 5 bps per side plus recorded funding.
- Moderate stress: +2 fee bps/side, +5 slippage bps/side, +2 bps one-way latency,
  funding ×1.5. Severe: +10/+15/+5 bps and funding ×3.

## Pre-PnL technical gates

- Exact standard Freqtrade 2026.7 linux/amd64 image digest:
  `sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.
- Config validation and unique strategy discovery must pass.
- Unit tests must prove direct T1/R1 long/short tags, causal informative timing,
  shifted channels, 1x leverage, safe sizing, setup exits, and absence of ML gating.
- Recursive counts are `[199, 399, 799, 1599, 2399]`; at 399 every reported
  decision indicator must have variance <=0.01% and entry/exit differences zero.
- Lookahead uses all pairs over `20240101-20260101`, minimum 100 and target 120
  analyzed trades. Bias, missing T1/R1 side representation, or tool ambiguity fails.
- Technical failure means `REJECT_PRO_DAY_TRADER_V3`; no PnL run follows.

## Sequential performance gates

TRAIN must have >=120 trades, return >0, PF >=1.25, wallet-curve DD <=12%, and
return/DD >=1.00. Only a TRAIN pass unlocks VALIDATION.

VALIDATION must have >=120 trades, return >0, PF >=1.35, DD <=10%, and return/DD
>=1.20. Each 2024/2025 must have >=40 trades, positive return, PF >=1.15, DD <=10%.
Each pair needs >=25 trades, PF >=0.90, return >-2%; at least two pairs positive and
the largest positive-pair contribution <=60%. Long and short each need >=35 trades,
positive net, PF >=1.05. T1 and R1 each need >=25 trades; any setup/regime with >=20
trades needs non-negative net and PF >=1.00. Largest winner share <=20%.

CURRENT requires >=20 trades, return >=0, PF >=1.10, and DD <=8%. Stability requires
at least 3/4 positive full years (2022-2025), median yearly PF >=1.20, worst year and
quarter >-3%, at least 10/16 positive full quarters and 5/8 validation quarters.
The inherited moderate/severe validation stress gates must all pass.

Any technically valid performance/sample/stress failure yields
`KEEP_OFFLINE_RESEARCH`. Only every gate passing yields `APPROVE_SEPARATE_DRY_RUN`.
Live trading, profit guarantees, automatic promotion, and leverage above 1x remain
forbidden.

## Frozen files and evidence

- Strategy wrapper: `user_data/strategies/ProDayTraderV3.py`, SHA256
  `73c78608f8cf048874282621c87f1e05948c90ea66b710800d162c7741402804`.
- Deterministic base: `user_data/strategies/ProDayTraderV2.py`, SHA256
  `6041f416e4c951b83b5f9cef5438319fd4f24d1d296eb37fd499415a00e47f45`.
- Config: `user_data/config-pro-day-v3-cycle1-research.json`, SHA256
  `b71ff01b880122fa60c956739b186ed028de2a60f2a4c3867c28cce2d1f268bb`.
- Canonical audit SHA256:
  `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`.
- Cycle 2 terminal decision SHA256
  `a66944317b0563fd6603323df7ae54872e8a3bd1095173220930d677b8148280`
  proves that no Cycle 2 qualification PnL was run.
- Manifest and trial ledger live under `user_data/reports/pro_day_v3_cycle1/`.
- Artifacts use explicit names `prodayv3-cycle1-{train,validation,current-partial,canonical}.zip`;
  no mtime or `latest` selection is permitted.
