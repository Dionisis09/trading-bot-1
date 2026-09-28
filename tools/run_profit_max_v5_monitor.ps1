$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$tool = Join-Path $PSScriptRoot 'monitor_profit_max_v5.py'
$database = Join-Path $workspace 'user_data\forward\profit-max-v5\trades.sqlite'
$output = Join-Path $workspace 'user_data\reports\profit_max_swing_cycle5\forward\forward_latest.json'
$statusPath = Join-Path $workspace 'user_data\reports\profit_max_swing_cycle5\forward\monitor_task_status.json'

try {
    & $python $tool --database $database --output $output --strategy ProfitMaxV5Asymmetric50 --started-at-utc '2026-08-16T12:51:31.3197031Z' --starting-wallet 1000
    if ($LASTEXITCODE -ne 0) { throw "monitor exit $LASTEXITCODE" }
    $status = @{ status = 'PASS'; checked_at_utc = (Get-Date).ToUniversalTime().ToString('o'); exit_code = 0 }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    exit 0
}
catch {
    $status = @{ status = 'FAIL'; checked_at_utc = (Get-Date).ToUniversalTime().ToString('o'); error = $_.Exception.Message }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    exit 1
}
