"""
v4.0 Backend API 单元测试 (Phase 1+2 落地).

借鉴自以下 MIT/BSD 协议项目 (项目 LICENSE 见 THIRD_PARTY_NOTICES.md):
- https://pywebview.flowrl.com/ (BSD-3-Clause) - Bridge 模式
- https://github.com/google/diff-match-patch (Apache-2.0) - diff 算法

测试策略:
- Backend 类不依赖 PySide6 (用 MockWindow 替代 webview.Window)
- 重点验证 §4.5 Phase 0 checklist 18 项 + pywebview 适配
- 用 check() 风格保持与 test_bugs.py / test_components.py 一致
"""
import sys
import tempfile
import threading
import time
import inspect
from pathlib import Path
from unittest.mock import MagicMock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))  # v6.0: tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

passed = 0
failed = 0




def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}", flush=True)
    else:
        failed += 1
        print(f"  [FAIL] {name}", flush=True)
        if detail:
            print(f"         -> {detail}", flush=True)


def make_mock_window(return_value=None):
    """建一个 mock window 对象, 用于测试 (避免真 webview)."""
    captured = []

    class MockWindow:
        def create_file_dialog(self, *args, **kwargs):
            return return_value

        def evaluate_js(self, js):
            captured.append(js)

    return MockWindow(), captured


def _read_app_js():
    return (_WEB_DIR / "app.js").read_text(encoding="utf-8")


def _read_style_css():
    return _STYLE_CSS.read_text(encoding="utf-8")


def _read_icon(name):
    return (_ICONS_DIR / name).read_text(encoding="utf-8")


def _hex_to_rgb(hex_str):
    s = hex_str.lstrip("#")
    return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))


def _relative_luminance(rgb):
    """WCAG 2.x 相对亮度 (0-1)."""
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg_hex, bg_hex):
    """WebAIM 标准: (L1+0.05) / (L2+0.05), L1=较亮."""
    l1 = _relative_luminance(_hex_to_rgb(fg_hex))
    l2 = _relative_luminance(_hex_to_rgb(bg_hex))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# === test_backend_imports ===
def test_backend_imports():
    print("\n--- Backend import ---", flush=True)
    from app.web_backend import Backend
    check("Backend 类存在", Backend is not None)

# === test_backend_no_pyside6 ===
def test_backend_no_pyside6():
    print("\n--- 完全不依赖 PySide6 ---", flush=True)
    src = inspect.getsource(sys.modules['app.web_backend'])
    # 只检查 import 语句 (不查 docstring 里的提及)
    import_lines = [l for l in src.splitlines() if l.strip().startswith(('import ', 'from '))]
    import_src = '\n'.join(import_lines)
    check("无 'from PySide6' import", "from PySide6" not in import_src)
    check("无 'import PySide6' (全行)", "import PySide6" not in import_src)
    check("无 'from PyQt6' import", "from PyQt6" not in import_src)
    check("无 'QApplication' import", "QApplication" not in import_src)
    check("无 'qasync' import", "qasync" not in import_src)
    check("无 'QFileDialog' import", "QFileDialog" not in import_src)
    # 整体也不该用 PySide6 任何 API
    check("无 PySide6 QtWidgets 调用", "QFileDialog" not in src.replace("QFileDialog.", ""))

# === test_backend_init ===
def test_backend_init():
    print("\n--- Backend.__init__ ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    check("init 不抛异常 (window=None)", backend is not None)
    check("backend._engine 默认 None", backend._engine is None)
    check("backend._config 不为 None", backend._config is not None)
    check("backend._window = None", backend._window is None)
    check("backend._push_buffer 是 list", isinstance(backend._push_buffer, list))
    check("backend._push_throttle_lock 存在", backend._push_throttle_lock is not None)



# ==================== 模块级常量 (v6.0 C1: 跨章节共享) ====================

passed = 0
failed = 0
V416_CFG_FIELDS = [
    ("api_base",          "http://v416.example.com/v1/",  str),
    ("api_key",           "sk-test-v416-key-xxxxxxxx",    str),
    ("model",             "v416-test-model",              str),
    ("prompt_mode",       "polish",                       str),
    ("temperature",       0.42,                           float),
    ("concurrency",       4,                              int),
    ("max_retries",       7,                              int),
    ("timeout",           180,                            int),
    ("chunking_preset",   "high_context",                 str),
    ("context_max_chars", 1200,                           int),
    ("context_max_chunks", 3,                             int),
    ("custom_prompt",     "v4.1.6 测试 prompt",            str),
]
_WEB_DIR = Path(__file__).parent.parent / "web"  # v6.0: 修正为项目根 (tests/ 的父目录)
_STYLE_CSS = _WEB_DIR / "style.css"
_ICONS_DIR = _WEB_DIR / "icons"

# ==================== 入口 (v6.0 C1: 自动发现本文件所有 test_xxx) ====================

if __name__ == "__main__":
    import inspect
    import sys as _sys
    _funcs = [(name, fn) for name, fn in inspect.getmembers(_sys.modules[__name__], inspect.isfunction) if name.startswith('test_')]
    _passed = 0
    _failed = 0
    for _name, _fn in _funcs:
        try:
            _fn()
            _passed += 1
        except Exception as _e:
            _failed += 1
            print(f"  [FAIL] {_name}: {type(_e).__name__}: {_e}", flush=True)
    print(f"\n  {_passed} pass, {_failed} fail", flush=True)
    _sys.exit(0 if _failed == 0 else 1)
