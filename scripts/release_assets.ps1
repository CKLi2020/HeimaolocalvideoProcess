function Test-RequiredReleaseAssets([string]$SourceRoot) {
    $Resources = Join-Path $SourceRoot "resources"
    if (-not (Test-Path -LiteralPath $Resources -PathType Container)) {
        throw "Required release directory not found: $Resources"
    }
}

function Copy-ReleaseAssets([string]$SourceRoot, [string]$ReleaseRoot) {
    Test-RequiredReleaseAssets $SourceRoot
    New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceRoot "resources") -Destination $ReleaseRoot -Recurse -Force
    $OptionalAssets = @(
        (-join ([char[]]@(0x8D34, 0x7EB8))),
        (-join ([char[]]@(0x914D, 0x7F6E, 0x6587, 0x4EF6)))
    )
    foreach ($Name in $OptionalAssets) {
        $Source = Join-Path $SourceRoot $Name
        if (Test-Path -LiteralPath $Source -PathType Container) {
            Copy-Item -LiteralPath $Source -Destination $ReleaseRoot -Recurse -Force
        }
        elseif (Test-Path -LiteralPath $Source) {
            throw "Optional release asset path is not a directory: $Source"
        }
        else {
            New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseRoot $Name) | Out-Null
            Write-Warning "Optional release assets not found: $Source. Created an empty directory; the app will use built-in defaults or user-selected media."
        }
    }
}
