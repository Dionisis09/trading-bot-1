# Forward Dashboard and Alerts

## Operating status

The forward-observation layer is fully separate from strategy execution. It
does not change entries, exits, position sizing, leverage, exchange settings,
or the locked decision gates.

Seven Compose services run:

- `freqtrade`: V1 control dry-run.
- `freqtrade-v2r`: selected V2R candidate dry-run.
- `forward-monitor`: read-only Freqtrade API collection every four hours.
- `forward-watchdog`: independent local freshness check every 60 seconds; it
  alerts when the scheduled snapshot is older than five hours.
- `dashboard-builder`: packages each new canonical snapshot into an offline
  self-contained HTML dashboard. It polls for a new artifact every 60 seconds.
- `daily-report-builder`: packages the answer-first daily KPI report into a
  self-contained HTML file and polls for a new artifact every 60 seconds.
- `dashboard-web`: serves only the generated dashboard and a minimal health
  endpoint on `127.0.0.1:8090` with no-cache and browser security headers. The
  daily report is available at `/daily`.

Neither monitoring service publishes a network port. The dashboard server is
bound to loopback only, makes no external requests, and does not expose source
JSON, configs, logs, APIs, or credentials.

## Dashboard

Open the latest dashboard on Windows:

```powershell
Start-Process http://127.0.0.1:8090
```

Open the daily report with `OPEN_DAILY_REPORT.cmd` or:

```powershell
.\deploy\vps\open_dashboard.ps1 -DailyReport
```

The direct offline file remains available at
`user_data/dashboard/forward_dashboard.html`. The web URL is recommended
because it always reads the newest generated file and disables browser caching.

The default view contains:

- coverage-weighted validated observation days versus the 30-day review
  minimum, alongside raw calendar days;
- four-hour scheduled-snapshot coverage, watchdog age, and daily-backup age;
- V1 and V2R closed trades versus the 30-trade minimum;
- V2R net closed-trade PnL, profit factor, and wallet-normalized drawdown;
- closed-trade accumulation and net-profit trends;
- latest V1 versus V2R comparison;
- all integrity, sample, and performance gates;
- the most recent deduplicated alerts.

Dashboard sources are the validated monitor artifacts under
`user_data/reports`. The artifact exposes only metrics and source paths; it
contains no API username, password, exchange key, secret, or webhook URL.

The canonical source is
`user_data/dashboard/forward_dashboard_artifact.json`. The generated HTML is
`user_data/dashboard/forward_dashboard.html`. The builder status is
`user_data/dashboard/forward_dashboard_build_status.json`.

The daily source artifact is
`user_data/dashboard/daily_report_artifact.json`, its generated page is
`user_data/dashboard/daily_report.html`, and its builder status is
`user_data/dashboard/daily_report_build_status.json`. One bounded KPI snapshot
per UTC day is archived under `user_data/reports/daily/`. The report leads with
the decision, operational safety, sample sufficiency, qualification progress,
and explicit caveats; it does not present dry-run PnL as a profit forecast.

## Alert rules

Alerts are emitted only on state changes, so normal four-hour snapshots do not
repeat the same warning.

| Event | Severity | Trigger |
|---|---|---|
| `MONITOR_BASELINE` | INFO | Alert state is initialized. |
| `DAILY_FORWARD_SUMMARY` | INFO | One fail-closed status summary is emitted per UTC day. |
| `NEW_CLOSED_TRADES` | INFO | A bot's closed-trade count increases. |
| `DECISION_CHANGED` | INFO/WARNING/CRITICAL | The machine decision changes. |
| `MONITORING_ERROR_ACTIVE` | CRITICAL | API, runtime, schema, or integrity monitoring fails. |
| `MONITORING_ERROR_RECOVERED` | INFO | Monitoring integrity recovers. |
| `STALE_MONITOR` | CRITICAL | The latest scheduled snapshot is older than five hours, unavailable, or clock-invalid. |
| `STALE_MONITOR_RECOVERED` | INFO | Scheduled snapshot freshness recovers. |
| `CONTINUITY_SEGMENT_RESET` | WARNING | A gap above eight hours resets the validated 30-day segment. |
| `BOT_RESTART_DETECTED` | INFO | A bot's reported start time changes. |
| `BACKUP_FAILED` | CRITICAL | The daily evidence backup fails. |
| `BACKUP_RECOVERED` | INFO | Evidence backup succeeds after a failure. |
| `DEADMAN_HEARTBEAT_FAILED` | WARNING | A configured external heartbeat cannot be delivered. |
| `DEADMAN_HEARTBEAT_RECOVERED` | INFO | External heartbeat delivery recovers. |
| `V2R_DRAWDOWN_WARNING` | WARNING | V2R drawdown reaches 8% of starting wallet. |
| `V2R_DRAWDOWN_LIMIT_REACHED` | CRITICAL | V2R drawdown reaches the locked 10% limit. |
| `V2R_DRAWDOWN_WARNING_CLEARED` | INFO | V2R drawdown falls below 8%. |

Local alerts are written to
`user_data/reports/forward_alerts.jsonl` and
`user_data/reports/forward_watchdog_alerts.jsonl`, included in the dashboard,
and printed to the relevant container log.

```powershell
docker compose logs -f --tail 50 forward-monitor forward-watchdog
```

## Optional webhook delivery

No external destination is configured by default. To activate a trusted HTTPS
JSON webhook, set `FORWARD_ALERT_WEBHOOK_URL` in a local `.env` file and recreate
the two alert-producing observation services:

```text
FORWARD_ALERT_WEBHOOK_URL=https://trusted.example/your-private-endpoint
```

```powershell
docker compose up -d --force-recreate forward-monitor forward-watchdog
```

The webhook receives one JSON batch containing `source`, `snapshot_utc`, and
`alerts`. The URL is never written to reports or logs. Keep `.env` private; do
not commit or share credential-bearing webhook URLs.

For an account-free push channel, the same variable also accepts a private
`https://ntfy.sh/<unguessable-topic>` URL. The monitor sends a compact readable
message with severity-based priority instead of the generic JSON batch. Topic
names act as passwords on the anonymous hosted service, so the configured topic
must be cryptographically random and must never appear in reports, logs, source
control, or screenshots. Operational alert content is transmitted to and
temporarily cached by the external ntfy service; exchange keys and API
credentials are never included.

On the configured Windows workstation, `OPEN_ALERTS.cmd` verifies the private
topic URL over SSH without printing or storing it locally, then opens the ntfy
web app using the browser's existing one-time subscription. The launcher does
not navigate to the secret URL or expose the topic in its output. A new browser
profile must complete the one-time subscription before using this launcher.

When the webhook is empty, alerts still remain in the local journals, logs,
dashboard, and daily report, while external delivery is shown as `LOCAL_ONLY`.

## Optional external dead-man heartbeat

`FORWARD_HEARTBEAT_URL` accepts a vendor-neutral HTTPS ping URL, including a
Healthchecks.io-compatible URL. While the scheduled monitor snapshot is fresh,
the watchdog sends one GET request per minute. It deliberately stops sending
when the snapshot is stale, so the external service transitions to down after
its configured grace period. This also detects a powered-off PC or stopped
Docker engine.

```text
FORWARD_HEARTBEAT_URL=https://your-heartbeat-provider.example/private-check-token
```

```powershell
docker compose up -d --force-recreate forward-watchdog
```

Configure the external check for an expected period of about two minutes and a
grace period of about three additional minutes. The heartbeat URL is a secret:
it remains only in the container environment and is never returned in status
JSON, alerts, logs, dashboard artifacts, or backups. HTTP URLs are rejected.
With the variable empty, status is `DISABLED` and no external request occurs.

## Verification

The portable dashboard passed canonical artifact validation, packaging, and
exact payload/semantic structural verification. The installed desktop browsers
could not satisfy the builder's controlled chart-extraction environment, so
the result is recorded as `structural_only`; automated per-artifact browser
geometry and source-dialog interaction checks were unavailable. The semantic
chart tables remain embedded for offline and no-script fallback.

Run the implementation tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_forward*.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_backup*.py" -v
node --check tools\refresh_forward_dashboard.mjs
node --test tools\test_dashboard_server.mjs
docker compose config --quiet
```

## Continuity and backups

Only valid scheduled snapshots count toward the 30-day clock. Manual runs do
not add coverage. Coverage must remain at least 95%; a gap above eight hours
starts a new validated segment. Every bot loop must be no older than 120
seconds, and every configured pair's latest completed 4h candle close must be
no older than five hours.

At most once per 24 hours, the monitor creates an atomic backup under
`user_data/backups`: both dry-run SQLite databases via SQLite's online backup
API, plus a ZIP of reports/dashboard evidence. The manifest records SHA-256,
file sizes, and SQLite integrity results. Configs, `.env`, credentials, and the
webhook URL are excluded. Retention is 35 days while the two newest complete
backups are always preserved. Full locked rules are in
`docs/forward_continuity_and_backup_plan.md`.

The local watchdog alone cannot send an alert if Windows, Docker, and all
containers are simultaneously offline. Configuring the optional external
dead-man heartbeat closes that availability gap without giving either monitor
exchange permissions.

The dashboard and alerts are observation tools. `FORWARD_REVIEW_READY` still
requires human review and never authorizes live trading or guarantees profit.

The overview also exposes the canonical live-readiness state, deterministic
execution-stress result, and each bot's account entry guard. Detailed risk and
qualification rules are in `professional_risk_and_live_readiness.md`.

## VPS operation

The Compose stack is portable to Ubuntu because the exact dashboard builder is
vendored under `vendor/data-analytics-plugin`; no Windows/Codex cache path is
required. VPS bootstrap, transactional cutover with local rollback, and secure
SSH-tunnel access are documented in `deploy/vps/README.md`.
