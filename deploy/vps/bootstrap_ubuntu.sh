#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root or with sudo." >&2
  exit 2
fi

source /etc/os-release
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "This bootstrap supports Ubuntu only." >&2
  exit 2
fi

case "${VERSION_ID:-}" in
  22.04|24.04|26.04) ;;
  *)
    echo "Supported Ubuntu LTS releases: 22.04, 24.04, 26.04." >&2
    exit 2
    ;;
esac

apt-get update
apt-get install -y ca-certificates curl fail2ban ufw

if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker
docker compose version

if ! id trader >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash trader
fi
usermod -aG docker trader
install -d -m 0750 -o trader -g trader /opt/trading-bot

source_user="${SUDO_USER:-root}"
source_home="$(getent passwd "${source_user}" | cut -d: -f6)"
if [[ -n "${source_home}" && -f "${source_home}/.ssh/authorized_keys" ]]; then
  install -d -m 0700 -o trader -g trader /home/trader/.ssh
  install -m 0600 -o trader -g trader "${source_home}/.ssh/authorized_keys" /home/trader/.ssh/authorized_keys
fi

ufw allow OpenSSH
ufw --force enable

install -m 0644 "${script_dir}/02-trading-bot-sshd.local" /etc/fail2ban/jail.d/trading-bot-sshd.local
systemctl enable --now fail2ban
fail2ban-client status sshd

echo "VPS_READY user=trader app_dir=/opt/trading-bot dashboard_bind=127.0.0.1:8090"
