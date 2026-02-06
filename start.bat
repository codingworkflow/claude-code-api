@echo off
setlocal
call "%~dp0make.bat" start %*
exit /b %ERRORLEVEL%
