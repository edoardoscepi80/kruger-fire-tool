@echo off
setlocal
echo ==============================================================
echo  Building Standalone Binary for Kruger Fire ^& Rainfall DSS
echo ==============================================================
echo.

set "PYTHON_EXE=C:\Users\Utente\AppData\Local\Programs\Python\Python312\python.exe"
set "TOOL_DIR=C:\Users\Utente\.gemini\antigravity\scratch\kruger_fire_tool"

cd /d "%TOOL_DIR%"

"%PYTHON_EXE%" -m PyInstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "KrugerFireDSS" ^
    --icon "%TOOL_DIR%\resources\logo_proges.ico" ^
    --add-data "%TOOL_DIR%\resources;resources" ^
    --add-data "%TOOL_DIR%\version.json;." ^
    "%TOOL_DIR%\main.py"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ==============================================================
    echo  ✔ Standalone binary built successfully in:
    echo  %TOOL_DIR%\dist\KrugerFireDSS\KrugerFireDSS.exe
    echo ==============================================================
) else (
    echo.
    echo [ERROR] PyInstaller build failed!
)
