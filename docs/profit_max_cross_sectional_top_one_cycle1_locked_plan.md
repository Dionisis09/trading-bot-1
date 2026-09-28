# ProfitMax Cross-Sectional Top-One Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only.

## Fixed hypothesis

The prior neutral 30-day model showed a positive top-leader long leg in every TRAIN year, while adding a second leader caused early losses and account-risk shutdown. This cycle isolates exactly one 30-day leader at a time and tests three predeclared fixed holding periods: 24h, 16h and 12h. No other rule differs.

Ranks use completed 4h closes across the frozen 50-pair universe, require >=35 valid pairs, and fill only at the next 4h open. The strategy is long-only, has an 8% hard stop and uses the frozen professional risk policy. No pair/threshold changes, hyperopt, ML or LLM order control are allowed after TRAIN.

Execution: exact fee 0.00075 per side plus funding, futures isolated, 1x, wallet 1,000 USDT, proposed stake 50 USDT before ATR scaling, max two account positions, protections enabled.

TRAIN 2021–2023 gates: 1,095–2,190 trades, return >0, PF >=1.30, wallet DD <=10%, return/DD >=2; every year positive/PF >=1.15; >=20 traded pairs, >=12 positive pairs, worst pair >-3%, largest positive contribution <=30%. No passer means `KEEP_OFFLINE_RESEARCH` and validation stays hidden.

Any passer must pass source/config reconciliation, zero-bias lookahead, recursive convergence and cost stress. VALIDATION 2024–2025 requires 731–1,462 trades, return >0, PF >=1.25, DD <=10%, return/DD >=1.5 and both years positive/PF >=1.10. CURRENT_PARTIAL requires 212–424 trades, return >=0, PF >=1.05, DD <=8%. Continuous 2021–2026-08 requires 1–2 trades/day, return >=15%, PF >=1.30, DD <=10%, all full years positive and moderate/severe stress profitable with PF >=1.15/1.05.

Only a full pass permits an isolated dry-run; no live authorization or profit guarantee follows.
