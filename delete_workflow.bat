@echo off
setlocal

echo Starting RITZZ project cleanup...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0delete_workflow.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo.
    echo SUCCESS: project cleanup completed.
) else (
    echo.
    echo FAILED: project cleanup exited with code %EXIT_CODE%.
)

echo.
pause
exit /b %EXIT_CODE%
