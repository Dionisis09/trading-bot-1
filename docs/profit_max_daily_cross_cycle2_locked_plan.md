# ProfitMax Daily Cross Cycle 2 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only; validation remains sealed and live trading unauthorized.

Cycle 1 established that the twice-daily seven-day leader/BTC-30d gate produced 1,038 trades, +50.334 USDT and PF 1.13 in a post-failure isolation run, but the inherited multi-day StoplossGuard/MaxDrawdown locks reduced the qualifying run to 372 trades. Cycle 2 changes no alpha, universe, fee, stake, leverage, timing or split. It tests a bounded risk-policy correction.

Three candidates are fixed before PnL: hard stops -12%, -16%, and -20%. All retain the exact Cycle 1 signal, 8h time exit, ATR stake reduction, fail-closed professional account guard and 1x leverage. Backtests enable protections, but the strategy's protection set is exactly one `CooldownPeriod` candle; the inherited 42/180-candle global locks are removed because their horizon is incompatible with a twice-daily eight-hour strategy.

TRAIN is 2021-01-01 through 2024-01-01. A candidate must have 1,095–2,190 trades, 1–2/day, return >0, PF >=1.15, wallet DD <=12%, return/DD >=1.0, every year positive with PF >=1.02, >=35 traded pairs, >=20 positive pairs, worst pair >-3% of starting wallet and largest positive-pair contribution <=25%. Passers rank by return/DD, then PF, then tighter stop. No passer means `KEEP_OFFLINE_RESEARCH` and no validation.

The selected TRAIN candidate must subsequently pass source/archive/config reconciliation, lookahead and recursive gates, then moderate/severe cost stress before one-time VALIDATION 2024–2025. Validation and current gates remain exactly those in Cycle 1. Only a full pass may authorize a separate dry-run; no outcome guarantees profit or authorizes live trading.

