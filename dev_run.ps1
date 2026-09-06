# ============================================================
#  New Era Proofreader v4.1.2 dev launcher (Windows PowerShell)
#
#  Reference 1: https://learn.microsoft.com/en-us/powershell/ (Microsoft Docs, CC-BY 4.0)
#    Borrowed: minimal PowerShell wrapper pattern
#    Method: idea only, code self-written
#    Copyright (c) Microsoft Corporation
#
#  v4.1.2: completely delegates to dev_launcher.py
#    - This .ps1 is a 6-line wrapper
#    - All diagnostics + launching in dev_launcher.py (UTF-8 safe)
#    - .bat wrapper does the same (no GBK parse risk)
#
#  Usage: powershell -ExecutionPolicy Bypass -File dev_run.ps1
#         or: .\dev_run.ps1  (if ExecutionPolicy already set)
# ============================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location $PSScriptRoot
# v4.1.8.2 (审计 K9): python 不在 PATH 时回退 py launcher
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { python dev_launcher.py } else { py -3 dev_launcher.py }
$code = $LASTEXITCODE
Read-Host 'Press Enter to close'
exit $code
