# ============================================================
#  墨准 v4.1.8.2 统一启动器 (start.py)
#
#  替代 dev_run.bat / dev_check.bat / dev_run.ps1 / dev_check.ps1
#  四件套 + dev_launcher.py 的散乱结构, 一个入口覆盖全部场景:
#
#    python start.py          # 智能模式 (默认): dist 里有 exe 启 exe,
#                             #   没有则走开发模式 (venv/依赖/WebView2 检查 + main.py)
#    python start.py dev      # 开发模式: 强制走 venv + main.py
#    python start.py exe      # 直接启动打包版 dist/墨准.exe
#    python start.py check    # 仅环境自检, 不启动任何东西
#
#  吸收 v4.1.8.2 审计 (K1/K2/K6/K8/K9) 的全部修复:
#    - 无 tail 窗口 (旧版孤儿控制台 + 日志句柄占用的根因), 日志统一走
#      ~/.proofreader/app.log, 失败时提示路径
#    - python 不在 PATH 时回退 py launcher
#    - 坏 .venv 活性探测 + --clear 重建
#    - 依赖探测校验 pywebview >= 6.2 且捕获探测超时
#    - 重复进程防护收窄到本项目根目录
#
#  设计约定 (沿用 dev_launcher.py 的结论):
#    - 逻辑全在 Python (UTF-8 无 codepage 坑), .bat/.ps1 只做 3 行薄包装
#    - 纯标准库, 不引入新依赖 (AGENTS.md 约定)
# ============================================================

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
EXE_PATH = ROOT / "dist" / "墨准.exe"
REQUIREMENTS = ROOT / "requirements.txt"
LOG_HINT = Path.home() / ".proofreader" / "app.log"

GREEN, RED, YELLOW, CYAN, RESET = (
    "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m",
)

# 依赖探测脚本: import 全部运行时依赖 + 校验 pywebview 版本下限
# (v4.1.8.2 K8: 旧版只查"能 import", 装着 pywebview 5.x 的环境永远不触发安装)
_DEP_PROBE = (
    "import re, webview, openai, requests, pythonnet, clr_loader, comtypes\n"
    "from importlib.metadata import version\n"
    "m = re.match(r'(\\d+)\\.(\\d+)', version('pywebview'))\n"
    "assert m and (int(m.group(1)), int(m.group(2))) >= (6, 2), "
    "'pywebview>=6.2.1 required, got ' + version('pywebview')\n"
    "print('OK')\n"
)


def c(code: str, text: str) -> str:
    """ANSI 包裹 (旧终端不识别也只是原样输出几个字符, 无害)."""
    return f"{code}{text}{RESET}"


def ok(msg: str) -> None:
    print(f"  {c(GREEN, '[OK]')} {msg}")


def warn(msg: str) -> None:
    print(f"  {c(YELLOW, '[WARN]')} {msg}")


def fail(msg: str) -> None:
    print(f"  {c(RED, '[FAIL]')} {msg}")


def info(msg: str) -> None:
    print(f"  {c(CYAN, '[i]')} {msg}")


# ---------------- 环境检查 ----------------

def find_python() -> tuple[str | None, str]:
    """定位可用解释器: venv (活性探测) -> python -> python3 -> py -3.

    返回 (解释器, 来源说明). 找不到返回 (None, "").
    """
    if VENV_PY.exists():
        try:
            subprocess.check_output(
                [str(VENV_PY), "-c", "print('ok')"],
                stderr=subprocess.STDOUT, timeout=15,
            )
            return str(VENV_PY), ".venv"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            warn(".venv 存在但 python.exe 失效 (base 解释器被升级/卸载?), 跳过")
    for name in ("python", "python3"):
        try:
            out = subprocess.check_output(
                [name, "-c", "import sys; print(sys.version_info[:2])"],
                stderr=subprocess.STDOUT, timeout=5,
            ).decode().strip()
            if out.startswith("(3,"):
                return name, "系统 PATH"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, ValueError):
            continue
    try:
        out = subprocess.check_output(
            ["py", "-3", "-c", "import sys; print(sys.version_info[:2])"],
            stderr=subprocess.STDOUT, timeout=5,
        ).decode().strip()
        if out.startswith("(3,"):
            return "py -3", "py launcher"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError):
        pass
    return None, ""


def ensure_venv(py: str) -> str:
    """确保 .venv 可用 (坏则 --clear 重建), 返回 venv python 路径. (K8)"""
    if VENV_PY.exists():
        try:
            subprocess.check_output(
                [str(VENV_PY), "-c", "print('ok')"],
                stderr=subprocess.STDOUT, timeout=15,
            )
            return str(VENV_PY)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            warn(".venv 失效, 用 --clear 重建 ...")
            subprocess.check_call([py, "-m", "venv", "--clear", str(VENV_DIR)])
    else:
        info(".venv 不存在, 创建中 ...")
        subprocess.check_call([py, "-m", "venv", str(VENV_DIR)])
    if not VENV_PY.exists():
        raise RuntimeError("venv 创建后仍找不到 .venv\\Scripts\\python.exe")
    return str(VENV_PY)


def deps_ok(py: str) -> tuple[bool, str]:
    """探测依赖是否齐全 (含 pywebview>=6.2 校验). (K2: 捕获超时)"""
    try:
        out = subprocess.check_output(
            [py, "-c", _DEP_PROBE], stderr=subprocess.STDOUT, timeout=30,
        ).decode(errors="replace").strip()
        return ("OK" in out), out[:200]
    except subprocess.TimeoutExpired:
        return False, "依赖探测超时 (杀软实时扫描/冷盘?), 建议重跑"
    except subprocess.CalledProcessError as e:
        return False, e.output.decode(errors="replace")[:200]


def webview2_ok() -> bool | None:
    """WebView2 Runtime 注册表检测 (微软官方 3 键). 非 Windows 返回 None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as k:
                winreg.QueryValueEx(k, "pv")
                return True
        except FileNotFoundError:
            continue
    return False


def duplicate_dev_running() -> bool:
    """开发模式重复启动防护, 收窄到本项目根目录. (K6: 旧版误伤其它项目)"""
    try:
        marker = str(ROOT).replace("'", "''")
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
             f"| Where-Object {{ $_.CommandLine -like '*{marker}*main.py*' }} "
             "| Select-Object -ExpandProperty ProcessId"],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode().strip()
        return bool(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ---------------- 各模式 ----------------

def cmd_check() -> int:
    """环境自检 (不启动, 不创建 venv)."""
    print("=" * 60)
    print("  环境自检 (check)")
    print("=" * 60)

    py, src = find_python()
    if py:
        ok(f"Python 3.10+ : {py}  ({src})")
    else:
        fail("未找到 Python 3.10+ (试过 python / python3 / py -3)")
        print("      安装: https://www.python.org/downloads/ 并勾选 Add to PATH")
        return 1

    # venv 状态只报告不创建
    if VENV_PY.exists():
        try:
            subprocess.check_output(
                [str(VENV_PY), "-c", "print('ok')"],
                stderr=subprocess.STDOUT, timeout=15,
            )
            ok(".venv 可用")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            warn(".venv 失效 (dev 模式会自动重建)")
    else:
        warn(".venv 不存在 (dev 模式会自动创建)")

    good, detail = deps_ok(py)
    if good:
        ok("依赖齐全: webview / openai / requests / pythonnet / clr_loader / comtypes (pywebview>=6.2)")
    else:
        warn(f"依赖缺失或版本过旧: {detail}")

    wv = webview2_ok()
    if wv is True:
        ok("WebView2 Runtime 已安装")
    elif wv is False:
        warn("注册表未检出 WebView2 — 下载: "
             "https://developer.microsoft.com/microsoft-edge/webview2/")
    else:
        info("非 Windows 平台, 跳过 WebView2 检测")

    if EXE_PATH.exists():
        ok(f"打包版 exe 存在: {EXE_PATH.name}")
    else:
        info("无打包版 exe (智能模式将走开发模式; 打包: "
             "python -m PyInstaller build.spec --clean)")

    print()
    print(f"  自检完成 — 日志文件: {LOG_HINT}")
    return 0


def cmd_dev() -> int:
    """开发模式: venv + 依赖 + main.py."""
    print("=" * 60)
    print("  开发模式启动")
    print("=" * 60)

    py, src = find_python()
    if not py:
        fail("未找到 Python 3.10+ (试过 python / python3 / py -3)")
        return 1
    ok(f"Python: {py}  ({src})")

    try:
        vpy = ensure_venv(py)
    except Exception as e:
        fail(f".venv 准备失败: {e}")
        return 1
    ok(f".venv 就绪: {vpy}")

    good, detail = deps_ok(vpy)
    if not good:
        info("依赖不齐, pip install -r requirements.txt ...")
        try:
            subprocess.check_call([vpy, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
        except Exception as e:
            fail(f"依赖安装失败: {e}")
            return 1
    else:
        ok("依赖齐全")

    wv = webview2_ok()
    if wv is False:
        warn("未检出 WebView2 Runtime, GUI 可能无法启动 (继续尝试)")

    if duplicate_dev_running():
        warn("本项目 main.py 已在运行 (仅匹配本项目路径), 请先关闭旧实例")
        return 1

    print()
    print("=" * 60)
    print(f"  启动 {c(CYAN, 'main.py')} (Ctrl+C 中断; 实时输出见本窗口)")
    print(f"  运行日志: {LOG_HINT}")
    print("=" * 60)
    print()
    try:
        rc = subprocess.call([vpy, "main.py"], cwd=str(ROOT))
    except KeyboardInterrupt:
        return 1
    if rc != 0:
        fail(f"main.py 异常退出 (code {rc}), 详情看: {LOG_HINT}")
    return rc


def cmd_exe() -> int:
    """直接启动打包版 exe."""
    if not EXE_PATH.exists():
        fail(f"未找到 {EXE_PATH}")
        info("先打包: python -m PyInstaller build.spec --clean")
        return 1
    info(f"启动 {EXE_PATH.name} ...")
    try:
        # detached: exe 自己是 windowed GUI, 不需要父进程陪跑
        subprocess.Popen([str(EXE_PATH)], cwd=str(EXE_PATH.parent))
        return 0
    except OSError as e:
        fail(f"启动失败: {e}")
        return 1


def cmd_auto() -> int:
    """智能模式: 有 exe 启 exe, 否则走开发模式."""
    if EXE_PATH.exists():
        info(f"检测到打包版 exe, 直接启动 (开发模式请用: python start.py dev)")
        return cmd_exe()
    info("无打包版 exe, 走开发模式 (强制开发模式请用: python start.py dev)")
    return cmd_dev()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="墨准统一启动器 (智能模式默认: exe 优先, 否则开发模式)",
    )
    parser.add_argument(
        "mode", nargs="?", default="auto",
        choices=["auto", "dev", "exe", "check"],
        help="auto=智能 (默认) / dev=开发模式 / exe=打包版 / check=仅自检",
    )
    args = parser.parse_args()

    print()
    return {
        "auto": cmd_auto,
        "dev": cmd_dev,
        "exe": cmd_exe,
        "check": cmd_check,
    }[args.mode]()


if __name__ == "__main__":
    sys.exit(main())
