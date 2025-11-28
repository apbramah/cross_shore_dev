@echo off

setlocal enabledelayedexpansion

set "CONFIG=C:\Users\apbra\Downloads\SimpleBGC_GUI_2_70b0\SimpleBGC_GUI_2_70b0\conf\bgc.properties"
set "EXE_PATH=C:\Users\apbra\Downloads\SimpleBGC_GUI_2_70b0\SimpleBGC_GUI_2_70b0\SimpleBGC_GUI.exe"


:: The argument comes in as %1, e.g.:
:: simplebgc://192.168.60.218:8080/

set "url=%~1"

:: 1. Remove "simplebgc://"
set "temp=%url:simplebgc://=%"

:: 2. Remove trailing slash if present
if "!temp:~-1!"=="/" set "temp=!temp:~0,-1!"

:: Now temp = 192.168.60.218:8080

:: 3. Split at the colon
for /f "tokens=1,2 delims=:" %%a in ("!temp!") do (
    set "ip=%%a"
    set "port=%%b"
)

set "newHost=tcp.remote_host=%ip%"
set "newPort=tcp.remote_port=%port%"

> "%CONFIG%.tmp" (
    for /f "usebackq delims=" %%A in ("%CONFIG%") do (
        set "line=%%A"

        rem Replace only the exact matching lines
        if "!line:~0,16!"=="tcp.remote_host=" set "line=!newHost!"
        if "!line:~0,16!"=="tcp.remote_port=" set "line=!newPort!"

        echo !line!
    )
)

move /y "%CONFIG%.tmp" "%CONFIG%" >nul

@echo off
setlocal

:: Get the folder the exe is in
for %%I in ("%EXE_PATH%") do set "EXE_DIR=%%~dpI"

:: Extract the executable name
for %%I in ("%EXE_PATH%") do set "EXE_NAME=%%~nxI"

:: Kill any running instances (forcefully). Note: THIS IS NOT FUTURE-PROOF when the SimpleBGC GUI updates!
taskkill /f /fi "WINDOWTITLE eq SimpleBGC32 GUI v2.70 b0" >nul 2>&1

:: Optional: wait a little to ensure process is terminated
timeout /t 1 >nul

:: Start the exe in its folder
start "" /D "%EXE_DIR%" "%EXE_PATH%"

endlocal
