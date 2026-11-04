@echo off
title XinRefinement source mode
REM ===================================================================
REM  XinRefinement source-mode launcher for manual acceptance testing.
REM  Runs the working tree in place (python -m xinrefinement.gui), so it
REM  is always the current code and needs no PyInstaller build.
REM
REM  Usage:
REM    run_dev.bat                                 launch the GUI
REM    run_dev.bat refine pat.xy phase.cif -o r.json   run the CLI
REM    run_dev.bat --version                       print version
REM    run_dev.bat --recipe --report out --esd ...     same as above,
REM                                                recipe/report/esd flags
REM
REM  Interpreter selection, first match wins:
REM    1. %XINREFINEMENT_DEV_PYTHON%  explicit override
REM    2. .venv\Scripts\python.exe
REM    3. venv\Scripts\python.exe
REM    4. D:\Project\XRD\python310\python.exe
REM    5. whatever "python" resolves to on PATH
REM
REM  KEEP THIS FILE ASCII-ONLY WITH CRLF LINE ENDINGS, AND DO NOT ADD:
REM    - parentheses inside echo text or any if-line
REM    - multi-line if-blocks
REM    - setlocal / endlocal, they discard variables before the
REM      errorlevel checks below can read them
REM    - goto labels
REM  cmd.exe parses a whole if-block before running it, so one stray
REM  bracket in an echo line kills the script and the window just
REM  flashes and closes.
REM ===================================================================
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PY="
if defined XINREFINEMENT_DEV_PYTHON set "PY=%XINREFINEMENT_DEV_PYTHON%"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY if exist "D:\Project\XRD\python310\python.exe" set "PY=D:\Project\XRD\python310\python.exe"
if not defined PY set "PY=python"

echo [XinRefinement] source mode - launching...
echo [XinRefinement] python: %PY%
echo.

if "%~1"=="" "%PY%" -m xinrefinement.gui
if not "%~1"=="" "%PY%" -m xinrefinement.cli %*

if errorlevel 1 echo.
if errorlevel 1 echo [XinRefinement] startup failed - the error is printed above.
if errorlevel 1 echo [XinRefinement] press any key to close this window.
if errorlevel 1 pause
