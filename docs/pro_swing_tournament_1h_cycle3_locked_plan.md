# V2-derived 1h Swing Tournament Cycle 3 — Locked plan

Status: `LOCKED_BEFORE_TOURNAMENT_TRAIN`. Research only; no live authorization.

The two purely intraday families failed TRAIN. Cycle 3 tests whether the historically profitable DualTrendFuturesV2 architecture retains edge when execution is accelerated from 4h to 1h while its regime is accelerated from 1d to completed 4h. Four fixed variants are tested once: Core (30/10 channel, 3-of-4 confluence, ADX>20), Slow (55/20), Selective (4-of-4), and StrongTrend (ADX>25). All other entry structure, DI/ADX/relative-volume/VWMA confluence, directional RSI ranges and channel/regime exits remain common.

Universe is BTC/ETH/BNB USDT futures; 1h base with completed 4h EMA20/50/200 and ROC63, 1x, isolated, maximum two trades, 100 USDT stake, 5 bps fee/side, no callbacks, no ML/LLM orders, no hyperopt, and no post-result edits.

TRAIN 2022-01-01 through 2024-01-01 gates: >=60 trades, return >0, PF >=1.15, wallet DD <=15%, return/DD >=0.50. The passing candidate with highest return wins, ties PF then lower DD. Only the winner can enter technical gates and one sealed validation reveal. Validation gates: >=60 trades, return >0, PF >=1.30, DD <=12%, return/DD >=0.75, both years positive, both sides represented, and >=2 profitable pairs.

Frozen SHA256:

- strategy `f87333d0135a4da026e8908e0102102110404dc760e5590e4427346c7dbfec82`
- config `a634d92284a22ac1da9b6098a0b9d97da73bc858d96a8c5bdfac94e6465a8ff3`
- tests `9460eafffbe740102ec72766aed1d2dbd647c8a4c3ecdaad4ab1febfacbcc66d`
- canonical data audit `f8382831e70604e233efc5428c9ed44b1f1046467feb9459d7fd78c0f1a4f772`
- risk policy `6a3e073fd08b21d645b0d4b4151022bef79adc610d8c130b36554a01e6f51e80`
- runtime `freqtradeorg/freqtrade@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`

