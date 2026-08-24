@echo off
chcp 65001 >nul
echo ============================================
echo   SocialReader - 启动调试浏览器
echo   （登录小红书/抖音一次，之后状态自动保存）
echo ============================================
echo.
echo 如果Chrome已经在运行，请先完全退出，否则本实例不会带调试端口。
echo.
set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" (
  echo [启动失败] 未找到 Chrome：%CHROME_EXE%
  pause
  exit /b 1
)
start "" "%CHROME_EXE%" --remote-debugging-port=9333 --user-data-dir="%~dp0profile" --no-first-run --no-default-browser-check --start-maximized
timeout /t 3 >nul
echo.
echo 浏览器已启动。请在新窗口里：
echo   1. 打开 https://www.xiaohongshu.com  登录小红书
echo   2. 打开 https://www.douyin.com      登录抖音
echo 登录一次即可，之后把链接发给你哥哥，他会用工具读取。
echo.
pause
