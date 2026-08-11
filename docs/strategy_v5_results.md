# Major Trend V5 - Train/Validation Decision

V5 was evaluated with its frozen five-symbol universe. The holdout remained
sealed.

- Train: 78 trades, +406.09%, PF 2.614, maximum drawdown 11.13%.
- Validation: 78 trades, +74.08%, PF 2.221, maximum drawdown 8.18%.
- Validation single-trade concentration: 17.57% of positive trade profit.
- Validation pair concentration: XRP/USDT contributes 52.31% of positive pair
  profit, above the fixed 50% limit.
- ADA/USDT validation result: -0.15%, PF 0.986, rather than the required
  positive return and PF of at least 1.00.

Decision: `NO_V5_HOLDOUT_CANDIDATE`. The near misses are not rounded into a
pass, and the 2026 holdout was not opened.

