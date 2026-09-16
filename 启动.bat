@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" goto no_venv

rem pythonw = 不带黑色控制台窗口启动
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0

:no_venv
echo.
echo   没有找到 rebuild\.venv,先跑一次 rebuild\安装.bat 建环境。
echo.
echo   如果只是想看看报错,直接跑 rebuild\启动-调试.bat。
echo.
pause
exit /b 1
