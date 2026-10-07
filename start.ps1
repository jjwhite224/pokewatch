param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$dataPath = Join-Path $projectPath 'data'
$botPath = Join-Path $projectPath 'bot.py'
$notifyPath = Join-Path $projectPath 'notify.ps1'
$config = Get-Content -LiteralPath (Join-Path $projectPath 'config.json') -Raw | ConvertFrom-Json
$dashboardUrl = "http://127.0.0.1:$($config.port)"
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$pythonCommand = Get-Command python.exe -ErrorAction Stop
$running = $false
try {
    $current = Invoke-RestMethod -Uri "$dashboardUrl/api/state" -TimeoutSec 2
    $running = ($null -ne $current.token -and $null -ne $current.products)
} catch {}
$pidPath = Join-Path $dataPath 'processes.json'
$processes = @{ bot = $null; notifier = $null }
if (Test-Path -LiteralPath $pidPath) {
    $saved = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json
    $processes.bot = $saved.bot
    $processes.notifier = $saved.notifier
}
if (-not $running) {
    $bot = Start-Process -FilePath $pythonCommand.Source -ArgumentList @('-u', "`"$botPath`"") -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataPath 'bot-output.log') -RedirectStandardError (Join-Path $dataPath 'bot-errors.log') -PassThru
    $processes.bot = $bot.Id
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $current = Invoke-RestMethod -Uri "$dashboardUrl/api/state" -TimeoutSec 2
            if ($null -ne $current.token) { $running = $true; break }
        } catch {}
        if ($bot.HasExited) { break }
    }
    if (-not $running) { throw 'The tracker could not start. See data\bot-errors.log for details.' }
}
$notifierRunning = $false
if ($processes.notifier) {
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($processes.notifier)" -ErrorAction SilentlyContinue
    $notifierRunning = ($existing -and $existing.CommandLine -like "*$notifyPath*")
}
if (-not $notifierRunning) {
    $notificationProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', "`"$notifyPath`"") -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataPath 'notifications-output.log') -RedirectStandardError (Join-Path $dataPath 'notifications-errors.log') -PassThru
    $processes.notifier = $notificationProcess.Id
}
$processes | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding UTF8
if (-not $NoBrowser) { Start-Process $dashboardUrl -WindowStyle Hidden }
Write-Output "PokeWatch is running at $dashboardUrl. Checks repeat every $([int]($config.interval_seconds / 60)) minutes."
Write-Output 'A PokeWatch tray icon provides desktop alerts. Use Stop PokeWatch.cmd to stop both processes.'
