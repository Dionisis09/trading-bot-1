[CmdletBinding()]
param(
    [string]$Server = "195.238.122.36",
    [string]$PublicKeyPath = "$env:USERPROFILE\.ssh\trading_bot_vps_ed25519.pub"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
    throw "SSH public key not found: $PublicKeyPath"
}

$publicKey = (Get-Content -LiteralPath $PublicKeyPath -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519\s+\S+') {
    throw "The public key is not a valid Ed25519 public key."
}
if ($publicKey.Contains("'")) {
    throw "The public key contains an unsupported quote character."
}

$remoteCommand = @(
    "umask 077"
    "mkdir -p /root/.ssh"
    "touch /root/.ssh/authorized_keys"
    "grep -qxF '$publicKey' /root/.ssh/authorized_keys || printf '%s\n' '$publicKey' >> /root/.ssh/authorized_keys"
    "chmod 700 /root/.ssh"
    "chmod 600 /root/.ssh/authorized_keys"
    "echo SSH_KEY_INSTALLED"
) -join "; "

Write-Host ""
Write-Host "Enter the NEW root password for $Server when SSH asks for it." -ForegroundColor Cyan
Write-Host "The password will not be displayed while you type. Press Enter when done." -ForegroundColor Yellow
Write-Host ""

& ssh.exe `
    -o StrictHostKeyChecking=accept-new `
    -o PreferredAuthentications=password `
    -o PubkeyAuthentication=no `
    "root@$Server" `
    $remoteCommand

if ($LASTEXITCODE -ne 0) {
    Write-Host "SSH key installation failed (exit code $LASTEXITCODE)." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "SSH key installation completed." -ForegroundColor Green
Read-Host "Press Enter to close"
