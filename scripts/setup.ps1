[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$toolsDir = Join-Path $projectRoot ".tools"
$uvExe = Join-Path $toolsDir "uv.exe"
$uvVersion = "0.12.19"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $toolsDir "python"
$env:UV_CACHE_DIR = Join-Path $toolsDir "cache"

function Install-VerifiedUv {
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    switch ($architecture) {
        "X64" {
            $asset = "uv-x86_64-pc-windows-msvc.zip"
            $expectedHash = "6dbb02d79e419522f1c500f0adb1cddcff0cda7d59b0d66ea7f5e3b4a1b2f5f0"
        }
        "Arm64" {
            $asset = "uv-aarch64-pc-windows-msvc.zip"
            $expectedHash = "115b54cb823bc48260670f5782001add6067ac8d98d18c8263a833704e287de9"
        }
        default { throw "Unsupported Windows architecture: $architecture" }
    }

    $downloadUrl = "https://releases.astral.sh/github/uv/releases/download/$uvVersion/$asset"
    $downloadPath = Join-Path ([IO.Path]::GetTempPath()) ("private-newsletter-uv-{0}-{1}.zip" -f $uvVersion, $PID)
    $extractPath = Join-Path $toolsDir ("uv-extract-{0}" -f $PID)
    Write-Host "[First run] Downloading verified uv $uvVersion..."
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $downloadPath
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $downloadPath).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "uv archive checksum mismatch; expected $expectedHash, got $actualHash"
        }
        Expand-Archive -LiteralPath $downloadPath -DestinationPath $extractPath -Force
        $downloadedUv = Get-ChildItem -LiteralPath $extractPath -Recurse -Filter "uv.exe" -File | Select-Object -First 1
        if (-not $downloadedUv) { throw "uv.exe was not found in the verified archive" }
        Copy-Item -LiteralPath $downloadedUv.FullName -Destination $uvExe -Force
    }
    finally {
        if (Test-Path -LiteralPath $downloadPath) { Remove-Item -LiteralPath $downloadPath -Force }
        if (Test-Path -LiteralPath $extractPath) { Remove-Item -LiteralPath $extractPath -Recurse -Force }
    }
}

if (-not (Test-Path -LiteralPath $uvExe)) {
    Install-VerifiedUv
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Test-Path -LiteralPath $venvPath) {
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    }
    Write-Host "[First run] Preparing project-local Python 3.12 (no administrator required)..."
    & $uvExe venv --python 3.12 $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the project virtual environment" }
}

Write-Host "Installing or updating project dependencies..."
& $uvExe pip install --python $venvPython -e $projectRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to install project dependencies" }

& $venvPython -c "import yaml, feedparser, requests, bs4, newsletter"
if ($LASTEXITCODE -ne 0) { throw "Installed environment validation failed" }

Write-Host "Environment setup completed."
