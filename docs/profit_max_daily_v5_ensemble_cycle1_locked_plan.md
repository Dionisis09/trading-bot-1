# ProfitMax Daily + V5 Ensemble Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_PORTFOLIO_EVALUATION`. Offline research only; live trading unauthorized.

## Frozen portfolio

Two independently executed sleeves share a 1,000 USDT research wallet:

1. `ProfitMaxDailyCrossStop20`: frozen 50-pair daily cross-sectional leader, BTC 30-day positive gate, two scheduled fills/day, 8h exit, -20% hard stop, no protection plugins, max two slots, 50 USDT proposed stake with ATR reduction.
2. `ProfitMaxV5Asymmetric50`: the exactly reproduced six-pair V5 swing sleeve, max two slots and 50 USDT proposed stake.

Both use 4h completed candles, next-open execution, isolated futures, 1x leverage and fee 0.00075 per side plus recorded funding. No exact pair/open-timestamp overlap is permitted between component archives. Trades are not netted; the combined wallet curve sums realized `profit_abs` at each close timestamp. The portfolio must never exceed four positions or 20% of starting-wallet open stake in the replay.

The component TRAIN archives are explicit and immutable. No component source, rule, threshold, pair, side, stake or result may be changed after this lock. ML/LLM inputs are excluded.

## TRAIN gates

For 2021-01-01 through 2024-01-01 the portfolio must have 1–2 trades/day, return >=10%, PF >=1.30, wallet DD <=10%, return/DD >=2.0, every year positive with PF >=1.05, and both sleeves independently profitable. The daily sleeve must have PF >=1.15 and V5 PF >=1.50. Maximum replay exposure is four positions and 20% starting-wallet stake.

Passing TRAIN unlocks source/config/archive reconciliation plus lookahead and recursive checks for the daily sleeve; V5 technical evidence must be reverified by hash. Moderate cost stress adds 5 bps slippage per side to every raw trade and must remain profitable/PF >=1.20; severe adds 15 bps per side and must remain profitable/PF >=1.05.

Only after technical gates may the daily sleeve be run once on 2024–2025 and combined with an explicit no-cache V5 validation archive. This period is unseen for the new daily sleeve but is not a globally sealed holdout because V5 has previously been evaluated on it. Validation must have 1–2 trades/day, return >0, PF >=1.25, DD <=10%, return/DD >=1.5, and both 2024/2025 positive with PF >=1.05. Each sleeve must remain net positive; the daily sleeve PF must be >=1.05 and V5 PF >=1.20.

Any failed performance gate produces `KEEP_OFFLINE_RESEARCH`; any technical/source/bias gate failure produces `REJECT_CANDIDATE`. Only all TRAIN, validation, current and continuous gates passing may authorize a separate dry-run. Nothing here guarantees future profit or authorizes live trading.

