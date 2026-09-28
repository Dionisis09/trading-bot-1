# ProfitMax Daily + V5 Ensemble Cycle 3 — Technical auditability

Status: `LOCKED_BEFORE_EQUIVALENCE_PNL`. Live trading unauthorized.

The pinned Freqtrade lookahead analyzer isolates one pair at a time and temporarily changes `DataProvider.current_whitelist()`. The frozen daily cross-sectional strategy therefore raised `KeyError: BTC/USDT:USDT` before testing any sliced signal. Cycle 3 makes one technical change only: rank-cache membership comes from the exact static `config.exchange.pair_whitelist` instead of the transient current whitelist.

All alpha, ordering, tie-breaking, timing, stop, stake, fee, leverage and risk behavior remain inherited unchanged. Before lookahead may resume, a no-cache TRAIN replay must exactly match the prior 1,038-trade archive on strategy totals and every trade's pair, side, timestamps, prices, stake, profit, fees and exit reason. Any mismatch rejects the technical variant. Validation remains unrevealed.

