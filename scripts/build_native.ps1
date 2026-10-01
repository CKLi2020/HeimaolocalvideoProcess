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
$Gcc = (Get-Command gcc.exe -ErrorAction SilentlyContinue).Source
if (-not $Gcc) {
    $NuitkaGccRoot = Join-Path $env:LOCALAPPDATA "Nuitka\Nuitka\Cache\downloads\gcc"
    $Gcc = Get-ChildItem -LiteralPath $NuitkaGccRoot -Filter gcc.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object FullName -Match 'mingw64\\bin\\gcc\.exe$' |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Gcc) { throw "64-bit gcc.exe not found (PATH or Nuitka cache)" }
& $Python -c "import Cython"
if ($LASTEXITCODE -ne 0) { throw "Cython is required" }

$PythonInclude = & $Python -c "import sysconfig; print(sysconfig.get_paths()['include'])"
$PythonLib = & $Python -c "import sysconfig; print(sysconfig.get_config_var('installed_base') + r'\libs')"
New-Item -ItemType Directory -Force -Path $Build | Out-Null

& $Python -m cython -3 --module-name app._flowcut_core -o $Generated $Source
if ($LASTEXITCODE -ne 0) { throw "Cython generation failed" }

& $Gcc -shared -O0 -fno-crossjumping -fno-ipa-icf -fno-reorder-blocks-and-partition `
    -DMS_WIN64=1 -D_M_X64=1 `
    "-I$PythonInclude" "-I$SdkInclude" $Generated `
    "-L$PythonLib" -lpython39 $SdkLibrary -o $Raw
if ($LASTEXITCODE -ne 0) { throw "Native compilation failed" }

$markers = @(
    "FCALGO:mask.alpha",
    "FCALGO:butterfly.plan",
    "FCALGO:template.window",
    "FCALGO:concat.segment",
    "FCALGO:random.playback",
    "FCALGO:random.filter",
    "FCALGO:color.adjust",
    "FCALGO:audio.mild"
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
& $Python -c "import importlib.util; p=r'$Protected'; s=importlib.util.spec_from_file_location('_flowcut_core',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.mask_alpha(1080,1920,20,.05,0); assert m.butterfly_plan(60,2)['main_frames']==1800; assert 'drawbox=' in m.window_matte_chain(1080,1920,50,50,80,100,200); assert len(m.concat_filter_segment(0,1,False,1080,1920,30))==2; assert .9 < m.playback_rate(.93,1.15,1) < 1.2; assert len(m.filter_segments(5,1)) == 5; assert 'eq=' in m.color_adjustments_filter('x',10,0,0,0,'',100)[0]; assert any('afftdn=' in x for x in m.mild_voice_filters('1:a',25,1)[0])"
if ($LASTEXITCODE -ne 0) { throw "Protected native module import test failed" }
try {
    Copy-Item -LiteralPath $Protected -Destination $Output -Force
}
catch {
    throw "Cannot replace $Output. Close the running app/Python process that loaded it, then build again."
}
Write-Host "Protected native core: $Output" -ForegroundColor Green
