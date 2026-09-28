$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$tool = Join-Path $PSScriptRoot 'backup_profit_max_v5.py'
$database = Join-Path $workspace 'user_data\forward\profit-max-v5\trades.sqlite'
$outputDir = Join-Path $workspace 'user_data\backups\profit-max-v5'
$statusPath = Join-Path $workspace 'user_data\reports\profit_max_swing_cycle5\forward\backup_task_status.json'

try {
    & $python $tool --database $database --output-dir $outputDir --retention-days 35
    if ($LASTEXITCODE -ne 0) { throw "backup exit $LASTEXITCODE" }
    $status = @{ status = 'PASS'; checked_at_utc = (Get-Date).ToUniversalTime().ToString('o'); exit_code = 0 }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    exit 0
}
catch {
    $status = @{ status = 'FAIL'; checked_at_utc = (Get-Date).ToUniversalTime().ToString('o'); error = $_.Exception.Message }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    exit 1
}
