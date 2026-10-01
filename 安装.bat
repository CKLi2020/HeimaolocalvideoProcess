@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   黑猫视频处理软件(本地版) 环境安装
echo ============================================================
echo.

rem ---- 1. 找 Python 3.x ----
set PY=
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
  if exist %%P if not defined PY set PY=%%P
)
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if exist "%%I" set PY="%%I"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)" 2^>nul') do if exist "%%I" set PY="%%I"
)
if not defined PY (
  echo   [X] 没找到 Python 3.x。请先安装 Python 3.10 或更高版本:
  echo       https://www.python.org/downloads/   安装时记得勾 Add python.exe to PATH
  pause
  exit /b 1
)
echo   [1/3] Python: %PY%

rem ---- 2. 建虚拟环境 ----
if exist ".venv\Scripts\python.exe" (
  echo   [2/3] .venv 已存在,跳过
) else (
  echo   [2/3] 创建 .venv ...
  %PY% -m venv .venv || (echo   [X] 建虚拟环境失败 & pause & exit /b 1)
)

rem ---- 3. 装依赖 ----
echo   [3/3] 安装依赖(customtkinter)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || (
  echo   [X] 依赖安装失败。断网的话可以先离线装好 customtkinter 再重跑本脚本。
  pause
  exit /b 1
)

rem ---- ffmpeg / ffprobe ----
set "FFMPEG_READY="
set "FFMPEG_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

if exist "bin\ffmpeg.exe" if exist "bin\ffprobe.exe" set "FFMPEG_READY=1"

if not defined FFMPEG_READY if exist "..\bin\ffmpeg.exe" if exist "..\bin\ffprobe.exe" (
  if not exist "bin" (
    echo   链接 bin\ -^> ..\bin ^(复用原程序的 ffmpeg,不占额外空间^)
    powershell -NoProfile -Command "New-Item -ItemType Junction -Path 'bin' -Target '..\bin' | Out-Null"
  )
  if exist "bin\ffmpeg.exe" if exist "bin\ffprobe.exe" set "FFMPEG_READY=1"
)

if not defined FFMPEG_READY (
  echo   下载 FFmpeg ^(约 110 MB^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $zip = Join-Path $env:TEMP 'heimao-ffmpeg.zip'; $extract = Join-Path $env:TEMP 'heimao-ffmpeg'; Remove-Item -LiteralPath $zip, $extract -Recurse -Force -ErrorAction SilentlyContinue; Invoke-WebRequest -Uri '%FFMPEG_URL%' -OutFile $zip -UseBasicParsing -TimeoutSec 600; Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force; $ffmpeg = Get-ChildItem -LiteralPath $extract -Filter 'ffmpeg.exe' -Recurse -File | Select-Object -First 1; $ffprobe = Get-ChildItem -LiteralPath $extract -Filter 'ffprobe.exe' -Recurse -File | Select-Object -First 1; New-Item -ItemType Directory -Path 'bin' -Force | Out-Null; Copy-Item -LiteralPath $ffmpeg.FullName -Destination 'bin\ffmpeg.exe' -Force; Copy-Item -LiteralPath $ffprobe.FullName -Destination 'bin\ffprobe.exe' -Force; Remove-Item -LiteralPath $zip, $extract -Recurse -Force -ErrorAction SilentlyContinue"
  if errorlevel 1 (
    echo   [X] FFmpeg 下载或解压失败。请检查网络后重跑本脚本。
    pause
    exit /b 1
  )
  set "FFMPEG_READY=1"
)

echo.
echo ============================================================
echo   装好了。双击 启动.bat 运行;想验证功能双击 自检.bat。
echo ============================================================
pause
