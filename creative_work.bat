@echo off
setlocal

echo Starting RITZZ creative package workflow...
if not "%~1"=="" goto run_with_arguments

set "INPUT_DIRECTORY="
set /p "INPUT_DIRECTORY=Enter the staging folder path: "
if not defined INPUT_DIRECTORY goto missing_input
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0creative_work.ps1" -InputDirectory "%INPUT_DIRECTORY%"
goto capture_result

:run_with_arguments
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0creative_work.ps1" %*
goto capture_result

:capture_result
set "EXIT_CODE=%ERRORLEVEL%"
goto display_result

:missing_input
echo.
echo FAILED: a staging folder path is required.
set "EXIT_CODE=1"

:display_result
if "%EXIT_CODE%"=="0" (
    echo.
    echo SUCCESS: creative package workflow completed.
) else (
    echo.
    echo FAILED: creative package workflow exited with code %EXIT_CODE%.
)

echo.
pause
exit /b %EXIT_CODE%
