@echo off
setlocal enabledelayedexpansion

if "%~1"=="" goto :help

set "TARGET=%~1"
shift
set "EXTRA_ARGS="
:collect_args
if "%~1"=="" goto :args_done
set "EXTRA_ARGS=!EXTRA_ARGS! %~1"
shift
goto :collect_args
:args_done

if /I "%TARGET%"=="help" goto :help

call :find_python
if errorlevel 1 exit /b 1

if /I "%TARGET%"=="install" goto :install
if /I "%TARGET%"=="install-dev" goto :install_dev
if /I "%TARGET%"=="start" goto :start
if /I "%TARGET%"=="start-prod" goto :start_prod
if /I "%TARGET%"=="test" goto :test
if /I "%TARGET%"=="test-no-cov" goto :test_no_cov
if /I "%TARGET%"=="fmt" goto :fmt
if /I "%TARGET%"=="lint" goto :lint

echo [ERROR] Unknown target: %TARGET%
goto :help

:find_python
set "PYTHON_CMD=python"
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 goto :eof

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PYTHON_CMD=py -3"
  goto :eof
)

echo [ERROR] Python not found in PATH.
exit /b 1

:install
%PYTHON_CMD% -m pip install -e .
exit /b %ERRORLEVEL%

:install_dev
%PYTHON_CMD% -m pip install -e ".[test,dev]"
exit /b %ERRORLEVEL%

:start
%PYTHON_CMD% -m uvicorn claude_code_api.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude=*.db* --reload-exclude=*.log
exit /b %ERRORLEVEL%

:start_prod
%PYTHON_CMD% -m uvicorn claude_code_api.main:app --host 0.0.0.0 --port 8000
exit /b %ERRORLEVEL%

:test
%PYTHON_CMD% -m pytest --cov=claude_code_api --cov-report=html tests/ -v %EXTRA_ARGS%
exit /b %ERRORLEVEL%

:test_no_cov
%PYTHON_CMD% -m pytest tests/ -v %EXTRA_ARGS%
exit /b %ERRORLEVEL%

:fmt
%PYTHON_CMD% -m black claude_code_api tests
exit /b %ERRORLEVEL%

:lint
%PYTHON_CMD% -m flake8 claude_code_api tests
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
%PYTHON_CMD% -m isort --check-only claude_code_api tests
exit /b %ERRORLEVEL%

:help
echo Claude Code API - Windows helper commands
echo.
echo Usage:
echo   make.bat ^<target^>
echo.
echo Targets:
echo   install
echo   install-dev
echo   start
echo   start-prod
echo   test
echo   test-no-cov
echo   fmt
echo   lint
echo   help
exit /b 0
