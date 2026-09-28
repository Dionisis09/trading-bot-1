# ProfitMax Weighted Daily + V5 Cycle 1 - Locked retrospective plan

Status: `LOCKED_BEFORE_CONTINUOUS_REPLAY`. Offline research only; live trading unauthorized.

All history through 2025 has now been seen. This cycle is explicitly retrospective robustness research, not a new holdout. It changes only portfolio allocation: `ProfitMaxDailyCrossStop20AuditV2` uses 20 USDT proposed stake, while `ProfitMaxV5Asymmetric50` retains 50 USDT. Signals, 50/6-pair universes, 4h timing, exits, stops, fee 0.00075/side, funding, isolated 1x execution and max two slots per sleeve are unchanged.

One no-cache continuous replay is fixed for 2021-01-01 through 2026-08-01. Combined gates: 1-2 trades/day, return >=10%, PF >=1.25, wallet DD <=10%, return/DD >=2, every full 2021-2025 year positive/PF >=1.05, 2026 partial positive/PF >=1.05, V5 full-stream PF >=1.50, daily full-stream nonnegative/PF >=1.00, max four positions and <=20% starting-wallet stake. An additive 5 bps slippage per side must remain profitable/PF >=1.15.

Passing authorizes only an isolated dry-run proposal. Since parameter allocation used already-seen history, forward evidence is mandatory and no live authorization or profit guarantee follows.
