# Historical Market Replay - Locked Plan

## Purpose

Replay the existing Binance USDT perpetual history in chronological order so
that several market years are evaluated in minutes.  This is a diagnostic
historical simulation.  It does not create new forward evidence and cannot
authorize live trading because the historical record has already been seen.

## Frozen inputs

- Control: `DualTrendFuturesV1`.
- Selected dry-run strategy: `DualTrendFuturesV2R`.
- Universe: BTC, ETH, BNB, XRP, ADA, and DOGE USDT perpetuals.
- Timeframes: 4h strategy candles and 1d informative candles.
- Continuous replay window: `2021-01-01` through `2026-08-01` UTC.
- Starting wallet: 1,000 USDT; isolated futures; 1x leverage; fixed 25 USDT
  proposed stake; maximum two open positions; existing protections and
  strategy callbacks unchanged.  These are the active dry-run settings.
- Standard Freqtrade fee: 0.05% per side.
- Cache disabled and trades exported for independent reconciliation.

The strategy source, parameters, pair list, timerange, and gates below are
locked before the replay result is generated.  No post-result threshold or
strategy change is allowed in this experiment.

## Fast-forward views

The exported continuous trade stream will be evaluated without reordering it:

- entire replay;
- each calendar year, with 2026 explicitly labelled partial;
- each calendar quarter, with the final 2026 quarter explicitly labelled
  partial;
- each pair and each long/short direction.

Equity drawdown is computed chronologically from the exported trades, starting
from 1,000 USDT.  Empty windows remain empty and are never converted into a
fake profit factor or a passing result.

## Execution-cost scenarios

The standard Freqtrade result is reconciled exactly first.  Two additional
trade-level adverse-cost scenarios are then applied using the same locked
method as the existing execution-stress evaluator:

- Moderate: +2 fee bps per side, 5 slippage bps per side, 2 latency bps, and
  recorded funding multiplied by 1.5.
- Severe: +10 fee bps per side, 15 slippage bps per side, 5 latency bps, and
  recorded funding multiplied by 3.0.

## Diagnostic gates

The selected V2R replay is called historically robust only if all of these
fixed conditions pass:

- standard whole-period net profit > 0, profit factor >= 1.20, and maximum
  drawdown <= 15% of the starting wallet;
- moderate whole-period net profit > 0 and profit factor >= 1.10;
- severe whole-period net profit > 0 and profit factor >= 1.00;
- at least four of six pairs have positive standard net profit;
- at least four full calendar years have positive standard net profit;
- no full calendar year has standard net profit below -5% of the starting
  wallet;
- source totals reconcile exactly with the Freqtrade export.

Quarterly results are descriptive stress diagnostics and are not required to
all be positive.  V1 is reported as a matched control; this replay does not
replace V2R or change the VPS regardless of the outcome.

## Pre-evaluation execution correction

The first command attempted after this plan used the research profile
(`10,000 USDT`, `unlimited` stake, four slots) instead of the active dry-run
profiles.  The professional account guard correctly rejected the control's
approximately 25% proposed exposure because its locked ceiling is 20%, making
that run configuration-invalid.  Its result is excluded before evaluation.

The replay is therefore executed again as two independent backtests, each with
its exact active dry-run profile (`1,000 USDT`, fixed 25 USDT stake, two slots).
This correction changes no strategy rule or result gate; it makes the command
match the already stated purpose of replaying the bots that are actually
running on the VPS.
