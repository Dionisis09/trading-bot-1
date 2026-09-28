# ProfitMax Multi-Setup 1h Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PNL`. Offline research only; live trading unauthorized.

## Fixed hypothesis

Prior locked TRAIN cycles established two facts: 15m strategies produced the requested frequency but were unprofitable after the exact Binance fee, while daily-regime trend strategies retained some positive expectancy but were too sparse. This cycle tests three predeclared 1h candidates on the same frozen 50-pair dataset:

- `ProfitMaxOneHourPullback`: daily trend regime plus 1h EMA pullback continuation;
- `ProfitMaxOneHourBreakout`: daily trend regime plus prior 24h channel breakout;
- `ProfitMaxOneHourHybrid`: the exact union of those two entry setups with separate immutable tags.

All use only completed OHLCV candles, the same exit rule, hard stop, risk policy and execution assumptions. No pair/side/setup/threshold changes are permitted after TRAIN. LLM and external news are excluded from decisions because no timestamped five-year point-in-time archive exists; adding them would make the replay unverifiable.

## Causal rules

- Main 1h; informative 1d merged by Freqtrade's causal informative mechanism; earliest fill is next 1h open.
- Daily long regime: previous completed daily close above EMA200 and ROC20 >0; short is mirrored.
- 1h common trend: EMA20/EMA50 alignment, ADX >=18, directional DI agreement, ATR/price in [0.25%, 8%], positive volume.
- Pullback long: close crosses above EMA20, RSI in (48,72), relative volume >=0.80; short mirrored with RSI in (28,52).
- Breakout long: close crosses above prior 24h high, RSI <78, relative volume >=1.00; short mirrored.
- Exit long on cross below EMA50 and bearish DI; short mirrored. Hard stop exactly 4%. No ROI take-profit or trailing stop.

## Execution and risk

- Fee 0.00075 per side (0.0015 minimum round trip), recorded funding included.
- Futures isolated, 1x leverage, 1,000 USDT wallet, 50 USDT proposed stake before the existing ATR scalar.
- Maximum two positions is enforced by the frozen professional risk policy; strategy protections are enabled and time-normalized for 1h.
- No hyperopt, grid search, pair removal, leverage increase, result-driven patch, ML or LLM order control.

## Gates

TRAIN 2021-01-01 through 2024-01-01: 1,095–2,190 trades, return >0, PF >=1.50, wallet DD <=12%, return/DD >=2; each year positive with PF >=1.10; >=35 traded pairs, >=25 positive pairs, worst pair >-3%, largest positive-pair contribution <=20%; long and short each >=300, net positive and PF >=1.15.

If multiple candidates pass, ranking is return/DD, PF, lower DD, lexical name. No passer means `KEEP_OFFLINE_RESEARCH` and validation remains hidden. A passer must then pass source/config reconciliation, lookahead analysis, recursive convergence and locked cost stress before one-time VALIDATION 2024–2025.

VALIDATION requires 731–1,462 trades, return >0, PF >=1.30, DD <=10%, return/DD >=1.5, both years positive with PF >=1.10, breadth and both sides positive. CURRENT_PARTIAL 2026-01-01 through 2026-08-01 requires 212–424 trades, return >=0, PF >=1.05, DD <=8%. Continuous 2021-01-01 through 2026-08-01 requires 1–2 trades/day, return >=30%, PF >=1.50, DD <=12%, every full year positive, >=40 traded pairs and >=30 positive pairs; moderate/severe stress must stay profitable with PF >=1.25/1.05.

Only a full pass authorizes an isolated dry-run. It does not authorize live trading or guarantee profit.
