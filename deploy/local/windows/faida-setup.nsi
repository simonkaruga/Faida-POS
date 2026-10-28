; FaidaSetup-<version>.exe: one file that installs or updates Faida on a Windows counter
; with no internet. Built by deploy/make-windows-setup.sh, which passes:
;   VERSION      e.g. 0.3.1
;   RELEASE_DIR  the unpacked release, with backend\wheels (Windows Python packages)
;   BUNDLE_DIR   the PostgreSQL 16 and Python 3.12 installers
;   OUTFILE      where to write the .exe
; The .exe unpacks to a temporary folder and runs deploy\local\windows\setup.ps1, which
; asks the install questions in a console window.

Unicode true
!include MUI2.nsh
!include x64.nsh
!include LogicLib.nsh

Name "Faida POS ${VERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails show
BrandingText "Faida POS by Avinaya Solutions Ltd  ·  Support +254 797 033 513"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Faida POS"
VIAddVersionKey "CompanyName" "Avinaya Solutions Ltd"
VIAddVersionKey "FileDescription" "Faida POS setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Avinaya Solutions Ltd"

!define MUI_ICON "faida.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Faida POS ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This installs Faida POS on this counter PC, or updates it if an older version is here.$\r$\n$\r$\nNo internet is needed: PostgreSQL, Python and everything else are inside this file.$\r$\n$\r$\nBefore you start:$\r$\n  •  Sign in to Windows as the account that will show the counter, and make it an administrator for now.$\r$\n  •  Plug in and switch on the receipt printer; share it in Windows as POS80.$\r$\n  •  Have the backup passphrase, business name, owner's name and menu file ready.$\r$\n  •  When updating: after closing, with every shift ended.$\r$\n$\r$\nA console window will ask the setup questions. Follow docs\install-checklist (the setup guide)."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "Faida POS setup finished"
!define MUI_FINISHPAGE_TEXT "Restart the PC: it should open straight into the Faida PIN screen.$\r$\n$\r$\nThen continue with the setup guide from step 3 (printers).$\r$\n$\r$\nSupport (call or WhatsApp): +254 797 033 513"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "Faida POS"
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Faida POS needs 64-bit Windows 10 or 11."
    Abort
  ${EndIf}

  InitPluginsDir
  DetailPrint "Unpacking Faida POS ${VERSION}..."
  SetOutPath "$PLUGINSDIR\release"
  File /r "${RELEASE_DIR}\*"
  SetOutPath "$PLUGINSDIR\bundle"
  File "${BUNDLE_DIR}\*.exe"

  ; New counter only: phone view through the cloud, or counter only?
  StrCpy $0 ""
  ${IfNot} ${FileExists} "C:\Faida\counter.env"
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
      "Will the owner use the phone view through the Faida cloud?$\r$\n$\r$\nYes: the counter can be linked to the cloud later (needs internet now and then).$\r$\n$\r$\nNo: counter only. Nothing leaves the bar, and no internet is ever needed." \
      IDYES ask_done
    StrCpy $0 "-Offline"
    ask_done:
  ${EndIf}

  DetailPrint "Running setup (answer the questions in the console window)..."
  ${DisableX64FSRedirection}
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\release\deploy\local\windows\setup.ps1" $0 -Bundle "$PLUGINSDIR\bundle"' $1
  ${EnableX64FSRedirection}
  ${If} $1 != 0
    MessageBox MB_ICONEXCLAMATION "Setup did not finish. Read the console window or the log in C:\Faida\setup-logs, fix the problem and run this again.$\r$\n$\r$\nSupport: +254 797 033 513"
    Abort "Setup did not finish."
  ${EndIf}
  SetOutPath "$TEMP"  ; let the temporary folder be removed
SectionEnd
