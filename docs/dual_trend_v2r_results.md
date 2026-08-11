# DualTrendFuturesV2R - Matched-Risk Validation and Forward Dry-Run

## Decision

`PARALLEL_DRY_RUN_RUNNING`

The single locked ATR/exposure overlay passed every absolute, matched-risk,
data, signal-identity, concentration, fee-stress, and bias gate. A separate V2R
dry-run is running locally on port 8081. The primary V1 dry-run remains running
unchanged on port 8080. Both have empty Binance credentials; live trading is
not authorized.

## Fixed overlay

The overlay was applied identically to V1R (control) and V2R (challenger):

- Base stake multiplier: 0.65 of Freqtrade's proposed stake.
- Volatility scalar: `3% / ATR%`, clamped to 0.50-1.00.
- Final multiplier range: 0.325-0.65 of proposed stake.
- Invalid/missing ATR fallback: conservative 0.325 multiplier.
- No signal, exit, stop, protection, market, timeframe, or leverage change.
- Hard -10% stop, no DCA/martingale, isolated 1x leverage.

The implementation follows Freqtrade's official
[`custom_stake_amount()` callback](https://www.freqtrade.io/en/stable/strategy-callbacks/).
ATR is used as a volatility measure, consistent with TradingView's
[ATR definition](https://in.tradingview.com/support/solutions/43000501823-average-true-range-atr/),
not as a direction predictor. Freqtrade's leverage documentation explicitly
warns that leverage modes are high risk; V2R therefore remains fixed at 1x and
dry-run only: [Freqtrade leverage guide](https://www.freqtrade.io/en/stable/leverage/).

## Matched-risk results

Both strategies used the identical sizing overlay, six-pair universe, archived
4h/1d/funding/mark data, 10,000 USDT research wallet, four maximum research
positions, portfolio protections, and 1x leverage.

| Window | V1R return / PF / DD | V2R return / PF / DD | V2R return change |
|---|---:|---:|---:|
| Train 2021-2023 | +141.07% / 1.734 / 18.19% | +111.01% / 1.720 / 17.08% | -30.06 pp |
| Validation 2024-2025 | +24.60% / 1.384 / 8.13% | **+37.85% / 1.689 / 9.35%** | +13.25 pp |
| 2024 | +21.16% / 1.693 / 8.05% | **+28.26% / 2.059 / 8.74%** | +7.10 pp |
| 2025 | +2.76% / 1.100 / 7.79% | **+7.52% / 1.342 / 9.35%** | +4.75 pp |
| Current 2026-01/08 | +7.33% / 1.495 / 6.64% | **+9.85% / 1.852 / 4.61%** | +2.51 pp |
| Train, 0.15% fee/side | +127.71% / 1.654 / 19.92% | +99.79% / 1.634 / 18.78% | -27.92 pp |
| Validation, 0.15% fee/side | +19.52% / 1.298 / 9.00% | **+32.83% / 1.582 / 9.96%** | +13.31 pp |

In validation, V2R improved return/max-drawdown by 33.77% versus V1R, above
the locked 20% requirement. It had 128 trades (80 long, 48 short), all six
pairs were profitable, pair-profit concentration was 31.96%, and the largest
winning-trade contribution was 13.25%.

## Important counter-evidence

V2R did not dominate every period. It underperformed V1R on the older
2021-2023 train window and its fee-stressed train, although both remained
strongly positive and V2R had slightly lower drawdown. This is retained as
evidence of regime sensitivity. The challenger is approved for forward data
collection, not declared universally superior.

## Validation evidence

- 22/22 pre-declared absolute and matched-risk gates passed.
- Container unit test verified exact stakes for ATR% 1%, 3%, 4%, 6%, 20%, and
  invalid ATR; callback output stayed between 32.5% and 65% of proposed stake.
- Trade identities were exactly unchanged from V1/V2 in all 14 comparisons:
  zero missing and zero extra trades. Only sizing changed.
- Raw trade rows exactly reconcile stored trade count, absolute profit, PF,
  wins, and losses for all V1R/V2R runs.
- The reused market-data audit remains at 100% declared-period coverage, with
  no duplicates, nulls, invalid OHLCV, or gaps. Previously recorded isolated
  4h-to-1d mismatch days remain below 0.2%.
- Lookahead analysis: 100 signals, zero biased entries/exits/indicators.
- Recursive analysis at startup 800: EMA200 1d variance -0.005%; no indicator
  lookahead detected.
- Executed notebook completed top-to-bottom without code-cell errors.

## Active dry-run topology

| Role | Strategy | URL | Configured stake | Max positions | Database |
|---|---|---|---:|---:|---|
| Primary control | DualTrendFuturesV1 | http://127.0.0.1:8080 | 25 USDT | 2 | `tradesv3.dual-futures-dryrun.sqlite` |
| Forward challenger | DualTrendFuturesV2R | http://127.0.0.1:8081 | 25 USDT proposed | 2 | `tradesv3.dual-futures-v2r-dryrun.sqlite` |

For V2R, the callback reduces the configured 25 USDT proposal to an intended
8.125-16.25 USDT before exchange minimum-stake clamping. Both runtimes use
separate databases and logs. Do not add live keys to both bots: Freqtrade warns
against multiple leveraged bots on one account, and this setup is approved
only because both are credential-free dry-runs.

## Evidence boundary and forward rule

The historical periods were already visible, so they are not a fresh sealed
holdout. The V2R dry-run starting now is the first genuinely new forward
comparison. Do not replace V1 or authorize live trading until V2R accumulates a
meaningful forward sample across multiple market regimes. Historical returns
and dry-run results cannot guarantee future profit.

## Reproducible artifacts

- Locked plan: `docs/dual_trend_v2r_locked_plan.md`
- Risk strategies: `user_data/strategies/DualTrendFuturesRisk.py`
- V2R dry-run config: `user_data/config-dual-futures-v2r-dry-run.json`
- Executed notebook: `user_data/notebooks/dual_trend_v2r_validation.ipynb`
- Summary: `user_data/reports/dual_trend_v2r_backtest_summary.csv`
- Matched comparison: `user_data/reports/dual_trend_v2r_vs_v1r.csv`
- Gate matrix: `user_data/reports/dual_trend_v2r_performance_gates.csv`
- Signal identity audit: `user_data/reports/dual_trend_v2r_signal_identity.csv`
- Raw reconciliation: `user_data/reports/dual_trend_v2r_backtest_reconciliation.csv`
- Stake profile: `user_data/reports/dual_trend_v2r_stake_profile.csv`
- Lookahead: `user_data/reports/DualTrendFuturesV2R_lookahead.csv`
- Runtime verification: `user_data/reports/dual_trend_v2r_runtime_verification.json`
- Machine decision: `user_data/reports/dual_trend_v2r_validation_decision.json`
