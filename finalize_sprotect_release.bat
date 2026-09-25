@echo off
setlocal
cd /d "%~dp0"

set "BUILD_PYTHON=%LocalAppData%\Programs\Python\Python39\python.exe"
if not exist "%BUILD_PYTHON%" (
  echo ERROR: Python 3.9 was not found:
  echo %BUILD_PYTHON%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\finalize_sprotect_release.ps1" -Python "%BUILD_PYTHON%"
if errorlevel 1 (
  echo.
  echo Finalization failed.
  pause
  exit /b 1
)
echo.
echo SProtect release finalized.
pause
