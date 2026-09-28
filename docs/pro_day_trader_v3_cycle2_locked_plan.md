# ProDayTraderV3 Cycle 2 - Locked Technical-Retry Research Plan

## Boundary

- Status: `LOCKED_BEFORE_FIRST_V3_CYCLE2_PNL_RUN` on 2026-08-16.
- Candidate source and every trading/risk/performance rule are identical to Cycle 1.
- Cycle 1 terminated before its recursive probe because `--network none` prevented
  Freqtrade from loading public Binance futures market metadata. Its recursive report
  has status `FAIL`, container exit 1, no model training, no backtest, and no PnL.
- Cycle 2 changes only the technical runner transport: public unauthenticated
  `exchangeInfo` access is allowed. Empty config credentials remain empty; private
  account/order endpoints, trading, deployment, and secret reads are forbidden.

## Frozen strategy and gates

- Strategy `ProDayTraderV3`, deterministic T1 trend plus R1 flat-regime mean reversion.
- 5m execution; causal 15m/1h/4h context; BTC, ETH, BNB USDT perpetuals.
- Isolated 1x, maximum two positions, inherited 0.25% wallet risk budget.
- No FreqAI/LLM/order-flow/OI/news in the order path.
- Recursive counts `[199, 399, 799, 1599, 2399]`, qualification count 399,
  BTC diagnostic window `20250701-20250801`, variance <=0.01%, zero signal differences,
  and zero indicator-only lookahead differences.
- A recursive pass alone unlocks the frozen all-pair lookahead gate. Only both technical
  gates passing unlock TRAIN `[20220101-20240101)`. The performance gates, sequential
  split policy, execution stress, and `APPROVE_SEPARATE_DRY_RUN` threshold are exactly
  those in `docs/pro_day_trader_v3_cycle1_locked_plan.md`.

## Evidence hashes

- Strategy SHA256:
  `73c78608f8cf048874282621c87f1e05948c90ea66b710800d162c7741402804`.
- Cycle 2 config SHA256:
  `be4fbf4f35aca78586a5e6a80c28b1f46b912c18712f111c01ed45bbde280e21`.
- Canonical audit SHA256:
  `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`.
- Cycle 1 plan SHA256:
  `bf7a41190fc20e2d16f6fd8d0aa1cc571ee02c77e24f9805fac5b0e8a824712c`.
- Cycle 1 manifest SHA256:
  `83b2e4f79d5e3ade690621faf374574f1d3d480f8c138e3c76aa642193a69ba9`.
- Cycle 1 recursive report SHA256:
  `cbf9247bac16919d1886a17ac508294976d00f3d3cef10e26e3c7a49f97d5774`.
- Cycle 1 frozen runner SHA256:
  `29748ce84ae70bcc09e3117d1d5a21892332d6a845dc881d21f5aad203a4e74d`.
- Freqtrade image digest:
  `sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.
- V1/V2R remain untouched; live trading and automatic promotion remain unauthorized.
