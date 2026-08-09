@echo off
setlocal
cd /d "%~dp0"

set "APP_PYTHON=%LocalAppData%\Programs\Python\Python39\python.exe"
if not exist "%APP_PYTHON%" goto fallback
"%APP_PYTHON%" -c "import PySide6" >nul 2>&1
if errorlevel 1 goto missing
goto run39

:fallback
py -3.11 -c "import PySide6" >nul 2>&1
if errorlevel 1 goto missing
echo Starting with Python 3.11...
py -3.11 main.py
goto done

:run39
echo Starting with Python 3.9...
"%APP_PYTHON%" main.py
goto done

:missing
echo ERROR: Python with PySide6 was not found.
echo Install command: py -3.11 -m pip install PySide6
pause
exit /b 1

:done
if errorlevel 1 pause
endlocal
