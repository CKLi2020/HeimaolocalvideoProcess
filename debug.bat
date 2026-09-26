@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv

rem 保留控制台:出错时堆栈直接印在窗口里,不会一闪而过
".venv\Scripts\python.exe" "main.py"
echo.
echo   ---- 程序已退出,退出码 %ERRORLEVEL% ----
pause
exit /b 0

:no_venv
echo   没有找到 rebuild\.venv,先跑一次 rebuild\安装.bat。
pause
exit /b 1
