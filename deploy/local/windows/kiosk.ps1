# Opens the counter full-screen once the backend answers ("Faida kiosk" task, at sign-in),
# and opens it again if it is closed. Only ever one counter window: it looks for the
# browser running with the Faida profile rather than waiting on the process it started,
# because Chrome and Edge often hand a new window to a browser already running and exit
# at once (waiting on that opened a new window every 2 seconds and froze the PC).
$Url = "http://localhost:8000"
for ($i = 0; $i -lt 90; $i++) {
  try { Invoke-WebRequest "$Url/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null; break } catch { Start-Sleep 2 }
}
$Edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$Chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$KioskProfile = "$env:LOCALAPPDATA\FaidaKiosk"

function Test-KioskOpen {
  [bool](Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe' OR Name = 'msedge.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*FaidaKiosk*" } | Select-Object -First 1)
}

while ($true) {
  if (-not (Test-KioskOpen)) {
    if ($Chrome) {
      Start-Process $Chrome -ArgumentList "--kiosk", "--app=$Url", "--user-data-dir=$KioskProfile", "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble", "--disable-translate", "--overscroll-history-navigation=0", "--disable-pinch"
    } elseif ($Edge) {
      Start-Process $Edge -ArgumentList "--kiosk", $Url, "--edge-kiosk-type=fullscreen", "--user-data-dir=$KioskProfile", "--no-first-run", "--overscroll-history-navigation=0"
    } else {
      exit 1
    }
    Start-Sleep 20  # time for the window to appear before looking again
  }
  Start-Sleep 5
}
