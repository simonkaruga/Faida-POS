<#
Install Faida on a Windows 10/11 counter PC. From an unpacked release, in PowerShell
"Run as administrator":

    powershell -ExecutionPolicy Bypass -File deploy\local\windows\install.ps1 [-KioskUser counter] [-Lan] [-Offline]

-KioskUser  the Windows account that logs in automatically and shows the counter
            full-screen (default: the account running this)
-Lan        also serve the screens on the local network (Android touch screen,
            second terminal). Without it only this PC can open them.
-Offline    counter only: the client keeps everything at the bar. No cloud link,
            no owner phone view; nothing is queued or sent.

Needs PostgreSQL 16 and Python 3.12; it installs them with winget if missing.
Safe to run again: existing settings, database and pictures are kept.
#>
param([string]$KioskUser = $env:USERNAME, [switch]$Lan, [switch]$Offline)
$ErrorActionPreference = "Stop"

$Release = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$Version = (Get-Content "$Release\VERSION").Trim()
$Base = "C:\Faida"
$EnvFile = "$Base\counter.env"
$State = "$Base\data"
$Here = "$Release\deploy\local\windows"
function Say($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run PowerShell as administrator."
}

Say "1/8 PostgreSQL and Python"
$PgBin = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $PgBin) {
  Write-Host "Installing PostgreSQL 16 (choose a superuser password and write it down)..."
  winget install -e --id PostgreSQL.PostgreSQL.16 --accept-package-agreements --accept-source-agreements
  $PgBin = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" | Sort-Object FullName -Descending | Select-Object -First 1
}
$PgBin = Split-Path $PgBin.FullName
$Python = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $Python) {
  winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine")
}

Say "2/8 Folders"
New-Item -ItemType Directory -Force "$Base\releases", "$State\images", "$State\logs", "$Base\update-backups" | Out-Null

Say "3/8 Faida $Version"
$Target = "$Base\releases\$Version"
if ($Release -ne $Target) {
  if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
  Copy-Item -Recurse $Release $Target
}
& py -3.12 -m venv "$Target\backend\.venv"
& "$Target\backend\.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "$Target\backend\requirements.txt"
if ($LASTEXITCODE) { throw "Installing the Python packages failed (is the internet on?)." }
if (Test-Path "$Base\current") { cmd /c rmdir "$Base\current" }
New-Item -ItemType Junction -Path "$Base\current" -Target $Target | Out-Null

Say "4/8 Database and settings ($EnvFile)"
if (-not (Test-Path $EnvFile)) {
  $Super = Read-Host "PostgreSQL superuser (postgres) password" -AsSecureString
  $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Super))
  $DbPass = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
  $exists = & "$PgBin\psql.exe" -U postgres -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='faida'"
  if ($exists -ne "1") { & "$PgBin\psql.exe" -U postgres -h localhost -qc "CREATE ROLE faida LOGIN PASSWORD '$DbPass'" }
  else { & "$PgBin\psql.exe" -U postgres -h localhost -qc "ALTER ROLE faida PASSWORD '$DbPass'" }
  $db = & "$PgBin\psql.exe" -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='faida'"
  if ($db -ne "1") { & "$PgBin\psql.exe" -U postgres -h localhost -qc "CREATE DATABASE faida OWNER faida" }
  Remove-Item Env:\PGPASSWORD

  $CounterPrinter = Read-Host "Counter printer [device:\\localhost\POS80  (share the USB printer as POS80)]"
  if (-not $CounterPrinter) { $CounterPrinter = "device:\\localhost\POS80" }
  $KitchenPrinter = Read-Host "Kitchen printer, e.g. network:192.168.1.50 [same as counter]"
  if (-not $KitchenPrinter) { $KitchenPrinter = $CounterPrinter }
  $PaperMm = Read-Host "Receipt paper width in mm, 80 or 58 [80]"
  if (-not $PaperMm) { $PaperMm = "80" }
  do {
    $p1 = Read-Host "Backup passphrase (write it down and keep it AWAY from the counter)" -AsSecureString
    $p2 = Read-Host "Type it again" -AsSecureString
    $a = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p1))
    $b = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p2))
  } while (-not $a -or $a -ne $b)
  $CloudUrl = if ($Offline) { "" } else { Read-Host "Cloud URL, e.g. https://faida.co.ke (empty: link later)" }
  $CloudToken = ""
  if ($CloudUrl) { $CloudToken = Read-Host "Counter token from 'register-device' on the cloud" }
  $PinSecret = & "$Target\backend\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))"
  @"
FAIDA_MODE=local
FAIDA_DATABASE_URL=postgresql+psycopg://faida:$DbPass@localhost:5432/faida
# Protects staff PINs. It is inside every backup; never share it.
FAIDA_PIN_SECRET=$PinSecret
FAIDA_TIMEZONE=Africa/Nairobi
FAIDA_STATE_DIR=$State
FAIDA_STATIC_DIR=$Base\current\frontend\dist
FAIDA_PG_BIN=$PgBin
FAIDA_COUNTER_PRINTER=$CounterPrinter
FAIDA_KITCHEN_PRINTER=$KitchenPrinter
# Thermal paper width in mm: 80 or 58. Change one if the printers differ.
FAIDA_COUNTER_PAPER_MM=$PaperMm
FAIDA_KITCHEN_PAPER_MM=$PaperMm
FAIDA_BACKUP_PASSPHRASE=$a
# true: counter only, nothing leaves the bar (no cloud, no phone view).
FAIDA_OFFLINE_ONLY=$(if ($Offline) { "true" } else { "false" })
FAIDA_CLOUD_URL=$CloudUrl
FAIDA_CLOUD_TOKEN=$CloudToken
# Email the daily closing (optional). Gmail: smtp.gmail.com, 587, an app password.
FAIDA_SMTP_HOST=
FAIDA_SMTP_PORT=587
FAIDA_SMTP_USER=
FAIDA_SMTP_PASSWORD=
FAIDA_SMTP_FROM=
"@ | Set-Content -Encoding ASCII $EnvFile
  # Only administrators and the system account may read it.
  icacls $EnvFile /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" | Out-Null
} else {
  Write-Host "Keeping the existing settings."
  if ($Offline) {
    $lines = @(Get-Content $EnvFile | Where-Object { $_ -notmatch '^FAIDA_OFFLINE_ONLY=' }) + "FAIDA_OFFLINE_ONLY=true"
    Set-Content -Encoding ASCII $EnvFile $lines
    Write-Host "Counter only: the cloud link is switched off."
  }
}
$ListenHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
Set-Content -Encoding ASCII "$Base\listen.txt" $ListenHost
if ($Lan) { New-NetFirewallRule -DisplayName "Faida counter" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow -ErrorAction SilentlyContinue | Out-Null }

$env:FAIDA_ENV_FILE = $EnvFile
$Py = "$Base\current\backend\.venv\Scripts\python.exe"
Push-Location "$Base\current\backend"
try {
  & $Py -m alembic upgrade head
  if ($LASTEXITCODE) { throw "Database migration failed." }

  Say "5/8 Business, owner and menu"
  $ErrorActionPreference = "Continue"  # its message goes to stderr
  & $Py -m app.ops set-up 2>$null
  $NotSetUp = $LASTEXITCODE
  $ErrorActionPreference = "Stop"
  if ($NotSetUp) {
    $Name = Read-Host "Business name (as on receipts)"
    $Owner = Read-Host "Owner's name"
    & $Py -m app.cli init-business --name $Name --owner $Owner
    $Menu = Read-Host "Menu file to load (JSON, empty to enter it on the counter later)"
    if ($Menu) { & $Py -m app.cli load-menu (Resolve-Path $Menu).Path }
  } else { Write-Host "Business already set up." }
} finally { Pop-Location }

Say "6/8 Start at boot"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Base\current\deploy\local\windows\start-counter.ps1`""
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Faida counter" -Action $Action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $Settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName "Faida counter"

Say "7/8 Nightly backup to the USB drive (04:30, or at start-up if missed)"
$Backup = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Base\current\deploy\local\windows\backup.ps1`""
$BSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Faida backup" -Action $Backup -Trigger (New-ScheduledTaskTrigger -Daily -At 4:30am) -Settings $BSettings -User "SYSTEM" -RunLevel Highest -Force | Out-Null

Push-Location "$Base\current\backend"
& $Py -m app.ops wait-healthy --version $Version --seconds 90
$ok = -not $LASTEXITCODE
Pop-Location
if (-not $ok) { throw "The counter didn't start. See $State\logs\counter.log" }

Say "8/8 Full-screen counter at login for $KioskUser"
$Kiosk = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Base\current\deploy\local\windows\kiosk.ps1`""
Register-ScheduledTask -TaskName "Faida kiosk" -Action $Kiosk -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $KioskUser) -User $KioskUser -Force | Out-Null

Write-Host @"

Faida $Version is installed and running: http://localhost:8000
  Settings:  $EnvFile   (printers, cloud link or counter only, email)
  Pictures, logs and backup status: $State
  Backups:   every night at 04:30 to a USB drive named FAIDABACKUP
             (rename the drive to FAIDABACKUP; test now: Start-ScheduledTask "Faida backup")
  Update:    $Base\current\deploy\local\windows\update.ps1 -Archive faida-<version>.zip
Turn on automatic sign-in for $KioskUser (netplwiz), then follow docs\install-checklist.md from step 3.
"@
if ($Offline) { Write-Host "Counter only: skip the cloud step (7) of the checklist." }
