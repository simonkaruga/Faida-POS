# Nightly encrypted backup to the USB drive named FAIDABACKUP ("Faida backup" task).
# If the drive isn't plugged in, the failure is recorded and the cloud alerts Avinaya.
$Base = "C:\Faida"
$env:FAIDA_ENV_FILE = "$Base\counter.env"
$Drive = Get-Volume -FileSystemLabel "FAIDABACKUP" -ErrorAction SilentlyContinue | Where-Object DriveLetter | Select-Object -First 1
$To = if ($Drive) { "$($Drive.DriveLetter):\faida" } else { "Z:\FAIDABACKUP-not-plugged-in\faida" }
Set-Location "$Base\current\backend"
& "$Base\current\backend\.venv\Scripts\python.exe" -m app.backup create --to $To *>> "$Base\data\logs\backup.log"
exit $LASTEXITCODE
