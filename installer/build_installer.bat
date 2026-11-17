@echo off
setlocal
echo ==============================================================
echo  Compiling Windows Installer for Kruger Fire & Rainfall DSS
echo ==============================================================
echo.

set "ISCC_PATH=C:\Users\Utente\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_PATH%" (
    set "ISCC_PATH=iscc.exe"
)

"%ISCC_PATH%" "%~dp0kruger_setup.iss"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ==============================================================
    echo  ✔ SUCCESS! Windows Installer created:
    echo  Location: %~dp0..\dist\Setup_Kruger_Fire_Tool_v1.0.0.exe
    echo ==============================================================
) else (
    echo.
    echo [ERROR] Compilation failed with error code %ERRORLEVEL%.
)
