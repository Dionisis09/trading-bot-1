# ProfitMax Portfolio Ensemble Cycle 3 - Locked validation plan

Status: `LOCKED_BEFORE_VALIDATION_PNL`. Exploratory offline research only.

This cycle uses only the three components independently reproduced with `--cache none` on TRAIN 2021-2023: `ProfitMaxCrossSectionalTopTwo8h` (2 slots, stake 50), `ProfitMaxV5Asymmetric50` (2 slots, stake 50), and `DualTrendFuturesV1` (1 slot, stake 50). V1 trades sharing exact pair and open timestamp with V5 are removed. No strategy, pair, side, parameter, stake, or deduplication change is permitted.

The already-seen TRAIN portfolio has 1,111 trades (1.015/day), +24.96%, PF 1.578 and wallet DD 2.84%; all three years are positive, although 2022 PF 1.012 is weak. Therefore this is an exploratory validation, not a retroactive TRAIN pass.

Validation is exactly 2024-01-01 through 2026-01-01, run once with `--cache none`, completed 4h candles, next-open fills, protections, isolated futures, 1x leverage, and fee 0.00075 per side plus funding. Gates: 1-2 trades/day, return >0, PF >=1.30, DD <=10%, return/DD >=2, both 2024 and 2025 positive, every selected component net positive with PF >=1.05, at least 20 retained V1 trades, observed positions <=5, and observed stake <=20% of the 1,000 USDT wallet.

A failure means `KEEP_OFFLINE_RESEARCH`. A pass only unlocks Cross lookahead/recursive analysis, continuous 2021-2026-08 reconciliation, and execution stress. It never authorizes live trading or guarantees profit.
