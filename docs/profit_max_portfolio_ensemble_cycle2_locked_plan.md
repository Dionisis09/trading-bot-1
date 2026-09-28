# ProfitMax Portfolio Ensemble Cycle 2 - Locked plan

Status: `LOCKED_BEFORE_CYCLE2_PNL`. Offline research only.

Cycle 1 reached 1.015 trades/day and positive aggregate return, but was rejected because two V1 trades exceeded the literal 50 USDT stake check through exchange minimum-stake uplift and TRAIN 2022 PF was only 1.012. Cycle 2 replaces the fragile V1 sleeve; it does not relax those failed results.

The fixed portfolio contains three independently reserved sleeves, all on completed 4h candles, next-open execution, 1x isolated futures, protections enabled, and fee 0.00075 per side plus recorded funding:

1. `ProfitMaxCrossSectionalTopTwo8h`: two slots, frozen 50-pair universe, proposed stake 12.5 USDT.
2. `ProfitMaxLiquid50V1`: five configured slots on the same frozen universe, proposed stake 25 USDT. Exact pair/open-time duplicates against either other sleeve are removed from portfolio attribution.
3. `ProfitMaxV5Asymmetric50`: two slots, original six-pair universe, proposed stake 100 USDT.

The weights were selected once from the already-seen Cycle 1 diagnostic grid: Cross and Liquid each in `[0.25, 0.50, 0.75, 1.00]` of their prior stake and V5 in `[1.00, 1.25, 1.50, 1.75, 2.00]`. The chosen 0.25/0.50/2.00 allocation maximized TRAIN profit among combinations satisfying the pre-existing frequency, aggregate PF, annual PF, drawdown, and 20% observed-exposure constraints. No further weight search is allowed in this cycle.

TRAIN is exactly 2021-01-01 through 2024-01-01. It must pass every gate:

- 1.0-2.0 selected trades/day;
- return >0, PF >=1.50, wallet-curve DD <=10%, return/DD >=3.0;
- 2021, 2022, and 2023 each positive with PF >=1.15;
- every selected component independently positive with PF >=1.10;
- at least 250 retained Liquid50 trades after deterministic deduplication;
- observed concurrent positions <=6 and observed concurrent stake <=20% of the 1,000 USDT wallet;
- embedded config, fee, timerange, universe, leverage, and stake contracts reconcile exactly. Exchange minimum-stake adjustment may raise an individual realized stake by at most 30% above its configured proposal.

Any failure produces `KEEP_OFFLINE_RESEARCH` and validation remains hidden. Only a full TRAIN pass plus technical/source/lookahead/recursive gates unlocks one validation reveal for 2024-01-01 through 2026-01-01. Validation must independently retain 1-2 trades/day, return >=15%, PF >=1.30, DD <=10%, both full years positive, and profitable locked execution stress. Nothing in this plan authorizes live trading or guarantees profit.
