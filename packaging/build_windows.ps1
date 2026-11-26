# Build the Windows installer on a Windows PC.  Needs: Python 3.11+, Inno Setup 6 (iscc on PATH).
# Usage (PowerShell, project root):   .\packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
py -3 -m venv .buildvenv
.\.buildvenv\Scripts\python -m pip install --upgrade pip
.\.buildvenv\Scripts\pip install -r requirements.txt pyinstaller
$env:PLAYWRIGHT_BROWSERS_PATH = "0"      # download Chromium into the playwright package so it gets bundled
.\.buildvenv\Scripts\python -m playwright install chromium
.\.buildvenv\Scripts\pyinstaller packaging\orders_desk.spec --noconfirm --clean
$version = (Select-String -Path src\orders_desk\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
iscc /DAppVersion=$version packaging\installer.iss
Compress-Archive -Path dist\OrdersDesk -DestinationPath "dist-installer\OrdersDesk-Portable-$version.zip" -Force
Write-Host "Done. Share the ZIP of the installer (WhatsApp blocks .exe files): dist-installer\"
