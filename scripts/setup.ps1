[CmdletBinding()]
param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Assert-SupportedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @()
    )
    & $Command @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 or newer is required."
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonExecutable) {
        Assert-SupportedPython -Command $PythonExecutable
        & $PythonExecutable -m venv (Join-Path $projectRoot ".venv")
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Assert-SupportedPython -Command "py" -Arguments @("-3")
        py -3 -m venv (Join-Path $projectRoot ".venv")
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        Assert-SupportedPython -Command "python"
        python -m venv (Join-Path $projectRoot ".venv")
    }
    else {
        throw "Python 3.11+ was not found. Install Python, or pass -PythonExecutable with an absolute path."
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Virtual environment creation failed: $venvPython"
    }
}

Assert-SupportedPython -Command $venvPython

& $venvPython -m pip install -e $projectRoot

Write-Host "Setup complete. Double-click 运行每日新闻.cmd to open Private Newsletter 控制中心."
