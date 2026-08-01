param(
    [string]$Python = "python",
    [string]$VmProtectDir = "C:\Program Files (x86)\VMProtect Ultimate"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path ([System.IO.Path]::GetTempPath()) "flowcut_native_build"
$Source = Join-Path $Root "native_src\flowcut_core.pyx"
$Generated = Join-Path $Build "flowcut_core.c"
$Raw = Join-Path $Build "_flowcut_core.raw.pyd"
$Protected = Join-Path $Build "_flowcut_core.protected.pyd"
$Output = Join-Path $Root "app\_flowcut_core.pyd"
$Project = Join-Path $Build "flowcut_core.vmp"
$VmProtect = Join-Path $VmProtectDir "VMProtect_Con.exe"
$SdkInclude = Join-Path $VmProtectDir "Include\C"
$SdkLibrary = Join-Path $VmProtectDir "Lib\Windows\MinGW\VMProtectSDK64.a"

foreach ($path in @($Source, $VmProtect, $SdkLibrary)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Native dependency not found: $path" }
}
if (-not (Get-Command gcc.exe -ErrorAction SilentlyContinue)) { throw "64-bit gcc.exe not found" }
& $Python -c "import Cython"
if ($LASTEXITCODE -ne 0) { throw "Cython is required" }

$PythonInclude = & $Python -c "import sysconfig; print(sysconfig.get_paths()['include'])"
$PythonLib = & $Python -c "import sysconfig; print(sysconfig.get_config_var('installed_base') + r'\libs')"
New-Item -ItemType Directory -Force -Path $Build | Out-Null

& $Python -m cython -3 --module-name app._flowcut_core -o $Generated $Source
if ($LASTEXITCODE -ne 0) { throw "Cython generation failed" }

& gcc.exe -shared -O1 -fno-crossjumping -fno-ipa-icf -fno-reorder-blocks-and-partition `
    -DMS_WIN64=1 -D_M_X64=1 `
    "-I$PythonInclude" "-I$SdkInclude" $Generated `
    "-L$PythonLib" -lpython39 $SdkLibrary -o $Raw
if ($LASTEXITCODE -ne 0) { throw "Native compilation failed" }

$markers = @(
    "FCNATIVE:license.sign",
    "FCNATIVE:license.verify",
    "FCNATIVE:mask.alpha",
    "FCNATIVE:task.verify",
    "FCNATIVE:mask.authorized",
    "FCNATIVE:butterfly.authorized"
) | ForEach-Object {
    "      <Procedure MapAddress=`"VMProtectMarker &quot;$_&quot;`" IncludedInCompilation=`"true`" Options=`"1`" CompilationType=`"2`"/>"
}
$xml = (@(
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<Document>',
    "  <Protection InputFileName=`"$Raw`" Options=`"32768`" CompressionMode=`"0`" VMCodeSectionName=`".vmp`" VMExecutorCount=`"1`">",
    '    <Folders/>',
    '    <Procedures>'
) + $markers + @(
    '    </Procedures>',
    '  </Protection>',
    '  <DLLBox/>',
    '  <Script IncludedInCompilation="true"></Script>',
    '</Document>'
)) -join "`r`n"
[System.IO.File]::WriteAllText($Project, $xml, [System.Text.Encoding]::UTF8)

& $VmProtect $Raw $Protected -pf $Project -we
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Protected)) {
    throw "VMProtect native protection failed"
}
Copy-Item -LiteralPath $Protected -Destination $Output -Force

Push-Location $Root
try {
    & $Python -c "from app._flowcut_core import mask_alpha; assert mask_alpha(1080, 1920, 20, .05, 0)"
    if ($LASTEXITCODE -ne 0) { throw "Protected native module import test failed" }
}
finally {
    Pop-Location
}
Write-Host "Protected native core: $Output" -ForegroundColor Green
