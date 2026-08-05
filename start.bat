@echo off
REM Manual runtime launcher. Hands off to Supervisor's own real fleet-boot entrypoint
REM (supervisor/__main__.py), run from Supervisor's own top-level install
REM (supervisor/install.py's install_supervisor() -- this directory's supervisor\ folder
REM is a real, permanent copy, never inside a release clone, per docs/PRINCIPLES.md
REM section 1.6). Supervisor's own venv (supervisor\.venv\) is separate from every
REM service's -- it only needs grpc, never a clone's full dependency set.

setlocal
cd /d "%~dp0"

set "SUP_PY=%~dp0supervisor\.venv\Scripts\python.exe"
if not exist "%SUP_PY%" (
    echo Supervisor's own venv is missing at supervisor\.venv\ -- run setup first.
    exit /b 1
)

"%SUP_PY%" -m supervisor %*
