param(
    [string]$Python = "python",
    [string]$VmProtectDir = "C:\Program Files (x86)\VMProtect Ultimate",
    [string]$Gcc = "",
    # Turn on the algorithm host gate: define FC_LICENSE_GATE at compile time so
    # the core algorithms refuse to run anywhere but inside the release launcher.
    # Off by default, so source-tree builds are unaffected. No key material is
    # involved and nothing is issued per customer: the gate compares paths at run
    # time (see native_src/flowcut_core.pyx).
    [switch]$LicenseGate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
$OriginalPath = $env:PATH
try {
$Build = Join-Path ([System.IO.Path]::GetTempPath()) "flowcut_native_build"
$VmProtect = Join-Path $VmProtectDir "VMProtect_Con.exe"
$SdkInclude = Join-Path $VmProtectDir "Include\C"
$SdkLibrary = Join-Path $VmProtectDir "Lib\Windows\MinGW\VMProtectSDK64.a"

foreach ($path in @($VmProtect, $SdkLibrary, (Join-Path $SdkInclude "VMProtectSDK.h"))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Native dependency not found: $path" }
}
$PythonBits = (& $Python -c "import struct; print(struct.calcsize('P') * 8)").Trim()
if ($LASTEXITCODE -ne 0 -or $PythonBits -ne "64") {
    throw "Protected native cores require a 64-bit Python interpreter"
}
$Candidates = @()
if ($Gcc) {
    $Candidates += $Gcc
}
else {
    $PathGcc = Get-Command gcc.exe -ErrorAction SilentlyContinue
    if ($PathGcc) { $Candidates += $PathGcc.Source }
    $NuitkaGccRoot = Join-Path $env:LOCALAPPDATA "Nuitka\Nuitka\Cache\downloads\gcc"
    $Candidates += @(Get-ChildItem -LiteralPath $NuitkaGccRoot -Filter gcc.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object FullName -Match 'mingw64\\bin\\gcc\.exe$' |
        Select-Object -ExpandProperty FullName)
    $Candidates += @("C:\msys64\ucrt64\bin\gcc.exe", "C:\msys64\mingw64\bin\gcc.exe")
}
$SelectedGcc = $null
foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }
    $Target = (& $Candidate -dumpmachine).Trim()
    if ($LASTEXITCODE -eq 0 -and $Target -match '^x86_64-.*mingw') {
        $SelectedGcc = $Candidate
        break
    }
    Write-Warning "Ignoring incompatible native compiler: $Candidate (target: $Target)"
}
if (-not $SelectedGcc) {
    throw "No x86_64 MinGW GCC found. Install a 64-bit toolchain or specify -Gcc."
}
$Gcc = $SelectedGcc
$env:PATH = (Split-Path -Parent $Gcc) + ";" + $env:PATH
Write-Host "Native compiler: $Gcc" -ForegroundColor Cyan
& $Python -c "import Cython"
if ($LASTEXITCODE -ne 0) { throw "Cython is required" }

$PythonInclude = & $Python -c "import sysconfig; print(sysconfig.get_paths()['include'])"
if ($LASTEXITCODE -ne 0) { throw "Cannot resolve Python include directory" }
$PythonLib = & $Python -c "import os, sys; print(os.path.join(sys.base_prefix, 'libs'))"
if ($LASTEXITCODE -ne 0) { throw "Cannot resolve Python library directory" }
$PythonLinkName = & $Python -c "import sys; print('python%d%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0) { throw "Cannot resolve Python link library" }
if (-not (Test-Path -LiteralPath (Join-Path $PythonLib "$PythonLinkName.lib"))) {
    throw "Python import library not found: $PythonLib\$PythonLinkName.lib"
}
New-Item -ItemType Directory -Force -Path $Build | Out-Null

$LicenseDefine = @()
if ($LicenseGate) { $LicenseDefine = @("-DFC_LICENSE_GATE") }

# Both protected cores. ``Markers`` must list exactly the strings the source
# passes to VMProtectBeginUltra, and the count is load-bearing: flowcut_core was
# keeps the host gate deliberately unmarked; refusal happens in C with ExitProcess
# instead of unwinding a Python exception through virtualized code.
$Modules = @(
    @{
        Module        = "app._flowcut_core"
        Short         = "_flowcut_core"
        Source        = Join-Path $Root "native_src\flowcut_core.pyx"
        Output        = Join-Path $Root "app\_flowcut_core.pyd"
        RequiredFile  = "engine\native_core.py"
        RequiredConst = "_REQUIRED"
        Smoke         = @'
import importlib.util, os, sys
p = r'__PYD__'
for _d in (sys.base_prefix, os.path.dirname(sys.executable), os.path.dirname(os.path.abspath(p))):
    if os.path.isdir(_d):
        try:
            os.add_dll_directory(_d)
        except (AttributeError, OSError):
            pass
s = importlib.util.spec_from_file_location('_flowcut_core', p)
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
assert m.mask_alpha(1080,1920,20,.05,0)
assert m.butterfly_plan(60,2)['main_frames']==1800
assert 'drawbox=' in m.window_matte_chain(1080,1920,50,50,80,100,200)
assert len(m.concat_filter_segment(0,1,False,1080,1920,30))==2
assert .9 < m.playback_rate(.93,1.15,1) < 1.2
assert len(m.filter_segments(5,1)) == 5
assert 'eq=' in m.color_adjustments_filter('x',10,0,0,0,'',100)[0]
assert any('afftdn=' in x for x in m.mild_voice_filters('1:a',25,1)[0])
q = m.qilin_pipeline_plan(1920,1080,1004)
assert q['geo_source'].count('drawbox=')==36
assert q['rotation_source'].count('drawbox=')==24
assert 'xstack=inputs=20' in q['grid_graph']
assert 'anoisesrc=color=pink' in q['blend_graph']
assert m.qilin_sps_compat_byte(bytes.fromhex('caf016a040402010'))==8
assert m.qilin_sps_compat_byte(bytes.fromhex('caf016a040402008'))==8
assert m.liuying_video_filter(1003).count('perspective=')==1
assert m.liuying_video_filter(1003,True).count('perspective=')==2
assert m.liuying_perspective_filter(1003).startswith('perspective=')
assert m.liuying_flash_filter(1003).startswith('perspective=')
assert m.liuying_base_filter().startswith('fps=60')
assert m.liuying_seed(1003,2)==210461
assert m.motianxinglun_pipeline_plan(1.25)['image_fps']=='120'
assert 'all_mode=screen' in m.tianbaixinglun_pipeline_plan(1.25)['blend_filter']
p = m.manluo_jinghong_plan('medium', 3.0, 4, 20261006)
assert p['fps'] > 0 and p['noise_indices'] and max(p['noise_indices']) < 4
assert 'fps=120' in m.qianchuan_filter()
assert 'level_in=5.72018' in m.qianchuan_audio_filter(2)
r = m.qianchuan_fission_recipe(1000000, 120, 576, 1024)
assert 23 <= r['frame_interval'] <= 29 and r['target_fps'] == 125
assert 'hqdn3d=4:4:4:4' in m.qianchuan_fission_filter(r)
assert m.qianchuan_verify_timestamps([{'pts_time': str(i / 120)} for i in range(20)])
q = m.qixia_pipeline_plan(True, True, True, 50)
assert q['filter_complex'].count('vflip') == 2
assert 'A*0.50+B*0.50' in q['filter_complex']
assert 'ref=4' in q['x264_params'] and 'b-adapt=0' in q['x264_params']
print('smoke test ok: 24 algorithm exports exercised')
'@
        Markers       = @(
            "FCALGO:mask.alpha",
            "FCALGO:butterfly.plan",
            "FCALGO:template.window",
            "FCALGO:concat.segment",
            "FCALGO:random.playback",
            "FCALGO:random.filter",
            "FCALGO:color.adjust",
            "FCALGO:audio.mild",
            "FCALGO:qilin.1004.pipeline",
            "FCALGO:qilin.1004.sps",
            "FCALGO:liuying.1003.video",
            "FCALGO:liuying.1003.branch",
            "FCALGO:liuying.1003.flash",
            "FCALGO:liuying.1003.base",
            "FCALGO:liuying.1003.seed",
            "FCALGO:motianxinglun.1005.pipeline",
            "FCALGO:tianbaixinglun.1005.pipeline",
            "FCALGO:manluo.jinghong",
            "FCALGO:qianchuan.filter",
            "FCALGO:qianchuan.audio",
            "FCALGO:qianchuan.fission",
            "FCALGO:qianchuan.fission.filter",
            "FCALGO:qianchuan.verify",
            "FCALGO:qixia.1007.pipeline"
        )
    },
    @{
        Module        = "app._random_frame_swap_core"
        Short         = "_random_frame_swap_core"
        Source        = Join-Path $Root "native_src\random_frame_swap_core.pyx"
        Output        = Join-Path $Root "app\_random_frame_swap_core.pyd"
        RequiredFile  = "engine\native_core.py"
        RequiredConst = "RANDOM_SWAP_REQUIRED"
        Smoke         = @'
import importlib.util, os, sys
p = r'__PYD__'
for _d in (sys.base_prefix, os.path.dirname(sys.executable), os.path.dirname(os.path.abspath(p))):
    if os.path.isdir(_d):
        try:
            os.add_dll_directory(_d)
        except (AttributeError, OSError):
            pass
s = importlib.util.spec_from_file_location('_random_frame_swap_core', p)
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
assert m.filter_graph().startswith('[0:v:0]fps=30,scale=720:1280')
assert m.filter_graph().endswith('setpts=N[vout]')
assert sorted(m.shuffled_order(20, 1)) == list(range(20))
assert m.shuffled_order(20, 1) == m.shuffled_order(20, 1)
assert m.special_offsets([1000, 1000, 1000], [0, 10, 20]) == [0, 498, 996]
print('smoke test ok: 3 random-swap exports exercised')
'@
        Markers       = @(
            "RFCORE:graph",
            "RFCORE:shuffle",
            "RFCORE:offsets"
        )
    }
)

# Export-set assertion: every name a build must ship, read straight out of the
# Python declaration (engine/native_core.py) so the two cannot drift. Guards
# against the V1.0.0 failure mode where the source was fixed but the shipped pyd
# was not (the release core lacked qilin_pipeline_plan while the loader demanded
# it). engine/native_core.py raises on import when the compiled core is missing,
# which is exactly the case during a build, hence the AST read instead of import.
$ExportCheck = @'
import ast, importlib.util, os, sys



core_path, required_path, const_name, module_name = sys.argv[1:5]
core_path = os.path.abspath(core_path)
core_dir = os.path.dirname(core_path)
# On Windows an extension module needs the selected Python DLL (and the gcc runtime) to
# resolve before it can load.
for candidate in (sys.base_prefix, os.path.dirname(os.path.abspath(sys.executable)), core_dir, os.path.dirname(core_dir)):
    try:
        os.add_dll_directory(candidate)
    except (AttributeError, OSError):
        pass
os.environ["PATH"] = os.pathsep.join([core_dir, os.path.dirname(core_dir), os.environ.get("PATH", "")])

tree = ast.parse(open(required_path, encoding="utf-8").read())
required = []
for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == const_name for t in node.targets):
        required = [element.value for element in node.value.elts]
if not required:
    raise SystemExit("could not read %s from %s" % (const_name, required_path))
spec = importlib.util.spec_from_file_location(module_name, core_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
missing = sorted(set(required) - {name for name in dir(module) if not name.startswith("_")})
if missing:
    raise SystemExit("protected core is missing required exports: " + ", ".join(missing))
print("export check ok: %d required symbols present" % len(required))
'@
$ExportCheckPath = Join-Path $Build "export_check.py"
[System.IO.File]::WriteAllText($ExportCheckPath, $ExportCheck, [System.Text.Encoding]::UTF8)

foreach ($m in $Modules) {
    $Short = $m.Short
    $Generated = Join-Path $Build "$Short.c"
    $Raw = Join-Path $Build "$Short.raw.pyd"
    $Protected = Join-Path $Build "$Short.protected.pyd"
    $Project = Join-Path $Build "$Short.vmp"

    if (-not (Test-Path -LiteralPath $m.Source)) { throw "Native source not found: $($m.Source)" }

    & $Python -m cython -3 --module-name $m.Module -o $Generated $m.Source
    if ($LASTEXITCODE -ne 0) { throw "Cython generation failed: $($m.Module)" }

    & $Gcc -shared -O0 -fno-crossjumping -fno-ipa-icf -fno-reorder-blocks-and-partition `
        -DMS_WIN64=1 -D_M_X64=1 @LicenseDefine `
        "-I$PythonInclude" "-I$SdkInclude" "-I$(Join-Path $Root 'native_src')" $Generated `
        "-L$PythonLib" "-l$PythonLinkName" $SdkLibrary -o $Raw
    if ($LASTEXITCODE -ne 0) { throw "Native compilation failed: $($m.Module)" }

    # No <LicenseManager> section: the gate does not use VMProtect's licensing
    # API, so the project needs no RSA private exponent, no per-customer serial
    # numbers, and the generated project file holds no secrets.
    $markers = $m.Markers | ForEach-Object {
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
        '  <Script IncludedInCompilation="true"></Script>'
    ) + @(
        '</Document>'
    )) -join "`r`n"
    [System.IO.File]::WriteAllText($Project, $xml, [System.Text.Encoding]::UTF8)

    $ProtectedOk = $false
    try {
        & $VmProtect $Raw $Protected -pf $Project -we
        $ProtectedOk = ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $Protected))
    }
    finally {
        # The project file is a throwaway build artifact; remove it either way.
        if (Test-Path -LiteralPath $Project) {
            Remove-Item -LiteralPath $Project -Force
        }
    }
    if (-not $ProtectedOk) { throw "VMProtect native protection failed: $($m.Module)" }

    & $Python $ExportCheckPath $Protected (Join-Path $Root $m.RequiredFile) $m.RequiredConst $Short
    if ($LASTEXITCODE -ne 0) { throw "Protected native core export check failed: $($m.Module)" }

    # Functional smoke test: actually calls the algorithms from this machine's own
    # Python, which is exactly what the host gate refuses. With -LicenseGate the
    # only place a protected core can be exercised is inside the packaged launcher.
    if ($LicenseGate) {
        Write-Host "Host gate is on: deferring the functional smoke test for $Short to the packaged launcher's --native-core-self-test." -ForegroundColor Yellow
    }
    else {
        & $Python -c $m.Smoke.Replace('__PYD__', $Protected)
        if ($LASTEXITCODE -ne 0) { throw "Protected native module import test failed: $($m.Module)" }
    }

    try {
        Copy-Item -LiteralPath $Protected -Destination $m.Output -Force
    }
    catch {
        throw "Cannot replace $($m.Output). Close the running app/Python process that loaded it, then build again."
    }
    Write-Host "Protected native core: $($m.Output)" -ForegroundColor Green
}
}
finally {
    $env:PATH = $OriginalPath
    Pop-Location
}
