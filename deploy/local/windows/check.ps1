<#
Faida-Check: finds out why the counter isn't working, tries to start Faida, and writes a
report (secrets hidden). On the USB stick, double-click Faida-Check.bat; install.ps1 also
runs it when the counter doesn't start.

    check.ps1 [-ReportDir <folder>] [-NoPause]
#>
param([string]$ReportDir = $PSScriptRoot, [switch]$NoPause)
$ErrorActionPreference = "Continue"
$Base = "C:\Faida"
$Report = Join-Path $ReportDir "faida-report-$env:COMPUTERNAME-$(Get-Date -Format yyyyMMdd-HHmmss).txt"
try { Start-Transcript -Path $Report | Out-Null } catch { $Report = $null }
function Head($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Health { try { Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 5 } catch { $null } }
function Stop-Faida {
  Stop-ScheduledTask -TaskName "Faida counter" -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
}

Head "This PC"
$os = Get-CimInstance Win32_OperatingSystem
"{0} {1}, build {2}, checked {3}" -f $os.Caption, $os.OSArchitecture, $os.BuildNumber, (Get-Date)
"Memory {0:N1} GB, free on C: {1:N1} GB" -f ($os.TotalVisibleMemorySize / 1MB), ((Get-PSDrive C).Free / 1GB)

Head "Faida files"
foreach ($p in "$Base\counter.env", "$Base\current\VERSION", "$Base\current\backend\.venv\Scripts\python.exe") {
  "{0}  {1}" -f $(if (Test-Path $p) { "OK     " } else { "MISSING" }), $p
}
if (Test-Path "$Base\current\VERSION") { "Version " + (Get-Content "$Base\current\VERSION") }

Head "Settings (secrets hidden)"
if (Test-Path "$Base\counter.env") {
  Get-Content "$Base\counter.env" | Where-Object { $_ -match '^FAIDA_' } | ForEach-Object {
    if ($_ -match '^(FAIDA_\w*(SECRET|PASSPHRASE|PASSWORD|TOKEN)\w*)=.+$') { "$($Matches[1])=<hidden>" }
    elseif ($_ -match '^(FAIDA_DATABASE_URL=.*//[^:]+):[^@]*(@.*)$') { "$($Matches[1]):<hidden>$($Matches[2])" }
    else { $_ }
  }
}

Head "Database (PostgreSQL service)"
$pg = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
if ($pg) { $pg | ForEach-Object { "{0}: {1} ({2})" -f $_.Name, $_.Status, $_.StartType } } else { "No PostgreSQL service found." }

Head "Faida tasks"
foreach ($t in "Faida counter", "Faida kiosk", "Faida backup") {
  $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  if (-not $task) { "${t}: MISSING"; continue }
  $i = $task | Get-ScheduledTaskInfo
  "{0}: {1}, last run {2}, result 0x{3:X}" -f $t, $task.State, $i.LastRunTime, $i.LastTaskResult
}

Head "Port 8000"
$listen = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
  $listen | ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "In use by {0} (pid {1}) {2}" -f $p.ProcessName, $_.OwningProcess, $p.Path }
} else { "Nothing is listening on port 8000." }

Head "Counter log (last 40 lines)"
$Log = "$Base\data\logs\counter.log"
if ((Test-Path $Log) -and (Get-Item $Log).Length -gt 0) { Get-Content $Log -Tail 40 } else { "Empty or missing: the background task has written nothing yet." }

Head "Is Faida answering?"
$h = Health
if ($h) {
  "YES. Faida $($h.version) is running for $($h.business_name). Printers: $($h.printers)."
} elseif (Test-Path "$Base\current\backend\.venv\Scripts\python.exe") {
  "No. Starting Faida by hand to see what happens (up to 3 minutes)..."
  Stop-Faida
  $out = Join-Path $env:TEMP "faida-check-out.txt"; $err = Join-Path $env:TEMP "faida-check-err.txt"
  $env:FAIDA_ENV_FILE = "$Base\counter.env"
  $proc = Start-Process "$Base\current\backend\.venv\Scripts\python.exe" -WorkingDirectory "$Base\current\backend" `
    -ArgumentList "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000" `
    -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
  $sw = [Diagnostics.Stopwatch]::StartNew()
  while ($sw.Elapsed.TotalSeconds -lt 180 -and -not $proc.HasExited -and -not ($h = Health)) { Start-Sleep 3; Write-Host -NoNewline "." }
  Write-Host ""
  $after = [int]$sw.Elapsed.TotalSeconds
  if ($h) { "Faida ANSWERED after $after s when started by hand." }
  elseif ($proc.HasExited) { "Faida STOPPED after $after s (code $($proc.ExitCode))." }
  else { "Still no answer after $after s." }
  "--- what Faida printed ---"
  Get-Content $out, $err -ErrorAction SilentlyContinue | Select-Object -Last 60
  "--- end ---"
  Stop-Faida
  # Hand it back to the background task, which also starts it at every boot.
  Start-ScheduledTask -TaskName "Faida counter" -ErrorAction SilentlyContinue
  if ($h) {
    "Starting it again in the background..."
    $sw.Restart()
    while ($sw.Elapsed.TotalSeconds -lt 180 -and -not ($h = Health)) { Start-Sleep 3; Write-Host -NoNewline "." }
    Write-Host ""
    if ($h) { "FIXED: Faida is running in the background now. Open http://localhost:8000, or restart the PC." }
    else { "Faida works by hand, but the background task doesn't start it. Send this report to support." }
  }
} else {
  "No, and Faida isn't installed completely. Run FaidaSetup.exe again."
}

Head "Report"
if ($Report) { Stop-Transcript | Out-Null; Write-Host "Saved: $Report" }
Write-Host "Problem not fixed? Send this report, or a photo of this window, to support: +254 797 033 513" -ForegroundColor Yellow
if (-not $NoPause) { Read-Host "`nPress Enter to close" | Out-Null }
