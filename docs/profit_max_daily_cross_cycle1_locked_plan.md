# ProfitMax Daily Cross Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_FREQTRADE_PNL`. Offline research only. Validation 2024–2025 is sealed for this cycle and live trading is unauthorized.

## Frozen hypothesis

The frozen 50-pair Binance USD-M universe is ranked twice per UTC day using seven-day momentum. At the close of the 4h candle immediately preceding 00:00 or 12:00 UTC, the strategy may select the single strongest pair. It enters long at the next 4h open only when BTC's completed-candle 30-day momentum is positive. It otherwise abstains. The position exits eight hours after the actual fill.

Exact rules:

- Main timeframe 4h, UTC, closed candles only; signal candle hours 08:00 and 20:00 UTC, earliest fills 12:00 and 00:00 respectively.
- Pair score: `close[t] / close[t-42] - 1`; BTC gate: `BTC_close[t] / BTC_close[t-180] - 1 > 0`.
- Rank across the exact frozen 50-pair whitelist; require at least 35 finite scores. Ties use frozen whitelist order through `rank(method="first")`.
- Long only the unique rank leader. No short, leverage 1x, fixed eight-hour time exit, 8% emergency stop, no ROI/trailing exit.
- Maximum two open trades, proposed stake 50 USDT, existing ATR exposure reduction and professional fail-closed account guard. Existing cooldown, stop-loss and drawdown protections remain enabled.
- Fee is exactly 0.00075 per side, plus recorded funding. No slippage is claimed in baseline; locked stress runs add slippage after baseline qualification.

The pre-PnL diagnostic family was enumerated in `train_screen.json`; exactly one candidate passed its diagnostic screen: `mom7d_0-12_8h_leader_long_btc30_positive`. Its raw per-trade return sum is not a wallet return and is not qualification evidence.

## Frozen splits and gates

TRAIN is 2021-01-01 through 2024-01-01. It must have 1,095–2,190 trades, 1–2 trades/day, wallet return >0, PF >=1.15, wallet-curve DD <=12%, return/DD >=1.0, and every year positive with PF >=1.02. At least 35 pairs must trade, at least 20 pairs must be net positive, no pair may lose more than 3% of the starting wallet, and the largest positive-pair contribution must be <=25%.

TRAIN also requires exact source/config/archive reconciliation, lookahead-analysis with zero biased entry/exit/indicator columns, and recursive convergence before validation. Moderate execution stress adds 5 bps slippage per side and must remain profitable with PF >=1.05; severe adds 15 bps per side and is diagnostic but must lose less than 3% of wallet.

Only a complete TRAIN pass reveals VALIDATION once. VALIDATION is 2024-01-01 through 2026-01-01 and must have 731–1,462 trades, 1–2/day, return >0, PF >=1.20, DD <=10%, return/DD >=1.25, and both years positive with PF >=1.05. CURRENT_PARTIAL 2026-01-01 through 2026-08-01 must remain profitable with PF >=1.05 and DD <=8%. Continuous 2021-01-01 through 2026-08-01 must be profitable in every full year, have PF >=1.25 and DD <=12%.

Any TRAIN performance failure produces `KEEP_OFFLINE_RESEARCH` and stops the cycle. Any technical, data, source, bias or reconciliation failure produces `REJECT_CANDIDATE`. Only every gate passing may authorize a separate dry-run; no result guarantees future profit or authorizes live trading.

