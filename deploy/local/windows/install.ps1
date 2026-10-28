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

Needs PostgreSQL 16 and Python 3.12. If missing, it installs them from -Bundle (the
folder FaidaSetup.exe unpacks, with their installers) or else with winget (internet).
Python packages come from backend\wheels when the release has them (no internet).
Safe to run again: existing settings, database and pictures are kept.
#>
param([string]$KioskUser = $env:USERNAME, [switch]$Lan, [switch]$Offline, [string]$Bundle = "")
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

function Plain($Secure) { [System.Net.NetworkCredential]::new("", $Secure).Password }
# A password typed twice (nothing shows while typing), saying clearly why it asks again.
function Ask-Secret($What, [switch]$Simple) {
  while ($true) {
    $a = Plain (Read-Host "$What (nothing shows while you type)" -AsSecureString)
    if (-not $a) { Write-Host "  It can't be empty. Try again." -ForegroundColor Yellow; continue }
    if ($Simple -and $a -notmatch '^[A-Za-z0-9]{8,}$') {
      Write-Host "  Use at least 8 letters and numbers only (no spaces or symbols). Try again." -ForegroundColor Yellow; continue
    }
    $b = Plain (Read-Host "  Confirm: type the same again" -AsSecureString)
    if ($a -ceq $b) { Write-Host "  OK." -ForegroundColor Green; return $a }
    Write-Host "  The two didn't match (check Caps Lock). Start again." -ForegroundColor Yellow
  }
}
function Bundled($Pattern) { if ($Bundle) { Get-ChildItem (Join-Path $Bundle $Pattern) -ErrorAction SilentlyContinue | Select-Object -First 1 } }
$HasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
function Find-Psql { Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1 }
function Has-Python312 { try { & py -3.12 --version *> $null; return $LASTEXITCODE -eq 0 } catch { return $false } }

Say "1/8 PostgreSQL and Python"
$PgSuperPass = $null  # set here when this installer installs PostgreSQL itself
$PgBin = Find-Psql
if (-not $PgBin) {
  if ($PgSetup = Bundled "postgresql-*.exe") {
    $PgSuperPass = Ask-Secret "Choose a password for PostgreSQL (the database), letters and numbers, 8 or more. Write it in the client file" -Simple
    Write-Host "Installing PostgreSQL 16 (a few minutes)..."
    Start-Process -Wait $PgSetup.FullName -ArgumentList "--mode", "unattended", "--unattendedmodeui", "minimal",
      "--superpassword", "`"$PgSuperPass`"", "--serverport", "5432", "--disable-components", "pgAdmin,stackbuilder"
  } elseif ($HasWinget) {
    Write-Host "Installing PostgreSQL 16 (choose a superuser password and write it down)..."
    winget install -e --id PostgreSQL.PostgreSQL.16 --accept-package-agreements --accept-source-agreements
  } else {
    throw "PostgreSQL 16 is not installed, and this PC has no winget to fetch it. Run FaidaSetup.exe (it carries PostgreSQL), or install PostgreSQL 16 by hand and run this again."
  }
  $PgBin = Find-Psql
  if (-not $PgBin) { throw "PostgreSQL did not install. Check C:\Program Files\PostgreSQL, then run this again." }
}
$PgBin = Split-Path $PgBin.FullName
if (-not (Has-Python312)) {
  if ($PySetup = Bundled "python-3.12*.exe") {
    Write-Host "Installing Python 3.12..."
    Start-Process -Wait $PySetup.FullName -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_launcher=1", "Include_test=0"
  } elseif ($HasWinget) {
    winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
  } else {
    throw "Python 3.12 is not installed, and this PC has no winget to fetch it. Run FaidaSetup.exe (it carries Python), or install Python 3.12 by hand and run this again."
  }
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Has-Python312)) { throw "Python 3.12 did not install. Run this again, or install it by hand." }
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
# Packages from the release's wheels folder (FaidaSetup.exe has one), else from the internet.
$PipFrom = if (Test-Path "$Target\backend\wheels") { @("--no-index", "--find-links", "$Target\backend\wheels") } else { @() }
& "$Target\backend\.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check @PipFrom -r "$Target\backend\requirements.txt"
if ($LASTEXITCODE) { throw "Installing the Python packages failed$(if (-not $PipFrom) { ' (is the internet on?)' })." }
if (Test-Path "$Base\current") { cmd /c rmdir "$Base\current" }
New-Item -ItemType Junction -Path "$Base\current" -Target $Target | Out-Null

Say "4/8 Database and settings ($EnvFile)"
if (-not (Test-Path $EnvFile)) {
  $env:PGPASSWORD = if ($PgSuperPass) { $PgSuperPass } else { Plain (Read-Host "PostgreSQL superuser (postgres) password" -AsSecureString) }
  $DbPass = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
  $exists = & "$PgBin\psql.exe" -U postgres -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='faida'"
  if ($exists -ne "1") { & "$PgBin\psql.exe" -U postgres -h localhost -qc "CREATE ROLE faida LOGIN PASSWORD '$DbPass'" }
  else { & "$PgBin\psql.exe" -U postgres -h localhost -qc "ALTER ROLE faida PASSWORD '$DbPass'" }
  $db = & "$PgBin\psql.exe" -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='faida'"
  if ($db -ne "1") { & "$PgBin\psql.exe" -U postgres -h localhost -qc "CREATE DATABASE faida OWNER faida" }
  Remove-Item Env:\PGPASSWORD

  # A bare name (POS80) means the Windows printer shared under that name.
  function Printer-Setting($Typed) { if ($Typed -and $Typed -notmatch ':') { "device:\\localhost\$Typed" } else { $Typed } }
  $CounterPrinter = Printer-Setting (Read-Host "Counter printer: press Enter for the USB printer shared as POS80")
  if (-not $CounterPrinter) { $CounterPrinter = "device:\\localhost\POS80" }
  $KitchenPrinter = Printer-Setting (Read-Host "Kitchen printer: press Enter if there is only one printer (or type network:<its IP>)")
  if (-not $KitchenPrinter) { $KitchenPrinter = $CounterPrinter }
  Write-Host "  Counter printer: $CounterPrinter    Kitchen printer: $KitchenPrinter"
  $PaperMm = Read-Host "Receipt paper width in mm, 80 or 58 [80]"
  if (-not $PaperMm) { $PaperMm = "80" }
  $a = Ask-Secret "Backup passphrase (write it down and keep it AWAY from the counter)"
  $CloudUrl = if ($Offline) { "" } else { Read-Host "Cloud address, e.g. https://faida.co.ke. Press Enter to link it later" }
  if ($CloudUrl -notmatch '^https?://') { $CloudUrl = "" }  # e.g. "later" typed: not linked
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
    if ($LASTEXITCODE) { throw "Setting up the business failed (see the message above). Run the setup again." }
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

Write-Host "Waiting for Faida to start. The first time can take a few minutes on a slow PC..."
Push-Location "$Base\current\backend"
& $Py -m app.ops wait-healthy --version $Version --seconds 300
$ok = -not $LASTEXITCODE
Pop-Location
if (-not $ok) {
  Write-Host "`nFaida didn't answer yet. Checking why, and trying to start it..." -ForegroundColor Yellow
  & "$Here\check.ps1" -ReportDir "$Base\setup-logs" -NoPause
  try { $ok = [bool](Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 5) } catch { $ok = $false }
  if (-not $ok) { throw "The counter didn't start. The check above says why; its report is in $Base\setup-logs." }
}

Say "8/8 Full-screen counter at login for $KioskUser"
$Kiosk = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Base\current\deploy\local\windows\kiosk.ps1`""
Register-ScheduledTask -TaskName "Faida kiosk" -Action $Kiosk -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $KioskUser) -User $KioskUser -Force | Out-Null
& "$Base\current\deploy\local\windows\shortcut.ps1"

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
