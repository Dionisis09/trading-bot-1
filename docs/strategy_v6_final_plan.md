# Major Trend V6 - Final Candidate Plan

This is the final research adjustment before the sealed holdout. It was written
before any V6 backtest. If V6 fails, no additional parameter or universe search
will be performed against the same train/validation data.

## Frozen rules and portfolio

V6 makes no strategy-rule change: it inherits the frozen V5/V4B logic. It adds
ETH/USDT to the V5 portfolio as a high-liquidity, long-history diversifier. ETH
was positive in validation but modestly negative in train, so this decision is
not equivalent to retaining only symbols positive in both research windows.

The exact universe is BTC/USDT, ETH/USDT, BNB/USDT, XRP/USDT, ADA/USDT, and
DOGE/USDT. The research wallet, fees, maximum positions, data, protections, and
chronological splits remain unchanged.

## Qualification gates before holdout

- Train: positive return and PF >= 1.10.
- Full validation: at least 60 trades, positive return, PF >= 1.50, and maximum
  drawdown <= 15%.
- At least 5 of 6 pairs have positive validation return.
- No validation pair loses more than 3% of starting equity or has PF below 0.75.
- Both 2024 and 2025 subwindows: positive return, PF >= 1.00, and at least 15
  trades.
- No pair contributes more than 50% of total positive pair profit and no single
  trade contributes more than 25% of total positive trade profit.
- Full train and validation remain positive at a 0.15% fee per side.
- Lookahead analysis finds no biased entry, exit, or indicator; recursive
  analysis finds no material variance at the adopted startup history.

## Sealed holdout

Only after every prior gate passes, open 2026-01-01 through 2026-08-01 exactly
once. It must have at least 12 trades, positive net return, PF >= 1.00, and
maximum drawdown <= 15%.

A pass authorizes only small-stake dry-run operation. It does not guarantee
future profitability and does not authorize live credentials or live orders.

## Pre-holdout technical correction

The first recursive analysis, performed before lookahead trade analysis and
before opening the holdout, measured approximately 0.399% EMA200 variance at
400 startup candles and -0.005% at 799. The inherited startup history was
therefore increased from 400 to 800 candles. This is an indicator-convergence
correction, not a PnL-selected parameter change. Every V6 economic gate must be
rerun with 800 before the candidate can advance.
