# Binance Major Trend Portfolio V4 - Train/Validation Decision

V4 was evaluated only on the locked train and validation windows. The final
holdout remained sealed.

| Strategy | Train trades | Train return | Train PF | Validation trades | Validation return | Validation PF | Validation DD | Positive pairs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MajorTrendV4A | 120 | 447.27% | 2.279 | 111 | 56.31% | 1.458 | 14.75% | 6/10 |
| MajorTrendV4B | 136 | 643.27% | 2.321 | 119 | 61.48% | 1.527 | 11.10% | 6/10 |
| MajorTrendV4C | 115 | 452.47% | 2.402 | 107 | 48.74% | 1.419 | 23.86% | 6/10 |
| MajorTrendV4D | 103 | 356.92% | 2.533 | 91 | 53.41% | 1.486 | 15.23% | 5/10 |

V4B has the highest minimum train/validation PF and the lowest validation
drawdown among the otherwise competitive variants. It nevertheless fails the
predeclared V4 asset-level gates: SOL/USDT and LINK/USDT have validation PF
below 0.75 with at least ten trades, and sparse LTC/USDT loses more than 8% of
starting equity.

Decision: `NO_V4_HOLDOUT_CANDIDATE`. The V4 results may be used for a disclosed
final model-selection phase, but V4 is not retroactively approved.

