# Python 3.12 for Faida, shared by setup.ps1, install.ps1 and update.ps1 (dot-source it).
# Found without the "py" launcher, which isn't always on the PATH.

# Where Faida's own environment says Python is, then the registry, then the usual folders.
function Find-Python312 {
  $Found = @()
  $Cfg = "C:\Faida\current\backend\.venv\pyvenv.cfg"
  if (Test-Path $Cfg) {
    $Home312 = (Get-Content $Cfg | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', ''
    if ($Home312) { $Found += Join-Path "$Home312".Trim() "python.exe" }
  }
  foreach ($Key in "HKLM:\SOFTWARE\Python\PythonCore\3.12\InstallPath", "HKCU:\SOFTWARE\Python\PythonCore\3.12\InstallPath") {
    $Exe = (Get-ItemProperty $Key -ErrorAction SilentlyContinue).ExecutablePath
    if ($Exe) { $Found += $Exe }
  }
  $Found += "$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  $Found | Where-Object { $_ -and (Test-Path $_) -and ((& $_ -c "import sys; print(sys.version_info[:2] == (3, 12))") -eq "True") } |
    Select-Object -First 1
}

# Installs Python 3.12 for all users if it is missing (e.g. someone uninstalled it, which
# also stops Faida): from the installer in $Bundle (FaidaSetup.exe has one), else winget.
# Reinstalled in the same place, Faida's existing environment works again.
function Install-Python312([string]$Bundle) {
  if (Find-Python312) { return }
  $Setup = if ($Bundle) { Get-ChildItem (Join-Path $Bundle "python-3.12*.exe") -ErrorAction SilentlyContinue | Select-Object -First 1 }
  if ($Setup) {
    Write-Host "Installing Python 3.12 (Faida needs it)..."
    Start-Process -Wait $Setup.FullName -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_launcher=1", "Include_test=0"
  } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
  } else {
    throw "Python 3.12 is not installed, and this PC has no winget to fetch it. Run FaidaSetup.exe (it carries Python)."
  }
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Find-Python312)) { throw "Python 3.12 did not install. Run FaidaSetup.exe again." }
}
