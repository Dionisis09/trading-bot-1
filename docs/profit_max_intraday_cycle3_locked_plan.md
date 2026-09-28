# ProfitMax Intraday Cycle 3 — Locked exit-repair plan

Status: `LOCKED_BEFORE_CYCLE3_PNL`. Research only; live trading unauthorized.

Cycle 2 found one near-break-even candidate after the user's exact Binance fee: `ProfitMaxIntradayShortBase15m` produced 904 TRAIN trades (`1.238/day`), return -0.842%, PF 0.983 and wallet drawdown 5.46%. Its 310 ROI exits earned +47.42%, while 405 fast invalidations lost -21.65% and 189 stop losses lost -26.61%. This final deterministic repair cycle tests only whether profit protection and loss-only signal suppression improve that fixed entry stream. It does not change the entry signal, universe, data, fee, stake, leverage, concurrency, split or frequency gate.

Exactly three candidates run once:

1. `ProfitMaxIntradayShortProfitOnly15m`: exact Cycle-2 ShortBase entry, ROI and -1.8% stop. Existing fast exit signals may close only when Freqtrade's current trade profit is positive by at least 0.15%, equal to the minimum round-trip fee.
2. `ProfitMaxIntradayShortBreakEven15m`: exact ShortBase including fast exits. Once current net profit exceeds 1.0%, the stop locks an open-relative +0.25%; otherwise the original -1.8% stop remains.
3. `ProfitMaxIntradayShortProfitOnlyBreakEven15m`: combines Candidates 1 and 2 without any other change.

All thresholds above are fixed before Cycle-3 PnL. No fourth candidate, pair deletion, entry edit, ROI edit, stop edit, hyperopt, ML or LLM order decision is allowed after the run. If no candidate passes, deterministic exit tuning stops for this research lineage.

TRAIN is 2022-01-01 through 2024-01-01 and remains the only revealed performance split. Gates are unchanged: 730–1,460 trades (1–2/day), return >0, PF >=1.15, wallet DD <=10%, return/DD >=0.75, every pair >=60 trades, at least four positive pairs, and worst pair return >-2%. Highest PF among complete passers wins.

Only a complete TRAIN passer may proceed to lookahead, recursive/source reconciliation and then one-time VALIDATION. Validation remains hidden after any failure. The baseline fee is exactly 0.00075 per side (minimum 0.0015 round trip), plus recorded funding. No result in this cycle authorizes live trading or claims guaranteed profit.
