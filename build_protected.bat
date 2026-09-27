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

"%BUILD_PYTHON%" -c "import Cython, nuitka, PySide6" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.9 is missing a build dependency.
  echo Run: "%BUILD_PYTHON%" -m pip install Cython Nuitka PySide6
  pause
  exit /b 1
)

echo Build Python: %BUILD_PYTHON%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_protected.ps1" -Python "%BUILD_PYTHON%"
if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Core-protected standalone build completed.
echo Protect the release EXE with SProtect, then run finalize_sprotect_release.bat.
pause
