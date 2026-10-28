<#
Update a Windows counter, after closing hours only (masterplan 7.1). As administrator:

    powershell -ExecutionPolicy Bypass -File C:\Faida\current\deploy\local\windows\update.ps1 -Archive faida-0.3.1.zip [-Force]

or with -Release <folder> for an unpacked release (FaidaSetup.exe does this).

backup -> install the new version beside the old -> migrate -> health check.
If anything fails it rolls back by itself: the migrations are undone (or, failing that,
the backup taken a minute earlier is restored) and the old version is started again.
-Force updates even with shifts or bills still open.
#>
param([string]$Archive, [string]$Release, [switch]$Force)
$ErrorActionPreference = "Stop"
if (-not $Archive -and -not $Release) { throw "Give -Archive faida-<version>.zip or -Release <folder>." }
$Base = "C:\Faida"
$env:FAIDA_ENV_FILE = "$Base\counter.env"
$Old = (Get-Item "$Base\current").Target | Select-Object -First 1
if (-not $Old) { $Old = (Resolve-Path "$Base\current").Path }
$OldVersion = (Get-Content "$Old\VERSION").Trim()
$Log = "$Base\data\logs\update-$(Get-Date -Format yyyyMMdd-HHmmss).log"
Start-Transcript -Path $Log | Out-Null
function Say($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Py($Dir) {
  # Python logs to stderr; in Windows PowerShell that must not count as a failure.
  $ErrorActionPreference = "Continue"
  Push-Location "$Dir\backend"
  try { & "$Dir\backend\.venv\Scripts\python.exe" @args; if ($LASTEXITCODE) { throw "python $($args -join ' ') failed" } }
  finally { Pop-Location }
}
function Stop-Counter {
  New-Item -ItemType File -Force "$Base\updating.flag" | Out-Null
  Stop-ScheduledTask -TaskName "Faida counter" -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
    ForEach-Object { taskkill /T /F /PID $_.ProcessId 2>$null | Out-Null }
  Start-Sleep 2
}
function Start-Counter {
  Remove-Item -Force "$Base\updating.flag" -ErrorAction SilentlyContinue
  Start-ScheduledTask -TaskName "Faida counter"
}
function Set-Current($Dir) {
  cmd /c rmdir "$Base\current"
  New-Item -ItemType Junction -Path "$Base\current" -Target $Dir | Out-Null
}

try {
  Say "Checking the counter is closed"
  if (-not $Force) { Py $Old -m app.ops busy }

  Say "Unpacking"
  if ($Release) {
    $Src = (Resolve-Path $Release).Path
  } else {
    $Work = Join-Path $env:TEMP "faida-update-$(Get-Random)"
    Expand-Archive -Path $Archive -DestinationPath $Work
    $Src = (Get-ChildItem $Work -Directory | Select-Object -First 1).FullName
  }
  $NewVersion = (Get-Content "$Src\VERSION").Trim()
  $New = "$Base\releases\$NewVersion"
  if ($New -eq $Old) { throw "Version $NewVersion is already running." }
  if (Test-Path $New) { Remove-Item -Recurse -Force $New }
  if ($Release) { Copy-Item -Recurse $Src $New } else { Move-Item $Src $New }
  & py -3.12 -m venv "$New\backend\.venv"
  $PipFrom = if (Test-Path "$New\backend\wheels") { @("--no-index", "--find-links", "$New\backend\wheels") } else { @() }
  & "$New\backend\.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check @PipFrom -r "$New\backend\requirements.txt"
  if ($LASTEXITCODE) { throw "Installing the Python packages failed$(if (-not $PipFrom) { ' (is the internet on?)' }). Nothing was changed." }

  Say "Backup before updating"
  $out = Py $Old -m app.backup create --to "$Base\update-backups" --keep 5 2>&1 | Out-String
  $Backup = ([regex]::Match($out, "Backup written: (.+)")).Groups[1].Value.Trim()
  if (-not $Backup) { throw "The backup failed; nothing was changed. $out" }
  $OldRevision = (Py $Old -m app.ops revision | Out-String).Trim()
} catch {
  Write-Host $_ -ForegroundColor Red
  Stop-Transcript | Out-Null
  exit 1
}

try {
  Say "Switching to $NewVersion"
  Stop-Counter
  Set-Current $New
  Py $New -m alembic upgrade head
  Start-Counter
  Py $New -m app.ops wait-healthy --version $NewVersion --seconds 300
} catch {
  Write-Host "`nUpdate failed: $_`nRolling back to $OldVersion" -ForegroundColor Yellow
  Stop-Counter
  try { Py $New -m alembic downgrade $OldRevision }
  catch {
    Write-Host "Undoing the migrations failed; restoring the backup taken before the update."
    Py $Old -m app.backup restore --file $Backup | Out-Null
  }
  Set-Current $Old
  Start-Counter
  try {
    Py $Old -m app.ops wait-healthy --version $OldVersion --seconds 90
    Write-Host "Rolled back. $OldVersion is running again; nothing was lost. Log: $Log" -ForegroundColor Yellow
  } catch {
    Write-Host "ROLLBACK DID NOT COME BACK HEALTHY. Call Avinaya. Backup: $Backup  Log: $Log" -ForegroundColor Red
  }
  Stop-Transcript | Out-Null
  exit 1
}

# Keep the three newest releases.
Get-ChildItem "$Base\releases" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 |
  Where-Object { $_.FullName -ne $New -and $_.FullName -ne $Old } | Remove-Item -Recurse -Force
Say "Updated $OldVersion -> $NewVersion. Log: $Log"
Stop-Transcript | Out-Null
