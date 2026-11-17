@echo off
setlocal
title Kruger Fire & Rainfall Management DSS

set "SCRIPT_DIR=%~dp0"
set "MAIN_PY=%SCRIPT_DIR%main.py"

:: 1. Try python in PATH
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python "%MAIN_PY%" %*
    goto :End
)

:: 2. Try common Python 3.12 / 3.11 / 3.10 install paths
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
) do (
    if exist "%%~P" (
        "%%~P" "%MAIN_PY%" %*
        goto :End
    )
)

echo [ERROR] Python 3.x was not found on this computer.
echo Please install Python from https://www.python.org or run the standalone package.
pause
exit /b 1

:End
exit /b 0
