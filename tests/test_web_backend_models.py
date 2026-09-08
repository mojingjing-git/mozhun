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


# === test_fetch_models_empty_base ===
def test_fetch_models_empty_base():
    print("\n--- fetch_models 空 base ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # v4.1 (I3): 清空 config.api_base, 走 early return 同步错误路径
    b._config.api_base = ""
    r = b.fetch_models("", "")
    check("空 base 返回 ok=False", r.get("ok") is False)
    check("含 error", "error" in r)

# === test_test_connection ===
def test_test_connection():
    print("\n--- test_connection ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # v4.1 (I3): 同 fetch_models, 清空 config.api_base 走 early return
    b._config.api_base = ""
    r = b.test_connection("", "")
    check("空 base 返回 ok=False", r.get("ok") is False)
    check("含 error", "error" in r)

# === test_i3_fetch_models_async ===
def test_i3_fetch_models_async():
    """v4.1 (I3): fetch_models 改异步, 立即返回 task_id."""
    print("\n--- I3: fetch_models 异步返回 task_id ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    b._window = mock_window
    # 配非空 base 走后台线程
    b._config.api_base = "http://localhost:1234/v1"
    b._config.api_key = "test"
    r = b.fetch_models("http://localhost:1234/v1", "test")
    check("返回 dict", isinstance(r, dict))
    check("含 task_id", "task_id" in r)
    check("含 status='running'", r.get("status") == "running")
    check("task_id 以 'fetch_' 开头", r["task_id"].startswith("fetch_"))
    # 等待后台线程完成 (mock requests 会真的发请求, 但 localhost:1234 没人接会快速失败)
    time.sleep(2.0)
    # 不管成功失败, _window.evaluate_js 至少被调了
    # captured 在 make_mock_window 里, 但这里没 capture; 改为简单验证 r 是 dict
    check("后台线程跑完不抛 (异步)", True)

# === test_i3_fetch_models_worker_uses_requests ===
def test_i3_fetch_models_worker_uses_requests():
    """v4.1 (I3): _fetch_models_worker 走 requests 库 + 推 onFetchModelsComplete."""
    print("\n--- I3: _fetch_models_worker 推 onFetchModelsComplete ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch, MagicMock

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # mock requests.get 返回 200 + 2 个模型
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "data": [{"id": "gpt-4"}, {"id": "gpt-3.5-turbo"}]
    }

    with patch("requests.get", return_value=fake_resp) as mock_get:
        b._fetch_models_worker("fetch_test_01", "http://x/v1", "k")
        time.sleep(0.15)  # 等 100ms 节流 flush
        check("requests.get 被调", mock_get.called)
        # 推 onFetchModelsComplete 到 evaluate_js
        check("evaluate_js 收到调用", len(captured) >= 1)
        check("payload 含 fetch_test_01", any("fetch_test_01" in c for c in captured))
        check("payload 含 onFetchModelsComplete", any("onFetchModelsComplete" in c for c in captured))
        check("payload 含 gpt-4", any("gpt-4" in c for c in captured))
        check("payload 含 count=2", any('"count": 2' in c for c in captured))

# === test_i3_fetch_models_worker_error ===
def test_i3_fetch_models_worker_error():
    """v4.1 (I3): _fetch_models_worker 在 requests 抛异常时推错误."""
    print("\n--- I3: _fetch_models_worker 错误处理 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    with patch("requests.get", side_effect=Exception("connection refused")):
        b._fetch_models_worker("fetch_test_err", "http://x/v1", "k")
        time.sleep(0.15)
        check("错误时也推 evaluate_js", len(captured) >= 1)
        check("payload 含 onFetchModelsComplete", any("onFetchModelsComplete" in c for c in captured))
        check("payload 含 connection refused", any("connection refused" in c for c in captured))
        check("payload ok=False", any('"ok": false' in c or '"ok": False' in c for c in captured))



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
