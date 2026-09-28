# ProfitMax Intraday ML Ensemble Cycle 2 - Locked plan

Status: `LOCKED_BEFORE_MODEL_AND_PNL`. Research only. Live trading is not authorized.

This cycle is a new, explicitly post-Cycle-1 research hypothesis. Cycle 1 proved that a zero prediction threshold was too selective (0.30 trades/day). Its post-failure TRAIN-only ranking diagnostic found that the first boundary above one trade/day occurred around 800 retained base trades. Before any new backtest, this cycle freezes one threshold, `-0.0135255`, slightly below the diagnostic's 800th prediction. No further threshold, feature, model, pair, exit, stake, or leverage change is allowed in this cycle.

The ML sleeve is `ProfitMaxIntradayMLV2`. It inherits the exact causal 15-feature schema, four-hour net target, fixed LightGBM capacity, deterministic seeds, six-pair universe, 15m/1h/4h data, 75 USDT proposed stake, three slots, isolated futures, 1x leverage, and 0.00075 fee per side from Cycle 1. It may only veto the deterministic `ProfitMaxIntradayShortBase15m` signal. A prediction is usable only when `do_predict == 1` and finite. It can never create a non-candidate trade, reverse a side, increase stake/leverage, or change exits.

The portfolio candidate has three independent sleeves:

1. `ProfitMaxIntradayMLV2`, at most three positions and 75 USDT proposed stake.
2. Reproducible `ProfitMaxV5Asymmetric50`, at most two positions and 50 USDT proposed stake.
3. Reproducible `DualTrendFuturesV1`, at most one position and 50 USDT proposed stake. Exact pair/open-time duplicates with V5 are removed; ML trades are not duplicates because they are a distinct short setup and timeframe.

TRAIN is the common OOS interval 2022-01-01 through 2024-01-01 (730 days). The ML sleeve trains on the preceding 365 days and retrains every 30 days. Validation remains 2024-01-01 through 2026-01-01 and may be opened once only if every TRAIN gate passes. Current partial 2026-01-01 through 2026-08-01 remains later diagnostic evidence.

TRAIN portfolio gates: 730-1460 trades (1-2/day), positive return, PF at least 1.30, wallet-curve DD at most 10%, return/DD at least 2.0, both 2022 and 2023 positive with PF at least 1.15, ML sleeve non-negative with PF at least 1.00, V5 and V1-unique positive, at least 20 unique V1 trades, no more than six simultaneous positions, and no more than 40% simultaneous proposed/actual stake. All costs are those recorded by Freqtrade and every trade must record exactly 0.00075 fee per side.

Any source, runtime, data, model isolation, reconciliation, or TRAIN performance failure closes the cycle as `KEEP_OFFLINE_RESEARCH`. Passing TRAIN only unlocks technical gates and one validation run; it does not authorize dry-run deployment, live trading, or claim guaranteed profit.
