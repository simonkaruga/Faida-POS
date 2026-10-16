# Opens the counter full-screen once the backend answers ("Faida kiosk" task, at login).
# If someone closes it, it opens again.
$Url = "http://localhost:8000"
for ($i = 0; $i -lt 90; $i++) {
  try { Invoke-WebRequest "$Url/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null; break } catch { Start-Sleep 2 }
}
$Edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$KioskProfile = "$env:LOCALAPPDATA\FaidaKiosk"
while ($true) {
  if ($Chrome) {
    Start-Process -Wait $Chrome -ArgumentList "--kiosk", "--app=$Url", "--user-data-dir=$KioskProfile", "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble", "--disable-translate", "--overscroll-history-navigation=0", "--disable-pinch"
  } else {
    Start-Process -Wait $Edge -ArgumentList "--kiosk", $Url, "--edge-kiosk-type=fullscreen", "--user-data-dir=$KioskProfile", "--no-first-run", "--overscroll-history-navigation=0"
  }
  Start-Sleep 2
}
