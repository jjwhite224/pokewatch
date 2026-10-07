$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $PSScriptRoot 'data\processes.json'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'No managed PokeWatch processes were recorded.'; exit 0 }
$saved = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json
foreach ($entry in @(@{ Id = $saved.bot; File = 'bot.py' }, @{ Id = $saved.notifier; File = 'notify.ps1' })) {
    if (-not $entry.Id) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.Id)" -ErrorAction SilentlyContinue
    $expected = Join-Path $PSScriptRoot $entry.File
    if ($process -and $process.CommandLine -like "*$expected*") {
        Stop-Process -Id $entry.Id -ErrorAction SilentlyContinue
        Write-Output "Stopped PokeWatch $($entry.File)."
    }
}
Write-Output 'Your saved products, references, and alert history have been retained.'
