# ProDayTraderV2 Cycle 2 — Locked Technical-Correction Addendum

## Status and evidence boundary

- Status: `LOCKED_BEFORE_FIRST_V2_CYCLE2_PNL_RUN` on 2026-08-11.
- Cycle: `pro_day_v2_cycle2`.
- Candidate class and source remain exactly `ProDayTraderV2` with SHA256
  `6041f416e4c951b83b5f9cef5438319fd4f24d1d296eb37fd499415a00e47f45`.
- This addendum cryptographically inherits every market rule, feature, target,
  model parameter, risk rule, split, cost scenario, performance gate, attribution
  gate, final-decision rule, and live-safety boundary from
  `docs/pro_day_trader_v2_locked_plan.md`, SHA256
  `707793fc95cc99f9663e354ed5ddae90cfb753a48e773d46ac1759d11bc11e6d`.
- Cycle 1 ended before qualification PnL with `REJECT_PRO_DAY_TRADER_V2` only
  because its recursive-analysis set requested counts above the official tool's
  reported Binance 5m limit. Its final decision SHA256 is
  `fdac3459fb940617371fb772ec5819e8254dc0a53d3ca0c78134f793c2b87dc9`.
- No Cycle 1 TRAIN, VALIDATION, CURRENT, cost-stress, return, PF, or drawdown was
  run or revealed. Therefore this new cycle corrects a tool-compatibility defect,
  not a performance result.
- No strategy source, feature, target, threshold, model capacity, universe, split,
  risk limit, execution cost, sample gate, or performance gate changes in Cycle 2.

## Exact Cycle 2 changes

Only the following namespace and technical-run changes are permitted:

1. Config: `user_data/config-pro-day-v2-cycle2-research.json`.
2. FreqAI identifier:
   `proday-v2-cycle2-canonical5m-lgbm-20260811`. This prevents reuse of the
   technical Cycle 1 models/predictions.
3. Reports: `user_data/reports/pro_day_v2_cycle2/`.
4. Manifest:
   `user_data/reports/pro_day_v2_cycle2/research_freeze_manifest.json`.
5. Trial ledger: `user_data/reports/pro_day_v2_cycle2/trial_ledger.json`.
6. Explicit artifacts:
   - `user_data/backtest_results/prodayv2-cycle2-train.zip`
   - `user_data/backtest_results/prodayv2-cycle2-validation.zip`
   - `user_data/backtest_results/prodayv2-cycle2-current-partial.zip`
   - `user_data/backtest_results/prodayv2-cycle2-canonical.zip`
7. Fixed recursive counts become `[199, 399, 799, 1599, 2399]`, all below the
   official tool's reported limit of 2,494. The frozen strategy startup remains
   399. At startup 399, every decision-critical deterministic indicator/candidate
   column must have absolute variance <=0.01%, and entry/exit signal differences
   must be zero. The other counts remain diagnostics. Any tool failure,
   non-target lookahead finding, variance failure, or signal difference fails
   closed.
8. The already frozen canonical directory is bind-mounted read-only as
   `/canonical/futures`, and every Freqtrade command must use `--datadir /canonical`.
   This satisfies Freqtrade's automatic futures subdirectory layout without moving,
   copying, rewriting, or changing any hashed canonical input.
9. Public, credential-free Binance exchange metadata access is permitted only so
   CCXT can load market precision/limits. Key and secret remain empty. Historical
   OHLCV/funding/mark inputs must come only from the read-only canonical mount.
10. `freqai.purge_old_models` is set to `0` for this research cycle so every
    walk-forward fold directory remains available for the plan-required model,
    metadata, feature-list, and training-boundary hashes. This is an audit-retention
    change only: it does not alter any feature, label, training row, prediction,
    model capacity, entry, exit, sizing, risk, split, or performance gate.
11. Recursive and lookahead analysis use separate, dedicated model roots under the
    Cycle 2 report namespace. Qualification uses the normal Cycle 2 identifier path
    only after proving it is absent. Technical-analysis models may be inventoried
    for evidence but may never be reused for TRAIN, VALIDATION, CURRENT, canonical,
    dry-run, or live decisions.
12. Freqtrade may report the single frozen FreqAI target column
    `&-candidate_net_log_return` as lookahead-biased because that column is deliberately the
    future training label. Only that exact target-column report is excluded from
    the indicator-bias decision. Biased entry signals, biased exit signals, any
    `%` feature, any deterministic indicator/candidate column, or any other `&`
    target remains an immediate failure. The report must retain both the raw tool
    result and this explicit target-only interpretation.
13. The lookahead gate uses all three locked pairs, timerange
    `20240101-20260101`, `minimum_trade_amount=100`, and
    `targeted_trade_amount=120`. It must represent `T1_long`, `T1_short`,
    `R1_long`, and `R1_short` among the analyzed trades. Tool output is captured;
    no return, profit factor, drawdown, or trade profit is parsed or stored.

## Reused immutable evidence

- Canonical data audit SHA256:
  `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`.
- Runtime compatibility SHA256:
  `155dbfe16892d5d4616ee1186d29678ea2baaab51cb84ea1673caaa7ed22ca1b`.
- Runtime remains linux/amd64
  `freqtradeorg/freqtrade:2026.7_freqai@sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000`.
- The 12 canonical OHLCV and six funding/mark auxiliary inputs are reused by exact
  hash. Native Binance 15m/1h/4h files remain excluded.

## Sequential decision

1. Freeze Cycle 2 before recursive/lookahead/model qualification.
2. Recursive fail: `REJECT_PRO_DAY_TRADER_V2` and stop.
3. Only recursive pass unlocks lookahead analysis. Lookahead fail: reject and stop.
4. Only both technical gates pass unlock one TRAIN OOS run
   `[2022-01-01, 2024-01-01)`.
5. TRAIN fail: `KEEP_OFFLINE_RESEARCH` and do not reveal validation/current.
6. Only TRAIN pass unlocks one VALIDATION OOS run; only its pass unlocks CURRENT,
   diagnostics, and locked cost stress.
7. Only every inherited absolute gate passes may produce
   `APPROVE_SEPARATE_DRY_RUN`. Live trading and automatic promotion remain false.

This addendum cannot be edited after the first Cycle 2 technical/model run. A later
change requires another named cycle and a new identifier.
