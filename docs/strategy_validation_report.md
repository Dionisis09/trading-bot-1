# Strategy Research Decision - 2026-08-03

## Outcome

**NO STRATEGY APPROVED.** Four executable candidates failed the pre-declared
validation gates. The `2026-01-01` to `2026-08-01` holdout was not evaluated,
no tested strategy was promoted to dry-run, and live trading is not authorized.

## Comparable results

All results use Binance Spot BTC/USDC + ETH/USDC, a 1,000 USDC research wallet,
maximum two simultaneous trades, `unlimited` research stake, protections where
supported through the common wrapper, and Freqtrade's 0.10% per-side fee.

| Strategy | Split | Trades | Return | Profit factor | Max drawdown | Worst pair PF |
|---|---:|---:|---:|---:|---:|---:|
| BinanceSpotTrendV1 | Train | 98 | -1.05% | 0.967 | 8.35% | 0.870 |
| BinanceSpotTrendV1 | Validation | 106 | -6.05% | 0.827 | 12.88% | 0.596 |
| BinanceSpotBreakoutV2 | Train | 79 | -10.44% | 0.741 | 10.60% | 0.720 |
| BinanceSpotBreakoutV2 | Validation | 99 | -12.87% | 0.745 | 18.81% | 0.507 |
| BandtasticRisk | Train | 864 | -67.08% | 0.529 | 67.08% | 0.522 |
| BandtasticRisk | Validation | 1,179 | -77.68% | 0.603 | 78.16% | 0.590 |
| SwingHighToSkyRisk | Train | 109 | -13.11% | 0.542 | 19.15% | 0.401 |
| SwingHighToSkyRisk | Validation | 148 | -40.98% | 0.274 | 41.00% | 0.196 |

`SupertrendRisk` from the same pinned open-source source was not assigned a
performance result. It was unavailable because the vendor implementation calls
`fillna(0)` on a pandas string column and fails under the current runtime. This
is recorded as `UNAVAILABLE_INCOMPATIBLE`, not as a zero-return backtest.

## Technical validity

- `BinanceSpotTrendV1` lookahead analysis: 100 signals checked, 0 biased entries,
  0 biased exits, `has_bias = False`.
- Recursive analysis: the 1h EMA200 varied by about 0.104% at 399 startup
  candles and effectively 0% at 799/800. The final strategy therefore uses 800.
- The final V1 backtests were rerun after that change and metrics were unchanged.
- Bias analysis was not run for candidates that had already failed the
  performance gates; this prevents spending analysis effort from being confused
  with qualification.
- The validation notebook recomputed trade count, PnL, win/loss counts, and
  profit factor from the raw zipped trade records and asserted equality with
  Freqtrade's stored totals.

## Open-source review

The ready-code benchmark used `freqtrade/freqtrade-strategies` commit
`dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4`. The repository itself warns that
many strategies were hyperoptimized and that results vary with pairs,
timeframes, and periods. The local evidence confirms that its historical summary
figures do not transfer to this Binance USDC scope.

NostalgiaForInfinity was reviewed but was not forced into this test. Its own
recommended operating scope is 40-80 pairs and 6-12 open trades, materially
different from this two-pair portfolio.

## Operational decision

- Keep Binance API key and secret empty.
- Keep the container and Web UI available, but leave trading state stopped.
- Do not deploy SampleStrategy, V1, V2, or either executable vendor benchmark.
- Preserve the final holdout for a genuinely new hypothesis.
- Next research should improve the portfolio/problem definition rather than
  tune nearby thresholds against these same periods.

## Evidence

- Executed notebook: `user_data/notebooks/strategy_validation.ipynb`
- Machine decision: `user_data/reports/strategy_validation_decision.json`
- Gate table: `user_data/reports/strategy_validation_gates.csv`
- Reconciliation: `user_data/reports/strategy_backtest_reconciliation.csv`
- Lookahead evidence: `user_data/reports/BinanceSpotTrendV1_lookahead.csv`
- Data-quality notebook: `user_data/notebooks/binance_ohlcv_data_quality.ipynb`

