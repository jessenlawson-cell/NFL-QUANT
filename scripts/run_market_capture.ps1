param([Parameter(Mandatory=$true)][string]$PythonExe)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $repository 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$worker = Join-Path $PSScriptRoot 'capture_market_intelligence.py'
$log = Join-Path $logs 'market-intelligence.log'
Add-Content -LiteralPath $log -Encoding UTF8 -Value ((Get-Date).ToUniversalTime().ToString('o') + ' TICK')
$captureOutput = & $PythonExe $worker --execute 2>&1
$captureExit = $LASTEXITCODE
Add-Content -LiteralPath $log -Encoding UTF8 -Value ($captureOutput | Out-String)
if ($captureExit -ne 0) { exit $captureExit }
exit 0
