[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $projectRoot "config"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $projectRoot "logs"
$projectToml = Get-Content -Raw -LiteralPath (Join-Path $projectRoot "pyproject.toml")
$versionMatch = [regex]::Match($projectToml, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { throw "Unable to read project version from pyproject.toml" }
$expectedVersion = $versionMatch.Groups[1].Value
$url = "http://127.0.0.1:$Port/"
$statusUrl = "${url}api/status"

function Get-ControlCenterStatus {
    try {
        return Invoke-RestMethod -UseBasicParsing -Uri $statusUrl -TimeoutSec 2
    }
    catch { return $null }
}

$existingStatus = Get-ControlCenterStatus
if ($existingStatus -and $existingStatus.app_version -eq $expectedVersion) {
    Write-Host "The control center $expectedVersion is already running. Opening the browser..."
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

if ($existingStatus -and $existingStatus.app_version) {
    Write-Host "A stale control center version $($existingStatus.app_version) is running; updating it to $expectedVersion."
    try {
        Invoke-RestMethod -UseBasicParsing -Method Post -Uri "${url}api/shutdown" `
            -ContentType "application/json" -Body "{}" -TimeoutSec 3 | Out-Null
    }
    catch { }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-ControlCenterStatus)) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-ControlCenterStatus) {
        throw "The old control center did not stop. Run the stop-control-center command, then start again."
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Project environment not found. Starting first-run setup."
    & (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "First-run setup failed" }
}

& $venvPython -c "import yaml, feedparser, requests, bs4, newsletter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Project dependencies are incomplete. Repairing the environment."
    & (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Dependency repair failed" }
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$arguments = @("-m", "newsletter.webapp", "--config", $configDir, "--port", "$Port")
if ($NoBrowser) { $arguments += "--no-browser" }

Write-Host "Private Newsletter $expectedVersion"
Write-Host "Starting the control center: $url"
Write-Host "Keep this window open while using the browser. Close it to stop the service."
Write-Host ""
& $venvPython @arguments
if ($LASTEXITCODE -ne 0) { throw "The control center exited with code $LASTEXITCODE" }
