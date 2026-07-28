@echo off
REM Manual runtime launcher — see start.sh for the full reasoning (identical here, this is
REM its Windows counterpart). Short version: in its final, shipped form this hands off to
REM Supervisor's own Boot Sequence, which isn't real code yet; the one thing that genuinely
REM runs today is Agent Control's gRPC service, so that's what this launches for now.
REM
REM PYTHON_BIN — the interpreter this launches under. Unset on every real end-user install,
REM always (Setup API's own environment detection picks the interpreter there, never this
REM variable). Set it here, in a dev checkout, to hands-on test against a non-default
REM interpreter — e.g. Python 3.15 ahead of a Forward-Compatibility Pattern review
REM (docs/PRINCIPLES.md §3.3.1), separately from noxfile.py's automated `forward_compat` gate.
REM
REM   start.bat                                   :: default pinned interpreter
REM   set PYTHON_BIN=py -3.15 ^&^& start.bat        :: the whole system running under 3.15
REM
REM The Windows `py` launcher (not a bare `python3.15` command) is the standard way to
REM select a specific installed version here — set PYTHON_BIN to "py -3.15", not "python3.15".

setlocal
cd /d "%~dp0"

if not defined PYTHON_BIN set "PYTHON_BIN=python"

%PYTHON_BIN% -m core.agent_control.service %*
