# Binance Major Trend Portfolio V3 - Train/Validation Decision

The V3 train and validation runs were completed with the trial budget, universe,
fees, protections, and chronological splits locked in
`strategy_v3_portfolio_plan.md`. The final holdout was not opened.

## Recomputed portfolio results

| Strategy | Train trades | Train return | Train PF | Validation trades | Validation return | Validation PF | Validation DD | Positive pairs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MajorTrendV3A | 139 | 176.45% | 1.776 | 128 | 111.49% | 1.781 | 11.67% | 6/10 |
| MajorTrendV3B | 115 | 268.96% | 2.040 | 107 | 78.49% | 1.710 | 12.33% | 6/10 |
| MajorTrendV3C | 156 | 538.56% | 1.845 | 121 | 73.63% | 1.579 | 19.27% | 6/10 |
| MajorTrendV3D | 170 | 555.67% | 1.890 | 153 | 49.17% | 1.360 | 17.07% | 7/10 |

The values above were independently extracted from the Freqtrade JSON exports,
not copied from terminal display tables.

## Gate failure

All four variants are net profitable in train and validation after the modeled
0.10% fee per side, and all pass the portfolio PF, validation trade-count, and
validation drawdown gates. None passes the predeclared pair-level floor:

- V3A validation minimum pair PF: AVAX/USDT, 0.000.
- V3B validation minimum pair PF: AVAX/USDT, 0.000.
- V3C validation minimum pair PF: AVAX/USDT, 0.000.
- V3D validation minimum pair PF: LINK/USDT, 0.023.
- V3A also exceeds the train concentration limit: SOL/USDT contributes 51.36%
  of total positive pair profit.

Decision: `NO_V3_HOLDOUT_CANDIDATE`. No V3 variant may be tested on the sealed
2026-01-01 through 2026-08-01 holdout.

