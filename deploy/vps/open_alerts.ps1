[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9.-]+$')]
    [string]$Server = '195.238.122.36',

    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_-]*$')]
    [string]$SshUser = 'trader',

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\trading_bot_vps_ed25519"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$sshArguments = @(
    '-i', [System.IO.Path]::GetFullPath($IdentityFile),
    '-o', 'BatchMode=yes',
    '-o', 'IdentitiesOnly=yes',
    '-o', 'StrictHostKeyChecking=yes',
    "${SshUser}@${Server}",
    "grep '^FORWARD_ALERT_WEBHOOK_URL=https://ntfy.sh/' /opt/trading-bot/.env | head -n 1 | cut -d= -f2-"
)
$topicUrl = (& ssh.exe @sshArguments).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not retrieve the private alert channel through SSH."
}
if ($topicUrl -notmatch '^https://ntfy\.sh/[A-Za-z0-9_-]{32,}$') {
    throw "The VPS does not have a valid private ntfy alert channel."
}

Start-Process 'https://ntfy.sh/app'
[pscustomobject]@{
    status = 'ALERT_APP_OPENED'
    channel = 'ntfy'
    subscription = 'existing_browser_profile'
    secret_url_printed = $false
} | ConvertTo-Json
