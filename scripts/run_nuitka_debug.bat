@echo off
setlocal
cd /d "%~dp0"
set "DEBUG_EXE="
for %%F in ("%~dp0*_NuitkaDebug.exe") do if exist "%%~fF" set "DEBUG_EXE=%%~fF"
if not defined DEBUG_EXE (
  echo ERROR: Diagnostic EXE was not found beside this BAT.
  pause
  exit /b 1
)

if not exist "logs" mkdir "logs"
if not exist "logs" (
  echo ERROR: Cannot create the logs directory.
  pause
  exit /b 1
)
set "RUN_LOG=%~dp0logs\console_%RANDOM%_%RANDOM%.log"
echo Starting: %DEBUG_EXE%
echo Console log: %RUN_LOG%
echo The console log will be displayed after the application exits.
set "PYTHONFAULTHANDLER=1"
set "PYTHONUNBUFFERED=1"
"%DEBUG_EXE%" %* >"%RUN_LOG%" 2>&1
set "RESULT=%ERRORLEVEL%"
echo. >>"%RUN_LOG%"
echo Exit code: %RESULT% >>"%RUN_LOG%"
type "%RUN_LOG%"
echo.
echo Keep the console and diagnostic logs when reporting a crash.
pause
exit /b %RESULT%
