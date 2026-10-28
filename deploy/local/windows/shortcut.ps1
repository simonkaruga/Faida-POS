# Puts the "Faida POS" icon on the desktop of every Windows account (Public desktop).
# It points through C:\Faida\current, so it keeps working after updates. Run as administrator
# (install.ps1 and setup.ps1 do).
$Base = "C:\Faida"
$Here = "$Base\current\deploy\local\windows"
$Link = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:PUBLIC\Desktop\Faida POS.lnk")
$Link.TargetPath = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$Link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Here\open-faida.ps1`""
$Link.IconLocation = "$Here\faida.ico,0"
$Link.WorkingDirectory = $Base
$Link.Description = "Open Faida POS"
$Link.Save()
Write-Host "Desktop icon: Faida POS"
