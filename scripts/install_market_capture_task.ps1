param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$pythonExe = (& py -3.14 -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python 3.14 is required. No capture task installed.'
}
$worker = Join-Path $PSScriptRoot 'capture_market_intelligence.py'
$logDirectory = Join-Path $repository 'logs'
$runner = Join-Path $PSScriptRoot 'run_market_capture.ps1'
$taskName = 'NFL-QUANT-Free-Market-Capture'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -PythonExe "{1}"' -f $runner, $pythonExe
if ($DryRun) {
    & $pythonExe $worker
    if ($LASTEXITCODE -ne 0) { throw 'Offline worker check failed.' }
    [pscustomobject]@{TaskName=$taskName; Worker=$worker; IntervalMinutes=15; NetworkCalls=0}
    exit 0
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists. Inspect it before changing an active schedule.'
}
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repository
# No immediate run: first tick at least fifteen minutes after registration.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(15) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Capture-only NFL market intelligence. Free-tier 84 credits/week; preserve 80 credits/cycle. No model scoring or paid-call retries.'
Register-ScheduledTask -TaskName $taskName -InputObject $task | Select-Object TaskName,State
