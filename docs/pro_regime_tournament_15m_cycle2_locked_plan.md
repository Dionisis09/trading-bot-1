# BTC Regime 15m Tournament Cycle 2 — Locked plan

Status: `LOCKED_BEFORE_TOURNAMENT_TRAIN`. Research only; no live authorization.

Cycle 1 showed that plain 15m EMA momentum was close to break-even after fees (301 trades, -0.0796%, PF 0.995), while its direction was regime-dependent. Cycle 2 tests one economic hypothesis, fixed before rerun: a slow BTC 1h EMA50/EMA200 regime with EMA200 slope over 12 completed hours controls long/short permission for every pair. It does not delete a pair or side based on Cycle 1 attribution.

Exactly four variants run once on the same TRAIN 2022-01-01 through 2024-01-01: `ProRegimeMomentum15m`, `ProRegimeBreakout15m`, `ProRegimePullback15m`, and `ProRelativeMomentum15m`. Universe, wallet, 5 bps/side fee, isolated futures, 1x leverage, two-position cap and next-candle execution remain unchanged. No callbacks, ML, LLM order input, hyperopt, grid search, or post-result edits.

TRAIN gates and winner selection are unchanged from Cycle 1: >=80 trades, return >0, PF >=1.15, wallet DD <=15%, return/DD >=0.50; highest return among complete passes, with PF then lower DD tie-break. No pass ends the cycle. A winner must subsequently pass recursive/prefix-causality/official lookahead technical checks before one validation reveal. Validation requires >=80 trades, return >0, PF >=1.30, DD <=12%, return/DD >=0.75, both years positive, both sides represented, and at least two profitable pairs.

Frozen SHA256:

- child strategy `3dd29879c086515750564fbe09d0d0a94ecac108828ec55c19a23e54446f8016`
- frozen parent `0f079b7f3134f3dad7fa46c7ff99a03efb3f44797a2b358fd70cf9d7e2ce1cdd`
- config `fd7bbba247f539c3a19a2aef6a2f83e1fd1db84b5bd05d53f09b14ca254851cf`
- tests `a83cc6b6a1892e1fe126260f60d0590e2cba1b4b315e622abc26cf18484ff3a0`
- canonical data audit `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`
- risk policy `6a3e073fd08b21d645b0d4b4151022bef79adc610d8c130b36554a01e6f51e80`
- runtime `freqtradeorg/freqtrade@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`

