param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = (& $Python -c "import runpy; print(runpy.run_path(r'$Root\version.py')['APP_VERSION'])").Trim()
$Name64 = (& $Python -c "import base64,runpy; print(base64.b64encode(runpy.run_path(r'$Root\version.py')['APP_NAME'].encode()).decode())").Trim()
$ProductName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Name64))
$Release = Join-Path $Root "dist-protected\${ProductName}_V$Version"
$BaseName = "${ProductName}_V$Version"
$Launcher = Join-Path $Release "$BaseName.exe"
$Protected = Join-Path $Release "$BaseName.sp.exe"
$BackupDir = Join-Path $Root "build\protected\sprotect-backups"
$Backup = Join-Path $BackupDir "$BaseName.unprotected.exe"

foreach ($path in @($Launcher, $Protected)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file not found: $path" }
    if ((Get-Item -LiteralPath $path).Length -lt 65536) { throw "Executable is unexpectedly small: $path" }
}
$OriginalHash = (Get-FileHash -LiteralPath $Launcher -Algorithm SHA256).Hash
$ProtectedHash = (Get-FileHash -LiteralPath $Protected -Algorithm SHA256).Hash
if ($OriginalHash -eq $ProtectedHash) { throw "SProtect output is identical to the original launcher" }
if (Test-Path -LiteralPath $Backup) { throw "Backup already exists; release was probably finalized: $Backup" }

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Move-Item -LiteralPath $Launcher -Destination $Backup
try {
    Move-Item -LiteralPath $Protected -Destination $Launcher
}
catch {
    Move-Item -LiteralPath $Backup -Destination $Launcher
    throw
}

$FinalHash = (Get-FileHash -LiteralPath $Launcher -Algorithm SHA256).Hash
$Manifest = "$FinalHash  $BaseName.exe`r`n"
[IO.File]::WriteAllText((Join-Path $Release "SHA256SUMS.txt"), $Manifest, [Text.Encoding]::ASCII)
Remove-Item -LiteralPath (Join-Path $Release "SPROTECT-NEXT-STEP.txt") -Force -ErrorAction SilentlyContinue

Write-Host "SProtect release finalized: $Launcher" -ForegroundColor Green
Write-Host "Original launcher backup: $Backup" -ForegroundColor Yellow
Write-Host "SHA256: $FinalHash"
