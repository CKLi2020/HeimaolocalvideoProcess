@echo off
setlocal
cd /d "%~dp0"

set "BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
  echo ERROR: Project virtual environment was not found:
  echo %BUILD_PYTHON%
  pause
  exit /b 1
)

"%BUILD_PYTHON%" -c "import nuitka, PySide6, av, numpy, cv2, cryptography"
if errorlevel 1 (
  echo ERROR: Missing diagnostic build dependencies.
  echo Run: "%BUILD_PYTHON%" -m pip install -r requirements.txt Nuitka
  pause
  exit /b 1
)

echo Building Nuitka-only diagnostic EXE. No VMProtect or SProtect.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_nuitka_debug.ps1" -Python "%BUILD_PYTHON%"
if errorlevel 1 (
  echo Diagnostic build failed. See the error above.
  pause
  exit /b 1
)
echo Diagnostic build completed. Use run_nuitka_debug.bat in the output folder.
pause
