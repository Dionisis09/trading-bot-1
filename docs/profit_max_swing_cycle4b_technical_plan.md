# Profit-Max Swing Cycle 4B - pair-isolated technical plan

Locked after Cycle 4's portfolio-wide lookahead result and before any Cycle 4B execution. No PnL is parsed or rerun in this cycle.

- Candidate, source, signals, risk overlay, six-pair universe, dates, stake, leverage and costs remain exactly those of Cycle 4: `DualTrendFuturesV2R`.
- Cycle 4's portfolio-wide official lookahead result remains a recorded FAIL: 120 analyzed trades, 4 unmatched entries, 2 unmatched exits, and zero differing indicator or signal columns.
- The diagnostic hypothesis is fixed in advance: Freqtrade's cut runs use only the current trade's pair, while the full run used six pairs with `max_open_trades=2` and portfolio-wide protections. Execution-path competition can therefore remove a realized trade without changing its causal signal.
- Qualification uses six independent official lookahead runs, one for each locked pair. Each run uses the full `20210101-20260801` timerange, minimum 20 analyzed trades, target 30, forced market transport, and must report `has_bias=false`, zero unmatched entries, zero unmatched exits and zero biased indicators.
- The already completed recursive gate must remain PASS at 1599 startup candles with <=0.01% variance and no indicator lookahead.
- Any pair failure blocks the isolated dry-run. A full technical pass permits dry-run only; it does not authorize live trading or claim future profitability.
