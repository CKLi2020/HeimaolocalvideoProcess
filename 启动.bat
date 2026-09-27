@echo off
setlocal
cd /d "%~dp0"

set "APP_PYTHON=%LocalAppData%\Programs\Python\Python39\python.exe"
if not exist "%APP_PYTHON%" goto fallback
"%APP_PYTHON%" -c "import PySide6" >nul 2>&1
if errorlevel 1 goto fallback
goto run39

:fallback
py -3.11 -c "import PySide6" >nul 2>&1
if errorlevel 1 goto python310
echo Starting with Python 3.11...
py -3.11 main.py
goto done

:python310
py -3.10 -c "import PySide6" >nul 2>&1
if errorlevel 1 goto missing
echo Starting with Python 3.10...
py -3.10 main.py
goto done

:run39
echo Starting with Python 3.9...
"%APP_PYTHON%" main.py
goto done

:missing
echo ERROR: Python with PySide6 was not found.
echo Install dependencies with: python -m pip install -r requirements.txt
pause
exit /b 1

:done
if errorlevel 1 pause
endlocal
