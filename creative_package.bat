@echo off
setlocal

call "%~dp0creative_work.bat" %*
exit /b %ERRORLEVEL%
