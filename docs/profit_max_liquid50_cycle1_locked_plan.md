# ProfitMax Liquid50 Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_DATA_AND_PNL`. Research only; live trading unauthorized.

## Hypothesis

`ProfitMaxV5Asymmetric50` is the strongest technically qualified five-year alpha already present in the workspace: on the six-pair continuous replay 2021-01-01 through 2026-08-01 it produced 252 trades, +50.61%, PF 2.456, wallet DD 2.52%, positive results in every calendar year, and passed moderate and severe execution stress. Its weakness relative to the user's objective is frequency, not profitability.

This cycle keeps the strategy logic and thresholds byte-for-byte unchanged and tests it on a larger fixed universe. The universe was selected before new data/PnL: the 50 currently active Binance USD-M USDT perpetuals onboarded no later than 2021-01-01 with the highest public rolling 24h quote volume at capture time, with symbol as deterministic tie-break. Exact members and API response hashes are frozen in `universe_selection.json`.

The historical evidence is conditional on a current-active universe and therefore has survivorship bias. It cannot be described as a survivor-free market-wide backtest. No pair may be removed after results.

## Execution and risk

- Main timeframe: 4h; informative timeframe: 1d; UTC closed candles only.
- Earliest fill is the next 4h open.
- Binance fee: exactly 0.00075 per side, minimum 0.0015 round trip, plus recorded funding.
- Futures isolated, leverage exactly 1x, dry-run wallet 1,000 USDT.
- Fixed stake 50 USDT before the existing ATR exposure overlay; max five concurrent positions.
- Strategy candidate: exactly `ProfitMaxLiquid50V1`, an empty subclass of `ProfitMaxV5Asymmetric50`.
- No threshold, exit, stake multiplier, pair, side, leverage, protection or signal change is allowed after the first PnL run.

## Splits and gates

TRAIN: 2021-01-01 through 2024-01-01. It must satisfy all gates:

- 1,095–2,190 trades (1–2 portfolio trades/day), return >0, PF >=1.50, wallet DD <=12%, return/DD >=2.0;
- 2021, 2022 and 2023 each return >0 and PF >=1.10;
- at least 35 pairs traded, at least 25 pairs net positive, every traded pair return >-3%, and largest positive-pair contribution <=20%;
- long and short each >=300 trades, net positive and PF >=1.15.

Only a complete TRAIN pass unlocks technical gates and one-time VALIDATION. Technical gates require source/config/archive reconciliation, pair-isolated lookahead with zero biased entries/exits/indicators, recursive convergence at a fixed candidate count, and cost stress.

VALIDATION: 2024-01-01 through 2026-01-01. It must satisfy 731–1,462 trades, return >0, PF >=1.30, wallet DD <=10%, return/DD >=1.5, both 2024 and 2025 positive with PF >=1.10, at least 35 pairs traded, at least 25 positive pairs, and both sides net positive with PF >=1.10.

CURRENT_PARTIAL: 2026-01-01 through 2026-08-01 requires at least 180 trades, return >=0, PF >=1.05 and DD <=8%.

The canonical continuous replay 2021-01-01 through 2026-08-01 must average 1–2 trades/day, return >=30%, PF >=1.50, DD <=12%, all full years positive, at least 40 traded pairs and at least 30 positive pairs. Moderate and severe execution stress must remain profitable with PF >=1.25/1.05 and DD <=13%/15% respectively.

Any data, frequency, performance, stability, breadth, technical, source or cost gate failure yields `KEEP_OFFLINE_RESEARCH`. A complete pass authorizes only a separate dry-run. It does not authorize live trading or guarantee future profit.
