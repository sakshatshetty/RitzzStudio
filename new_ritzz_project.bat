@echo off
setlocal

set "PROJECT_ID=%~1"
set "TOPIC=%~2"
set "DURATION=%~3"

if "%PROJECT_ID%"=="" set /p "PROJECT_ID=Project ID: "
if "%TOPIC%"=="" set /p "TOPIC=Topic: "
if "%DURATION%"=="" set /p "DURATION=Target duration (minutes): "

if "%PROJECT_ID%"=="" goto :missing
if "%TOPIC%"=="" goto :missing
if "%DURATION%"=="" goto :missing

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0New-RitzzProject.ps1" -ProjectId "%PROJECT_ID%" -Topic "%TOPIC%" -TargetDurationMinutes "%DURATION%"
exit /b %errorlevel%

:missing
echo Project ID, topic, and target duration are all required.
exit /b 1
