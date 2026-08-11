[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9.-]+$')]
    [string]$Server = '195.238.122.36',

    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_-]*$')]
    [string]$SshUser = 'trader',

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\trading_bot_vps_ed25519",

    [ValidateRange(1024, 65535)]
    [int]$LocalPort = 8090,

    [switch]$DailyReport
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$dashboardUrl = if ($DailyReport) {
    "http://127.0.0.1:$LocalPort/daily"
} else {
    "http://127.0.0.1:$LocalPort"
}
$healthUrl = "http://127.0.0.1:$LocalPort/health"
$existingListener = Get-NetTCPConnection `
    -LocalAddress 127.0.0.1 `
    -LocalPort $LocalPort `
    -State Listen `
    -ErrorAction SilentlyContinue

if (-not $existingListener) {
    $sshArguments = @(
        '-i', [System.IO.Path]::GetFullPath($IdentityFile),
        '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-N',
        '-L', "${LocalPort}:127.0.0.1:8090",
        "${SshUser}@${Server}"
    )
    $tunnelProcess = Start-Process `
        -FilePath 'ssh.exe' `
        -ArgumentList $sshArguments `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 2
    if ($tunnelProcess.HasExited) {
        throw "The SSH dashboard tunnel exited with code $($tunnelProcess.ExitCode)."
    }
}

$health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 10
if ($health.status -ne 'ready') {
    throw "Dashboard health check did not return ready."
}
if ($DailyReport -and $health.daily_report_status -ne 'ready') {
    throw "Daily report is not ready yet."
}

Start-Process $dashboardUrl
[pscustomobject]@{
    status = if ($DailyReport) { 'DAILY_REPORT_OPENED' } else { 'DASHBOARD_OPENED' }
    url = $dashboardUrl
    tunnel = if ($existingListener) { 'reused' } else { 'started' }
    dashboard_updated_utc = $health.dashboard_updated_utc
} | ConvertTo-Json
