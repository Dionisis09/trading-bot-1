# Binance Dual-Trend Trading Bot

Λειτουργικό ερευνητικό bot βασισμένο στο Freqtrade για Binance USDT-M Futures.
Η τελική στρατηγική `DualTrendFuturesV1` ακολουθεί ανοδικές και καθοδικές τάσεις
με συμμετρικά long/short rules, 4h candles, ημερήσιο regime filter και 1× leverage.

## Τρέχουσα κατάσταση

- Docker container: `binance-freqtrade-dry-run`.
- State: `RUNNING`.
- Mode: Binance Futures, isolated margin, αποκλειστικά `dry_run`.
- Simulated stake: 25 USDT ανά θέση, έως 2 ταυτόχρονες θέσεις.
- Universe: BTC, ETH, BNB, XRP, ADA και DOGE perpetuals.
- Web UI: <http://127.0.0.1:8080>.
- Binance API key/secret: κενά.
- Live trading: δεν είναι εξουσιοδοτημένο.

## Γρήγορη χρήση

```powershell
docker compose up -d
docker compose ps
docker compose logs -f --tail 100 freqtrade
```

Τερματισμός:

```powershell
docker compose down
```

## Επαλήθευση

```powershell
.\.venv\Scripts\python.exe tools\create_dual_trend_validation_notebook.py
```

Το command αναδημιουργεί και εκτελεί ολόκληρο το validation notebook, διαβάζει
τα raw zipped Freqtrade exports, επανυπολογίζει trades/profit/PF, ελέγχει τα
δεδομένα και επιβεβαιώνει το ενεργό local dry-run runtime.

- Τελική αναφορά: `docs/dual_trend_validation_report.md`
- Εκτελεσμένο notebook: `user_data/notebooks/dual_trend_validation.ipynb`
- Machine decision: `user_data/reports/dual_trend_validation_decision.json`
- Strategy: `user_data/strategies/DualTrendFuturesV1.py`
- Dry-run config: `user_data/config-dual-futures-dry-run.json`

## V2 challenger status

`DualTrendFuturesV2` tested a locked 3-of-4 DMI/ADX, relative-volume, and VWMA
confluence model. It improved 2024-2026 return and profit factor, but failed the
pre-declared validation and 2025 drawdown gates. V2 was not deployed; V1 remains
the active dry-run strategy. See `docs/dual_trend_v2_results.md` and reproduce
the audit with:

```powershell
.\.venv\Scripts\python.exe tools\create_dual_trend_v2_validation_notebook.py
```

## V2R matched-risk forward test

`DualTrendFuturesV2R` applies a locked ATR/exposure stake multiplier of
32.5%-65% without changing V2 signals. It passed all 22 pre-declared gates and
runs as a separate credential-free dry-run at <http://127.0.0.1:8081>. The V1
primary remains at <http://127.0.0.1:8080>. Rebuild the V2R audit with:

```powershell
.\.venv\Scripts\python.exe tools\create_dual_trend_v2r_validation_notebook.py
```

Full result: `docs/dual_trend_v2r_results.md`. This is forward evidence
collection only; it does not authorize live trading or replacement of V1.

## Final strategy selection

The final locked Chandelier-exit challenger was rejected because it weakened
2025/current-2026 and risk-adjusted validation performance. The selected best
research strategy remains `DualTrendFuturesV2R`, running in credential-free
dry-run at <http://127.0.0.1:8081>. V1 remains the control at
<http://127.0.0.1:8080>.

```powershell
.\.venv\Scripts\python.exe tools\create_final_strategy_tournament_notebook.py
```

Full selection report: `docs/final_strategy_selection.md`. V3R was not deployed
and no live trading is authorized.

## Automated forward monitoring

The `forward-monitor` Compose service takes a read-only snapshot of both dry-run
APIs immediately on startup and every four hours. It independently recomputes
closed-trade profit, profit factor, drawdown, pair breadth, and V2R-versus-V1
risk-adjusted performance. Start or inspect it with:

```powershell
docker compose up -d forward-monitor
docker compose logs --tail 20 forward-monitor
Get-Content user_data/reports/forward_monitor_decision.json
```

The locked review rules require at least 30 coverage-weighted validated days,
95% scheduled-snapshot coverage, no continuity gap above eight hours, and 30
closed trades from each bot. The monitor also validates bot-loop and completed
4h-candle freshness, and creates a daily integrity-checked evidence backup.
It can only emit a human-review readiness decision; it
cannot promote a strategy or authorize live trading. See
`docs/forward_monitoring_plan.md` and run its unit tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_forward_monitor.py" -v
```

The source-backed dashboard is rebuilt automatically after each new monitor
snapshot. The easiest read-only UI is served locally with browser caching
disabled:

```powershell
Start-Process http://127.0.0.1:8090
docker compose logs -f --tail 50 forward-monitor forward-watchdog dashboard-builder dashboard-web
```

The answer-first daily KPI report is rebuilt independently and served at
`http://127.0.0.1:8090/daily`. On the configured Windows workstation,
`OPEN_DAILY_REPORT.cmd` starts or reuses the private SSH tunnel and opens it.

For 24/7 operation on an Ubuntu VPS, use the reviewed bootstrap and rollback-
safe cutover workflow in `deploy/vps/README.md`. The remote dashboard remains
private and is opened through an SSH tunnel; no API or dashboard port is made
public.

Professional account-level entry guards, execution-cost stress validation, and
a fail-closed live-readiness report are now part of the same evidence pipeline.
The locked limits and current qualification rules are documented in
`docs/professional_risk_and_live_readiness.md`. A `READY_FOR_HUMAN_REVIEW`
result still cannot enable live trading by itself.

Local deduplicated alerts cover new trades, decision changes, runtime/data
failures and recovery, plus V2R drawdown warning/limit transitions. Optional
webhook delivery is disabled until `FORWARD_ALERT_WEBHOOK_URL` is explicitly set.
One fail-closed `DAILY_FORWARD_SUMMARY` is also recorded per UTC day. Without a
trusted HTTPS webhook, external delivery is reported truthfully as `LOCAL_ONLY`.
The alert adapter supports generic HTTPS JSON receivers and private ntfy topics.
`OPEN_ALERTS.cmd` verifies the private ntfy channel over SSH and opens the ntfy
app using the existing browser subscription. The secret URL is neither printed
nor placed in the browser address bar by the launcher.
The independent watchdog checks snapshot freshness every minute and supports
an optional secret HTTPS dead-man heartbeat for whole-PC/Docker outage
detection. Full operating notes: `docs/forward_dashboard_and_alerts.md` and
`docs/forward_continuity_and_backup_plan.md`.

## Safety boundary

Το image είναι pinned στο Freqtrade `2026.7` και το Web UI εκτίθεται μόνο στο
`127.0.0.1`. Το `dry_run=true` υπάρχει στο config και επιβάλλεται ξανά από το
Docker command. Η στρατηγική επιστρέφει πάντα 1× leverage, δεν κάνει DCA και
έχει hard stop 10% μαζί με portfolio protections.

Τα backtests είναι ιστορικές προσομοιώσεις, όχι υπόσχεση κέρδους. Τα μεγάλα
research returns χρησιμοποιούν `unlimited` stake για συγκρισιμότητα και δεν
είναι πρόβλεψη της απόδοσης του fixed-stake dry-run. Futures, shorting και
μόχλευση μπορούν να προκαλέσουν γρήγορες απώλειες· οποιαδήποτε μελλοντική live
λειτουργία απαιτεί νέα ρητή απόφαση, περιορισμένο key χωρίς withdrawals, IP
allowlist και νέο forward validation.
