param(
    [string]$Python = "python",
    [string]$VmProtectDir = "C:\Program Files (x86)\VMProtect Ultimate"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build\protected"
$Dist = Join-Path $Root "dist-protected"
$NativeBuild = Join-Path $PSScriptRoot "build_native.ps1"
$Version = (& $Python -c "import runpy; print(runpy.run_path(r'$Root\version.py')['APP_VERSION'])").Trim()
if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+(\.\d+){2,3}$') {
    throw "Invalid APP_VERSION in version.py: $Version"
}
$ProductNameBase64 = (& $Python -c "import base64,runpy; print(base64.b64encode(runpy.run_path(r'$Root\version.py')['APP_NAME'].encode()).decode())").Trim()
$ProductName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ProductNameBase64))
$Release = Join-Path $Dist "${ProductName}_V$Version"
$LauncherName = "${ProductName}_V$Version.exe"
$Icon = Join-Path $Root "ico\xinghuo_logo.ico"
$Ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
$Ffprobe = (Get-Command ffprobe.exe -ErrorAction SilentlyContinue).Source

if (-not (Test-Path -LiteralPath $Icon)) { throw "Icon not found: $Icon" }
if (-not $Ffmpeg -or -not $Ffprobe) { throw "ffmpeg.exe and ffprobe.exe are required" }
if (-not (Test-Path -LiteralPath $NativeBuild)) { throw "Native build script not found: $NativeBuild" }
& $Python -c "import modes; modes.MODES_DIR=''; g=modes.load_modes(); ids={m.id for ms in g.values() for m in ms}; assert len(g)==8, list(g); assert 'shipinhao/qixia_mode5' in ids, (sorted(ids), modes.load_modes.errors)"
if ($LASTEXITCODE -ne 0) { throw "Packaged mode registry preflight failed" }

$DistFull = [IO.Path]::GetFullPath($Dist).TrimEnd('\') + '\'
$ReleaseFull = [IO.Path]::GetFullPath($Release)
if (-not $ReleaseFull.StartsWith($DistFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe release path: $ReleaseFull"
}
$RunningRelease = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    try {
        $_.Path -and [IO.Path]::GetFullPath($_.Path).StartsWith(
            $ReleaseFull + '\', [StringComparison]::OrdinalIgnoreCase
        )
    }
    catch { $false }
}
if ($RunningRelease) {
    throw "Close the running $LauncherName before building again."
}
$BuildFull = [IO.Path]::GetFullPath($Build).TrimEnd('\') + '\'
foreach ($name in @("main.build", "main.dist", "main.onefile-build")) {
    $path = [IO.Path]::GetFullPath((Join-Path $Build $name))
    if (-not $path.StartsWith($BuildFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe Nuitka cleanup path: $path"
    }
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
if (Test-Path -LiteralPath $Release) {
    Remove-Item -LiteralPath $Release -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Build, $Release | Out-Null

Write-Host "==> Building and VMProtecting native algorithm core" -ForegroundColor Cyan
& $NativeBuild -Python $Python -VmProtectDir $VmProtectDir
if ($LASTEXITCODE -ne 0) { throw "Protected native core build failed" }

& $Python -m nuitka --version
if ($LASTEXITCODE -ne 0) { throw "Nuitka is required: python -m pip install nuitka" }

Write-Host "==> Building Nuitka standalone application" -ForegroundColor Cyan
Push-Location $Root
try {
    & $Python -m nuitka `
        --standalone --assume-yes-for-downloads `
        --enable-plugin=pyside6 --windows-console-mode=disable `
        --include-module=app._flowcut_core --include-module=app._random_frame_swap_core `
        --include-package=core --include-package=modes --include-package=cryptography `
        --nofollow-import-to=engine.dev_core `
        --include-data-dir=ico=ico --include-data-dir=resources=resources `
        --include-data-dir=mode_defs=mode_defs --include-data-dir=client=client `
        --include-data-files=modes/douyin/feimao_ffargs.json=modes/douyin/feimao_ffargs.json `
        --include-data-files=modes/douyin/feimao_metadata.txt=modes/douyin/feimao_metadata.txt `
        --include-data-files=modes/douyin/filter_complex.txt=modes/douyin/filter_complex.txt `
        --windows-icon-from-ico="$Icon" `
        --product-name="$ProductName" `
        --file-description="$ProductName" `
        --file-version="$Version" --product-version="$Version" `
        --output-dir="$Build" --output-filename="$LauncherName" `
        main.py
    if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }
}
finally {
    Pop-Location
}

$NuitkaDist = Get-ChildItem -LiteralPath $Build -Directory -Filter "*.dist" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $NuitkaDist) { throw "Nuitka standalone directory was not produced" }
$BuiltLauncher = Join-Path $NuitkaDist.FullName $LauncherName
if (-not (Test-Path -LiteralPath $BuiltLauncher)) { throw "Nuitka launcher not found: $BuiltLauncher" }

Copy-Item -Path (Join-Path $NuitkaDist.FullName "*") -Destination $Release -Recurse -Force

function ConvertFrom-CodePoints([int[]]$Codes) {
    return -join ($Codes | ForEach-Object { [char]$_ })
}
$ReleaseAssets = @(
    "resources",
    (ConvertFrom-CodePoints @(0x8D34, 0x7EB8)),
    (ConvertFrom-CodePoints @(0x914D, 0x7F6E, 0x6587, 0x4EF6))
)
foreach ($name in $ReleaseAssets) {
    $source = Join-Path $Root $name
    if (-not (Test-Path -LiteralPath $source)) { throw "Release directory not found: $source" }
    Copy-Item -LiteralPath $source -Destination $Release -Recurse -Force
}
$WorkingDirectories = @(
    "showlight", "startmovie",
    (ConvertFrom-CodePoints @(0x4E3B, 0x89C6, 0x9891)),
    (ConvertFrom-CodePoints @(0x8F85, 0x52A9, 0x89C6, 0x9891)),
    (ConvertFrom-CodePoints @(0x8499, 0x7248, 0x6210, 0x54C1)),
    ((ConvertFrom-CodePoints @(0x8774, 0x8776)) + "AB" + (ConvertFrom-CodePoints @(0x6210, 0x54C1))),
    (ConvertFrom-CodePoints @(0x6A21, 0x677F)),
    (ConvertFrom-CodePoints @(0x62FC, 0x63A5, 0x6210, 0x54C1)),
    (ConvertFrom-CodePoints @(0x80CC, 0x666F, 0x97F3, 0x4E50)),
    (ConvertFrom-CodePoints @(0x88C1, 0x526A, 0x6210, 0x54C1))
)
foreach ($name in $WorkingDirectories) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Release $name) | Out-Null
}
New-Item -ItemType Directory -Force -Path (Join-Path $Release "ico") | Out-Null
Copy-Item -LiteralPath $Icon -Destination (Join-Path $Release "ico") -Force
Copy-Item -LiteralPath $Ffmpeg, $Ffprobe -Destination $Release -Force

$SProtectName = "$([IO.Path]::GetFileNameWithoutExtension($LauncherName)).sp.exe"
$Instructions = @(
    "The native algorithm core is protected by VMProtect Ultra.",
    "",
    "Next steps:",
    "1. Open $LauncherName with SProtect.",
    "2. Save the protected output as $SProtectName in this directory.",
    "3. Run finalize_sprotect_release.bat from the project root."
) -join [Environment]::NewLine
[IO.File]::WriteAllText((Join-Path $Release "SPROTECT-NEXT-STEP.txt"), $Instructions, [Text.Encoding]::UTF8)

Write-Host "Native core protected and standalone build completed." -ForegroundColor Green
Write-Host "SProtect input: $(Join-Path $Release $LauncherName)" -ForegroundColor Yellow
Write-Host "Release directory: $Release" -ForegroundColor Green
Write-Host "Next: protect the release launcher with SProtect, then run finalize_sprotect_release.bat." -ForegroundColor Yellow
