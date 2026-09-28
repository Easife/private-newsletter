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
$url = "http://127.0.0.1:$Port/"
$statusUrl = "${url}api/status"

function Test-ControlCenter {
    try {
        $status = Invoke-RestMethod -UseBasicParsing -Uri $statusUrl -TimeoutSec 2
        return [bool]$status.app_version
    }
    catch { return $false }
}

if (Test-ControlCenter) {
    Write-Host "The control center is already running. Opening the browser..."
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
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
$stdoutLog = Join-Path $logDir "control-center.stdout.log"
$stderrLog = Join-Path $logDir "control-center.stderr.log"
$arguments = "-m newsletter.webapp --config `"$configDir`" --port $Port --no-browser"
$process = Start-Process -FilePath $venvPython -ArgumentList $arguments `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (Test-ControlCenter) {
        Set-Content -LiteralPath (Join-Path $logDir "control-center.pid") -Value $process.Id -Encoding ascii
        Write-Host "Control center started: $url"
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    if ($process.HasExited) { break }
    Start-Sleep -Milliseconds 500
}

$details = ""
if (Test-Path -LiteralPath $stderrLog) {
    $details = (Get-Content -LiteralPath $stderrLog -Tail 20) -join [Environment]::NewLine
}
throw "The control center failed to start.$([Environment]::NewLine)$details"
