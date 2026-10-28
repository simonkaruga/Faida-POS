# Opens the counter screen full-screen: the "Faida POS" icon on the desktop. The counter
# also opens by itself at sign-in ("Faida kiosk" task); this is for when it was closed.
$Url = "http://localhost:8000"
$KioskProfile = "$env:LOCALAPPDATA\FaidaKiosk"
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$Edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$Browser = if ($Chrome) { $Chrome } else { $Edge }
if (-not $Browser) {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show("Neither Chrome nor Microsoft Edge is installed. Support: +254 797 033 513", "Faida POS") | Out-Null
  exit 1
}
Start-Process $Browser -ArgumentList "--app=$Url", "--start-fullscreen", "--user-data-dir=$KioskProfile", "--no-first-run", "--disable-translate"
