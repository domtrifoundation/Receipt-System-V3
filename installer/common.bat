@echo off
REM Shared bootstrap logic for setup.bat and setup-dev.bat (Setup API deep-dive, section 4).
REM Windows counterpart of common.sh -- same wire contract, same channel-resolution rules, same
REM one-shared-implementation discipline (PRINCIPLES.md section 1.5). Read common.sh's own
REM header comment for the full reasoning; this file states only what differs mechanically on
REM Windows.
REM
REM Plain ASCII only in this file, deliberately -- cmd.exe's batch parser does not reliably
REM handle non-ASCII characters or LF-only line endings, confirmed the hard way while building
REM this (an early UTF-8, LF-only draft made cmd.exe try to execute fragments of prose as
REM commands). This file is CRLF, ASCII-only, on purpose.
REM
REM Called as: call common.bat :do_bootstrap <dev_mode true|false> <install_root>
REM Batch has no real function-return-value mechanism, so every "returning" subroutine below
REM writes its result into a caller-visible variable instead (documented per subroutine).

setlocal enabledelayedexpansion

if "%~1"=="" goto :eof
goto %~1

REM ------------------------------------------------------------------------------------------
:set_defaults
if not defined KEYMASTER_BASE_URL set "KEYMASTER_BASE_URL="
set "REPO_URL=https://github.com/domtrifoundation/Receipt-System-V3"
set "REPO_CLONE_URL=%REPO_URL%.git"
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :resolve_channel_ref <channel> -- sets REF, or sets REF to "" on failure to resolve
:resolve_channel_ref
REM Deliberately flat -- no goto/label lives inside any parenthesized block in this function.
REM Confirmed the hard way while testing this script for real: batch's parenthesized blocks
REM parse unreliably once a goto and a label both live inside one ("was unexpected at this
REM time" from the parser's own paren-matching pre-scan, even for a for/do block).
set "_channel=%~1"
set "REF="

if /i not "%_channel%"=="stable" goto :resolve_channel_ref_try_beta
git ls-remote --exit-code --tags "%REPO_CLONE_URL%" "refs/tags/stable" >nul 2>&1
if not errorlevel 1 set "REF=stable"
exit /b 0

:resolve_channel_ref_try_beta
if /i not "%_channel%"=="beta" goto :resolve_channel_ref_try_alpha
git ls-remote --exit-code --tags "%REPO_CLONE_URL%" "refs/tags/beta" >nul 2>&1
if not errorlevel 1 set "REF=beta"
exit /b 0

:resolve_channel_ref_try_alpha
if /i not "%_channel%"=="alpha" goto :resolve_channel_ref_try_ltsc
git ls-remote --exit-code --tags "%REPO_CLONE_URL%" "refs/tags/alpha" >nul 2>&1
if not errorlevel 1 set "REF=alpha"
exit /b 0

:resolve_channel_ref_try_ltsc
if /i not "%_channel%"=="ltsc" goto :resolve_channel_ref_try_latest
REM Picks the LAST matching ltsc/* branch found, not the first -- avoiding an early-exit goto
REM from inside this for/do loop for the same parenthesized-block reliability reason explained
REM in this function's own header comment. common.sh's own version picks the first (head -n1)
REM instead; a genuine, minor cross-platform difference, worth stating rather than silently
REM having the two disagree. Irrelevant while zero ltsc/* branches exist.
for /f "tokens=2 delims=	" %%b in ('git ls-remote --heads "%REPO_CLONE_URL%" "refs/heads/ltsc/*" 2^>nul') do (
    set "_full=%%b"
    set "REF=!_full:refs/heads/=!"
)
exit /b 0

:resolve_channel_ref_try_latest
if /i not "%_channel%"=="latest_commit" exit /b 0
set "REF=main"
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :prompt_channel -- sets CHANNEL
:prompt_channel
echo.
echo Which channel do you want?
echo   [1] Stable (recommended)
echo   [2] Beta
echo   [3] Alpha
echo   [4] LTSC (long-term support)
echo   [5] Latest development commit
set /p "_choice=Choice [1]: "
if "%_choice%"=="" set "_choice=1"
set "CHANNEL="
if "%_choice%"=="1" set "CHANNEL=stable"
if "%_choice%"=="2" set "CHANNEL=beta"
if "%_choice%"=="3" set "CHANNEL=alpha"
if "%_choice%"=="4" set "CHANNEL=ltsc"
if "%_choice%"=="5" set "CHANNEL=latest_commit"
if not defined CHANNEL set "CHANNEL=stable"
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :prompt_license_key -- sets LICENSE_KEY (possibly empty)
:prompt_license_key
if "%KEYMASTER_BASE_URL%"=="" (
    echo.
    echo Licensing is not yet configured for this pre-release build -- skipping the
    echo license-key step and cloning without one.
    set "LICENSE_KEY="
    exit /b 0
)
set /p "LICENSE_KEY=License key (leave blank to skip): "
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :generate_instance_id -- sets INSTANCE_ID
REM PowerShell's own GUID generator -- deliberately not a hardware fingerprint, same reasoning
REM as common.sh's own generate_instance_id (plan file 02, Branding and Naming).
:generate_instance_id
for /f "delims=" %%i in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString()"') do set "INSTANCE_ID=%%i"
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :keymaster_get_clone_token <license_key> <instance_id> -- sets CLONE_TOKEN (possibly empty)
:keymaster_get_clone_token
set "CLONE_TOKEN="
if "%~1"=="" exit /b 0
if "%KEYMASTER_BASE_URL%"=="" exit /b 0
set "_body_file=%TEMP%\keymaster_response_%RANDOM%.json"
powershell -NoProfile -Command ^
    "try { $r = Invoke-RestMethod -Method Post -Uri '%KEYMASTER_BASE_URL%/v1/clone-tokens' -ContentType 'application/json' -Body (@{license_key='%~1'; instance_id='%~2'} | ConvertTo-Json) -TimeoutSec 10; $r.token } catch { '' }" > "%_body_file%" 2>nul
set /p "CLONE_TOKEN=" < "%_body_file%"
del "%_body_file%" >nul 2>&1
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :trim_trailing_space <var_name> -- strips trailing spaces from the named variable in place
REM
REM The standard batch idiom for this (repeatedly strip one trailing char while the last char
REM is a space) -- confirmed the hard way that `for /f "tokens=* delims= "` does NOT do this,
REM despite looking like it should; that idiom trims LEADING whitespace only.
:trim_trailing_space
setlocal enabledelayedexpansion
set "_tv=!%~1!"
:trim_trailing_space_loop
if not "!_tv:~-1!"==" " goto :trim_trailing_space_done
set "_tv=!_tv:~0,-1!"
goto :trim_trailing_space_loop
:trim_trailing_space_done
endlocal & set "%~1=%_tv%"
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :detect_python_bin -- sets PYTHON_BIN, unless already set by the caller's own environment
REM
REM Confirmed the hard way, not assumed: a bare PYTHON_BIN=python default silently hung on this
REM project's own already-documented Day-0 gap (docs/MAINTENANCE.md section 8.1 -- grpcio has
REM no prebuilt wheel for 3.15, and building it from source has already failed outright in this
REM project's own environment). 3.13 is preferred first, not 3.14: confirmed directly against
REM PyPI that rapidocr-onnxruntime has no build at all for 3.13 or newer in any released
REM version (every 1.3.x/1.4.x release caps at "Requires-Python <3.13"), so 3.14 buys nothing
REM over 3.13 for that specific dependency while every other real requirement (grpcio included)
REM already works on 3.13. rapidocr stays unavailable either way; text_layer/pytesseract/
REM WindowsOCR remain real, working engines on 3.13. 3.14 is the fallback for a machine that
REM has it but not 3.13, ahead of the last-resort bare "python". A two-word value like
REM "py -3.13" works correctly here because batch variable expansion is plain text substitution
REM (%PYTHON_BIN% -m ...), unlike a POSIX shell where the same value would need array handling
REM to avoid being treated as one literal command name (see common.sh's own detect_python_bin
REM for that distinction).
:detect_python_bin
if defined PYTHON_BIN exit /b 0
py -3.13 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_BIN=py -3.13"
    exit /b 0
)
py -3.14 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_BIN=py -3.14"
    exit /b 0
)
set "PYTHON_BIN=python"
exit /b 0

REM ------------------------------------------------------------------------------------------
REM :do_bootstrap <dev_mode> <install_root>
:do_bootstrap
call :set_defaults
set "_dev_mode=%~2"
set "_install_root=%~3"

REM Deliberately flat control flow, not a parenthesized if-block, for the dev-mode confirm
REM step -- confirmed the hard way while testing this script for real that batch's
REM parenthesized "if (...)" blocks parse unreliably once a goto and a label both live inside
REM one ("was unexpected at this time" from the parser's own paren-matching pre-scan). A goto
REM past this whole section when dev_mode is not "true" is the same idea in a shape batch
REM actually handles correctly.
if /i not "%_dev_mode%"=="true" goto :skip_dev_confirm
echo This installs the full development environment -- documentation, test
echo suite, and CI scaffolding. If you just want to run the program, close
echo this and run setup.bat instead.
set /p "_confirm=Continue? [y/N]: "
if /i "!_confirm!"=="y" goto :skip_dev_confirm
if /i "!_confirm!"=="yes" goto :skip_dev_confirm
echo Cancelled.
exit /b 0
:skip_dev_confirm

REM Deliberately flat, no goto inside any parenthesized block -- see this file's own header
REM comment and the do_bootstrap confirm section above for why.
if not defined REF_OVERRIDE goto :prompt_for_channel
REM A real, standing escape hatch, not just a today-only test knob -- see common.sh's own
REM identical feature for the full reasoning. Skips the channel prompt entirely.
REM
REM Trimmed via :trim_trailing_space below -- confirmed the hard way that this matters:
REM `set REF_OVERRIDE=foo && setup-dev.bat` (a completely ordinary way to set an env var
REM before a chained command) leaves a trailing space IN THE VALUE under cmd.exe's own set
REM command semantics, unlike `set "VAR=value"`. Without trimming, that trailing space becomes
REM part of the git ref and the clone fails with a "branch not found" error that looks nothing
REM like a whitespace problem. Confirmed separately that `for /f "tokens=* delims= "` -- the
REM usual batch idiom people reach for here -- trims LEADING whitespace only, not trailing.
set "REF=%REF_OVERRIDE%"
call :trim_trailing_space REF
echo.
echo REF_OVERRIDE set -- bootstrapping %REF% directly, skipping channel selection.
goto :channel_resolved

:prompt_for_channel
call :prompt_channel
call :resolve_channel_ref "%CHANNEL%"
if not "%REF%"=="" goto :channel_resolved
echo.
echo The %CHANNEL% channel doesn't have a release yet -- this project is
echo still in pre-release development. Falling back to the latest
echo development commit instead.
set "REF=main"
:channel_resolved

call :generate_instance_id
call :prompt_license_key
call :keymaster_get_clone_token "%LICENSE_KEY%" "%INSTANCE_ID%"

if not exist "%_install_root%\releases" mkdir "%_install_root%\releases"
set "_tmp_clone_dir=%_install_root%\releases\.bootstrap-clone-%RANDOM%"

echo.
echo Cloning %REF%...
if not "%CLONE_TOKEN%"=="" (
    git clone --branch "%REF%" --depth 1 "https://x-access-token:%CLONE_TOKEN%@github.com/domtrifoundation/Receipt-System-V3.git" "%_tmp_clone_dir%"
) else (
    git clone --branch "%REF%" --depth 1 "%REPO_CLONE_URL%" "%_tmp_clone_dir%"
)
if errorlevel 1 (
    echo Error: clone failed 1>&2
    exit /b 1
)

set "_raw_version="
for /f "tokens=2 delims==" %%v in ('findstr /c:"PROGRAM_VERSION = " "%_tmp_clone_dir%\common\version.py"') do (
    set "_raw_version=%%v"
)
set "_version=!_raw_version: =!"
set "_version=!_version:"=!"
for /f "delims=" %%h in ('git -C "%_tmp_clone_dir%" rev-parse --short HEAD') do set "_commit_hash=%%h"
set "_final_dir=%_install_root%\releases\!_version!_!_commit_hash!"
move "%_tmp_clone_dir%" "%_final_dir%" >nul

echo Cloned into %_final_dir%
echo Handing off to Setup API's own finalize routine...

call :detect_python_bin
echo Using interpreter: %PYTHON_BIN%

REM bootstrap.py itself (run by this bare, no-venv interpreter, before any per-service venv
REM exists) imports common\frozen_dict.py transitively via services\setup\contracts.py -- on
REM any interpreter below 3.15 that needs the real `frozendict` PyPI package, not just the
REM per-service venvs bootstrap.py goes on to create. Confirmed the hard way: a fresh install
REM on a bare 3.13/3.14 interpreter with no `frozendict` already present fails immediately
REM with a raw ModuleNotFoundError before finalize does anything at all. Same environment
REM marker as every other consumer of this shim (common/requirements.txt) -- installing it
REM unconditionally on 3.15+ would be harmless but pointless, since the builtin already wins.
%PYTHON_BIN% -m pip install --quiet "frozendict; python_version < '3.15'"
if errorlevel 1 (
    echo Error: failed to install bootstrap's own frozendict dependency 1>&2
    exit /b 1
)

set "_finalize_args=%_final_dir%"
if /i "%_dev_mode%"=="true" set "_finalize_args=%_final_dir% --dev-mode"

pushd "%_final_dir%"
set "PYTHONPATH=%_final_dir%"
%PYTHON_BIN% -m services.setup.bootstrap %_finalize_args%
set "_finalize_exit=%errorlevel%"
popd

if not "%_finalize_exit%"=="0" (
    echo Error: finalize failed -- see the output above 1>&2
    exit /b 1
)

echo.
echo Done. You are ready to go.
echo Run: %_install_root%\start.bat
exit /b 0


