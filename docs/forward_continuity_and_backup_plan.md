# Locked Forward Continuity and Backup Plan

## Why this layer exists

Calendar time alone is not valid forward evidence. A 30-day counter could
otherwise advance while the computer, Docker, an API, or market data were
offline. These rules were locked while both bots still had zero closed forward
trades and before continuity-qualified evidence was collected.

This layer changes no strategy, signal, stake, leverage, pair, or exchange
setting.

## Observation grain and freshness rules

- Scheduled monitor grain: one slot every 14,400 seconds (4 hours).
- Ad-hoc/manual snapshots: diagnostic only and excluded from coverage counts.
- Required current-segment slot coverage: at least 95%.
- Stale-monitor warning: latest scheduled snapshot older than 18,000 seconds
  (5 hours).
- Major continuity gap: more than 28,800 seconds (8 hours) between valid
  scheduled snapshots.
- Major-gap action: preserve the lifetime audit, start a new validated segment,
  and restart the 30 validated-day clock.
- Bot-loop freshness: each Freqtrade `/health` last-process value must be no
  more than 120 seconds old and no more than 30 seconds in the future.
- Market-data freshness: every configured 4h pair must expose a latest completed
  candle whose close is no more than 18,000 seconds old and no more than 30
  seconds in the future.

The official Freqtrade `/health` endpoint is read-only and reports the last bot
loop. Pair freshness is read from the existing read-only `/pair_candles`
endpoint. No exchange order endpoint is used.

## Validated observation time

The current continuity segment records unique scheduled slot indexes. Extra
restarts or duplicate snapshots inside the same slot cannot inflate coverage.

`coverage_ratio = observed_unique_slots / expected_slots`

`validated_observation_days = current_segment_calendar_days * coverage_ratio`

Forward review now requires all of the following in addition to the existing
trade and performance gates:

- at least 30 validated observation days;
- coverage ratio at least 95%;
- no current-segment gap above 8 hours;
- fresh bot loops and completed 4h candles for both bots.

The original monitoring epoch is retained for audit. A major gap resets only
the current validated segment. Changes in each bot's `/health` `bot_start`
timestamp are counted as bot restarts without exposing the Docker socket.

## Local watchdog

A separate read-only watchdog checks the latest monitor snapshot every 60
seconds. It emits deduplicated `STALE_MONITOR` and
`STALE_MONITOR_RECOVERED` events at the five-hour boundary.

The watchdog can detect a failed monitor while Docker and the watchdog remain
running. An optional secret HTTPS heartbeat is sent only while the snapshot is
fresh. If configured, an external dead-man service detects a powered-off
computer or Docker engine from the missing heartbeat. The URL remains only in
the environment and is excluded from reports, logs, dashboards, and backups.

## Backup contract

- Cadence: at most one successful backup per 24 hours.
- Retention: 35 days, while always preserving the two newest complete backups.
- Databases: V1 and V2R SQLite databases copied with SQLite's online backup API.
- Evidence: current `user_data/reports` and `user_data/dashboard` files stored
  in a ZIP archive.
- Integrity: SHA-256 and byte size recorded for every backup artifact.
- Atomicity: each backup is built in a staging directory and renamed only after
  all files and the manifest are complete.
- Exclusions: API configs, `.env`, exchange credentials, and webhook URLs are
  never copied.

Backups are written under `user_data/backups`. Retention deletion is restricted
to validated timestamp-named child directories inside that exact root.

## Decision boundary

Continuity, freshness, or backup failures cannot authorize live trading.
Continuity and freshness failures make the forward evidence ineligible until
the rules above recover. Backup failure is an operational alert but does not
change trade performance metrics.
