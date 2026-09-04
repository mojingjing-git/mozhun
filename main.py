"""
新时代校对大师 v4.1 入口 (pywebview 版本)。

借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause)
借鉴内容: 标准窗口创建模式 + js_api Bridge 注入
借鉴方式: 思路借鉴,代码自写
Copyright (c) 2014-2024 Roman Yurchak

v4.1 修订:
- C1: 修复 PyInstaller frozen 模式下 web/ 路径找不到的致命问题。
  frozen 时, Path(__file__).parent 指向 dist/ 临时目录, web/ 在 _MEIPASS/web/。
  必须检测 sys.frozen 并切换到 sys._MEIPASS 根。
- I8: 显式指定 webview.start(gui='edgechromium')，避免在某些环境自动选错 GUI。
- M5: Windows 4K 屏 DPI 感知, 用 ctypes.windll.shcore.SetProcessDpiAwareness(2)
  (Per-Monitor V2) 提前设置,避免启动后 UI 模糊。
"""
import sys
from pathlib import Path

import webview

from app.web_backend import Backend
from app.logger import setup_logging


def _enable_dpi_awareness() -> None:
    """Windows 4K 屏 DPI 感知 (Per-Monitor V2)。

    v4.1 (M5): 调用前移到 webview 启动之前, 避免启动后 UI 模糊。
    - shcore.dll 仅 Win8.1+ 有, 失败不致命 (XP/Win7 用户跳过)
    - try/except 多重兜底: shcore 失败 -> user32 SetProcessDPIAware
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # Per-Monitor V2 (Windows 10 1703+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            # 退化到 System DPI Aware (Win Vista+)
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            # 都没法设就算了, 不致命
            pass


def _resolve_web_index() -> str:
    """v4.1 (C1): 解析 web/index.html 路径, 兼容开发模式 + PyInstaller frozen 模式。

    - 开发模式: Path(__file__).parent / "web" / "index.html"
    - frozen 模式: sys._MEIPASS / "web" / "index.html"
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 临时解压目录
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    else:
        base = Path(__file__).resolve().parent
    return str(base / "web" / "index.html")


def main():
    # M5: 启动前先开 DPI 感知, 避免 WebView2 模糊
    _enable_dpi_awareness()

    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("新时代校对大师 v4.1 启动 (pywebview)")
    logger.info(f"日志文件: {Path.home() / '.proofreader' / 'app.log'}")

    # pywebview 启动顺序: 先建 Backend (window=None), 再 create_window 注入,
    # 最后把 window 引用反注入回 backend (因为 create_window 需要 js_api 但 window 自己才被创建).
    # 借鉴自 pywebview (BSD-3-Clause) 的标准 js_api 注入范式.
    backend = Backend(window=None)
    window = webview.create_window(
        title="新时代校对大师",
        url=_resolve_web_index(),
        width=1200,
        height=800,
        min_size=(900, 600),
        js_api=backend,
        text_select=True,
    )
    backend._window = window  # 反向注入, 让 choose_files() 等能用

    # v4.1.3 (F2): 注册 drop 事件. 必须用 Python DOM API (window.dom.get_element(...).on('drop', ...)),
    # 前端 addEventListener('drop') 不会触发 _dnd_state['num_listeners']++, 拿不到 pywebviewFullPath.
    # 在 events.loaded 之后才注册 (DOM 已注入 data-pywebview-id), init_drag_drop 内部处理.
    backend.init_drag_drop(window)

    try:
        # I8: 显式指定 edgechromium GUI, 避免在多 WebView 环境下选错。
        # 某些环境 (Win7 + Edge Legacy 残留) 会自动选 edgechromium 但版本太老,
        # 强制指定能提前失败, 提示用户装 WebView2 Runtime。
        webview.start(gui='edgechromium')
    except Exception as e:
        logger.error(f"启动失败: {e}")
        # 兜底: 系统 WebView2 不可用时提示安装
        msg = str(e)
        if "WebView2" in msg or "webview" in msg.lower() or "edge" in msg.lower():
            sys.stderr.write(
                "\n" + "=" * 50 + "\n"
                "ERROR: 系统未安装 WebView2 Runtime\n"
                "请访问 https://developer.microsoft.com/microsoft-edge/webview2/ 下载安装\n"
                "=" * 50 + "\n"
            )
        raise


if __name__ == "__main__":
    main()
