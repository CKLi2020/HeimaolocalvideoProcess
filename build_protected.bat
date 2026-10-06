@echo off
setlocal
cd /d "%~dp0"

set "BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
  echo ERROR: Project virtual environment was not found:
  echo %BUILD_PYTHON%
  echo Run the project installation script to create .venv first.
  pause
  exit /b 1
)

"%BUILD_PYTHON%" -c "import Cython, nuitka, PySide6" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Project virtual environment is missing a build dependency.
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
echo Core-protected standalone build completed and ready to use.
echo Optional: protect the release EXE with SProtect, then run finalize_sprotect_release.bat.
pause
