# ProfitMax Ensemble Cross-Swing Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only.

## Fixed hypothesis

This cycle combines the two independently positive TRAIN sleeves already present in the workspace instead of adding another weak rank or tuning an indicator threshold after seeing results:

- the long-only, top-two, 30-day cross-sectional momentum sleeve with an 8-hour rebalance horizon;
- the previously qualified `ProfitMaxV5Asymmetric50` daily-breakout swing sleeve, restricted to its original six-pair universe.

The cross-sectional sleeve has priority only when no swing entry exists on the same pair and candle. A swing entry has priority on an overlap. Cross-sectional trades use their fixed 8-hour exit. Swing trades use the original channel/daily/confluence exit. Both share a conservative 8% hard stop. This is a predeclared change from the swing sleeve's former 10% hard stop and must be evaluated as a new candidate, not treated as inherited qualification.

## Frozen execution and risk

- Candidate: exactly `ProfitMaxEnsembleCrossSwingV1`.
- Universe: the frozen 50-pair Liquid50 Cycle 1 universe.
- Swing eligibility: exactly BTC, ETH, BNB, XRP, ADA and DOGE perpetual futures.
- Timeframe: 4h; daily informative candles are merged through Freqtrade's causal informative mechanism.
- Signals use completed candles and fills occur no earlier than the next 4h open.
- Exact fee: `0.00075` per side, minimum round trip `0.00150`, plus recorded funding.
- Wallet: 1,000 USDT; proposed stake: 50 USDT; leverage: 1x isolated futures.
- Maximum open trades: 3. Professional daily, weekly, wallet-drawdown and total-exposure guards remain enabled.
- No ML or LLM trading input. Neither has a frozen point-in-time feature/news archive demonstrating incremental edge for this cycle.
- No parameter, pair, side, setup, horizon or threshold may change after the freeze.

## Splits and gates

TRAIN is exactly 2021-01-01 through 2024-01-01 and is the only initially visible PnL split. It must pass all of:

- 1.0–2.0 trades per day;
- return greater than 0%;
- profit factor at least 1.30;
- wallet-curve drawdown at most 10%;
- return/drawdown at least 2.0;
- every full TRAIN year positive with PF at least 1.15;
- both setup sleeves trade and are independently net positive with PF at least 1.10;
- at least 20 pairs traded, at least 12 pairs net positive, worst pair return greater than -3%, and largest positive-pair contribution at most 30%.

Any TRAIN failure produces `KEEP_OFFLINE_RESEARCH` and keeps validation hidden. Only a complete TRAIN and technical/source/reconciliation pass unlocks one validation run.

VALIDATION is exactly 2024-01-01 through 2026-01-01 and requires 1.0–2.0 trades/day, positive return, PF at least 1.25, drawdown at most 10%, return/drawdown at least 1.5, both years positive/PF at least 1.10, and both setup sleeves independently positive/PF at least 1.05.

CURRENT_PARTIAL is 2026-01-01 through 2026-08-01. The canonical continuous replay is 2021-01-01 through 2026-08-01 and requires 1.0–2.0 trades/day, return at least 15%, PF at least 1.30, drawdown at most 10%, every full year positive, both setup sleeves positive, and profitable moderate/severe cost stress with PF at least 1.15/1.05.

A complete pass authorizes only a separate isolated dry-run. It never authorizes live money or guarantees future profit.
