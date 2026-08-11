# DualTrendFuturesV1 - Final Validation Report

## Outcome

`DRY_RUN_APPROVED_AND_RUNNING`

Το `DualTrendFuturesV1` είναι λειτουργικό στο τοπικό Freqtrade/Binance Futures
περιβάλλον και πέρασε όλα τα προκαθορισμένα performance, data-quality και bias
gates. Η έγκριση αφορά μόνο dry-run με κενά API keys. Δεν εγκρίνεται live
trading και δεν υπάρχει εγγύηση μελλοντικού κέρδους.

## Authoritative results

| Window | Trades (L/S) | Net return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|
| Train 2021-2023 | 203 (97/106) | +254.20% | 1.514 | 29.02% |
| Validation 2024-2025 | 139 (92/47) | +45.04% | 1.390 | 13.07% |
| 2024 | 71 (50/21) | +41.23% | 1.781 | 12.75% |
| 2025 | 68 (42/26) | +2.64% | 1.060 | 12.69% |
| Current bearish regime 2026-01/08 | 38 (0/38) | +10.71% | 1.462 | 10.07% |
| Train, fee 0.15%/side | 203 (97/106) | +222.70% | 1.451 | 31.38% |
| Validation, fee 0.15%/side | 139 (92/47) | +35.73% | 1.307 | 14.14% |
| Untouched backcast holdout 2020-08/12 | 23 (23/0) | +32.09% | 3.111 | 11.60% |

Το βασικό Binance Futures backtest χρησιμοποίησε το worst-case exchange fee που
επέλεξε το Freqtrade, 0.05% ανά πλευρά, και πραγματικά διαθέσιμα funding/mark
archives. Το stress test χρησιμοποίησε 0.15% ανά πλευρά.

Στο full validation και τα 6 pairs ήταν θετικά. Το μεγαλύτερο pair contribution
ήταν 44.72% του συνολικού θετικού pair profit και το μεγαλύτερο winning trade
14.92% του συνολικού θετικού trade profit, κάτω από τα όρια 50% και 25%.

## Bias and data validation

- Lookahead analysis: 100 signals, 0 biased entries, 0 biased exits, no biased
  indicators.
- Recursive analysis: EMA200 variance -0.005% στο startup 800, έναντι σχεδόν
  μηδενικής απόκλισης στα μεγαλύτερα histories.
- 6 futures markets, 4h και 1d: 100% κάλυψη όλων των δηλωμένων windows, χωρίς
  duplicates, nulls, invalid OHLCV ή gaps.
- 4h-to-1d reconciliation: 2-4 isolated mismatch days ανά pair, 0.084%-0.167%
  των συγκρινόμενων ημερών. Οι ημερομηνίες και τα πεδία διατηρούνται στο
  `dual_trend_timeframe_reconciliation.csv`; δεν αποκρύφθηκαν.
- Τα raw trade rows συμφωνούν ακριβώς με Freqtrade trades, absolute profit,
  profit factor, wins και losses.

## Live local runtime verification

- UI HTTP 200 και API `pong`.
- State `running`, `dry_run=true`.
- Strategy `DualTrendFuturesV1`, timeframe `4h`.
- Trading mode `futures`, shorts enabled, leverage callback 1×.
- Fixed simulated stake 25 USDT, maximum 2 positions.
- Binance key length 0 και secret length 0 σε base και deployment configs.
- Runtime database: `tradesv3.dual-futures-dryrun.sqlite`.

## Important limitations

Η spot V6 με long-only logic απέτυχε έντιμα στο sealed 2026 holdout: 0 trades,
0%, ενώ το market change ήταν -38.15%. Αυτό οδήγησε σε ξεχωριστό, προδηλωμένο
symmetrical futures candidate — όχι σε post-holdout tuning της V6.

Το backcast holdout είναι ανέγγιχτο ως προς candidate PnL selection, αλλά
χρονολογικά προηγείται του train και συνεπώς είναι ασθενέστερη απόδειξη από ένα
μελλοντικό forward holdout. Το 2026 futures window επίσης δεν χαρακτηρίζεται
sealed, επειδή το προηγούμενο spot test είχε ήδη αποκαλύψει το bearish regime.
Το fixed σημερινό universe δημιουργεί survivorship bias.

Τέλος, τα research backtests χρησιμοποιούν 10,000 USDT και `unlimited` stake με
compounding. Το ενεργό dry-run χρησιμοποιεί μόνο 25 USDT ανά simulated trade·
οι παραπάνω αποδόσεις δεν μεταφέρονται αυτούσιες στο deployment και δεν
προβλέπουν μελλοντική κερδοφορία.

## Reproducible artifacts

- Plan: `docs/dual_trend_v1_futures_plan.md`
- Strategy: `user_data/strategies/DualTrendFuturesV1.py`
- Executed notebook: `user_data/notebooks/dual_trend_validation.ipynb`
- Summary: `user_data/reports/dual_trend_backtest_summary.csv`
- Reconciliation: `user_data/reports/dual_trend_backtest_reconciliation.csv`
- Gate matrix: `user_data/reports/dual_trend_performance_gates.csv`
- Lookahead: `user_data/reports/DualTrendFuturesV1_lookahead.csv`
- Runtime proof: `user_data/reports/dual_trend_runtime_verification.json`
- Machine decision: `user_data/reports/dual_trend_validation_decision.json`

