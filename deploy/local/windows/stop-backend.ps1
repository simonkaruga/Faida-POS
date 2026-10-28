# Stops Faida's backend (uvicorn) and what it started, shared by setup.ps1 and update.ps1
# (dot-source it). Stop-Process, not taskkill /T: taskkill reports an error for a child
# that has already exited, and with $ErrorActionPreference = "Stop" that failed the update.
function Stop-Backend {
  for ($i = 0; $i -lt 15; $i++) {
    $All = @(Get-CimInstance Win32_Process)
    $Ids = @($All | Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -like "*uvicorn*app.main*" } |
      ForEach-Object { $_.ProcessId })
    if (-not $Ids) { return }
    # Their children too (the environment's python.exe starts the real one).
    $Ids += @($All | Where-Object { $Ids -contains $_.ParentProcessId } | ForEach-Object { $_.ProcessId })
    $Ids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep 2
  }
  throw "Faida's backend would not stop. Restart the PC, then run FaidaSetup.exe again."
}
