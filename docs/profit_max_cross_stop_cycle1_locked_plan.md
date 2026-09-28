# ProfitMax Cross Stop Cycle 1 - Locked plan

Status: `LOCKED_BEFORE_PNL`. Research only; live trading is unauthorized.

The reproducible `ProfitMaxCrossSectionalTopTwo8h` sleeve generated positive TRAIN alpha, but its fixed 8% stop dominated losses in both seen TRAIN and the now-seen 2024-2025 baseline. This cycle tests one bounded structural hypothesis: reduce tail loss while leaving every entry, rank, universe, holding period, protection, fee, stake rule, and leverage rule unchanged.

Exactly three candidates are allowed: `ProfitMaxCrossTopTwo8hStop2`, `ProfitMaxCrossTopTwo8hStop4`, and `ProfitMaxCrossTopTwo8hStop6`, with fixed stops of -2%, -4%, and -6%. No trailing stop, ROI, pair filter, regime filter, or other parameter is allowed.

TRAIN is 2021-01-01 through 2024-01-01. A candidate must have at least 0.75 trades/day, positive return, PF at least 1.15, wallet DD at most 5%, and positive profit in every TRAIN year. Among complete passers, the fixed selection rule is highest return/DD, then higher PF, then tighter stop. The selected cross sleeve is combined with the already no-cache-reproduced V5 and V1 archives. The portfolio must achieve 1-2 trades/day, positive return, PF at least 1.30, DD at most 10%, return/DD at least 2.0, and every TRAIN year positive with PF at least 1.15.

Only a complete TRAIN portfolio pass can unlock one exact no-cache validation run for 2024-01-01 through 2026-01-01. The 2024-2025 baseline is already seen, so a later pass is robustness evidence rather than a sealed holdout. Current partial 2026 remains the later untouched temporal check. Fee is exactly 0.00075 per side, futures are isolated, leverage is 1x, proposed stake is 50 USDT, and maximum cross positions are two.

Any source, data, technical, or performance failure closes the cycle as `KEEP_OFFLINE_RESEARCH`. No result authorizes live trading, guarantees profit, or permits automatic deployment.
