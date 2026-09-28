# ProfitMax Cross-Sectional Long Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only; live trading unauthorized.

## Fixed hypothesis

In the prior frozen TRAIN, the 30-day cross-sectional neutral strategy was positive overall but failed. Its independently reconciled long leg was positive in every TRAIN year: PF 1.391 in 2021, 1.480 in 2022 and 1.266 in 2023, while the short leg lost money in all three years. This cycle tests the predeclared hypothesis that two diversified long leaders can retain that edge and mechanically reach the requested portfolio frequency without the destructive short leg.

Candidates fixed before PnL:

- `ProfitMaxCrossSectionalLong30d48h`: top two 30-day leaders, fixed 48h holding;
- `ProfitMaxCrossSectionalLong60d48h`: top two 60-day leaders, fixed 48h holding;
- `ProfitMaxCrossSectionalLong30d36h`: top two 30-day leaders, fixed 36h holding.

Ranks use only the current and earlier completed 4h closes; fills occur at the next 4h open. Ties use frozen universe order, and at least 35 simultaneous pairs are required. No shorting, pair deletion, hyperopt, ML, LLM order control or post-result threshold patch is permitted.

## Execution and risk

- Main 4h; exact fee 0.00075 per side plus recorded funding; hard stop 8%; no ROI/trailing exit.
- Futures isolated, 1x, 1,000 USDT wallet, proposed stake 100 USDT before frozen ATR scaling.
- Frozen professional policy caps two concurrent positions and 20% total open stake; 4h protections enabled.
- Current-active-universe survivorship bias remains explicit.

## Gates

TRAIN 2021–2023: 1,095–2,190 trades, return >0, PF >=1.30, wallet DD <=10%, return/DD >=2; every year positive and PF >=1.15; >=25 traded pairs, >=15 positive pairs, worst pair >-3%, largest positive-pair contribution <=25%.

Multiple passers rank by return/DD, PF, lower DD, lexical name. No passer means `KEEP_OFFLINE_RESEARCH`, without validation. A passer must then clear archive/source/config reconciliation, lookahead analysis, recursive convergence and locked cost stress before one-time validation.

VALIDATION 2024–2025: 731–1,462 trades, return >0, PF >=1.25, DD <=10%, return/DD >=1.5, each year positive/PF >=1.10, >=25 traded and >=15 positive pairs. CURRENT_PARTIAL 2026-01-01 through 2026-08-01: 212–424 trades, return >=0, PF >=1.05, DD <=8%. Continuous 2021-01-01 through 2026-08-01: 1–2 trades/day, return >=20%, PF >=1.30, DD <=10%, every full year positive, >=30 traded and >=20 positive pairs. Moderate/severe stress must stay profitable with PF >=1.15/1.05.

Only a full pass authorizes a separate dry-run. It does not authorize live trading or guarantee future profit.
