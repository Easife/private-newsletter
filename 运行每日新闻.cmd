@echo off
setlocal
chcp 65001 >nul
title Private Newsletter 控制中心

set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"

echo.
echo   Private Newsletter 2.2.0
echo   正在准备本机控制台……
echo.

if not exist "%VENV_PYTHON%" (
    echo [首次运行] 未发现项目虚拟环境，将自动执行一次安装。
    echo 安装过程需要可用的 Python 3.11+ 和网络连接。
    echo.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\setup.ps1"
    if errorlevel 1 goto :failure
)

"%VENV_PYTHON%" -c "import yaml, feedparser, requests, bs4" >nul 2>&1
if errorlevel 1 (
    echo [修复环境] 依赖不完整，正在重新执行安装。
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\setup.ps1"
    if errorlevel 1 goto :failure
)

echo 控制台将在浏览器中打开：http://127.0.0.1:8765/
echo 请保留本窗口；关闭窗口会停止本机控制服务，但不会中断已完成的简报。
echo.
"%VENV_PYTHON%" -m newsletter.webapp --config "%PROJECT_ROOT%config"
if errorlevel 1 goto :failure
goto :end

:failure
echo.
echo [启动失败] 请查看上面的错误信息。窗口将保持打开。
pause
exit /b 1

:end
endlocal
