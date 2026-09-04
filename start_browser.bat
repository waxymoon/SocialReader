@echo off
set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME_EXE%" (
  echo Chrome was not found: %CHROME_EXE%
  pause
  exit /b 1
)

start "" "%CHROME_EXE%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9333 --user-data-dir="%~dp0profile" --no-first-run --no-default-browser-check --start-maximized
exit /b 0
