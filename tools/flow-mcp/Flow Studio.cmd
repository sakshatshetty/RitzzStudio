@echo off
rem Double-click to start the Flow Studio panel on Windows. Close this window to stop it.
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

if not exist dist\studio.js (
  set "NPM_CMD="
  where npm >nul 2>nul
  if not errorlevel 1 set "NPM_CMD=npm"
  if not defined NPM_CMD if defined RITZZ_NPM_CMD if exist "%RITZZ_NPM_CMD%" set "NPM_CMD=%RITZZ_NPM_CMD%"
  if not defined NPM_CMD if exist "D:\AIStudio\tools\node-v24.20.0-win-x64\npm.cmd" set "NPM_CMD=D:\AIStudio\tools\node-v24.20.0-win-x64\npm.cmd"
  if not defined NPM_CMD (
    echo ERROR: Flow Studio needs a build, but npm was not found.
    pause
    exit /b 1
  )
  call "%NPM_CMD%" run build
  if errorlevel 1 (
    echo ERROR: Flow Studio build failed.
    pause
    exit /b 1
  )
)

"%NODE_EXE%" dist\studio.js
if errorlevel 1 echo ERROR: Flow Studio did not start successfully.
pause
