# VPS deployment and safe cutover

## Target

- Ubuntu 24.04 LTS recommended; 22.04 and 26.04 LTS are also accepted.
- At least 2 vCPU, 2 GB RAM, 25 GB SSD, and a stable public IPv4 address.
- Provider firewall: allow inbound SSH only. Do not expose ports 8080, 8081,
  8090, or the Docker socket publicly.
- The deployment remains credential-free dry-run. It does not authorize live
  trading or add Binance keys.

## 1. Bootstrap a new VPS

Upload and run the reviewed bootstrap script using the provider's initial SSH
account:

```powershell
scp .\deploy\vps\bootstrap_ubuntu.sh root@SERVER_IP:/tmp/bootstrap_ubuntu.sh
ssh root@SERVER_IP "bash /tmp/bootstrap_ubuntu.sh"
```

If the provider uses `ubuntu` instead of `root`, upload with that user and run
`sudo bash /tmp/bootstrap_ubuntu.sh`. The script installs Docker from Docker's
official Ubuntu repository, enables Docker at boot, creates the unprivileged
`trader` account, copies the current SSH public-key authorization, creates
`/opt/trading-bot`, and enables an SSH-only UFW policy. It does not modify SSH
daemon authentication settings.

Verify access:

```powershell
ssh trader@SERVER_IP "docker compose version"
```

After key access is verified, install `01-trading-bot-hardening.conf` under
`/etc/ssh/sshd_config.d/`, validate with `sshd -t`, and reload SSH. This keeps
key-based access while disabling SSH password authentication and root password
login. It also reduces authentication retries, disables unused forwarding
features, and preserves local TCP forwarding for the private dashboard tunnel.
The provider console remains the recovery path.

The bootstrap installs and enables `fail2ban` with
`02-trading-bot-sshd.local`. The SSH jail bans an address for one hour after
five failed attempts within ten minutes. Confirm it with:

```bash
sudo fail2ban-client status sshd
```

Rollback the SSH drop-in only from a still-open verified key session or the
provider console. Restore the newest timestamped backup, validate, and reload:

```bash
backup="$(ls -1t /etc/ssh/sshd_config.d/01-trading-bot-hardening.conf.bak-* | head -n 1)"
sudo install -m 0600 -o root -g root "$backup" /etc/ssh/sshd_config.d/01-trading-bot-hardening.conf
sudo sshd -t
sudo systemctl reload ssh
```

To remove only the banning layer while leaving key-only SSH intact:

```bash
sudo systemctl disable --now fail2ban
sudo rm -f /etc/fail2ban/jail.d/trading-bot-sshd.local
```

## 2. Review the cutover plan

```powershell
.\deploy\vps\cutover_to_vps.ps1 -Server SERVER_IP -PlanOnly
```

The plan refuses non-empty exchange credentials. Actual cutover first checks
the remote host, then stops the local services, creates an integrity-checked
SQLite backup, transfers only runtime code/config/state over SSH, starts every
service declared by the reviewed Compose file, and validates the dashboard. If
remote startup fails, it stops
the remote stack and restarts the local stack.

## 3. Execute cutover

```powershell
.\deploy\vps\cutover_to_vps.ps1 -Server SERVER_IP
```

Do not start the local trading services again after success; two independent
copies would corrupt the forward comparison. The local containers remain
available but stopped as a recovery copy.

## 4. Open the UI securely

The dashboard listens only on the VPS loopback interface. Create an encrypted
SSH tunnel:

```powershell
ssh -N -L 8090:127.0.0.1:8090 trader@SERVER_IP
```

Keep that terminal open and browse to <http://127.0.0.1:8090>. Freqtrade APIs
remain loopback-only on ports 8080 and 8081. No dashboard, API, password, or
Docker port is public.

On the configured Windows workstation, double-click `OPEN_DASHBOARD.cmd` in
the project directory. It safely reuses or starts the SSH tunnel, verifies the
dashboard health endpoint, and opens the UI in the default browser. Closing the
browser does not stop the VPS bot.

Double-click `OPEN_DAILY_REPORT.cmd` to open the answer-first daily KPI report
through the same private tunnel. The report route is `/daily`; it remains
loopback-only and does not expose source artifacts or credentials.

Double-click `OPEN_ALERTS.cmd` to verify the private ntfy topic through SSH and
open the already-subscribed ntfy web app without printing or navigating to the
secret URL. The real topic remains only in the VPS `.env` file. The one-time
browser subscription must be completed before using this launcher in a new
browser profile.

## Remaining external inputs

Provisioning a paid server requires the owner's provider account and billing
approval. The scripts cannot create or charge an account. The actual cutover
requires only `SERVER_IP` after the VPS exists and SSH key access works.
