# ============================================================
#  New Era Proofreader v4.1.2 dev mode launcher (Python)
#
#  Reference 1: https://learn.microsoft.com/en-us/powershell/ (Microsoft Docs, CC-BY 4.0)
#    Borrowed: cross-platform Unicode/UTF-8 default in Python 3
#    Method: idea only, code self-written
#    Copyright (c) Microsoft Corporation
#
#  Reference 2: https://github.com/microsoft/vscode (MIT)
#    Borrowed: status banner + checklist pattern (like VS Code setup status checks)
#    Method: idea only, code self-written
#    Copyright (c) Microsoft Corporation
#
#  Why a Python launcher instead of .bat / .ps1 directly:
#    - .bat in PowerShell 5.1 GBK environment has nested-quote issues
#    - .ps1 works but requires PowerShell ExecutionPolicy tweak
#    - Python 3 default is UTF-8, runs anywhere, no codepage issues
#    - Single file = single source of truth for both dev_run.bat and dev_run.ps1
#
#  Usage:
#    python dev_launcher.py          # via dev_run.bat / dev_run.ps1
#    python dev_launcher.py --check  # diagnostic only, no GUI
# ============================================================

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
import winreg  # type: ignore[import-not-found]  # Windows-only
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
LOG_DIR = ROOT / "logs"
REQUIREMENTS = ROOT / "requirements.txt"

# 借鉴 vscode 状态输出: [OK] / [FAIL] / [WARN] / [SKIP]
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def color(code: str, text: str) -> str:
    """Wrap text in ANSI color (cmd / PowerShell 5.1 may not display, but harmless)."""
    return f"{code}{text}{RESET}"


def banner() -> None:
    print("=" * 60)
    print(f"  {color(CYAN, 'New Era Proofreader v4.1.2 dev launcher')}")
    print(f"  Working dir: {ROOT}")
    print()
    print("  3 windows will pop up:")
    print("    1) main console  (this window, waits for main.py, do NOT close)")
    print("    2) tail console  (live log viewer, debug helper)")
    print("    3) GUI           (pywebview app, close GUI = exit main.py)")
    print()
    print("  If you see errors, run dev_check.bat first (5-sec env check)")
    print("=" * 60)
    print()


def find_python() -> str | None:
    """Locate a usable Python 3.10+ interpreter (prefer venv)."""
    if VENV_PY.exists():
        return str(VENV_PY)
    # 退而求其次: 系统 PATH 上的 python
    for name in ("python", "python3", "py"):
        try:
            out = subprocess.check_output(
                [name, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                stderr=subprocess.STDOUT, timeout=5,
            ).decode().strip()
            major, minor = map(int, out.split())
            if (major, minor) >= (3, 10):
                return name
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            continue
    return None


def ensure_venv(py: str) -> str:
    """Create .venv if missing, return path to venv python.

    v4.1.8.2 (审计 K8): 对已存在的 .venv 做活性探测 — base 解释器被卸载/升级
    后 .venv 常见整体失效, 旧版直接 "[OK] already exists" 返回, 后续 pip/import
    全部报难以理解的错误. 探测失败用 --clear 重建.
    """
    if VENV_PY.exists():
        try:
            subprocess.check_output(
                [str(VENV_PY), "-c", "print('ok')"],
                stderr=subprocess.STDOUT, timeout=15,
            )
            print(f"  {color(GREEN, '[OK]')} .venv already exists")
            return str(VENV_PY)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            print(f"  {color(YELLOW, '[WARN]')} .venv exists but python.exe broken, recreating ...")
            subprocess.check_call([py, "-m", "venv", "--clear", str(VENV_DIR)])
    else:
        print(f"  {color(YELLOW, '[i]')} .venv not found, creating ...")
        subprocess.check_call([py, "-m", "venv", str(VENV_DIR)])
    if not VENV_PY.exists():
        raise RuntimeError("venv creation succeeded but .venv\\Scripts\\python.exe missing")
    print(f"  {color(GREEN, '[OK]')} venv ready")
    return str(VENV_PY)


def ensure_deps(py: str) -> None:
    """Install requirements.txt into venv if missing.

    v4.1.8.2 (审计 K2): 捕获 TimeoutExpired — pythonnet/clr_loader 首次导入
    在杀软实时扫描/冷盘下可能超 10s, 旧版漏捕会绕过 pip install 直接终止启动.
    v4.1.8.2 (审计 K8): 探测同时校验 pywebview >= 6.2.1 (旧版只查"能 import",
    装着 5.x 的环境永远不触发安装, 运行期才以怪异方式出错).
    """
    print(f"  {color(CYAN, '[i]')} checking deps in venv ...")
    probe = (
        "import re, webview, openai, requests, pythonnet, clr_loader, comtypes\n"
        "from importlib.metadata import version\n"
        "m = re.match(r'(\\d+)\\.(\\d+)', version('pywebview'))\n"
        "assert m and (int(m.group(1)), int(m.group(2))) >= (6, 2), 'pywebview>=6.2.1 required, got ' + version('pywebview')\n"
        "print('OK')\n"
    )
    try:
        out = subprocess.check_output(
            [py, "-c", probe],
            stderr=subprocess.STDOUT, timeout=30,
        ).decode().strip()
        if "OK" in out:
            print(f"  {color(GREEN, '[OK]')} webview / openai / requests / pythonnet / clr_loader / comtypes all installed (pywebview >= 6.2)")
            return
    except subprocess.TimeoutExpired:
        print(f"  {color(YELLOW, '[i]')} dep probe timed out (AV scan / cold disk?), falling back to pip install")
    except subprocess.CalledProcessError as e:
        print(f"  {color(YELLOW, '[i]')} some deps missing/outdated: {e.output.decode(errors='replace')[:200]}")
    print(f"  {color(CYAN, '[i]')} pip install -r requirements.txt ...")
    if REQUIREMENTS.exists():
        subprocess.check_call([py, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    else:
        raise FileNotFoundError(f"requirements.txt not found at {REQUIREMENTS}")


def check_webview2_runtime() -> bool:
    """Check 3 registry keys for WebView2 Runtime. Returns True if found."""
    keys = [
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",  # HKCU
    ]
    hives = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    for hive, key in zip(hives, keys):
        try:
            with winreg.OpenKey(hive, key) as k:
                winreg.QueryValueEx(k, "pv")
                return True
        except FileNotFoundError:
            continue
    return False


def check_duplicate_process() -> bool:
    """Check if main.py is already running. Returns True if duplicate detected.

    v4.1.8.2 (审计 K6): 过滤收紧到本项目根目录 — 旧版匹配任意 *main.py*,
    开发机上其它 Python 项目 (FastAPI/脚本) 会被误判成重复进程拒绝启动.
    """
    try:
        root_marker = str(ROOT).replace("'", "''")  # PS 单引号转义
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
             f"| Where-Object {{ $_.CommandLine -like '*{root_marker}*main.py*' }} "
             "| Select-Object -ExpandProperty ProcessId"],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode().strip()
        return bool(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def pop_tail_window(log_path: Path) -> None:
    """Pop a separate PowerShell window that tails log file.

    v4.1.8.2 (审计 K1): 设置窗口标题供 kill_tail_window 的 WINDOWTITLE 过滤器
    匹配 (旧版从未设置标题, taskkill 永远匹配 0 个窗口, 每次运行遗留一个孤儿
    控制台并占用日志句柄); Get-Content 加 -Encoding UTF8 修中文乱码.
    """
    cmd = (
        "$host.UI.RawUI.WindowTitle='NewEraProofreader-tail'; "
        "Write-Host 'Live tail: close this window = stop tail (main.py keeps running)'; "
        f"Get-Content -Path '{log_path}' -Wait -Encoding UTF8"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", cmd],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    time.sleep(1)  # 弹窗时延


def kill_tail_window() -> None:
    """Kill the tail window by title."""
    try:
        subprocess.run(
            ["taskkill", "/FI", "WINDOWTITLE eq NewEraProofreader-tail*", "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
    except subprocess.TimeoutExpired:
        pass


def launch_main(py: str, log_path: Path) -> int:
    """Run main.py with stdout/stderr redirected to log file. Returns exit code."""
    print()
    print("=" * 60)
    print(f"  Launching {color(CYAN, 'main.py')} (Ctrl+C to interrupt)")
    print(f"  Full log: {log_path}")
    print("=" * 60)
    print()
    with open(log_path, "wb") as logf:
        proc = subprocess.Popen(
            [py, "main.py"],
            stdout=logf, stderr=subprocess.STDOUT,
            cwd=str(ROOT),
        )
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            return 1


def tail_log(log_path: Path, n: int = 30) -> None:
    """Print last N lines of log file."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-n:]) if lines else "(empty)"
        print(f"  Last {n} log lines:")
        print("  " + "-" * 50)
        for ln in tail.splitlines():
            print(f"  {ln}")
        print("  " + "-" * 50)
    except Exception as e:
        print(f"  (could not read log: {e})")


def main() -> int:
    parser = argparse.ArgumentParser(description="New Era Proofreader v4.1.2 dev launcher")
    parser.add_argument("--check", action="store_true", help="env check only, no GUI")
    args = parser.parse_args()

    banner()

    # 1. Find Python
    print("[1/5] Finding Python 3.10+ ...")
    py = find_python()
    if not py:
        print(f"  {color(RED, '[FAIL]')} No Python 3.10+ found on PATH")
        print(f"  {color(YELLOW, '[Hint]')} Install from https://www.python.org/downloads/")
        print(f"  {color(YELLOW, '[Hint]')} Check 'Add Python to PATH' during install")
        input("Press Enter to exit ...")
        return 1
    print(f"  {color(GREEN, '[OK]')} Python: {py}")

    # 2. Ensure venv + deps
    print("[2/5] Ensuring venv + deps ...")
    try:
        py = ensure_venv(py)
        ensure_deps(py)
    except Exception as e:
        print(f"  {color(RED, '[FAIL]')} {e}")
        input("Press Enter to exit ...")
        return 1

    if args.check:
        print()
        print(f"  {color(GREEN, '[OK]')} env check complete, run without --check to launch GUI")
        return 0

    # 3. WebView2 check (non-blocking)
    print("[3/5] Checking WebView2 Runtime ...")
    if check_webview2_runtime():
        print(f"  {color(GREEN, '[OK]')} WebView2 installed")
    else:
        print(f"  {color(YELLOW, '[WARN]')} WebView2 not detected in registry")
        print(f"  {color(YELLOW, '[Note]')} GUI may fail. Download: https://developer.microsoft.com/microsoft-edge/webview2/")

    # 4. Duplicate launch guard
    print("[4/5] Duplicate launch guard ...")
    if check_duplicate_process():
        print(f"  {color(YELLOW, '[WARN]')} main.py already running")
        print(f"  {color(YELLOW, '[Hint]')} End existing python.exe in Task Manager, or close previous GUI")
        input("Press Enter to exit ...")
        return 1
    print(f"  {color(GREEN, '[OK]')} no duplicate process")

    # 5. Log + tail + launch
    print("[5/5] Preparing log + tail window ...")
    LOG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"dev-{ts}.log"
    log_path.write_text("", encoding="utf-8")
    print(f"  {color(CYAN, '[i]')} log file: {log_path}")
    pop_tail_window(log_path)

    exit_code = launch_main(py, log_path)
    kill_tail_window()

    print()
    print("=" * 60)
    print(f"  main.py exited (code: {exit_code})")
    print(f"  Log: {log_path}")
    print("=" * 60)

    if exit_code == 0:
        print(f"  {color(GREEN, '[OK]')} normal exit")
    else:
        print(f"  {color(RED, '[FAIL]')} abnormal exit")
        tail_log(log_path, n=30)
        print()
        print(f"  Full log at: {log_path}")

    input("Press Enter to close ...")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
