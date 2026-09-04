@echo off
REM ============================================================
REM  New Era Proofreader v4.1.2 dev launcher (Windows CMD)
REM
REM  Reference 1: https://learn.microsoft.com/en-us/windows/win32/ (Microsoft Docs, CC-BY 4.0)
REM    Borrowed: minimal cmd wrapper (echo off / chcp / cd)
REM    Method: idea only, code self-written
REM    Copyright (c) Microsoft Corporation
REM
REM  v4.1.2: completely delegates to dev_launcher.py
REM    - This .bat is now a 4-line wrapper
REM    - All diagnostics + launching logic in dev_launcher.py (UTF-8, no GBK issues)
REM    - .ps1 wrapper does the same (cross-platform consistent)
REM
REM  Usage: double-click this file
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"
python dev_launcher.py
pause
