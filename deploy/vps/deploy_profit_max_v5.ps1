[CmdletBinding()]
param(
    [string]$Server = '195.238.122.36',
    [string]$SshUser = 'trader',
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$IdentityFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$resolvedIdentity = [System.IO.Path]::GetFullPath($IdentityFile)
$target = "${SshUser}@${Server}"
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
$stage = Join-Path $tempRoot ('profit-max-v5-stage-' + [guid]::NewGuid().ToString('N'))
$archive = Join-Path $tempRoot ('profit-max-v5-' + [guid]::NewGuid().ToString('N') + '.tgz')
$remoteToken = [guid]::NewGuid().ToString('N')
$remoteArchive = "/tmp/profit-max-v5-$remoteToken.tgz"
$remoteInstaller = "/tmp/install-profit-max-v5-$remoteToken.sh"

$sourceMap = [ordered]@{
    'deploy\vps\docker-compose.profit-max-v5.yml' = 'docker-compose.profit-max-v5.yml'
    'tools\check_freqtrade_process.py' = 'tools_profit_max_v5\check_freqtrade_process.py'
    'tools\monitor_profit_max_v5.py' = 'tools_profit_max_v5\monitor_profit_max_v5.py'
    'tools\backup_profit_max_v5.py' = 'tools_profit_max_v5\backup_profit_max_v5.py'
    'user_data\strategies\ProfitMaxSwingV5.py' = 'user_data\strategies_profit_max_v5\ProfitMaxSwingV5.py'
    'user_data\strategies\DualTrendFuturesRisk.py' = 'user_data\strategies_profit_max_v5\DualTrendFuturesRisk.py'
    'user_data\strategies\DualTrendFuturesV1.py' = 'user_data\strategies_profit_max_v5\DualTrendFuturesV1.py'
    'user_data\strategies\DualTrendFuturesV2.py' = 'user_data\strategies_profit_max_v5\DualTrendFuturesV2.py'
    'user_data\strategies\ProfessionalRisk.py' = 'user_data\strategies_profit_max_v5\ProfessionalRisk.py'
    'user_data\config-profit-max-v5-dry-run.json' = 'user_data\config-profit-max-v5-dry-run.json'
    'user_data\risk_policy.json' = 'user_data\risk_policy-profit-max-v5.json'
}

foreach ($relativeSource in $sourceMap.Keys) {
    $source = Join-Path $projectRoot $relativeSource
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required deployment file is missing: $relativeSource"
    }
}

$config = Get-Content -Raw (Join-Path $projectRoot 'user_data\config-profit-max-v5-dry-run.json') | ConvertFrom-Json
if (-not $config.dry_run -or $config.trading_mode -ne 'futures' -or $config.margin_mode -ne 'isolated') {
    throw 'The deployment config does not satisfy the dry-run futures safety contract.'
}
foreach ($field in @('key', 'secret')) {
    if (-not [string]::IsNullOrWhiteSpace([string]$config.exchange.$field)) {
        throw "Refusing nonempty exchange.$field in the deployment config."
    }
}

try {
    New-Item -ItemType Directory -Path $stage | Out-Null
    foreach ($entry in $sourceMap.GetEnumerator()) {
        $source = Join-Path $projectRoot $entry.Key
        $destination = Join-Path $stage $entry.Value
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }

    & tar -czf $archive -C $stage .
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the scoped deployment archive.'
    }
    $archiveHash = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()

    & scp -i $resolvedIdentity -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
        $archive "${target}:${remoteArchive}"
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not upload the scoped deployment archive.'
    }
    & scp -i $resolvedIdentity -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
        (Join-Path $PSScriptRoot 'install_profit_max_v5.sh') "${target}:${remoteInstaller}"
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not upload the VPS installer.'
    }

    & ssh -i $resolvedIdentity -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
        $target "bash '$remoteInstaller' '$remoteArchive' '$archiveHash'"
    if ($LASTEXITCODE -ne 0) {
        throw "Scoped VPS deployment failed with exit code $LASTEXITCODE."
    }
} finally {
    foreach ($candidate in @($stage, $archive)) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) {
            continue
        }
        $resolved = [System.IO.Path]::GetFullPath([string]$candidate)
        if (-not $resolved.StartsWith($tempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing unsafe local cleanup path: $resolved"
        }
        if (Test-Path -LiteralPath $resolved) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
