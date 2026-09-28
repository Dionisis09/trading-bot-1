# ProfitMax Portfolio Ensemble Cycle 1 - Locked plan

Status: `LOCKED_BEFORE_NEW_COMPONENT_PNL`. Offline research only.

## Architecture

The single-strategy Ensemble caused long-lived swing positions to consume the slots reserved for the fast cross-sectional sleeve. This cycle isolates the sleeves at portfolio level and evaluates their combined closed-trade wallet curve:

1. `ProfitMaxCrossSectionalTopTwo8h`: two reserved slots, frozen 50-pair universe, 50 USDT proposed stake.
2. `ProfitMaxV5Asymmetric50`: two reserved slots, original six-pair universe, 50 USDT proposed stake.
3. `DualTrendFuturesV1`: one reserved auxiliary slot, original six-pair universe, 50 USDT proposed stake.

An auxiliary V1 trade is excluded when V5 has the exact same pair and entry timestamp. Cross-sectional trades are never deduplicated against swing trades because the frozen TRAIN artifacts show no exact pair/timestamp overlap and they represent different holding horizons.

All sleeves use completed 4h candles, next-open execution, 1x isolated futures, exact fee 0.00075 per side plus recorded funding, a 10% or stricter strategy-native stop, and enabled protections. Combined maximum open stake is 20% of a common 1,000 USDT research wallet and the hard combined position ceiling is five. ML and LLM inputs are excluded.

## Frozen TRAIN gate

TRAIN is 2021-01-01 through 2024-01-01. The new V5 and V1 component runs use the fixed stake/slot contract above. The previously frozen cross archive is reused without rerunning or changing its strategy.

The portfolio must pass all of:

- 1.0-2.0 selected trades/day;
- return >0, PF >=1.30, wallet-curve DD <=10%, return/DD >=2.0;
- each full TRAIN year positive with PF >=1.15;
- each of the three selected component streams independently net positive with PF >=1.10;
- at least 20 unique retained V1 trades after deterministic deduplication;
- maximum concurrent positions <=5 and maximum concurrent stake <=20% of the starting wallet;
- every trade has fee_open=fee_close=0.00075 and the component timeranges/days match exactly.

Any failure produces `KEEP_OFFLINE_RESEARCH`; validation stays hidden. A TRAIN pass unlocks technical/source reconciliation, lookahead/recursive checks for the executable components, and only then a single validation portfolio run for 2024-01-01 through 2026-01-01. Continuous approval requires 1-2 trades/day, return >=15%, PF >=1.30, DD <=10%, all full years positive and profitable moderate/severe stress. No result authorizes live trading or guarantees future profit.
