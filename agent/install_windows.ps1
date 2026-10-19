# DeviceWatch - Windows installer (no admin needed)
# Right-click > "Run with PowerShell", or:  powershell -ExecutionPolicy Bypass -File install_windows.ps1
$ErrorActionPreference = "Stop"
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target  = Join-Path $env:LOCALAPPDATA "DeviceWatch"
$Startup = [Environment]::GetFolderPath("Startup")
$Lnk     = Join-Path $Startup "DeviceWatch.lnk"

Write-Host "`n=== DeviceWatch installer ===`n" -ForegroundColor Cyan

# 1. Find Python (python.org installer or Microsoft Store)
$py = $null
foreach ($cmd in @("py", "python")) {
    try {
        $exe = & $cmd -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $py = $exe.Trim(); break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3 not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and re-run." -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }
Write-Host "Using Python: $py"

# 2. Stop an old copy if running
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*device_agent.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 3. Copy files (keeps an existing config.json)
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item (Join-Path $Here "*.py") $Target -Force
Copy-Item (Join-Path $Here "config.example.json") $Target -Force
$cfg = Join-Path $Target "config.json"
if (-not (Test-Path $cfg)) {
    Push-Location $Target
    & $py device_agent.py --setup
    Pop-Location
} else {
    Write-Host "Keeping existing config: $cfg"
}

# 4. Start at logon (Startup folder shortcut, hidden, no console)
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($Lnk)
$s.TargetPath = $pyw
$s.Arguments = "`"$Target\device_agent.py`""
$s.WorkingDirectory = $Target
$s.WindowStyle = 7
$s.Description = "DeviceWatch agent"
$s.Save()

# 5. Test + start now
Push-Location $Target
& $py device_agent.py --test
Start-Process -FilePath $pyw -ArgumentList "`"$Target\device_agent.py`"" -WorkingDirectory $Target -WindowStyle Hidden
Pop-Location

Write-Host "`nInstalled to $Target and started." -ForegroundColor Green
Write-Host "Edit apps/settings:  notepad `"$cfg`"   (then re-run this installer to restart)"
Write-Host "Find a game's process name:  cd `"$Target`"; py device_agent.py --discover"
Write-Host "Can it be woken remotely?    cd `"$Target`"; py device_agent.py --wake-check"
Read-Host "`nPress Enter to close"
