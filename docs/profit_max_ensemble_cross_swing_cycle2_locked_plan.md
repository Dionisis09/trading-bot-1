# ProfitMax Ensemble Cross-Swing Cycle 2 — Locked technical correction

Status: `LOCKED_BEFORE_PNL`. Offline research only.

Cycle 1 was invalidated before performance interpretation because Freqtrade 2026.7 does not invoke `custom_exit` when `use_exit_signal` is false. Its positions therefore did not follow the frozen setup-specific exit contract. No Cycle 1 PnL is admissible and validation remained hidden.

Cycle 2 changes exactly one execution mechanism and no alpha, universe, cost, risk, stake, horizon or signal parameter:

- `use_exit_signal` is true so `custom_exit` runs;
- `confirm_trade_exit` rejects only an `exit_signal` for a trade whose entry tag starts with `xsmom_`;
- the 8-hour `custom_exit`, stop-loss and force/emergency exits remain allowed for those trades;
- swing-tagged trades accept their original swing exit signal.

All other terms, splits and gates are exactly those in `profit_max_ensemble_cross_swing_cycle1_locked_plan.md`. The sole candidate is `ProfitMaxEnsembleCrossSwingV2`. TRAIN must pass every locked gate before validation can be run. A full eventual pass authorizes only a new isolated dry-run, never live trading or guaranteed profit.
