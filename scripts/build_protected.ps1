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
$FinalExe = Join-Path $Dist "黑猫苍老师.exe"
$Icon = Join-Path $Root "ico\feng_logo.ico"
$VmProtect = Join-Path $VmProtectDir "VMProtect_Con.exe"
$Project = Join-Path $Build "flowcut.vmp"
$NativeBuild = Join-Path $PSScriptRoot "build_native.ps1"

if (-not (Test-Path -LiteralPath $Icon)) { throw "Icon not found: $Icon" }
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

Write-Host "Protected executable: $FinalExe" -ForegroundColor Green
