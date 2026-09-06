# ============================================================
#  New Era Proofreader v4.1.2 environment diagnostic (PowerShell)
#
#  v4.1.2: delegates to dev_launcher.py --check
# ============================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location $PSScriptRoot
# v4.1.8.2 (审计 K9): python 不在 PATH 时回退 py launcher
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { python dev_launcher.py --check } else { py -3 dev_launcher.py --check }
$code = $LASTEXITCODE
Read-Host 'Press Enter to close'
exit $code
