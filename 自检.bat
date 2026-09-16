@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" "selftest.py"
echo.
echo   ---- 自检退出码 %ERRORLEVEL%  (0 = 全过) ----
pause
exit /b %ERRORLEVEL%

:no_venv
echo   没有找到 rebuild\.venv,先跑一次 rebuild\安装.bat。
pause
exit /b 1
