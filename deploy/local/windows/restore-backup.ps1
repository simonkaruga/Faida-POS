<#
Restore-Backup: puts a Faida backup (.fbk) back on this counter, e.g. on a new or repaired
PC after installing Faida with FaidaSetup.exe. On the USB stick, double-click
Restore-Backup.bat. Everything on this counter is replaced by the backup; a backup of
what is here now is taken first (C:\Faida\update-backups), so this can be undone.

    restore-backup.ps1 [-File <backup.fbk>]
#>
param([string]$File)
$ErrorActionPreference = "Continue"
$Base = "C:\Faida"
$env:FAIDA_ENV_FILE = "$Base\counter.env"
$Backend = "$Base\current\backend"
$Py = "$Backend\.venv\Scripts\python.exe"
function Say($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Done($Text, $Colour) {
  Write-Host "`n$Text" -ForegroundColor $Colour
  Read-Host "`nPress Enter to close this window" | Out-Null
  exit
}
# Faida's Python in the backend folder. Run-Py shows what it says and returns only its
# exit code; Read-Py returns what it says, with the exit code in $script:PyCode.
function Read-Py {
  Push-Location $Backend
  $lines = @(& $Py @args 2>&1 | ForEach-Object { "$_" })
  $script:PyCode = $LASTEXITCODE
  Pop-Location
  return $lines
}
function Run-Py {
  Read-Py @args | ForEach-Object { Write-Host $_ }
  return $script:PyCode
}
if (-not (Test-Path $Py)) { Done "Faida POS is not installed on this PC. Run FaidaSetup.exe first, then this again." Red }

Say "Which backup?"
if (-not $File) {
  # The newest backups: on the FAIDABACKUP drive, this stick, and the update backups.
  $Places = @("$PSScriptRoot", "$Base\update-backups")
  Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter } | ForEach-Object { $Places += "$($_.DriveLetter):\faida" }
  $Found = @($Places | Where-Object { Test-Path $_ } | ForEach-Object { Get-ChildItem $_ -Filter "faida-*.fbk" -ErrorAction SilentlyContinue } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 9)
  if (-not $Found) { Done "No backup (faida-....fbk) found on the FAIDABACKUP drive, this stick or C:\Faida\update-backups. Copy one next to this file and try again." Red }
  for ($i = 0; $i -lt $Found.Count; $i++) {
    Write-Host ("  {0}. {1}   {2}" -f ($i + 1), $Found[$i].LastWriteTime.ToString("ddd d MMM yyyy HH:mm"), $Found[$i].FullName)
  }
  $Pick = Read-Host "Type the number of the backup to restore (1 is the newest), or press Enter to stop"
  if (-not ($Pick -match '^\d$') -or [int]$Pick -lt 1 -or [int]$Pick -gt $Found.Count) { Done "Stopped. Nothing was changed." Yellow }
  $File = $Found[[int]$Pick - 1].FullName
}
if (-not (Test-Path $File)) { Done "Backup not found: $File" Red }
Write-Host "Restoring: $File"

Say "Backup passphrase"
Write-Host "The passphrase written down at installation (in the sealed envelope). Press Enter to use the one saved on this PC."
$Secure = Read-Host "Passphrase" -AsSecureString
$Typed = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure))
if ($Typed) { $env:FAIDA_BACKUP_PASSPHRASE = $Typed }  # wins over the settings file

Write-Host "`nEverything on this counter (orders, stock, staff, settings in Faida) will be replaced by this backup." -ForegroundColor Yellow
if ((Read-Host "Type RESTORE to go on, or press Enter to stop") -ne "RESTORE") { Done "Stopped. Nothing was changed." Yellow }

Say "Stopping the counter"
New-Item -ItemType File -Force "$Base\updating.flag" | Out-Null
Stop-ScheduledTask -TaskName "Faida counter" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 3

Say "Backing up what is here now (to undo this)"
$Saved = $env:FAIDA_BACKUP_PASSPHRASE
Remove-Item Env:FAIDA_BACKUP_PASSPHRASE -ErrorAction SilentlyContinue  # this PC's own passphrase for its own backup
if ((Run-Py -m app.backup create --to "$Base\update-backups" --keep 10) -ne 0) {
  Write-Host "Could not back up this counter first (see above); going on, since a new PC has nothing to keep." -ForegroundColor Yellow
}
if ($Saved) { $env:FAIDA_BACKUP_PASSPHRASE = $Saved }

Say "Restoring"
$Out = Read-Py -m app.backup restore --file $File
$Out | Where-Object { $_ -notmatch '^FAIDA_PIN_SECRET=' } | ForEach-Object { Write-Host $_ }
$Secret = $Out | Where-Object { $_ -match '^FAIDA_PIN_SECRET=' } | Select-Object -First 1
if (-not $Secret) {
  Remove-Item -Force "$Base\updating.flag" -ErrorAction SilentlyContinue
  Start-ScheduledTask -TaskName "Faida counter" -ErrorAction SilentlyContinue
  Done "The restore did not work (see above): wrong passphrase, or a damaged file. This counter was not changed. Support (call or WhatsApp): +254 797 033 513" Red
}
# Staff PINs only work with the secret they were made with: the backup's.
$Env = Get-Content "$Base\counter.env" | Where-Object { $_ -notmatch '^FAIDA_PIN_SECRET=' }
Set-Content -Path "$Base\counter.env" -Value (@($Env) + $Secret) -Encoding ASCII
Write-Host "Staff PINs: the backup's secret is now in counter.env."

Say "Bringing the database up to this version"
if ((Run-Py -m alembic upgrade head) -ne 0) { Done "Updating the restored database failed (see above). Support (call or WhatsApp): +254 797 033 513" Red }

Say "Starting the counter"
Remove-Item -Force "$Base\updating.flag" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "Faida counter"
$Version = (Get-Content "$Base\current\VERSION").Trim()
if ((Run-Py -m app.ops wait-healthy --version $Version --seconds 180) -ne 0) {
  Done "Restored, but the counter did not start. Run Faida-Check.bat and send the report to support: +254 797 033 513" Red
}
Done "Restored. Sign in with your usual PIN. Check today's orders and the stock, then restart the PC." Green
