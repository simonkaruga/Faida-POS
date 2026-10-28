<#
Loads the sample menu (docs/sample-menu.json: drinks, food, stock items, recipes, tables)
and its pictures onto a counter whose menu is still empty. On the USB stick, double-click
Load-Demo-Menu.bat. Prices are examples: the owner changes them on the counter.
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

Write-Host "Loading the sample menu into Faida POS..." -ForegroundColor Cyan
Set-Location $Backend
& $Py -m app.cli load-menu "$Base\current\docs\sample-menu.json" 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE) { Done "Nothing was loaded (see the message above). Support (call or WhatsApp): +254 797 033 513" Red }
& $Py -m app.cli load-images "$Base\current\docs\sample-images" 2>&1 | ForEach-Object { "$_" }
Done "Done. On the counter, lock and sign in again to see the menu. Change prices in Owner > Menu and Stock." Green
