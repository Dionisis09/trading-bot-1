# ProfitMax Liquid50 1h Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_DATA_AND_PNL`. Offline research only; live trading unauthorized.

## Fixed hypothesis

The prior 4h Liquid50 TRAIN was profitable in each of 2021, 2022 and 2023 but failed the required frequency and profit-factor gates. This new cycle tests one predeclared mechanism: preserve the same causal daily regime, confluence, fee, risk overlay and asymmetric short sizing, while using a 1h execution timeframe. Three temporal horizons are fixed before any new PnL is parsed:

- `ProfitMaxLiquid50OneHour30`: prior 30h entry channel and prior 10h exit channel;
- `ProfitMaxLiquid50OneHour60`: prior 60h entry channel and prior 20h exit channel;
- `ProfitMaxLiquid50OneHour120`: prior 120h entry channel and prior 40h exit channel.

No other signal, filter, side, pair or threshold differs between candidates. The exact 50-pair universe remains the immutable pre-PnL selection from Liquid50 Cycle 1. Candidate selection is allowed only on TRAIN, and no candidate or threshold may be altered after TRAIN results.

## Execution and risk

- Main timeframe 1h; informative timeframe 1d; UTC closed candles only; earliest fill at the next 1h open.
- Binance fee exactly 0.00075 per side (0.0015 minimum round trip), plus recorded funding.
- Futures isolated, leverage 1x, dry-run wallet 1,000 USDT, fixed stake 50 USDT before the existing ATR exposure overlay, maximum five concurrent positions.
- Existing 4h protection durations are time-normalized to 1h candles. Backtests run with protections enabled.
- No hyperopt, grid search, post-result pair deletion, ML/LLM order control or validation-driven patching.

## Splits and gates

TRAIN is 2021-01-01 through 2024-01-01. A candidate passes only if every gate passes:

- 1,095–2,190 trades (1–2 portfolio trades/day), return >0, PF >=1.50, wallet-curve DD <=12%, return/DD >=2.0;
- 2021, 2022 and 2023 each return >0 and PF >=1.10;
- at least 35 pairs traded, at least 25 net-positive pairs, every traded pair return >-3%, and largest positive-pair contribution <=20%;
- long and short each >=300 trades, each net positive and PF >=1.15.

If more than one candidate passes, select by highest return/DD, then PF, then lower DD, then lexical strategy name. If none passes, decision is `KEEP_OFFLINE_RESEARCH` and validation remains hidden.

Only a complete TRAIN pass unlocks archive/source/config reconciliation, pair-isolated lookahead analysis with zero bias, recursive convergence, and cost stress. Only a complete technical pass unlocks one-time VALIDATION 2024-01-01 through 2026-01-01, requiring 731–1,462 trades, return >0, PF >=1.30, DD <=10%, return/DD >=1.5, both years positive with PF >=1.10, breadth gates, and profitable long/short sides.

CURRENT_PARTIAL 2026-01-01 through 2026-08-01 requires 212–424 trades, return >=0, PF >=1.05 and DD <=8%. The continuous 2021-01-01 through 2026-08-01 replay must average 1–2 trades/day, return >=30%, PF >=1.50, DD <=12%, all full years positive, at least 40 traded pairs and at least 30 positive pairs. Moderate and severe execution stress must remain profitable with PF >=1.25 and >=1.05 respectively.

Any failed data, source, frequency, performance, stability, breadth, bias, recursion or cost gate yields `KEEP_OFFLINE_RESEARCH`. A full pass authorizes only a separate dry-run and never guarantees future profit.
