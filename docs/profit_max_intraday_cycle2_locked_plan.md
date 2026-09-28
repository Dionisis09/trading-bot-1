# ProfitMax Intraday Cycle 2 — Locked plan

Status: `LOCKED_BEFORE_CYCLE2_PNL`. Research only; live trading unauthorized.

Cycle 1 established one bounded hypothesis: 15m short breakouts produced 854 TRAIN trades (`1.17/day`) and PF 0.962 after a 0.075% fee per side, materially stronger than long breakout (PF 0.787) and reclaim (PF about 0.70). Cycle 2 tests whether causal exit/risk handling can turn that fixed short entry stream profitable. This is an explicitly post-Cycle-1 hypothesis; all history is seen robustness evidence, not a sealed holdout.

Inputs, six-pair universe, canonical 15m-derived data, TRAIN/VALIDATION dates, 75 USDT stake, three-position cap, isolated futures, 1x leverage, 0.075% fee per side, funding, next-candle fills and `1.0–2.0 trades/day` hard frequency gate are unchanged from Cycle 1.

The fixed short entry is exactly the Cycle-1 breakout short: aligned 4h/1h bearish regime, `ema_gap_atr_4h <= -0.35`, negative 24h momentum, 1h ADX >=22 and greater than its value four base candles earlier, close below the prior 32-candle low and volume >1.25 times the prior-20 median. Long entries are disabled for Candidates 1–2 only as the predeclared asymmetry hypothesis.

Exactly three candidates run once:

1. `ProfitMaxIntradayShortTight15m`: short-only; stop -1.2%; ROI 1.8%/0.9%/0.3%/0% at 0/240/720/1440 minutes; exit on close above 15m EMA20 or 1h bullish EMA alignment.
2. `ProfitMaxIntradayShortBase15m`: short-only; stop -1.8%; ROI 2.4%/1.2%/0.5%/0% at the same times; the same close-above-EMA20 exit.
3. `ProfitMaxIntradayAsymmetric15m`: exact base short plus a strong long breakout requiring the shared bullish regime, `ema_gap_atr_4h >=0.70`, close at least `0.15*ATR14` above the previous 32-candle high and volume >1.5 times prior median; stop -1.5%; ROI 2.0%/1.0%/0.4%/0%; mirrored close/EMA20 exit.

No fourth candidate, pair deletion, threshold edit, hyperopt, ML or LLM order decision is permitted after the first Cycle-2 PnL run.

TRAIN gates: 730–1,460 trades (`1–2/day`), return >0, PF >=1.15, wallet DD <=10%, return/DD >=0.75, every pair >=60 trades, at least four pairs positive and worst pair return >-2%. The asymmetric candidate additionally requires both sides positive and at least 100 long trades. Highest PF among complete passers wins.

Only a TRAIN passer may run lookahead/recursive/source checks and then reveal VALIDATION once. VALIDATION requires 731–1,462 trades, return >0, PF >=1.20, DD <=10%, return/DD >=1.0, both years positive, at least four positive pairs and worst pair >-2%. Moderate and severe stress gates remain those of Cycle 1. No TRAIN pass means `KEEP_OFFLINE_RESEARCH` and no validation.

