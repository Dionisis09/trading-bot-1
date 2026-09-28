# Profit-Max Swing Cycle 5 - winner qualification plan

Locked after deterministic tournament selection and before cost or technical qualification. Winner: `ProfitMaxV5Asymmetric50`.

Frozen evidence:

- continuous sanitized ZIP SHA256 `c8290f42b9aa05e98969cc446cbb2d1e2f6a18c035893dd336c1a4f523062a1e`
- tournament JSON SHA256 `793ded53669c5182be4a1e81726a33bd85180f6cc1fddde4d5f8071bc53a3f50`
- winner source SHA256 `5e2612cb989eb6fd9bf142f3a5ad75aa3db4a4fa923f96b0f88871d7e3c5ec17`
- config SHA256 `5d5fccef730a2dfd44dc6891bb597e2fbb46be723ed8dac52dd483f55bca22ec`

Qualification gates:

1. Continuous moderate and severe deterministic execution-cost stress must each remain profitable. Moderate PF >= 1.10 and realized DD <= 15%; severe PF >= 1.00 and DD <= 20%.
2. Recursive analysis uses BTC full timerange `20210101-20260801`, startup counts `[199,399,799,1599]`; the 1599 result requires <=0.01% material variance and no indicator lookahead.
3. Pair-isolated official lookahead runs use all six pairs separately, full timerange, minimum 20 and target 30 signals. Every pair requires no bias, zero unmatched entry/exit signals and zero biased indicators.
4. Any failure keeps the winner offline. A complete pass permits only a fresh isolated dry-run with a new empty database; never live trading.
