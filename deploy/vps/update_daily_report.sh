#!/usr/bin/env bash
set -Eeuo pipefail

archive="${1:-}"
app_root="/opt/trading-bot"

if [[ -z "$archive" || ! -f "$archive" ]]; then
  echo "Usage: $0 /absolute/path/to/trading-daily-update.tar.gz" >&2
  exit 2
fi

case "$archive" in
  /*) ;;
  *)
    echo "The update archive path must be absolute." >&2
    exit 2
    ;;
esac

if [[ ! -d "$app_root" || ! -f "$app_root/docker-compose.yml" ]]; then
  echo "Expected deployment root is unavailable: $app_root" >&2
  exit 2
fi

stage="$(mktemp -d "$app_root/.daily-report-stage.XXXXXX")"
backup="$app_root/deploy-backups/daily-report-$(date -u +%Y%m%dT%H%M%SZ)"

cleanup() {
  case "$stage" in
    "$app_root"/.daily-report-stage.*) rm -rf -- "$stage" ;;
    *) echo "Refusing to remove unexpected stage path: $stage" >&2 ;;
  esac
}
trap cleanup EXIT

while IFS= read -r member; do
  case "$member" in
    /*|../*|*/../*|*/..)
      echo "Unsafe archive member: $member" >&2
      exit 2
      ;;
  esac
done < <(tar -tzf "$archive")

tar -xzf "$archive" -C "$stage"

files=(
  "docker-compose.yml"
  "tools/daily_report_artifact.py"
  "tools/test_daily_report_artifact.py"
  "tools/monitor_forward_dry_runs.py"
  "tools/test_forward_monitor.py"
  "tools/serve_dashboard.mjs"
  "tools/test_dashboard_server.mjs"
  "deploy/vps/open_dashboard.ps1"
  "deploy/vps/open_alerts.ps1"
  "deploy/vps/cutover_to_vps.ps1"
  "deploy/vps/update_daily_report.sh"
  "deploy/vps/README.md"
  "docs/forward_dashboard_and_alerts.md"
  "README.md"
  ".env.example"
  "OPEN_ALERTS.cmd"
  "OPEN_DAILY_REPORT.cmd"
)

for relative_path in "${files[@]}"; do
  if [[ ! -f "$stage/$relative_path" ]]; then
    echo "Update archive is missing $relative_path" >&2
    exit 2
  fi
done

docker compose --project-directory "$app_root" -f "$stage/docker-compose.yml" config --quiet

mkdir -p "$backup"
: > "$backup/existed.txt"
for relative_path in "${files[@]}"; do
  if [[ -f "$app_root/$relative_path" ]]; then
    printf '%s\n' "$relative_path" >> "$backup/existed.txt"
    install -D -m 0644 "$app_root/$relative_path" "$backup/$relative_path"
  fi
done

rollback() {
  echo "Update failed; restoring the previous runtime files." >&2
  for relative_path in "${files[@]}"; do
    if grep -Fqx "$relative_path" "$backup/existed.txt"; then
      install -D -m 0644 "$backup/$relative_path" "$app_root/$relative_path"
    else
      rm -f -- "$app_root/$relative_path"
    fi
  done
  docker compose --project-directory "$app_root" -f "$app_root/docker-compose.yml" up -d || true
}

for relative_path in "${files[@]}"; do
  mode="0644"
  [[ "$relative_path" == "deploy/vps/update_daily_report.sh" ]] && mode="0755"
  install -D -m "$mode" "$stage/$relative_path" "$app_root/$relative_path"
done

if ! docker compose --project-directory "$app_root" -f "$app_root/docker-compose.yml" config --quiet; then
  rollback
  exit 1
fi

if ! docker compose --project-directory "$app_root" -f "$app_root/docker-compose.yml" up -d; then
  rollback
  exit 1
fi

expected="$(docker compose --project-directory "$app_root" -f "$app_root/docker-compose.yml" config --services | wc -l)"
running="$(docker compose --project-directory "$app_root" -f "$app_root/docker-compose.yml" ps --status running --services | wc -l)"
if [[ "$running" -ne "$expected" ]]; then
  rollback
  exit 1
fi

printf 'DAILY_REPORT_UPDATE_APPLIED expected_services=%s running_services=%s backup=%s\n' \
  "$expected" "$running" "$backup"
