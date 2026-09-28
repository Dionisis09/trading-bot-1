# ProfitMax Cross-Sectional Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only; live trading unauthorized.

## Fixed hypothesis

Per-pair 15m/1h strategies either lost after fees or failed the required 1–2 trades/day. This cycle tests a structurally different, literature-supported cross-sectional momentum mechanism on the already frozen 50-pair Binance USD-M universe. At each completed 4h candle it ranks trailing returns across all available pairs; orders fill no earlier than the next 4h open.

Three candidates are fixed before PnL:

- `ProfitMaxCrossSectional7dNeutral`: long the single strongest 7-day coin and short the single weakest;
- `ProfitMaxCrossSectional30dNeutral`: long the single strongest 30-day coin and short the single weakest;
- `ProfitMaxCrossSectional7dRegime`: hold only the 7-day leader when BTC is above its causal 200-day EMA proxy, otherwise only the weakest coin short.

Ties use the frozen universe order. At least 35 simultaneous valid pairs are required. Every position exits after 24 hours; if still eligible it may re-enter on the following completed candle. Hard stop is 8%. The rank, BTC regime and signals use only data at or before the current completed candle. No pair removal, threshold patch, hyperopt, ML or LLM order control is allowed after TRAIN.

## Execution and risk

- Main 4h, UTC closed candles, earliest fill at next 4h open.
- Fee 0.00075 per side (0.0015 round trip) plus recorded funding.
- Futures isolated, 1x, 1,000 USDT wallet, 50 USDT proposed stake before existing ATR sizing.
- Frozen professional policy limits the account to two open positions and 20% total open stake. Existing 4h protections are enabled.
- Current-active-universe survivorship bias remains explicit; this is not a delisting-complete market replay.

## Gates

TRAIN 2021-01-01 through 2024-01-01: 1,095–2,190 trades, return >0, PF >=1.50, wallet DD <=12%, return/DD >=2; each year positive with PF >=1.10; >=35 traded pairs, >=25 positive pairs, worst pair >-3%, largest positive-pair contribution <=20%. Neutral candidates require long and short each >=300, net positive and PF >=1.15. The regime candidate requires both sides represented, each net positive and PF >=1.10.

Multiple passers rank by return/DD, PF, lower DD, then lexical name. No passer means `KEEP_OFFLINE_RESEARCH` and no validation. A TRAIN passer must pass exact source/config/trade reconciliation, zero-bias lookahead, recursive convergence and locked cost stress before one-time VALIDATION 2024–2025.

VALIDATION: 731–1,462 trades, return >0, PF >=1.30, DD <=10%, return/DD >=1.5, both years positive/PF >=1.10, breadth and both sides positive. CURRENT_PARTIAL 2026-01-01 through 2026-08-01: 212–424 trades, return >=0, PF >=1.05, DD <=8%. Continuous 2021-01-01 through 2026-08-01: 1–2 trades/day, return >=30%, PF >=1.50, DD <=12%, every full year positive, >=40 traded pairs and >=30 positive pairs. Moderate/severe stress must stay profitable with PF >=1.25/1.05.

Only a full pass authorizes an isolated dry-run. It never guarantees future profit or authorizes live trading.
