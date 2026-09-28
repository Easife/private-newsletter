@echo off
setlocal
title Stop Private Newsletter Control Center

echo Stopping the local control center...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:8765/api/shutdown' -ContentType 'application/json' -Body '{}' -TimeoutSec 3 ^| Out-Null; Write-Host 'Control center stopped.' } catch { Write-Host 'The control center is not running.' }"
endlocal
