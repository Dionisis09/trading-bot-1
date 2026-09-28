# ProfitMax Ensemble Cross-Swing Cycle 3 — Locked capacity/isolation plan

Status: `LOCKED_BEFORE_PNL`. Offline research only.

Cycle 2 showed that the combined portfolio was profitable but only produced 0.644 trades/day because two cross-sectional slots and up to two swing positions competed for three shared slots, while a global stop-loss guard allowed losses from one sleeve to suspend the other. It also showed that Freqtrade passes the configured exit tag, not only the literal `exit_signal`, to `confirm_trade_exit`.

This cycle keeps all entry signals, ranks, horizons, stops, fees and pair eligibility unchanged. It tests exactly two portfolio implementations:

- `ProfitMaxEnsembleCrossSwingV3Global`: four slots and the original global protections;
- `ProfitMaxEnsembleCrossSwingV3PairGuard`: four slots, with StoplossGuard isolated per pair while MaxDrawdown remains global.

Both reject the two swing exit tags and the literal `exit_signal` only for `xsmom_` trades. Cross-sectional trades therefore exit only at their fixed 8-hour rebalance, stop-loss, force-exit or emergency-exit. Swing trades retain their original exit signals. A swing signal retains priority over a cross-sectional signal on the same pair and candle.

The fixed contract is: frozen 50-pair universe; swing sleeve restricted to BTC, ETH, BNB, XRP, ADA and DOGE; 4h base and causal 1d informative data; completed candles and next-open fills; long-only top-two 30-day cross-sectional sleeve plus long/short swing sleeve; four maximum positions; 50 USDT proposed stake; 1,000 USDT wallet; maximum total open stake 20%; 1x isolated futures; 8% hard stop; exact fee 0.00075 per side plus funding. ML and LLM trading inputs are excluded.

TRAIN is exactly 2021-01-01 through 2024-01-01. A candidate must pass 1.0–2.0 trades/day, return >0, PF >=1.30, wallet DD <=10%, return/DD >=2.0, each year positive/PF >=1.15, both sleeves independently positive/PF >=1.10, >=20 traded pairs, >=12 positive pairs, worst pair >-3%, and largest positive-pair contribution <=30%.

Failure keeps validation hidden and produces `KEEP_OFFLINE_RESEARCH`. Only a complete TRAIN plus source, reconciliation, lookahead and recursive pass unlocks one validation run for 2024-01-01 through 2026-01-01. Continuous approval still requires 1–2 trades/day, return >=15%, PF >=1.30, DD <=10%, every full year positive and profitable moderate/severe cost stress. Any complete pass authorizes only a separate isolated dry-run, never live trading or guaranteed profit.
