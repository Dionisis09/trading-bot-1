# Profit-Max Swing Cycle 5 - locked asymmetric-short plan

Status: `LOCKED_BEFORE_PNL`. Historical robustness research only; no live authorization.

The unchanged control is `DualTrendFuturesV2R`. Four fixed variants are declared once, with no hyperopt, grid search or post-result edits:

1. `ProfitMaxV5Asymmetric50`: identical signals; a short receives 50% of the control's volatility-adjusted stake.
2. `ProfitMaxV5SelectiveShort`: identical long rules and stake; a short is permitted only when the completed daily EMA200 is below its value seven days earlier.
3. `ProfitMaxV5Balanced`: combines the same seven-day declining-EMA200 short filter with 50% short stake.
4. `ProfitMaxV5LongOnly`: disables shorts and is a diagnostic upper bound only. It is ineligible for selection because it abandons bear-side coverage.

All variants keep the six-pair universe, 4h base plus causal 1d informative data, isolated futures, 1x leverage, 1000 USDT wallet, 125 USDT proposed stake, maximum two open positions and 5 bps fee per side. Entry and exit rules, protections, long stake and stoploss otherwise remain unchanged.

Time sequence:

- TRAIN: `20210101-20240101`.
- VALIDATION: `20240101-20260101`, revealed once only if at least one eligible candidate passes TRAIN.
- CURRENT_PARTIAL: `20260101-20260801`, diagnostic only after validation.
- CONTINUOUS: `20210101-20260801`, final descriptive replay of the selected eligible candidate and the unchanged control only.

TRAIN gates for an eligible candidate: at least 100 trades, positive return, PF >= 1.30, wallet DD <= 12%, return/DD >= 1.5, at least 25 long and 25 short trades. VALIDATION gates: at least 70 trades, positive return, PF >= 1.25, wallet DD <= 10%, return/DD >= 1.5, at least 20 long and 20 short trades, positive return in both 2024 and 2025. Selection is the highest validation return/DD among candidates passing every gate, tie-broken by PF then lower DD. The control is eligible. Long-only is always diagnostic-only.

After selection, moderate and severe execution-cost stress, recursive analysis and pair-isolated lookahead are mandatory. A pass permits a new isolated dry-run only. Historical data are already seen and cannot guarantee future profit.
