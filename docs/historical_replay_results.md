# Accelerated Historical Replay Results

## Decision

`HISTORICAL_DIAGNOSTIC_PASS`, with material regime weaknesses still visible.

The active V1 and V2R dry-run profiles were replayed independently and in
chronological order from `2021-01-01` through `2026-08-01`.  The simulation
processed roughly 5.6 market years in seconds.  All 9 locked whole-period
diagnostic gates passed, and both raw Freqtrade totals reconciled exactly with
the exported trades.

This is historical evidence only.  It does not count toward the 30-day forward
sample, does not authorize Binance credentials or live trading, and does not
guarantee future profit.

## Whole-period results

| Strategy / costs | Trades | Net USDT | Profit factor | Realized drawdown |
|---|---:|---:|---:|---:|
| V1 standard | 254 | +189.303 | 1.981 | 2.47% |
| V1 moderate | 254 | +165.813 | 1.820 | 2.89% |
| V1 severe | 254 | +100.913 | 1.444 | 5.04% |
| V2R standard | 205 | +104.625 | 2.325 | 1.10% |
| V2R moderate | 205 | +94.149 | 2.139 | 1.23% |
| V2R severe | 205 | +65.426 | 1.704 | 1.58% |

V1 produced more absolute historical profit with its full fixed stake.  V2R
produced the stronger profit factor and materially smaller drawdown because its
ATR/exposure callback reduces the proposed 25 USDT stake.  The comparison is
therefore useful for the behavior of the two active bots, not a claim that
their absolute returns carry identical risk.

## V2R calendar replay

| Period | Trades | Standard net USDT | Standard PF | Severe net USDT | Severe PF |
|---|---:|---:|---:|---:|---:|
| 2021 | 36 | +60.810 | 4.390 | +42.763 | 3.012 |
| 2022 | 45 | +3.167 | 1.196 | **-2.344** | **0.878** |
| 2023 | 22 | +8.439 | 2.093 | +5.094 | 1.543 |
| 2024 | 41 | +23.888 | 2.713 | +17.803 | 2.077 |
| 2025 | 38 | +4.134 | 1.278 | +0.231 | 1.014 |
| 2026 partial | 23 | +4.188 | 1.500 | +1.879 | 1.192 |

Every calendar fold was positive at standard cost, but 2022 failed both the
yearly moderate threshold (PF 1.097 versus 1.10) and the severe test.  The 2025
severe margin was also very thin.  This confirms the existing execution-stress
warning instead of removing it.

## Regime diagnostics

- 10 of 23 calendar quarters were negative at standard cost.
- Standard long trades contributed +107.247 USDT; shorts contributed -2.622
  USDT.  The short side did not add historical edge in this active-profile
  replay.
- BNB, XRP, ADA, and DOGE were positive.  BTC and ETH produced no closed trades
  under the active two-slot/protection replay, so pair breadth passed only at
  the exact locked minimum of four.
- The first attempted artifact is excluded: it mistakenly used the unlimited
  research profile, causing the account guard to reject the V1 control.  The
  two reported archives use the exact active 1,000 USDT wallet, fixed 25 USDT
  proposed stake, and two-position profiles.
- Newly generated replay ZIPs were sanitized and ZIP-tested after Freqtrade's
  config export was found to retain a dashboard JWT value.  Trade payloads and
  source reconciliation remained unchanged after sanitization.

## Evidence

- Locked plan: `docs/historical_replay_locked_plan.md`
- Decision: `user_data/reports/historical_replay_decision.json`
- Detailed metrics: `user_data/reports/historical_replay_metrics.csv`
- V1 archive: `user_data/backtest_results/historical_replay_v1_active.zip`
- V2R archive: `user_data/backtest_results/historical_replay_v2r_active.zip`

The practical conclusion is to keep V2R in credential-free dry-run.  The fast
historical replay is useful and broadly positive, but the 2022 cost failure,
weak short contribution, exact-minimum pair breadth, and negative quarters are
reasons the genuine forward observation period is still required.

