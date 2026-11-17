@echo off
setlocal enabledelayedexpansion
title Kruger Fire & Rainfall Management DSS

echo =====================================================================
echo  Kruger National Park - Fire & Rainfall Management DSS
echo  PROGES / South African National Parks
echo =====================================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "MAIN_PY=%SCRIPT_DIR%main.py"
set "QGIS_BAT="

:: 1. Check if configured in environment or standard paths
if exist "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" (
    set "QGIS_BAT=C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat"
    goto :FoundQgis
)

:: 2. Search for any python-qgis-ltr.bat in Program Files
for /d %%D in ("C:\Program Files\QGIS 3*") do (
    if exist "%%D\bin\python-qgis-ltr.bat" (
        set "QGIS_BAT=%%D\bin\python-qgis-ltr.bat"
        goto :FoundQgis
    )
    if exist "%%D\bin\python-qgis.bat" (
        set "QGIS_BAT=%%D\bin\python-qgis.bat"
        goto :FoundQgis
    )
)

:: 3. Search OSGeo4W
if exist "C:\OSGeo4W\bin\python-qgis-ltr.bat" (
    set "QGIS_BAT=C:\OSGeo4W\bin\python-qgis-ltr.bat"
    goto :FoundQgis
)
if exist "C:\OSGeo4W64\bin\python-qgis-ltr.bat" (
    set "QGIS_BAT=C:\OSGeo4W64\bin\python-qgis-ltr.bat"
    goto :FoundQgis
)

:NotFound
echo [ERROR] QGIS 3.x LTR Python runtime not found on this computer!
echo.
echo Kruger Fire DSS requires QGIS 3.x (64-bit) to run its spatial GIS algorithms.
echo Please download and install QGIS from: https://qgis.org
echo.
pause
exit /b 1

:FoundQgis
echo Found QGIS Python runtime: "%QGIS_BAT%"
echo Launching Application...
call "%QGIS_BAT%" "%MAIN_PY%"
exit /b 0
