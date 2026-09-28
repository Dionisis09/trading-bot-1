# ProfitMax Cross-Sectional Four-Hour Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only.

The earlier top-two 30-day leader strategy was profitable in every TRAIN year at an 8-hour hold, but reached only 0.855 trades/day. The top-one 4-hour diagnostic was approximately break-even. This cycle tests the smallest structural intersection needed to reach the requested 1–2 trades/day range while limiting multiple testing:

- `ProfitMaxCrossSectionalTopTwo4h`: the same causal 30-day ranks and top-two selection, fixed 4-hour hold;
- `ProfitMaxCrossSectionalTopTwo4hPositive`: identical, but requires the selected pair's completed-candle 30-day return to be strictly positive.

No other horizon, rank count, stop, universe, side or filter is allowed. Both candidates are long-only, use the frozen 50-pair universe, at least 35 valid ranked pairs, an 8% hard stop, exact 0.00075 fee per side plus funding, 1x isolated futures, 1,000 USDT wallet, 50 USDT proposed stake, two open positions and enabled protections. Signals use completed 4h candles and fill no earlier than the next 4h open. ML/LLM inputs are excluded.

TRAIN is 2021-01-01 through 2024-01-01. Gates: 1.0–2.0 trades/day, return >0, PF >=1.30, wallet DD <=10%, return/DD >=2.0, every year positive/PF >=1.15, >=20 traded pairs, >=12 positive pairs, worst pair >-3%, and largest positive-pair contribution <=30%.

Any TRAIN failure means `KEEP_OFFLINE_RESEARCH` and validation remains hidden. A complete TRAIN plus technical/source gate pass unlocks one VALIDATION run for 2024-01-01 through 2026-01-01, requiring 1.0–2.0 trades/day, return >0, PF >=1.25, DD <=10%, return/DD >=1.5 and both years positive/PF >=1.10.

CURRENT_PARTIAL is 2026-01-01 through 2026-08-01. Continuous 2021-01-01 through 2026-08-01 must deliver 1.0–2.0 trades/day, return >=15%, PF >=1.30, DD <=10%, every full year positive and profitable moderate/severe cost stress with PF >=1.15/1.05. A full pass authorizes isolated dry-run only, never live trading or guaranteed profit.
