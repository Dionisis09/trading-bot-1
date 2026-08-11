[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9.-]+$')]
    [string]$Server,

    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_-]*$')]
    [string]$SshUser = 'trader',

    [ValidatePattern('^/opt/[A-Za-z0-9._/-]+$')]
    [string]$RemoteDir = '/opt/trading-bot',

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$IdentityFile,

    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$target = "${SshUser}@${Server}"
$resolvedIdentityFile = $null
$sshArguments = @()
$scpArguments = @()
if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
    $resolvedIdentityFile = [System.IO.Path]::GetFullPath($IdentityFile)
    $sshArguments = @('-i', $resolvedIdentityFile, '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes')
    $scpArguments = @('-i', $resolvedIdentityFile, '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes')
}
$requiredRelativePaths = @(
    'docker-compose.yml',
    '.env.example',
    'tools',
    'vendor\data-analytics-plugin',
    'user_data\strategies',
    'user_data\reports',
    'user_data\dashboard',
    'user_data\config.json',
    'user_data\config-dual-futures-dry-run.json',
    'user_data\config-dual-futures-v2r-dry-run.json',
    'user_data\risk_policy.json'
)
$databaseNames = @(
    'tradesv3.dual-futures-dryrun.sqlite',
    'tradesv3.dual-futures-v2r-dryrun.sqlite'
)

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $Name"
    }
}

function Assert-CredentialFreeConfig([string]$Path) {
    $config = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($config.exchange) {
        foreach ($field in @('key', 'secret')) {
            $value = [string]$config.exchange.$field
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                throw "Refusing VPS bundle: exchange.$field is not empty in $Path"
            }
        }
    }
}

function Copy-RelativePath([string]$RelativePath, [string]$DestinationRoot) {
    $source = Join-Path $projectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Required deployment path is missing: $source"
    }
    $destination = Join-Path $DestinationRoot $RelativePath
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
}

foreach ($relativePath in $requiredRelativePaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relativePath))) {
        throw "Required deployment path is missing: $relativePath"
    }
}
foreach ($configName in @(
    'user_data\config.json',
    'user_data\config-dual-futures-dry-run.json',
    'user_data\config-dual-futures-v2r-dry-run.json'
)) {
    Assert-CredentialFreeConfig (Join-Path $projectRoot $configName)
}

$sourceFiles = foreach ($relativePath in $requiredRelativePaths) {
    $item = Get-Item -LiteralPath (Join-Path $projectRoot $relativePath)
    if ($item.PSIsContainer) {
        Get-ChildItem -LiteralPath $item.FullName -Recurse -File
    } else {
        $item
    }
}
$plan = [pscustomobject]@{
    server = $Server
    ssh_user = $SshUser
    identity_file = if ($resolvedIdentityFile) { $resolvedIdentityFile } else { 'ssh-default' }
    remote_directory = $RemoteDir
    static_files = @($sourceFiles).Count
    static_megabytes = [math]::Round((($sourceFiles | Measure-Object Length -Sum).Sum / 1MB), 2)
    exchange_credentials_empty = $true
    local_services_will_stop_only_after_remote_preflight = $true
    rollback_restarts_local_services = $true
}
if ($PlanOnly) {
    $plan | ConvertTo-Json
    exit 0
}

foreach ($commandName in @('docker', 'ssh', 'scp', 'tar')) {
    Assert-Command $commandName
}

Push-Location $projectRoot
$localStopped = $false
$remoteStarted = $false
$stagingDirectory = $null
$archivePath = $null
try {
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Local Docker Compose validation failed.' }

    ssh @sshArguments $target "test -d '$RemoteDir' && test -w '$RemoteDir' && docker compose version >/dev/null"
    if ($LASTEXITCODE -ne 0) { throw 'Remote VPS preflight failed.' }

    docker compose stop forward-watchdog forward-monitor daily-report-builder dashboard-builder dashboard-web freqtrade-v2r freqtrade
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the local services safely.' }
    $localStopped = $true

    $python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
    $backupOutput = & $python tools\backup_forward_state.py `
        --user-data-dir user_data `
        --backup-dir user_data\backups `
        --state user_data\reports\forward_backup_state.json `
        --interval-seconds 1 `
        --retention-days 35
    if ($LASTEXITCODE -ne 0) { throw 'Final cutover backup failed.' }
    $backupResult = $backupOutput | Select-Object -Last 1 | ConvertFrom-Json
    if ($backupResult.status -ne 'CREATED') { throw 'Final cutover backup was not created.' }
    $backupDirectory = [System.IO.Path]::GetFullPath([string]$backupResult.backup_directory)

    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $stagingDirectory = Join-Path $tempRoot ("trading-vps-stage-" + [guid]::NewGuid().ToString('N'))
    if ([System.IO.Path]::GetFullPath((Split-Path -Parent $stagingDirectory)) -ne $tempRoot.TrimEnd('\')) {
        throw 'Unsafe staging-directory resolution.'
    }
    New-Item -ItemType Directory -Path $stagingDirectory | Out-Null
    foreach ($relativePath in $requiredRelativePaths) {
        Copy-RelativePath $relativePath $stagingDirectory
    }
    if (Test-Path -LiteralPath (Join-Path $projectRoot '.env')) {
        Copy-RelativePath '.env' $stagingDirectory
    }
    foreach ($databaseName in $databaseNames) {
        $sourceDatabase = Join-Path $backupDirectory $databaseName
        $destinationDatabase = Join-Path $stagingDirectory (Join-Path 'user_data' $databaseName)
        Copy-Item -LiteralPath $sourceDatabase -Destination $destinationDatabase -Force
    }

    $archivePath = Join-Path $tempRoot ("trading-vps-bundle-" + [guid]::NewGuid().ToString('N') + '.tgz')
    tar -czf $archivePath -C $stagingDirectory .
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the deployment archive.' }

    $remoteArchive = "/tmp/trading-vps-bundle-$([guid]::NewGuid().ToString('N')).tgz"
    scp @scpArguments $archivePath "${target}:${remoteArchive}"
    if ($LASTEXITCODE -ne 0) { throw 'Secure copy to the VPS failed.' }

    ssh @sshArguments $target "tar -xzf '$remoteArchive' -C '$RemoteDir' && mkdir -p '$RemoteDir/user_data/data' '$RemoteDir/user_data/logs' '$RemoteDir/user_data/backups' && chmod 600 '$RemoteDir/user_data/config.json' '$RemoteDir/user_data/config-dual-futures-dry-run.json' '$RemoteDir/user_data/config-dual-futures-v2r-dry-run.json' '$RemoteDir/user_data/risk_policy.json' && if test -f '$RemoteDir/.env'; then chmod 600 '$RemoteDir/.env'; fi && cd '$RemoteDir' && docker compose config --quiet && docker compose up -d"
    if ($LASTEXITCODE -ne 0) { throw 'Remote Compose startup failed.' }
    $remoteStarted = $true

    Start-Sleep -Seconds 20
    $remoteServiceCounts = @(
        ssh @sshArguments $target "cd '$RemoteDir' && docker compose config --services | wc -l && docker compose ps --services --status running | wc -l"
    )
    if ($LASTEXITCODE -ne 0 -or $remoteServiceCounts.Count -ne 2) {
        throw 'Remote service-count query failed.'
    }
    $expectedServiceCount = [int]$remoteServiceCounts[0]
    $runningServiceCount = [int]$remoteServiceCounts[1]
    if ($runningServiceCount -ne $expectedServiceCount) {
        throw "Remote service-count check failed: $runningServiceCount/$expectedServiceCount running."
    }
    $remoteHealth = ssh @sshArguments $target "curl -fsS http://127.0.0.1:8090/health"
    if ($LASTEXITCODE -ne 0) { throw 'Remote dashboard health check failed.' }

    $localStopped = $false
    [pscustomobject]@{
        status = 'VPS_CUTOVER_COMPLETE'
        remote = $target
        remote_directory = $RemoteDir
        local_services = 'stopped'
        dashboard_tunnel = if ($resolvedIdentityFile) {
            "ssh -i `"$resolvedIdentityFile`" -N -L 8090:127.0.0.1:8090 $target"
        } else {
            "ssh -N -L 8090:127.0.0.1:8090 $target"
        }
        dashboard_url = 'http://127.0.0.1:8090'
    } | ConvertTo-Json
} catch {
    if ($remoteStarted) {
        ssh @sshArguments $target "cd '$RemoteDir' && docker compose stop" 2>$null
    }
    if ($localStopped) {
        docker compose up -d
    }
    throw
} finally {
    Pop-Location
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    foreach ($candidate in @($stagingDirectory, $archivePath)) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
        $resolved = [System.IO.Path]::GetFullPath([string]$candidate)
        if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean an unsafe temporary path: $resolved"
        }
        if (Test-Path -LiteralPath $resolved) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
