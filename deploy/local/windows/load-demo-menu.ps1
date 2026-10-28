<#
Loads a menu (drinks, food, stock items, recipes, tables) and its pictures onto a counter
whose menu is still empty: menu.json and the pictures folder next to this file on the USB
stick (made with "python -m app.cli export-menu"), or else the sample menu. Double-click
Load-Demo-Menu.bat. The owner then changes the prices on the counter.
#>
$ErrorActionPreference = "Continue"
$Base = "C:\Faida"
$env:FAIDA_ENV_FILE = "$Base\counter.env"
$Backend = "$Base\current\backend"
$Py = "$Backend\.venv\Scripts\python.exe"
function Done($Text, $Colour) {
  Write-Host "`n$Text" -ForegroundColor $Colour
  Read-Host "`nPress Enter to close this window" | Out-Null
  exit
}
if (-not (Test-Path $Py)) { Done "Faida POS is not installed on this PC. Run FaidaSetup.exe first." Red }

$Menu = "$PSScriptRoot\menu.json"
$Pictures = "$PSScriptRoot\pictures"
if (-not (Test-Path $Menu)) { $Menu = "$Base\current\docs\sample-menu.json"; $Pictures = "$Base\current\docs\sample-images" }
Write-Host "Loading the menu into Faida POS from $Menu ..." -ForegroundColor Cyan
Set-Location $Backend
& $Py -m app.cli load-menu $Menu 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE) { Done "Nothing was loaded (see the message above). Support (call or WhatsApp): +254 797 033 513" Red }
if (Test-Path $Pictures) { & $Py -m app.cli load-images $Pictures 2>&1 | ForEach-Object { "$_" } }
Done "Done. On the counter, lock and sign in again to see the menu. Change prices in Owner > Menu and Stock." Green
