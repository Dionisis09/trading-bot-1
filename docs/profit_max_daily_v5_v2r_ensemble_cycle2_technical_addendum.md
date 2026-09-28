# ProfitMax Daily + V5 + V2R Ensemble Cycle 2 - Technical config addendum

Locked after two pre-PnL CLI validation failures and before any V2R data load or PnL evaluation. Cycle 1 omitted the exchange name because the historical V2R config stores only the exchange credential and whitelist object, while Freqtrade 2026.7 backtesting requires `exchange.name` in configuration and does not accept `--exchange` for this command.

The sole correction is a third config overlay containing `exchange.name = binance`. All Cycle 1 signals, sources, allocations, fee, protections, timerange, gates and immutable Daily/V5 archives remain unchanged. This technical correction does not authorize a new performance trial or live trading.
