param(
    [string]$Python = "",
    [int]$Jobs = 2
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $Root ".venv\Scripts\python.exe" }
if ($Jobs -lt 1) { throw "Jobs must be positive" }
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }

$Version = & $Python -c "import runpy; print(runpy.run_path(r'$Root\version.py')['APP_VERSION'])"
if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+(\.\d+){2,3}$') {
    throw "Cannot read APP_VERSION"
}
$ProductNameBase64 = & $Python -c "import base64,runpy; print(base64.b64encode(runpy.run_path(r'$Root\version.py')['APP_NAME'].encode()).decode())"
if ($LASTEXITCODE -ne 0) { throw "Cannot read APP_NAME" }
$ProductName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ProductNameBase64))
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$Build = Join-Path $Root "build\nuitka-debug\$Stamp"
$Release = Join-Path $Root "dist-nuitka-debug\${ProductName}_V${Version}_$Stamp"
$LauncherName = "${ProductName}_V${Version}_NuitkaDebug.exe"
$Icon = Join-Path $Root "ico\xinghuo_logo.ico"
$Tools = @()
foreach ($name in @("ffmpeg.exe", "ffprobe.exe")) {
    $local = Join-Path $Root "bin\$name"
    if (Test-Path -LiteralPath $local) {
        $Tools += $local
    }
    else {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $command) { throw "$name not found in bin or PATH" }
        $Tools += $command.Source
    }
}
if (-not (Test-Path -LiteralPath $Icon)) { throw "Icon not found: $Icon" }

New-Item -ItemType Directory -Force -Path $Build | Out-Null
Push-Location $Root
try {
    & $Python -c "import nuitka, PySide6, av, numpy, cv2, cryptography"
    if ($LASTEXITCODE -ne 0) { throw "Diagnostic build dependencies are missing" }

    & $Python -m nuitka `
        --standalone --mingw64 --assume-yes-for-downloads "--jobs=$Jobs" `
        --enable-plugin=pyside6 --windows-console-mode=force `
        --include-module=main --include-module=engine.dev_core `
        --include-module=modes.shipinhao.heimao_luoyue_core `
        --include-package=core --include-package=modes --include-package=cryptography `
        --nofollow-import-to=app._flowcut_core `
        --nofollow-import-to=app._random_frame_swap_core `
        --include-data-dir=ico=ico --include-data-dir=resources=resources `
        --include-data-dir=mode_defs=mode_defs --include-data-dir=client=client `
        --include-data-files=modes/douyin/feimao_metadata.txt=modes/douyin/feimao_metadata.txt `
        --include-data-dir=modes/douyin/qilin_artifacts=modes/douyin/qilin_artifacts `
        --include-data-dir=modes/kuaishou/tianbaixinglun_artifacts=modes/kuaishou/tianbaixinglun_artifacts `
        "--windows-icon-from-ico=$Icon" "--product-name=$ProductName Nuitka Debug" `
        "--file-description=$ProductName Nuitka-only diagnostic build" `
        "--file-version=$Version" "--product-version=$Version" `
        "--output-dir=$Build" "--output-filename=$LauncherName" `
        main_nuitka_debug.py
    if ($LASTEXITCODE -ne 0) { throw "Nuitka diagnostic build failed" }
}
finally {
    Pop-Location
}

$NuitkaDist = Join-Path $Build "main_nuitka_debug.dist"
$BuiltLauncher = Join-Path $NuitkaDist $LauncherName
if (-not (Test-Path -LiteralPath $BuiltLauncher)) { throw "Diagnostic EXE not found: $BuiltLauncher" }
foreach ($name in @("_flowcut_core.pyd", "_random_frame_swap_core.pyd")) {
    if (Get-ChildItem -LiteralPath $NuitkaDist -Filter $name -Recurse -File) {
        throw "Protected core unexpectedly included in diagnostic build: $name"
    }
}

New-Item -ItemType Directory -Force -Path $Release | Out-Null
Copy-Item -Path (Join-Path $NuitkaDist "*") -Destination $Release -Recurse -Force
Copy-Item -LiteralPath $Tools -Destination $Release -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "run_nuitka_debug.bat") -Destination $Release
function ConvertFrom-CodePoints([int[]]$Codes) {
    return -join ($Codes | ForEach-Object { [char]$_ })
}
$OptionalAssets = @(
    (ConvertFrom-CodePoints @(0x914D, 0x7F6E, 0x6587, 0x4EF6)),
    (ConvertFrom-CodePoints @(0x8D34, 0x7EB8)),
    (ConvertFrom-CodePoints @(0x80CC, 0x666F, 0x97F3, 0x4E50))
)
foreach ($name in $OptionalAssets) {
    $source = Join-Path $Root $name
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $Release -Recurse -Force
    }
}
Write-Host "Nuitka-only diagnostic EXE: $(Join-Path $Release $LauncherName)" -ForegroundColor Green
Write-Host "Run with logs: $(Join-Path $Release 'run_nuitka_debug.bat')" -ForegroundColor Yellow
