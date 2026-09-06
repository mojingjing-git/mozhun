@echo off
REM ============================================================
REM  MoZhun - unified launcher (thin wrapper)
REM
REM  All logic lives in start.py (UTF-8, no codepage issues).
REM  Keep this file ASCII-only (project convention since v4.1.2:
REM  cmd GBK codepage mis-parses non-ASCII batch files).
REM
REM  Usage: double-click            -> smart mode (exe first, else dev)
REM         start.py dev / exe / check via: python start.py <mode>
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"

REM v4.1.8.2 (audit K9): fall back to py launcher when python is not on PATH
where python >nul 2>nul
if %errorlevel%==0 (
  python start.py %*
) else (
  py -3 start.py %*
)
set EXITCODE=%errorlevel%
if not "%EXITCODE%"=="0" echo [FAIL] start.py exited with code %EXITCODE%
pause
exit /b %EXITCODE%
