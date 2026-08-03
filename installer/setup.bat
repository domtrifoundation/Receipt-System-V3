@echo off
REM The normal, immersive first-run installer (Setup API deep-dive, section 4.1).
REM See setup.sh's own header comment -- same behaviour, Windows counterpart. Real logic lives
REM in common.bat, shared with setup-dev.bat (PRINCIPLES.md section 1.5).
REM
REM Plain ASCII only in this file -- see common.bat's own header comment for why.

setlocal
cd /d "%~dp0"

set "INSTALL_ROOT=%~1"
if "%INSTALL_ROOT%"=="" set "INSTALL_ROOT=%CD%\resibo"

call "%~dp0common.bat" :do_bootstrap false "%INSTALL_ROOT%"
exit /b %errorlevel%
