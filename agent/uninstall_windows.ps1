# DeviceWatch - Windows uninstaller
$Target = Join-Path $env:LOCALAPPDATA "DeviceWatch"
$Lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "DeviceWatch.lnk"

Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*device_agent.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Remove-Item $Lnk -Force -ErrorAction SilentlyContinue
$keep = Read-Host "Delete config too? (y/N)"
if ($keep -eq "y") { Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue }
else { Remove-Item (Join-Path $Target "device_agent.py") -Force -ErrorAction SilentlyContinue }
Write-Host "DeviceWatch removed." -ForegroundColor Green
Read-Host "Press Enter to close"
