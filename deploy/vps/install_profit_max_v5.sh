#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: install_profit_max_v5.sh ARCHIVE EXPECTED_SHA256" >&2
  exit 2
fi

readonly ROOT="/opt/trading-bot"
readonly ARCHIVE="$1"
readonly EXPECTED_ARCHIVE_SHA="$2"

[[ "$ARCHIVE" == /tmp/profit-max-v5-*.tgz ]] || {
  echo "unsafe archive path" >&2
  exit 3
}

cd "$ROOT"
exec 9>"$ROOT/.profit-max-v5-deploy.lock"
flock -n 9 || {
  echo "deployment is already locked" >&2
  exit 4
}

actual_archive_sha="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[[ "$actual_archive_sha" == "$EXPECTED_ARCHIVE_SHA" ]]

stage="$(mktemp -d "$ROOT/.profit-max-v5-stage.XXXXXX")"
[[ "$stage" == "$ROOT"/.profit-max-v5-stage.* ]]
started=0
env_file="$ROOT/user_data/reports/profit_max_swing_cycle5/forward/vps-dry-run.env"

dc() {
  docker compose \
    -p profit-max-v5 \
    --project-directory "$ROOT" \
    --env-file "$env_file" \
    -f "$ROOT/docker-compose.profit-max-v5.yml" \
    "$@"
}

cleanup() {
  local rc=$?
  if [[ "$rc" -ne 0 && "$started" -eq 1 ]]; then
    dc stop profit-max-v5-monitor profit-max-v5-backup profit-max-v5-dry-run >/dev/null 2>&1 || true
  fi
  rm -rf -- "$stage"
  rm -f -- "$ARCHIVE"
  exit "$rc"
}
trap cleanup EXIT

mkdir -p "$stage/extract"
tar -xzf "$ARCHIVE" -C "$stage/extract"

required=(
  docker-compose.profit-max-v5.yml
  tools_profit_max_v5/check_freqtrade_process.py
  tools_profit_max_v5/monitor_profit_max_v5.py
  tools_profit_max_v5/backup_profit_max_v5.py
  user_data/strategies_profit_max_v5/ProfitMaxSwingV5.py
  user_data/strategies_profit_max_v5/DualTrendFuturesRisk.py
  user_data/strategies_profit_max_v5/DualTrendFuturesV1.py
  user_data/strategies_profit_max_v5/DualTrendFuturesV2.py
  user_data/strategies_profit_max_v5/ProfessionalRisk.py
  user_data/config-profit-max-v5-dry-run.json
  user_data/risk_policy-profit-max-v5.json
)
for rel in "${required[@]}"; do
  [[ -f "$stage/extract/$rel" ]]
done

python3 - "$stage/extract/user_data/config-profit-max-v5-dry-run.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)

assert config.get("dry_run") is True
assert config.get("trading_mode") == "futures"
assert config.get("margin_mode") == "isolated"
assert config.get("strategy") == "ProfitMaxV5Asymmetric50"
assert config.get("timeframe") == "4h"
assert config.get("max_open_trades") == 2
exchange = config.get("exchange") or {}
assert not str(exchange.get("key") or "").strip()
assert not str(exchange.get("secret") or "").strip()
PY

base_containers=(
  binance-freqtrade-dry-run
  binance-freqtrade-v2r-dry-run
  trading-forward-monitor
  trading-forward-watchdog
  trading-daily-report-builder
  trading-dashboard-builder
  trading-dashboard-web
  trading-derivatives-collector
)
for name in "${base_containers[@]}"; do
  docker inspect -f "$name|{{.Id}}" "$name"
done > "$stage/before.ids"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
deploy_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
backup_dir="$ROOT/user_data/backups/deployments/profit-max-v5-$stamp"
mkdir -p "$backup_dir"
cp "$stage/before.ids" "$backup_dir/preexisting-container-ids.txt"
sha256sum "$ROOT/docker-compose.yml" > "$backup_dir/base-compose.sha256"

for rel in \
  docker-compose.profit-max-v5.yml \
  user_data/config-profit-max-v5-dry-run.json \
  user_data/risk_policy-profit-max-v5.json; do
  if [[ -e "$ROOT/$rel" ]]; then
    mkdir -p "$backup_dir/$(dirname "$rel")"
    cp -a "$ROOT/$rel" "$backup_dir/$rel"
  fi
done

if [[ -e "$ROOT/user_data/forward/profit-max-v5/trades.sqlite" ]]; then
  echo "refusing non-fresh remote database" >&2
  exit 5
fi

mkdir -p \
  "$ROOT/tools_profit_max_v5" \
  "$ROOT/user_data/strategies_profit_max_v5" \
  "$ROOT/user_data/forward/profit-max-v5" \
  "$ROOT/user_data/backups/profit-max-v5" \
  "$ROOT/user_data/reports/profit_max_swing_cycle5/forward" \
  "$ROOT/user_data/logs"

install -m 0644 "$stage/extract/docker-compose.profit-max-v5.yml" "$ROOT/docker-compose.profit-max-v5.yml"
install -m 0644 "$stage/extract/tools_profit_max_v5/"*.py "$ROOT/tools_profit_max_v5/"
install -m 0644 "$stage/extract/user_data/strategies_profit_max_v5/"*.py "$ROOT/user_data/strategies_profit_max_v5/"
install -m 0600 "$stage/extract/user_data/config-profit-max-v5-dry-run.json" "$ROOT/user_data/config-profit-max-v5-dry-run.json"
install -m 0600 "$stage/extract/user_data/risk_policy-profit-max-v5.json" "$ROOT/user_data/risk_policy-profit-max-v5.json"
printf 'PROFIT_MAX_V5_FORWARD_STARTED_AT_UTC=%s\n' "$deploy_utc" > "$env_file"
chmod 0600 "$env_file"

dc config --quiet
service_inventory="$(dc config --services | sort | tr '\n' ',')"
[[ "$service_inventory" == "profit-max-v5-backup,profit-max-v5-dry-run,profit-max-v5-monitor," ]]

dc run --rm --no-deps --entrypoint freqtrade profit-max-v5-dry-run \
  show-config \
  --config /freqtrade/user_data/config-profit-max-v5-dry-run.json \
  > "$stage/show-config.log" 2>&1
dc run --rm --no-deps --entrypoint freqtrade profit-max-v5-dry-run \
  list-strategies \
  --config /freqtrade/user_data/config-profit-max-v5-dry-run.json \
  --strategy-path /freqtrade/user_data/strategies_profit_max_v5 \
  > "$stage/list-strategies.log" 2>&1
grep -Eq 'ProfitMaxV5Asymmetric50.*OK' "$stage/list-strategies.log"

dc up -d
started=1

healthy=0
for _ in $(seq 1 36); do
  bot_state="$(docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' binance-profit-max-v5-dry-run 2>/dev/null || true)"
  monitor_state="$(docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' profit-max-v5-forward-monitor 2>/dev/null || true)"
  backup_state="$(docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' profit-max-v5-backup 2>/dev/null || true)"
  if [[ "$bot_state" == "running|healthy" && "$monitor_state" == "running|healthy" && "$backup_state" == "running|healthy" ]]; then
    healthy=1
    break
  fi
  sleep 5
done
[[ "$healthy" -eq 1 ]]

docker exec profit-max-v5-forward-monitor python /freqtrade/tools/monitor_profit_max_v5.py \
  --healthcheck \
  --output /freqtrade/output/forward_latest.json \
  --health-max-age-seconds 7200
docker exec profit-max-v5-backup python /freqtrade/tools/backup_profit_max_v5.py \
  --healthcheck \
  --output-dir /freqtrade/output \
  --health-max-age-seconds 90000

for name in "${base_containers[@]}"; do
  docker inspect -f "$name|{{.Id}}" "$name"
done > "$stage/after.ids"
cmp -s "$stage/before.ids" "$stage/after.ids"
for name in "${base_containers[@]}"; do
  [[ "$(docker inspect -f '{{.State.Status}}' "$name")" == "running" ]]
done
[[ -z "$(docker port binance-profit-max-v5-dry-run)" ]]

python3 - "$ROOT/user_data/reports/profit_max_swing_cycle5/forward/forward_latest.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    report = json.load(handle)
assert report["mode"] == "dry_run"
assert report["live_trading_authorized"] is False
assert report["auto_promotion_enabled"] is False
assert report["decision"] == "CONTINUE_DRY_RUN"
assert report["qualification_status"] == "EVIDENCE_INCOMPLETE"
print("FORWARD=" + "|".join([
    report["qualification_status"],
    report["decision"],
    str(report["metrics"]["closed_trades"]),
    str(report["database"]["open_trades"]),
]))
PY

python3 - "$ROOT/user_data/backups/profit-max-v5/latest.json" "$ROOT/user_data/backups/profit-max-v5" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
with manifest_path.open(encoding="utf-8") as handle:
    manifest = json.load(handle)
database = root / manifest["database"]
actual = hashlib.sha256(database.read_bytes()).hexdigest()
assert actual == manifest["sha256"]
assert manifest["integrity_check"] == "ok"
print("BACKUP=" + manifest["database"] + "|ok|hash_match")
PY

printf 'DEPLOYMENT=PASS\n'
printf 'DEPLOYED_AT_UTC=%s\n' "$deploy_utc"
printf 'ROLLBACK_EVIDENCE=%s\n' "$backup_dir"
printf 'BASE_SERVICES_UNCHANGED=yes\n'
for name in binance-profit-max-v5-dry-run profit-max-v5-forward-monitor profit-max-v5-backup; do
  docker inspect -f "$name|{{.Id}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}" "$name"
done
printf 'NEW_PUBLISHED_PORTS=none\n'
printf 'FILES_SHA256\n'
sha256sum \
  "$ROOT/docker-compose.profit-max-v5.yml" \
  "$ROOT/user_data/config-profit-max-v5-dry-run.json" \
  "$ROOT/user_data/risk_policy-profit-max-v5.json" \
  "$ROOT/user_data/strategies_profit_max_v5/ProfitMaxSwingV5.py" \
  "$ROOT/tools_profit_max_v5/monitor_profit_max_v5.py" \
  "$ROOT/tools_profit_max_v5/backup_profit_max_v5.py"
