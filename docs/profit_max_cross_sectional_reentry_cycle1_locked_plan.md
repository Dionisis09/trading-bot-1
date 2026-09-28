# ProfitMax Cross-Sectional Re-entry Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only.

The 8-hour top-two 30-day leader candidate was positive in each TRAIN year (+5.78%, PF 1.207, 0.855 trades/day), while shortening the holding period to 4 hours raised frequency to 0.984/day but destroyed the edge. This cycle therefore preserves the profitable 8-hour holding horizon and changes only the post-trade cooldown from two 4h candles to one 4h candle.

Two candidates are frozen: `ProfitMaxCrossSectionalTopTwo8hFastReentry` and the identical `ProfitMaxCrossSectionalTopTwo8hFastReentryPositive`, which requires the selected pair's completed-candle 30-day return to be positive. No other parameter or filter is allowed.

Universe, causal ranking, >=35-pair breadth, long-only side, two slots, 8% stop, 1x isolated futures, 1,000 USDT wallet, 50 USDT proposed stake, exact fee 0.00075 per side, funding, StoplossGuard and MaxDrawdown protection remain unchanged. ML/LLM inputs are excluded.

TRAIN 2021-01-01 through 2024-01-01 must pass 1.0–2.0 trades/day, return >0, PF >=1.30, wallet DD <=10%, return/DD >=2.0, every year positive/PF >=1.15, >=20 traded pairs, >=12 positive pairs, worst pair >-3%, and largest positive-pair contribution <=30%. Any failure means `KEEP_OFFLINE_RESEARCH` and validation stays hidden.

Only a full TRAIN and technical pass unlocks VALIDATION 2024-01-01 through 2026-01-01. The later validation/current/continuous gates remain exactly those in the preceding cross-sectional plans, including continuous return >=15%, PF >=1.30, DD <=10%, 1–2 trades/day, all full years positive and profitable cost stress. A full pass authorizes isolated dry-run only.
