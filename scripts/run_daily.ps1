[CmdletBinding()]
param(
    [string]$RunDate = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $projectRoot "config"
$logDir = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$launcherLog = Join-Path $logDir ("launcher-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
$exitCode = 1

Start-Transcript -Path $launcherLog -Append | Out-Null
try {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Project virtual environment is missing. Run scripts\setup.ps1 first."
    }

    if ($RunDate) {
        & $venvPython -m newsletter run --date $RunDate --config $configDir
    }
    else {
        & $venvPython -m newsletter run --config $configDir
    }
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    try {
        Stop-Transcript | Out-Null
    }
    catch { }
}
exit $exitCode
