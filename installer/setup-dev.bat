@echo off
REM The bare-bones developer installer (Setup API deep-dive, section 4.1).
REM See setup-dev.sh's own header comment -- same behaviour, Windows counterpart.
REM
REM Plain ASCII only in this file -- see common.bat's own header comment for why.

setlocal
cd /d "%~dp0"

set "INSTALL_ROOT=%~1"
REM Same fix as setup.bat's own: this script's own directory IS the install root.
if "%INSTALL_ROOT%"=="" set "INSTALL_ROOT=%CD%"

call "%~dp0common.bat" :do_bootstrap true "%INSTALL_ROOT%"
exit /b %errorlevel%
