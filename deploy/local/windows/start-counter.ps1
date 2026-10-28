# Runs the counter backend (started at boot by the "Faida counter" task). Restarts it
# if it stops, and keeps a log in C:\Faida\data\logs.
$Base = "C:\Faida"
$env:FAIDA_ENV_FILE = "$Base\counter.env"
$ListenHost = (Get-Content "$Base\listen.txt" -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $ListenHost) { $ListenHost = "127.0.0.1" }
$Log = "$Base\data\logs\counter.log"
while ($true) {
  if ((Test-Path $Log) -and (Get-Item $Log).Length -gt 20MB) { Move-Item -Force $Log "$Log.old" }
  Set-Location "$Base\current\backend"
  # Plain lines in the log (Python's own messages, not PowerShell's error wrapping of
  # them), in the same encoding ">>" used before.
  & "$Base\current\backend\.venv\Scripts\python.exe" -m uvicorn app.main:create_app --factory --host $ListenHost --port 8000 2>&1 |
    ForEach-Object { "$_" } | Out-File -Append -Encoding Unicode $Log
  # Stopped on purpose by update.ps1: wait for it to start us again.
  if (Test-Path "$Base\updating.flag") { exit 0 }
  Start-Sleep -Seconds 3
}
