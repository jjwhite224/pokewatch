$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
$script:dashboardUrl = "http://127.0.0.1:$($config.port)"
$script:seenPath = Join-Path $PSScriptRoot 'data\notification-seen.json'
$script:seen = [System.Collections.Generic.HashSet[string]]::new()
if (Test-Path -LiteralPath $script:seenPath) {
    foreach ($entry in (Get-Content -LiteralPath $script:seenPath -Raw | ConvertFrom-Json)) { [void]$script:seen.Add([string]$entry) }
} else {
    # Existing saved history is not a fresh desktop alert on first launch.
    try {
        $initial = Invoke-RestMethod -Uri "$script:dashboardUrl/api/state" -TimeoutSec 3
        foreach ($alert in $initial.alerts) { [void]$script:seen.Add([string]$alert.id) }
    } catch {}
}
$script:tray = New-Object System.Windows.Forms.NotifyIcon
$script:tray.Icon = [System.Drawing.SystemIcons]::Information
$script:tray.Text = 'PokeWatch - checking Pokemon releases'
$script:tray.Visible = $true
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$openItem = $menu.Items.Add('Open PokeWatch')
$openItem.add_Click({ Start-Process $script:dashboardUrl -WindowStyle Hidden })
$testItem = $menu.Items.Add('Test desktop notification')
$testItem.add_Click({ $script:tray.ShowBalloonTip(6000, 'PokeWatch is ready', 'New release and price-match alerts will appear here.', [System.Windows.Forms.ToolTipIcon]::Info) })
$exitItem = $menu.Items.Add('Exit desktop alerts')
$exitItem.add_Click({ [System.Windows.Forms.Application]::Exit() })
$script:tray.ContextMenuStrip = $menu
$script:tray.add_DoubleClick({ Start-Process $script:dashboardUrl -WindowStyle Hidden })
$script:tray.add_BalloonTipClicked({ Start-Process $script:dashboardUrl -WindowStyle Hidden })
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$script:busy = $false
$timer.add_Tick({
    if ($script:busy) { return }
    $script:busy = $true
    try {
        $state = Invoke-RestMethod -Uri "$script:dashboardUrl/api/state" -TimeoutSec 3
        $fresh = @($state.alerts | Where-Object { -not $script:seen.Contains([string]$_.id) })
        if ($fresh.Count -gt 0) {
            $alert = $fresh[-1]
            if ($fresh.Count -gt 1) {
                $title = "$($fresh.Count) new PokeWatch alerts"
                $body = 'New releases or price matches were found. Click to open your dashboard.'
            } elseif ($alert.kind -eq 'release') {
                $title = 'New Pokemon product announcement'
                $body = $alert.title
            } else {
                $title = 'Pokemon price match'
                $amount = ([decimal]$alert.price_cents / 100).ToString('F2', [Globalization.CultureInfo]::InvariantCulture)
                $body = "$($alert.title) - `$$amount at $($alert.store)"
            }
            $script:tray.ShowBalloonTip(8000, $title, $body.Substring(0, [Math]::Min(240, $body.Length)), [System.Windows.Forms.ToolTipIcon]::Info)
            foreach ($entry in $fresh) { [void]$script:seen.Add([string]$entry.id) }
        }
        # Keep only identifiers still in the bot's bounded alert history.
        $retained = @($state.alerts | Where-Object { $script:seen.Contains([string]$_.id) } | ForEach-Object { [string]$_.id })
        ConvertTo-Json -InputObject $retained | Set-Content -LiteralPath $script:seenPath -Encoding UTF8
        $script:tray.Text = 'PokeWatch - desktop alerts active'
    } catch {
        $script:tray.Text = 'PokeWatch - waiting for local bot'
    } finally { $script:busy = $false }
})
$timer.Start()
try { [System.Windows.Forms.Application]::Run() }
finally { $timer.Stop(); $timer.Dispose(); $script:tray.Visible = $false; $script:tray.Dispose() }
