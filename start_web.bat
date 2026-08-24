@echo off
chcp 65001 >nul
title SocialReader Web
set PYTHONPATH=
set "PYTHON_EXE=D:\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
echo 正在启动 SocialReader 本地操作界面...
echo.
"%PYTHON_EXE%" "%~dp0web_capture.py"
echo.
echo Web 控制台已停止。按任意键关闭窗口。
pause >nul
