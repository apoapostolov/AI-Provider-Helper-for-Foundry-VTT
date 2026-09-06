# Win11 companion. Leave this window open while you play.
# If double-click is blocked:
#   powershell -ExecutionPolicy Bypass -File ".\AI Helper.ps1"
param(
    [switch]$Hosted
)
Set-Location -LiteralPath $PSScriptRoot

$embed = Join-Path $PSScriptRoot "python\python.exe"
$repoVenv = Join-Path $PSScriptRoot "..\backend\.venv\Scripts\python.exe"
$exe = $null
if (Test-Path -LiteralPath $embed) {
    $exe = $embed
} elseif (Test-Path -LiteralPath $repoVenv) {
    $exe = $repoVenv
}

if (-not $exe) {
    Write-Error "This folder has no Python runtime. Download AI-Helper-windows.zip from GitHub Releases."
    if ($Host.Name -eq "ConsoleHost") {
        Read-Host "Press Enter to close"
    }
    exit 1
}

$launch = Join-Path $PSScriptRoot "launch.py"
$pass = @()
if ($Hosted) {
    $pass += "--hosted"
}
foreach ($arg in $args) {
    $pass += $arg
}

& $exe $launch @pass
$code = $LASTEXITCODE
if ($code -ne 0 -and $Host.Name -eq "ConsoleHost") {
    Read-Host "Press Enter to close"
}
exit $code
