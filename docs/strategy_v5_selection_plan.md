# Major Trend V5 - Final Model-Selection Plan

This plan was fixed before any V5 portfolio backtest. The 2026 holdout is still
sealed. V5 is explicitly data-driven model selection using only train and
validation results, so only the later holdout can provide final out-of-sample
evidence.

## Fixed strategy and universe

No further indicator parameter is tuned. V5 freezes `MajorTrendV4B`: 63-day
positive daily ROC, EMA20 > EMA50 > EMA200, 30-candle Donchian entry,
10-candle Donchian exit, and a -10% hard stop.

The universe rule is also frozen: include a symbol only when V4B had positive
net pair return in both the 2021-2023 train window and the 2024-2025 validation
window. Applied once, this yields exactly:

- BTC/USDT
- BNB/USDT
- XRP/USDT
- ADA/USDT
- DOGE/USDT

This selection is intentionally transparent and is not claimed to be independent
of the research results. No symbol may be added or removed after the V5 tests.

## Qualification gates before holdout

- Full train: positive return, PF >= 1.10.
- Full validation: at least 40 trades, positive return, PF >= 1.25, maximum
  drawdown <= 15%.
- Every selected pair: positive return and PF >= 1.00 on full validation.
- Both calendar subwindows 2024 and 2025: positive return, PF >= 1.00, and at
  least 15 trades each.
- No pair contributes more than 50% of total positive pair profit.
- No single trade contributes more than 25% of total positive trade profit.
- Positive full train and validation result at 0.15% fee per side.
- No lookahead bias and no material recursive-indicator variance.

## One-time sealed holdout

The 2026-01-01 through 2026-08-01 holdout may be opened once only after all
prior gates pass. It must have at least 10 trades, positive net return, PF >=
1.00, and maximum drawdown <= 15%.

Any pass authorizes dry-run operation only. The dry-run will use small fixed
stakes rather than the unlimited research sizing. No future-profit guarantee,
live key, or live order is authorized.

