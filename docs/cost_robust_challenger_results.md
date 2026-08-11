# Cost-Robust Challenger - Results

## Decision

`RETAIN_V2R`

None of the six pre-declared candidates passed every training gate.  Per the
locked plan, validation was not run and no post-result parameter adjustment
was allowed.  The active `DualTrendFuturesV2R` dry-run remains unchanged.

## Strongest candidate and counter-evidence

`CostRobustRoc10` was the only candidate that repaired the 2022 moderate and
severe execution-cost failures.  It removed five weaker trades and improved
the severe result from -3.801 USDT / PF 0.810 to +0.775 USDT / PF 1.045.
However, it produced only 16 trades in 2023, below the locked minimum of 20.
That smaller sample is insufficient to call the filter robust.

| Year / scenario | V2R trades / net / PF | ROC10 trades / net / PF |
|---|---:|---:|
| 2021 standard | 37 / +61.007 / 4.401 | 37 / +58.259 / 4.247 |
| 2021 severe | 37 / +42.843 / 3.016 | 37 / +40.392 / 2.901 |
| 2022 standard | 46 / +1.732 / 1.103 | 41 / +5.498 / 1.375 |
| 2022 moderate | 46 / +0.193 / 1.011 | 41 / +4.179 / 1.272 |
| 2022 severe | 46 / -3.801 / 0.810 | 41 / +0.775 / 1.045 |
| 2023 standard | 22 / +10.670 / 2.585 | 16 / +8.994 / 2.703 |
| 2023 severe | 22 / +6.989 / 1.844 | 16 / +6.188 / 1.955 |

Net values are USDT from the fixed 1,000 USDT research wallet.  Stress metrics
are deterministic diagnostics applied to exported trades, not forecasts.

## Complete rejection summary

| Candidate | Standard net, 2021-2023 | Severe net, 2021-2023 | Failed gates |
|---|---:|---:|---|
| ROC5 | +72.999 | +46.538 | 2022 moderate, 2022 severe, 2023 trade count |
| ROC10 | +72.751 | +47.354 | 2023 trade count |
| EMA separation 1% | +73.906 | +47.579 | 2022 moderate, 2022 severe |
| ATR minimum 1% | +71.870 | +44.713 | 2022 moderate, 2022 severe |
| Breakout 50 | +76.052 | +49.925 | 2022 moderate, 2022 severe, 2023 trade count |
| ROC5 + EMA1 | +74.019 | +48.621 | 2022 moderate, 2022 severe, 2023 trade count |

All source totals reconciled exactly with the raw exported trades.  No
pair-specific exclusion was used.  The validation windows were deliberately
left unqueried after the training decision, as required by the plan.

## Artifacts

- Locked plan: `docs/cost_robust_challenger_locked_plan.md`
- Research strategies: `user_data/strategies/DualTrendFuturesCostResearch.py`
- Training archives: `user_data/backtest_results/cost_research_train_2021.zip`,
  `cost_research_train_2022.zip`, and `cost_research_train_2023.zip`
- Full metrics: `user_data/reports/cost_research_metrics.csv`
- Machine decision: `user_data/reports/cost_research_decision.json`

This research does not authorize live trading and cannot guarantee profit.
