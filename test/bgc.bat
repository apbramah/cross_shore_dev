@echo off

:: Path to the log file
set LOGFILE=C:\Users\apbra\Documents\cross_shore_dev\test\bgc_log.txt

setlocal enabledelayedexpansion

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

echo IP = %ip% >> "%LOGFILE%"
echo PORT = %port% >> "%LOGFILE%"
