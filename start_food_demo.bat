@echo off
chcp 65001 >nul
set PYTHONPATH=
set "PYTHON_EXE=D:\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

powershell.exe -NoProfile -Command "$primary='http://127.0.0.1:8787'; $food=$primary+'/food'; try { $ok=(Invoke-WebRequest -UseBasicParsing -Uri $food -TimeoutSec 1).StatusCode -eq 200 } catch { $ok=$false }; if($ok){Start-Process $food; exit}; try{$occupied=(Invoke-WebRequest -UseBasicParsing -Uri $primary -TimeoutSec 1).StatusCode -eq 200}catch{$occupied=$false}; $port=if($occupied){8788}else{8787}; Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList @('%~dp0web_capture.py','--port',$port,'--no-open') -WorkingDirectory '%~dp0' -WindowStyle Hidden; Start-Sleep -Seconds 2; Start-Process ('http://127.0.0.1:'+ $port +'/food')"
exit /b 0
