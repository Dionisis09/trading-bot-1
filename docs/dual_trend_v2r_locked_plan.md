# DualTrendFuturesV2R - Locked Matched-Risk Plan

This document was written before the first V1R/V2R backtest. V2R changes no
V2 signal, indicator, exit, stop, protection, market, timeframe, or leverage
rule. It tests exactly one professional-style capital-allocation hypothesis.

## Fixed risk overlay

Apply the identical callback to V1 (`DualTrendFuturesV1R`, control) and V2
(`DualTrendFuturesV2R`, challenger):

- Start with 65% of Freqtrade's proposed stake. With four unlimited-stake
  research slots, this caps aggregate nominal exposure near 65% before
  volatility adjustment.
- Calculate ATR percentage from the latest analyzed closed 4h candle.
- Volatility scalar = `3% / ATR%`, clamped to `[0.50, 1.00]`.
- Final stake = `proposed_stake * 0.65 * volatility_scalar`.
- Therefore, the intended callback multiplier is `[0.325, 0.65]` of the
  proposed stake. Missing/invalid ATR uses the conservative 0.325 fallback.
- Keep the hard -10% stop and isolated 1x leverage. No DCA, martingale,
  leverage adjustment, signal threshold change, or parameter search.

ATR is used only for position sizing because it measures volatility rather
than direction. The callback uses Freqtrade's analyzed dataframe interface and
never increases the proposed stake.

## Fixed matched-risk matrix

Both V1R and V2R use the same six Binance USDT perpetuals, existing audited
4h/1d/funding/mark archives, 10,000 USDT wallet, four maximum research
positions, protections, and fees.

- Train: 2021-01-01 through 2024-01-01.
- Validation: 2024-01-01 through 2026-01-01.
- Calendar 2024 and 2025.
- Current regime: 2026-01-01 through 2026-08-01.
- 0.15% fee/side validation for both control and challenger.
- 0.15% fee/side train for V2R.
- V2R lookahead and recursive analysis at startup 800.

These periods have already been inspected. They are matched-risk comparative
evidence, not a new sealed holdout. No constants will change after results.

## V2R absolute gates

- Train: positive return, PF >= 1.20, DD <= 30%.
- Validation: at least 100 trades, positive return, PF >= 1.50, DD <= 12%.
- 2024: positive return, PF >= 1.20, DD <= 12%, at least 20 trades.
- 2025: positive return, PF >= 1.15, DD <= 12%, at least 20 trades.
- Current 2026: positive return, PF >= 1.30, DD <= 10%, at least 12 trades.
- Fee validation: positive return, PF >= 1.30, DD <= 13%.
- Fee train: positive return and PF >= 1.20.
- At least five of six validation pairs positive; pair profit concentration
  <= 50%; winning-trade concentration <= 25%.
- Zero lookahead-biased entries/exits/indicators; recursive EMA200 variance at
  startup 800 no more than 0.01% in absolute value.

## Matched-risk superiority gates

Compared with V1R under the identical overlay:

- Validation return and PF must both be higher.
- Validation return/max-drawdown ratio must be at least 20% higher.
- 2025 and current-2026 return must both be higher.
- Fee-stress validation return and PF must both be higher.

Passing all gates authorizes a separate small fixed-stake V2R dry-run only. It
does not authorize live credentials or live trading, and cannot guarantee
future profit. Replacing V1 requires genuinely new forward dry-run evidence.
