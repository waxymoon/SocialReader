@echo off
chcp 65001 >nul
set PYTHONPATH=
set "PYTHON_EXE=D:\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "APP_URL=http://127.0.0.1:8787"

powershell.exe -NoProfile -Command "$url='%APP_URL%'; try { $running=(Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1).StatusCode -eq 200 } catch { $running=$false }; if (-not $running) { Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList @('%~dp0web_capture.py','--no-open') -WorkingDirectory '%~dp0' -WindowStyle Hidden }"
powershell.exe -NoProfile -Command "Start-Sleep -Seconds 2"
start "" "%APP_URL%"
