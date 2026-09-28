# ProfitMax CAGR15 Cycle 4 — Technical Addendum

Locked before Cycle 4 PnL. Cycle 3 produced zero trades because Freqtrade's
`confirm_trade_entry` call did not include leverage in `kwargs`; the inherited guard
therefore treated leveraged notional as margin and rejected every entry.

Cycle 4 changes only the callback adapter: it supplies the already locked fixed 2.5x
value to the unchanged `ProfessionalRiskMixin.confirm_trade_entry` calculation. All
Cycle 3 signal, exit, fee, stake, universe, timerange and performance/risk gates remain
unchanged. The guard continues to enforce a maximum 20% account margin allocation.

This remains research/dry-run only and does not alter `risk_policy.json` or authorize
leverage for production/live use.
