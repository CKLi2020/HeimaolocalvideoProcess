@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv

".venv\Scripts\python.exe" -c "import PySide6, av, numpy, cv2, cryptography" >nul 2>&1
if errorlevel 1 goto no_dependencies

rem 保留控制台:出错时堆栈直接印在窗口里,不会一闪而过
".venv\Scripts\python.exe" "main.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"
echo.
echo   ---- 程序已退出,退出码 %APP_EXIT_CODE% ----
pause
exit /b %APP_EXIT_CODE%

:no_venv
echo   没有找到项目虚拟环境 .venv，请先运行 安装.bat。
pause
exit /b 1

:no_dependencies
echo   .venv 缺少运行依赖，请先运行 安装.bat。
pause
exit /b 1
