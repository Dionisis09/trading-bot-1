# ProfitMax CAGR15 Cycle 2 — Locked Research Plan

Locked after Cycle 1 failed and before any Cycle 2 PnL run. All history is already
seen; this is retrospective research, not a holdout and not a profit guarantee.

## Fixed candidate

- Candidate: `ProfitMaxCagr15V2`.
- Logic: inherit the already implemented and tested `ProfitMaxV5LongOnly` diagnostic.
  No new indicator or threshold is introduced.
- Binance isolated USD-M futures, 1x leverage, 4h candles.
- BTC, ETH, BNB, XRP, ADA and DOGE remain in the universe.
- Wallet 1,000 USDT; configured stake 300 USDT; one open trade maximum.
- Existing ATR overlay caps a long at `300 * 0.65 = 195 USDT` before lower-volatility
  scaling, respecting the locked 20% total-open-stake account limit.
- Fee exactly 0.075% per side; Freqtrade funding included.
- Timerange `20210101-20260801`; no frequency requirement.

No pair deletion, alternate stake or signal change is allowed after the result.

## Gates

- CAGR >= 15%; PF >= 2.0; Freqtrade wallet DD <= 12%; return/DD >= 10.
- Every full year 2021–2025 net positive; partial 2026 return > -2%.
- At least 80 trades and all trades long.
- Observed peak concurrent stake <= 20% of initial wallet.
- Moderate extra 0.05%/side: CAGR >= 13%, PF >= 1.70, realized DD <= 15%.
- Severe extra 0.10%/side: CAGR >= 10%, PF >= 1.40, realized DD <= 18%.

Pass permits an isolated dry-run only. Live trading remains unauthorized.
