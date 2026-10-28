<#
Run by FaidaSetup.exe from the folder it unpacks: installs Faida on a new counter, or
updates an existing one to this version (backup first, rolls back by itself on failure).

    setup.ps1 [-Offline] [-Bundle <folder with the PostgreSQL and Python installers>]

The window stays open at the end so the technician can read what happened; everything is
also written to C:\Faida\setup-logs.
#>
param([switch]$Offline, [string]$Bundle = "")
$ErrorActionPreference = "Stop"
$Release = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$Version = (Get-Content "$Release\VERSION").Trim()
$Base = "C:\Faida"
New-Item -ItemType Directory -Force "$Base\setup-logs" | Out-Null
$Log = "$Base\setup-logs\setup-$Version-$(Get-Date -Format yyyyMMdd-HHmmss).log"
Start-Transcript -Path $Log | Out-Null
$Host.UI.RawUI.WindowTitle = "Faida POS $Version setup"

$ok = $true
try {
  # Faida stamps every sale with this PC's clock; a clock behind the day this setup was
  # built is certainly wrong.
  if (Test-Path "$Release\BUILT") {
    $Built = [datetime]::ParseExact((Get-Content "$Release\BUILT").Trim(), "yyyy-MM-dd", $null)
    if ((Get-Date) -lt $Built) {
      $Says = (Get-Date).ToString("d MMMM yyyy")
      $Msg = "This PC's date is wrong: it says $Says. Faida records every sale with it.`n" +
             "Fix it first: Settings > Time & Language > Date & time. Turn off 'Set time automatically' if there is no internet, " +
             "click Change, set today's date and time, and the time zone (UTC+03:00) Nairobi. Then run this setup again."
      throw $Msg
    }
  }
  $Installed = (Test-Path "$Base\counter.env") -and (Test-Path "$Base\current\VERSION")
  if (-not $Installed) {
    Write-Host "Installing Faida POS $Version on this PC.`n" -ForegroundColor Cyan
    & "$PSScriptRoot\install.ps1" -Offline:$Offline -Bundle $Bundle
  } else {
    $Current = (Get-Content "$Base\current\VERSION").Trim()
    if ($Current -eq $Version) {
      try { $Health = Invoke-RestMethod "http://localhost:8000/api/health" -TimeoutSec 5 } catch { $Health = $null }
      $Finished = Get-ScheduledTask -TaskName "Faida kiosk" -ErrorAction SilentlyContinue  # the installer's last step
      if ($Health -and $Health.set_up -and $Health.version -eq $Version -and $Finished) {
        Write-Host "Faida POS $Version is already installed and running here." -ForegroundColor Green
        & "$Base\current\deploy\local\windows\shortcut.ps1"
      } else {
        # An earlier install stopped part-way: stop what is running and finish it.
        Write-Host "Finishing the installation of Faida POS $Version (settings already saved are kept).`n" -ForegroundColor Cyan
        $Env = Get-Content "$Base\counter.env"
        if (-not $Offline -and -not ($Env -match '^FAIDA_OFFLINE_ONLY=true') -and -not ($Env -match '^FAIDA_CLOUD_URL=https?://')) {
          $Answer = Read-Host "Counter only: nothing leaves the bar, no internet needed (no phone view)? Press Enter for YES, or type N"
          if ($Answer -notmatch '^[nN]') { $Offline = [switch]$true }
        }
        Stop-ScheduledTask -TaskName "Faida counter" -ErrorAction SilentlyContinue
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
          ForEach-Object { taskkill /T /F /PID $_.ProcessId 2>$null | Out-Null }
        Start-Sleep 2
        & "$PSScriptRoot\install.ps1" -Offline:$Offline -Bundle $Bundle
      }
    } else {
      Write-Host "Updating Faida POS $Current -> $Version. Do this after closing, with every shift ended.`n" -ForegroundColor Cyan
      & "$PSScriptRoot\update.ps1" -Release $Release
      if ($LASTEXITCODE) { $ok = $false }
      else { & "$Base\current\deploy\local\windows\shortcut.ps1" }  # counters installed before the icon existed
    }
  }
} catch {
  $ok = $false
  Write-Host "`n$_" -ForegroundColor Red
}

if ($ok) {
  Write-Host "`nDone." -ForegroundColor Green
} else {
  Write-Host "`nSetup did not finish. Fix the problem above and run FaidaSetup.exe again; settings already saved are kept." -ForegroundColor Red
  Write-Host "Support (call or WhatsApp): +254 797 033 513" -ForegroundColor Yellow
}
Write-Host "Log: $Log"
Stop-Transcript | Out-Null
Read-Host "`nPress Enter to close this window" | Out-Null
exit $(if ($ok) { 0 } else { 1 })
