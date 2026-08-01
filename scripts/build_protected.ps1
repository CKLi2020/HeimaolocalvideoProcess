param(
    [string]$Python = "python",
    [string]$VmProtectDir = "C:\Program Files (x86)\VMProtect Ultimate",
    [switch]$SkipVmProtect
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build\protected"
$Dist = Join-Path $Root "dist-protected"
$RawExe = Join-Path $Build "BlackCatFlowCut.nuitka.exe"
$Version = (& $Python -c "import runpy; print(runpy.run_path(r'$Root\version.py')['APP_VERSION'])").Trim()
if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+(\.\d+){2,3}$') {
    throw "Invalid APP_VERSION in version.py: $Version"
}
function ConvertFrom-CodePoints([int[]]$Codes) {
    return -join ($Codes | ForEach-Object { [char]$_ })
}
$ProductName = ConvertFrom-CodePoints @(0x9ED1, 0x732B, 0x82CD, 0x8001, 0x5E08)
$FinalExe = Join-Path $Dist "${ProductName}_V$Version.exe"
$Icon = Join-Path $Root "ico\feng_logo.ico"
$VmProtect = Join-Path $VmProtectDir "VMProtect_Con.exe"
$Project = Join-Path $Build "flowcut.vmp"
$NativeBuild = Join-Path $PSScriptRoot "build_native.ps1"
$Ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
$Ffprobe = (Get-Command ffprobe.exe -ErrorAction SilentlyContinue).Source

if (-not (Test-Path -LiteralPath $Icon)) { throw "Icon not found: $Icon" }
if (-not $Ffmpeg -or -not $Ffprobe) { throw "ffmpeg.exe and ffprobe.exe are required" }
if (-not $SkipVmProtect -and -not (Test-Path -LiteralPath $VmProtect)) {
    throw "VMProtect not found: $VmProtect"
}

New-Item -ItemType Directory -Force -Path $Build, $Dist | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File $NativeBuild -Python $Python -VmProtectDir $VmProtectDir
if ($LASTEXITCODE -ne 0) { throw "Native protection failed" }
& $Python -m nuitka --version
if ($LASTEXITCODE -ne 0) { throw "Nuitka is required: python -m pip install nuitka" }

Push-Location $Root
try {
    & $Python -m nuitka `
        --standalone --onefile --assume-yes-for-downloads `
        --enable-plugin=pyside6 --windows-console-mode=disable `
        --include-module=app._flowcut_core `
        --include-package=cryptography `
        --include-data-dir=ico=ico --include-data-dir=resources=resources `
        --windows-icon-from-ico="$Icon" `
        --product-name="BlackCat FlowCut" `
        --file-description="BlackCat FlowCut" `
        --file-version="$Version" --product-version="$Version" `
        --output-dir="$Build" --output-filename="BlackCatFlowCut.nuitka.exe" `
        main.py
    if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }
}
finally {
    Pop-Location
}

if ($SkipVmProtect) {
    Copy-Item -LiteralPath $RawExe -Destination $FinalExe -Force
}
else {
    $xml = @"
<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <Protection InputFileName="$RawExe" Options="37632" CompressionMode="1" VMCodeSectionName=".vmp" VMExecutorCount="1">
    <Folders/>
    <Procedures>
      <Procedure MapAddress="EntryPoint" IncludedInCompilation="true" Options="1" CompilationType="2"/>
    </Procedures>
  </Protection>
  <DLLBox/>
  <Script IncludedInCompilation="true"></Script>
</Document>
"@
    [System.IO.File]::WriteAllText($Project, $xml, [System.Text.Encoding]::UTF8)
    & $VmProtect $RawExe $FinalExe -pf $Project -we
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $FinalExe)) {
        throw "VMProtect protection failed"
    }
}

$ReleaseAssets = @(
    "ico", "resources", "showlight", "startmovie",
    (ConvertFrom-CodePoints @(0x8D34, 0x7EB8)),
    (ConvertFrom-CodePoints @(0x914D, 0x7F6E, 0x6587, 0x4EF6))
)
foreach ($name in $ReleaseAssets) {
    $source = Join-Path $Root $name
    if (-not (Test-Path -LiteralPath $source)) { throw "Release directory not found: $source" }
    Copy-Item -LiteralPath $source -Destination $Dist -Recurse -Force
}
$WorkingDirectories = @(
    (ConvertFrom-CodePoints @(0x4E3B, 0x89C6, 0x9891)),
    (ConvertFrom-CodePoints @(0x8F85, 0x52A9, 0x89C6, 0x9891)),
    (ConvertFrom-CodePoints @(0x8499, 0x7248, 0x6210, 0x54C1)),
    ((ConvertFrom-CodePoints @(0x8774, 0x8776)) + "AB" + (ConvertFrom-CodePoints @(0x6210, 0x54C1)))
)
foreach ($name in $WorkingDirectories) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Dist $name) | Out-Null
}
Copy-Item -LiteralPath $Ffmpeg, $Ffprobe -Destination $Dist -Force

Write-Host "Protected executable: $FinalExe" -ForegroundColor Green
Write-Host "Release directory: $Dist" -ForegroundColor Green
