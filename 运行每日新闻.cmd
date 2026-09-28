@echo off
setlocal
title Private Newsletter Control Center

set "PROJECT_ROOT=%~dp0"

echo.
echo   Private Newsletter 2.2.3
echo   Starting the local control center...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\start_control_center.ps1"
if errorlevel 1 goto :failure
goto :end

:failure
echo.
echo [STARTUP FAILED] Review the message above and logs\control-center.stderr.log.
pause
exit /b 1

:end
endlocal
