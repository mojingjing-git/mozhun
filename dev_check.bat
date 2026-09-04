@echo off
REM ============================================================
REM  New Era Proofreader v4.1.2 environment diagnostic (Windows CMD)
REM
REM  v4.1.2: delegates to dev_launcher.py --check
REM    - Same diagnostic as before, but in Python (UTF-8 safe)
REM    - No nested PowerShell quotes, no GBK parse issues
REM ============================================================

chcp 65001 >nul
cd /d "%~dp0"
python dev_launcher.py --check
pause
