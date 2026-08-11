# Final Strategy Selection

## Final decision

`FINAL_BEST_DUALTRENDFUTURESV2R_RETAINED`

No strategy can be demonstrated to be universally ideal or guaranteed
profitable. Under the complete locked tournament used in this project,
`DualTrendFuturesV2R` is the strongest robust research candidate. It remains
running as the credential-free forward dry-run on port 8081. The V1 control
remains running on port 8080. The final V3R challenger was never deployed.

## Final challenger hypothesis

V3R kept V2R entries, 0.325-0.65 ATR/exposure stake sizing, hard stop,
protections, and 1x leverage. It replaced V2 exits with the official
Chandelier-style formula:

- Long exit = 22-candle highest high - 3 x ATR14.
- Short exit = 22-candle lowest low + 3 x ATR14.
- Daily EMA20 regime failure remained an exit.

TradingView describes the [Chandelier Exit](https://www.tradingview.com/support/solutions/43000773013-chandelier-exit/)
as a volatility-based local-extreme/ATR exit intended to keep a trade in an
established trend until a significant reversal. The formula was tested exactly
once with no grid or post-result threshold change.

## Tournament results

| Window | Selected V2R return / PF / DD | Rejected V3R return / PF / DD |
|---|---:|---:|
| Backcast 2020-08/12 | +12.85% / 2.267 / 5.57% | +15.93% / 2.497 / 7.71% |
| Train 2021-2023 | +111.01% / 1.720 / 17.08% | +135.48% / 1.840 / 16.10% |
| Validation 2024-2025 | **+37.85% / 1.689 / 9.35%** | +38.56% / 1.693 / 10.70% |
| 2025 | **+7.52% / 1.342 / 9.35%** | +5.05% / 1.219 / 9.98% |
| Current 2026-01/08 | **+9.85% / 1.852 / 4.61%** | +1.16% / 1.067 / 10.52% |
| Fee validation, 0.15%/side | **+32.83% / 1.582 / 9.96%** | +33.36% / 1.585 / 11.40% |

V3R gained only 0.71 percentage points of validation return while increasing
drawdown by 1.35 points. Its validation return/max-drawdown was 10.97% worse.
Its current-2026 return was 8.69 points lower, PF fell from 1.852 to 1.067, and
drawdown more than doubled.

## Annual robustness

| Fold | V2R return | V3R return |
|---|---:|---:|
| 2021 | +92.34% | +106.59% |
| 2022 | +2.09% | +1.48% |
| 2023 | +7.33% | +12.96% |
| 2024 | +28.26% | +31.79% |
| 2025 | **+7.52%** | +5.05% |
| 2026 partial | **+9.85%** | +1.16% |

The Chandelier exit improved strong historical trends but degraded the more
recent weak/bearish regimes. This is precisely the regime sensitivity that the
final rules were designed to reject.

## Block-bootstrap stress

A deterministic four-week circular block bootstrap used 261 observed weekly
train+validation returns and 5,000 simulated five-year paths per strategy.

| Strategy | Terminal return p05 / median / p95 | Max weekly DD p50 / p95 |
|---|---:|---:|
| V2R | **+24.62% / +174.75% / +656.62%** | **14.76% / 25.96%** |
| V3R | +21.53% / +205.25% / +905.62% | 15.59% / 27.79% |

V3R had a higher median/upside tail but a lower fifth-percentile return and
higher drawdown tail. Bootstrap is a resampling diagnostic, not a forecast.

## Gate outcome

V3R failed the absolute current-2026 gate and six incumbent-superiority gates:

- Validation return/max-DD improvement.
- 2025 return.
- Current-2026 return.
- Fee-validation return/max-DD.
- Worst-fold return.
- Bootstrap fifth-percentile terminal return.

Its technical checks passed: 100 lookahead signals with zero bias, recursive
EMA200 variance -0.005%, and zero Chandelier indicator variance at startup 800.
Clean code does not compensate for weaker risk-adjusted performance.

## Selected strategy definition

The selected `DualTrendFuturesV2R` combines:

- Daily EMA20/50/200 and ROC63 long/short regime.
- 4h 30-candle breakout/breakdown.
- Three-of-four DMI, rising ADX, relative-volume, and VWMA/SMA confluence.
- V2 channel/daily/VWMA-DMI invalidation exits.
- ATR/exposure stake multiplier from 0.325 to 0.65.
- Hard stop -10%, protections, isolated 1x leverage, no DCA or martingale.

Freqtrade's official [`custom_stake_amount()` documentation](https://www.freqtrade.io/en/stable/strategy-callbacks/)
supports the selected sizing callback. The system remains dry-run only; live
trading and API credentials are not authorized.

## Active runtime

- Selected V2R forward dry-run: http://127.0.0.1:8081
- Primary V1 control: http://127.0.0.1:8080
- Both states: running, futures, shorts enabled, empty keys, separate DB/log.
- V3R: rejected and not running.

The historical periods were visible during development. The only new evidence
is the forward dry-run beginning now, which currently has no closed trades.
Replacing the V1 control or using live funds requires a meaningful future
sample across multiple regimes. Nothing here guarantees future profit.

## Automated forward evidence

The read-only `forward-monitor` service now snapshots both dry-run APIs every
four hours. Its rules were locked before the first snapshot: at least 30 days,
at least 30 closed trades per bot, V2R PF at least 1.20, V2R wallet-normalized
drawdown at most 10%, at least four traded pairs, and forward risk-adjusted
performance no worse than the V1 control. Runtime safety and independently
recomputed API reconciliation must also pass.

The service can emit only `FORWARD_REVIEW_READY`, never automatic promotion or
live authorization. Current machine state is stored in
`user_data/reports/forward_monitor_decision.json`; the complete locked rules
are in `docs/forward_monitoring_plan.md`.

## 2026-08-11 cost-robustness follow-up

A later locked matrix tested six pair-independent entry filters against the
incumbent's weak 2022 adverse-cost result.  ROC63 above 10% repaired both 2022
cost gates, including severe net profit from -3.801 to +0.775 USDT, but reduced
2023 from 22 to 16 trades and failed the pre-declared minimum sample gate.  All
other variants still failed the 2022 cost gates.  No candidate was advanced to
validation, no parameters were changed after results, and V2R was retained.
See `docs/cost_robust_challenger_results.md` for the complete counter-evidence.

## Reproducible artifacts

- Locked plan: `docs/dual_trend_final_challenger_locked_plan.md`
- V3R source: `user_data/strategies/DualTrendFuturesV3R.py`
- Selected V2R source: `user_data/strategies/DualTrendFuturesRisk.py`
- Executed notebook: `user_data/notebooks/final_strategy_tournament.ipynb`
- Tournament summary: `user_data/reports/final_tournament_summary.csv`
- Comparison: `user_data/reports/final_tournament_comparison.csv`
- Bootstrap: `user_data/reports/final_tournament_block_bootstrap.csv`
- Absolute gates: `user_data/reports/final_v3r_absolute_gates.csv`
- Superiority gates: `user_data/reports/final_v3r_superiority_gates.csv`
- Machine decision: `user_data/reports/final_strategy_decision.json`
- Runtime evidence: `user_data/reports/final_strategy_runtime.json`
- Forward monitor: `tools/monitor_forward_dry_runs.py`
- Forward decision: `user_data/reports/forward_monitor_decision.json`
- Cost-robustness decision: `user_data/reports/cost_research_decision.json`
