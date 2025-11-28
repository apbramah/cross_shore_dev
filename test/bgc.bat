@echo off

:: Path to the log file
set LOGFILE=C:\Users\apbra\Documents\cross_shore_dev\test\bgc_log.txt

echo ---- New Call ---- >> "%LOGFILE%"
echo %date% %time% >> "%LOGFILE%"
echo Arguments: %* >> "%LOGFILE%"
echo. >> "%LOGFILE%"
