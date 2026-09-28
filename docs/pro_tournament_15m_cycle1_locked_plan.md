# Professional 15m Tournament Cycle 1 — Locked plan

Status: `LOCKED_BEFORE_TOURNAMENT_TRAIN`. Research only; no live authorization.

Exactly five causal, non-ML strategy families are tested once on TRAIN 2022-01-01 through 2024-01-01: `ProTrendBreakout15m`, `ProTrendPullback15m`, `ProMomentumCross15m`, `ProVolatilityBreakout15m`, and `ProMeanReversion15m`. Universe is exactly BTC/USDT:USDT, ETH/USDT:USDT, BNB/USDT:USDT; 15m base, completed 1h/4h context, next-candle execution, futures isolated, 1x, two concurrent trades, 100 USDT stake, 5 bps fee per side.

No candidate, parameter, side, or pair may be edited after TRAIN. No hyperopt, LLM order decision, order-flow, OI, or post-result deletion is allowed. The five candidates are one predeclared family tournament, not five sequential attempts.

A candidate is TRAIN-eligible only with at least 80 trades, positive return, profit factor >=1.15, wallet-curve drawdown <=15%, and return/drawdown >=0.50. Among eligible candidates, the winner is the highest return; ties use higher PF and then lower DD. If none pass, the cycle ends `KEEP_OFFLINE_RESEARCH`. Only the winner may proceed to recursive analysis, independent prefix-causality analysis, official lookahead diagnostics, then a single validation reveal for 2024-01-01 through 2026-01-01. Validation gates remain stricter: at least 80 trades, return >0, PF >=1.30, DD <=12%, return/DD >=0.75, both years positive, both sides represented, and at least two profitable pairs. Current partial and cost stress run only after validation passes.

Frozen SHA256 inputs:

- strategy `0f079b7f3134f3dad7fa46c7ff99a03efb3f44797a2b358fd70cf9d7e2ce1cdd`
- config `838928506590ae3d081cd3391c5339619c0d9c233e13a7e3cb6c36a1d49b1f75`
- strategy tests `b476fc604f8b86ef76b02f800eadc1aab274277ee6f10e50dc2ef2d277dec2d7`
- canonical data audit `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`
- risk policy `6a3e073fd08b21d645b0d4b4151022bef79adc610d8c130b36554a01e6f51e80`
- runtime `freqtradeorg/freqtrade@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`

