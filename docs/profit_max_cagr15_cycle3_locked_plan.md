# ProfitMax CAGR15 Cycle 3 — Locked Research Plan

Locked after the 1x Cycle 2 produced 7.44% CAGR and before Cycle 3 PnL.
All history is seen. Results are retrospective and cannot authorize live trading.

## Candidate

- `ProfitMaxCagr15V3`: identical long-only signals, exits and ATR margin sizing as
  Cycle 2, with a fixed 2.5x leverage callback.
- Binance isolated USD-M futures; wallet 1,000 USDT; configured margin stake 300;
  one trade maximum; ATR overlay caps requested margin near 195 USDT.
- Universe remains all six pairs; 4h; `20210101-20260801`.
- Fee exactly 0.075% per side and funding included.
- No frequency gate and no post-result parameter change.

This leverage is research-only. The current production risk policy remains capped at
1x and this cycle does not modify it.

## Gates

- CAGR >= 15%; PF >= 2.0; wallet DD <= 12%; return/DD >= 10.
- 2021–2025 each net positive; partial 2026 > -2%; >= 80 long trades.
- Peak concurrent margin <= 20% wallet; no shorts; leverage exactly 2.5 on all trades.
- Moderate +0.05%/side: CAGR >= 13%, PF >= 1.70, DD <= 15%.
- Severe +0.10%/side: CAGR >= 10%, PF >= 1.40, DD <= 18%.

All pass => isolated dry-run research candidate only. Live authorization is false.
