# ProfitMaxV5 exact Binance fee verification

Status: `FIXED_COST_DIAGNOSTIC_BEFORE_RUN`.

This diagnostic changes no strategy, pair, side, signal, stake, leverage, risk or execution parameter. It replays the already qualified `ProfitMaxV5Asymmetric50` over the canonical continuous period 2021-01-01 through 2026-08-01 on its original six-pair futures universe, with the fee overridden to exactly `0.00075` per entry side and `0.00075` per exit side, plus recorded funding.

The history is already seen and this is not a new holdout. The output may verify cost-adjusted historical profitability but cannot guarantee future profit or authorize live trading. No strategy edit may follow from this diagnostic without a new locked research cycle.
