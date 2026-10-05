param(
    [string]$Python = "python",
    [string]$ReleasePrivateKey = "C:\Users\KK198\.blackcat-release\manifest-private.pem"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = (& $Python -c "import runpy; print(runpy.run_path(r'$Root\version.py')['APP_VERSION'])").Trim()
$Name64 = (& $Python -c "import base64,runpy; print(base64.b64encode(runpy.run_path(r'$Root\version.py')['APP_NAME'].encode()).decode())").Trim()
$ProductName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Name64))
$ProductId = (& $Python -c "import runpy; print(runpy.run_path(r'$Root\version.py')['APP_ID'])").Trim()
if ($LASTEXITCODE -ne 0 -or -not $ProductId) { throw "version.py must define APP_ID" }
$Release = Join-Path $Root "dist-protected\${ProductName}_V$Version"
$BaseName = "${ProductName}_V$Version"
$Launcher = Join-Path $Release "$BaseName.exe"
$Protected = Join-Path $Release "$BaseName.sp.exe"
$BackupDir = Join-Path $Root "build\protected\sprotect-backups"
$Backup = Join-Path $BackupDir "$BaseName.unprotected.exe"
$Core = Join-Path $Release "app\_flowcut_core.pyd"
$ManifestScript = Join-Path $PSScriptRoot "build_release_manifest.py"

foreach ($path in @($Launcher, $Protected, $Core, $ManifestScript, $ReleasePrivateKey)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file not found: $path" }
}
foreach ($path in @($Launcher, $Protected, $Core)) {
    if ((Get-Item -LiteralPath $path).Length -lt 65536) { throw "Executable is unexpectedly small: $path" }
}
# The signing key is the root of release trust. Keep it out of the repository and
# make sure a leaked file alone is not enough to sign a forgery: the passphrase
# comes from the environment and is never written anywhere.
$RootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
$KeyFull = [IO.Path]::GetFullPath($ReleasePrivateKey)
if ($KeyFull.StartsWith($RootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release signing key must live outside the repository: $KeyFull"
}
if ((Get-Content -LiteralPath $ReleasePrivateKey -Raw) -notmatch "ENCRYPTED") {
    throw "Release signing key is not passphrase-protected. Create an encrypted one with scripts/make_release_signing_key.py: $KeyFull"
}
if (-not $env:BLACKCAT_RELEASE_KEY_PASSWORD) {
    throw "Set BLACKCAT_RELEASE_KEY_PASSWORD to the signing key passphrase before finalizing a release."
}
# Check the key before swapping any files: a key that does not match the
# _PUBLIC_KEY compiled into this build would sign a manifest the app rejects.
& $Python $ManifestScript --release-root $Release --private-key $ReleasePrivateKey `
    --build-id "$ProductId-$Version" --check-key-only
if ($LASTEXITCODE -ne 0) { throw "Release signing key preflight failed" }
$OriginalHash = (Get-FileHash -LiteralPath $Launcher -Algorithm SHA256).Hash
$ProtectedHash = (Get-FileHash -LiteralPath $Protected -Algorithm SHA256).Hash
if ($OriginalHash -eq $ProtectedHash) { throw "SProtect output is identical to the original launcher" }
if (Test-Path -LiteralPath $Backup) { throw "Backup already exists; release was probably finalized: $Backup" }

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Move-Item -LiteralPath $Launcher -Destination $Backup
try {
    Move-Item -LiteralPath $Protected -Destination $Launcher
    & $Python $ManifestScript --release-root $Release `
        --private-key $ReleasePrivateKey --build-id "$ProductId-$Version" --product-id $ProductId
    if ($LASTEXITCODE -ne 0) { throw "Generating the signed release manifest failed" }
    # Last gate before declaring the release done: SProtect rewrote the launcher
    # and VMProtect rewrote the cores, so confirm from outside that the packaged
    # app will still start -- signed manifest intact, both cores still loadable,
    # no plaintext algorithm in the tree.
    & $Python (Join-Path $PSScriptRoot "verify_release.py") --release-root $Release
    if ($LASTEXITCODE -ne 0) { throw "Release self-check failed; not shipping this build" }
}
catch {
    Remove-Item -LiteralPath (Join-Path $Release "manifest.json"), (Join-Path $Release "manifest.sig") `
        -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $Launcher) {
        Move-Item -LiteralPath $Launcher -Destination $Protected -Force
    }
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
