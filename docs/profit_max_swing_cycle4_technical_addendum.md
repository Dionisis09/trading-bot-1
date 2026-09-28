# Profit-Max Swing Cycle 4 — Technical addendum

Locked before technical execution. The selected candidate is `DualTrendFuturesV2R`; no signal, risk-overlay, stake, universe, fee, or source change is allowed.

- Runtime: `freqtradeorg/freqtrade@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.
- Recursive analysis: BTC/USDT:USDT, full timerange `20210101-20260801`, startup counts `[199,399,799,1599]`. Qualification at 1599 requires zero entry/exit signal differences, zero indicator-only lookahead differences and <=0.01% fractional variance for every non-signal indicator.
- Official lookahead analysis: all six locked pairs, timerange `20210101-20260801`, minimum 100 and targeted 120 analyzed trades. It requires `has_bias=false`, zero false entry signals, zero false exit signals and zero biased indicators.
- Lookahead-only execution transport uses Freqtrade's forced market orders with `price_side=other` and order-book pricing. This is not a performance run and its PnL must not be used.
- Any failure blocks dry-run creation. Passing both gates permits only an isolated dry-run proposal, never live trading.

Execution note (locked before retry, with no intervening PnL): the originally declared 3199-candle run was rejected before analysis because Freqtrade 2026.7 enforces Binance's 4h startup limit of 2494 candles. The maximum declared count was therefore reduced to 1599; no strategy, pair, date, signal, risk or performance parameter changed.
