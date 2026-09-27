[CmdletBinding()]
param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonExecutable) {
        & $PythonExecutable -m venv (Join-Path $projectRoot ".venv")
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.11 -m venv (Join-Path $projectRoot ".venv")
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv (Join-Path $projectRoot ".venv")
    }
    else {
        throw "Python 3.11+ was not found. Install Python, or pass -PythonExecutable with an absolute path."
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Virtual environment creation failed: $venvPython"
    }
}

& $venvPython -m pip install -e $projectRoot

Write-Host "Setup complete. Run scripts\run_daily.ps1 when you are ready to test."
