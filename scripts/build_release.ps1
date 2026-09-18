param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$version = '0.2.0'
$artifactName = "DiskScope-v$version-test-windows-x64"
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$frontend = Join-Path $projectRoot 'frontend'
$buildRoot = Join-Path $projectRoot 'build\m9-release'
$pyinstallerDist = Join-Path $buildRoot 'dist'
$pyinstallerWork = Join-Path $buildRoot 'work'
$releaseRoot = Join-Path $projectRoot 'release'
$releaseDirectory = Join-Path $releaseRoot $artifactName
$zipPath = Join-Path $releaseRoot "$artifactName.zip"
$checksumPath = "$zipPath.sha256"

function Assert-ProjectChild([string]$path) {
    $resolved = [IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing path outside project: $resolved"
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Missing .venv Python. Run setup.bat first.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js is required on the release build machine.'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm is required on the release build machine.'
}

& $python -c "import struct,sys; assert sys.version_info[:2] >= (3,11) and sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) { throw 'Release build requires supported 64-bit Python.' }

if (-not $SkipDependencyInstall) {
    & $python -m pip install -r (Join-Path $projectRoot 'packaging\build-requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller dependency installation failed.' }
}

& npm.cmd --prefix $frontend ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
& npm.cmd --prefix $frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

foreach ($target in @($buildRoot, $releaseDirectory, $zipPath, $checksumPath)) {
    Assert-ProjectChild $target
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $buildRoot, $releaseRoot -Force | Out-Null

& $python -m PyInstaller --noconfirm --clean `
    --distpath $pyinstallerDist --workpath $pyinstallerWork `
    (Join-Path $projectRoot 'packaging\DiskScope.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$packagedApplication = Join-Path $pyinstallerDist 'DiskScope'
if (-not (Test-Path -LiteralPath (Join-Path $packagedApplication 'DiskScope.exe'))) {
    throw 'Packaged executable was not produced.'
}
Copy-Item -LiteralPath $packagedApplication -Destination $releaseDirectory -Recurse
New-Item -ItemType Directory -Path (Join-Path $releaseDirectory 'data') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $releaseDirectory 'logs') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $releaseDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\QUICKSTART.md') -Destination $releaseDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\THIRD-PARTY-NOTICES.txt') -Destination $releaseDirectory
Set-Content -LiteralPath (Join-Path $releaseDirectory 'VERSION.txt') -Value $version -Encoding ascii

Compress-Archive -LiteralPath $releaseDirectory -DestinationPath $zipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$hash  $artifactName.zip" -Encoding ascii

Write-Output "Release directory: $releaseDirectory"
Write-Output "Release archive: $zipPath"
Write-Output "SHA-256: $hash"
