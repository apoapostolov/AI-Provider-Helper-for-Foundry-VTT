# Win11 PowerShell launcher for the AI helper. Leave this window open while you play.
# If double-click is blocked: powershell -ExecutionPolicy Bypass -File .\run-helper.ps1
Set-Location -LiteralPath $PSScriptRoot

$exe = $null
$prefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $exe = "py"
    $prefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $exe = "python"
} else {
    Write-Error "Python 3 not found. Install it and tick Add python.exe to PATH."
    if ($Host.Name -eq "ConsoleHost") {
        Read-Host "Press Enter to close"
    }
    exit 1
}

$script = Join-Path $PSScriptRoot "run-helper.py"
& $exe @prefix $script @args
$code = $LASTEXITCODE
if ($code -ne 0 -and $Host.Name -eq "ConsoleHost") {
    Read-Host "Press Enter to close"
}
exit $code
