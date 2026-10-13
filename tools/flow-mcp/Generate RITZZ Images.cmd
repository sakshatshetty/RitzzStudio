@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 (
  echo ERROR: Could not switch to the Flow MCP folder.
  pause
  exit /b 1
)

set "NODE_EXE="
where node >nul 2>nul
if not errorlevel 1 set "NODE_EXE=node"
if not defined NODE_EXE if defined RITZZ_NODE_EXE if exist "%RITZZ_NODE_EXE%" set "NODE_EXE=%RITZZ_NODE_EXE%"
if not defined NODE_EXE if exist "D:\AIStudio\tools\node-v24.20.0-win-x64\node.exe" set "NODE_EXE=D:\AIStudio\tools\node-v24.20.0-win-x64\node.exe"
if not defined NODE_EXE (
  echo ERROR: Node.js was not found on PATH or in the configured tools folder.
  pause
  exit /b 1
)

if not exist "scripts\ritzz-generate-flow-images.mjs" (
  echo ERROR: RITZZ image-generation script is missing.
  pause
  exit /b 1
)

if /i "%~1"=="--dry-run" (
  echo Validating the creative brief without contacting Flow...
) else (
  echo Starting Flow for this run, loading the single creative brief from the temp folder, and generating images...
)
"%NODE_EXE%" "%~dp0scripts\run-ritzz-image-generation.mjs" %*
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
  echo.
  echo SUCCESS: Flow images are staged for review.
  echo Review them before creating the GitHub release.
) else (
  echo.
  echo FAILED: RITZZ image generation exited with code %EXIT_CODE%.
  echo Check the Flow Studio window for session or generation errors.
)

if /i "%~1"=="--dry-run" exit /b %EXIT_CODE%

echo.
pause
exit /b %EXIT_CODE%
