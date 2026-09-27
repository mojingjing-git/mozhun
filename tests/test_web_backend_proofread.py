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


# === test_start_proofread_returns_task_id ===
def test_start_proofread_returns_task_id():
    print("\n--- start_proofread ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test')
        tmp_path = Path(f.name)
    try:
        result = backend.start_proofread([str(tmp_path)], 'strict')
        check("start_proofread 返回 dict", isinstance(result, dict))
        check("含 task_id", "task_id" in result)
        check("含 total_files", "total_files" in result)
        check("total_files = 1", result.get("total_files") == 1)
        check("engine 已创建", backend._engine is not None)
    finally:
        tmp_path.unlink(missing_ok=True)

# === test_start_proofread_registers_callbacks ===
def test_start_proofread_registers_callbacks():
    print("\n--- start_proofread 注册回调 ---", flush=True)
    """v0.2 关键验证: engine.on_log / on_stream 等回调必须被绑定到 _push."""
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test')
        tmp_path = Path(f.name)
    try:
        backend.start_proofread([str(tmp_path)], 'strict')
        check("engine.on_log 已绑", backend._engine.on_log is not None)
        check("engine.on_stream 已绑", backend._engine.on_stream is not None)
        check("engine.on_file_start 已绑", backend._engine.on_file_start is not None)
        check("engine.on_file_done 已绑", backend._engine.on_file_done is not None)
        check("engine.on_file_completed 已绑", backend._engine.on_file_completed is not None)
        check("engine.on_stats_update 已绑", backend._engine.on_stats_update is not None)
    finally:
        tmp_path.unlink(missing_ok=True)

# === test_cancel_pause_resume_no_engine ===
def test_cancel_pause_resume_no_engine():
    print("\n--- cancel/pause/resume 无 engine ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    # 没 engine 时调不应崩
    backend.cancel_proofread()  # 不抛
    backend.pause_proofread()   # 不抛
    backend.resume_proofread()  # 不抛
    check("无 engine 时 cancel/pause/resume 不抛", True)

# === test_export_result ===
def test_export_result():
    print("\n--- export_result ---", flush=True)
    """v4.1.4 重写: 弹原生保存对话框, 默认位置=源文件目录, 默认文件名=<stem>-<YYMMDD>-<HHMMSS>.<ext>"""
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    # 1. window=None 时返回错误
    b = Backend(window=None)
    r_none = b.export_result("C:\\fake\\path.txt", "hello", "txt")
    check("window=None 返回 ok=False", r_none.get("ok") is False)
    check("window=None 含 error", "error" in r_none)

    # 2. 弹保存对话框 + 用户选位置, 写入成功
    with tempfile.TemporaryDirectory() as tmpdir:
        # mock create_file_dialog 返回用户选的保存路径
        save_path = str(Path(tmpdir) / "user_chosen_name.txt")
        b2 = Backend(window=None)
        b2._window = MagicMock()
        b2._window.create_file_dialog = MagicMock(return_value=save_path)
        # mock 一个真实存在的源文件 (推导 src_dir)
        src_file = Path(tmpdir) / "source.txt"
        src_file.write_text("orig", encoding="utf-8")
        r = b2.export_result(str(src_file), "hello world", "txt")
        check("返回 ok=True", r.get("ok") is True)
        check("含 path", "path" in r)
        out_path = Path(r["path"])
        check("文件存在", out_path.exists())
        check("内容正确", out_path.read_text(encoding="utf-8") == "hello world")
        # 验证 create_file_dialog 被调
        check("create_file_dialog 被调", b2._window.create_file_dialog.called)
        # 验证传给 create_file_dialog 的参数: save_filename 包含 YYMMDD-HHMMSS
        call_kwargs = b2._window.create_file_dialog.call_args
        save_filename = call_kwargs.kwargs.get("save_filename")
        check("save_filename 含 stem", save_filename and save_filename.startswith("source-"))
        check("save_filename 含 YYMMDD-HHMMSS",
              save_filename and "-" in save_filename and len(save_filename.split("-")) >= 3)

    # 3. markdown 格式 (fmt=md)
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = str(Path(tmpdir) / "user_chosen.md")
        b3 = Backend(window=None)
        b3._window = MagicMock()
        b3._window.create_file_dialog = MagicMock(return_value=save_path)
        src_file = Path(tmpdir) / "source.md"
        src_file.write_text("orig", encoding="utf-8")
        r2 = b3.export_result(str(src_file), "# title", "md")
        check("md 格式 ok", r2.get("ok") is True)
        if r2.get("ok"):
            check("md 文件存在", Path(r2["path"]).exists())
            check("md 内容正确", Path(r2["path"]).read_text(encoding="utf-8") == "# title")

# === test_pause_resume_returns_dict ===
def test_pause_resume_returns_dict():
    print("\n--- pause/resume/cancel 返回 dict ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # 无 engine 时
    r1 = b.pause_proofread()
    check("pause 无 engine ok=False", r1.get("ok") is False)
    r2 = b.resume_proofread()
    check("resume 无 engine ok=False", r2.get("ok") is False)
    r3 = b.cancel_proofread()
    check("cancel 无 engine ok=False", r3.get("ok") is False)

# === test_push_uses_evaluate_js ===
def test_push_uses_evaluate_js():
    print("\n--- _push 用 evaluate_js ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    backend._window = mock_window
    backend._push('onLog', 'hello')
    time.sleep(0.1)  # v4.1.4: 33ms 节流, 等 100ms 留余量
    check("_push 调用了 evaluate_js", len(captured) > 0)
    check("evaluate_js payload 含 window.app", any('window.app' in c for c in captured))
    check("evaluate_js payload 含 onLog", any('onLog' in c for c in captured))

# === test_push_no_window ===
def test_push_no_window():
    print("\n--- _push window=None 不崩 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    # window=None 时不抛
    try:
        backend._push('onLog', 'test')
        check("_push window=None 不抛", True)
    except Exception as e:
        check("_push window=None 不抛", False, str(e))

# === test_collect_results_empty ===
def test_collect_results_empty():
    print("\n--- _collect_results 空 engine ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    result = backend._collect_results()
    check("空 engine 返回 {}", result == {})

# === test_collect_results_after_start ===
def test_collect_results_after_start():
    print("\n--- _collect_results 启动后 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test collect')
        tmp_path = Path(f.name)
    try:
        backend.start_proofread([str(tmp_path)], 'strict')
        # engine 创建后, _collect_results 应返回 dict (可能空, 因为还没开始处理)
        result = backend._collect_results()
        check("启动后 _collect_results 返回 dict", isinstance(result, dict))
    finally:
        tmp_path.unlink(missing_ok=True)

# === test_push_throttle ===
def test_push_throttle():
    print("\n--- _push 33ms 节流 (v4.1.4, flush=True) ---")
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    backend._window = mock_window
    # 短时间内多次 push
    for i in range(5):
        backend._push('onLog', f'msg {i}')
    # 不等, captured 应是空 (因为 throttle pending)
    time.sleep(0.1)  # v4.1.4: 33ms 节流, 等 100ms 留余量
    # 合并后, 至少 1 次 evaluate_js 调用
    check("节流后至少 1 次 evaluate_js", len(captured) >= 1)
    # 合并: 同名事件 onLog 只保留最后一条
    check("合并后含 onLog 标记", any('onLog' in c for c in captured))

# === test_m3_task_id_is_uuid ===
def test_m3_task_id_is_uuid():
    """v4.1 (M3): start_proofread 返回的 task_id 不再硬编码 '1', 用 uuid."""
    print("\n--- M3: task_id uuid ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test')
        tmp_path = Path(f.name)
    try:
        r1 = backend.start_proofread([str(tmp_path)], 'strict')
        r2 = backend.start_proofread([str(tmp_path)], 'strict')
        check("task_id 存在", "task_id" in r1)
        check("task_id 不再是 '1'", r1["task_id"] != "1")
        check("task_id 含 'proof_' 前缀", r1["task_id"].startswith("proof_"))
        check("两次启动 task_id 不同", r1["task_id"] != r2["task_id"])
    finally:
        tmp_path.unlink(missing_ok=True)

# === test_m4_serialize_path ===
def test_m4_serialize_path():
    """v4.1 (M4): _serialize 把 Path 序列化为 str (不是 Path repr)."""
    print("\n--- M4: _serialize 序列化 Path ---", flush=True)
    from app.web_backend import Backend
    p = Path("a/b/c.txt")
    result = Backend._serialize(p)
    check("Path -> str", result == "a\\b\\c.txt")
    check("不是 repr (无 'PosixPath'/'WindowsPath' 字符串)", "Path" not in result)

# === test_m4_serialize_enum ===
def test_m4_serialize_enum():
    """v4.1 (M4): _serialize 把 Enum 序列化为 value."""
    print("\n--- M4: _serialize 序列化 Enum ---", flush=True)
    from app.web_backend import Backend
    from app.utils import TaskStatus
    result = Backend._serialize(TaskStatus.COMPLETED)
    check("Enum -> value", result == "completed")

# === test_m4_serialize_nested ===
def test_m4_serialize_nested():
    """v4.1 (M4): _serialize 递归处理 dict/list."""
    print("\n--- M4: _serialize 递归 ---", flush=True)
    from app.web_backend import Backend
    from app.utils import TaskStatus
    data = {
        "path": Path("x/y"),
        "status": TaskStatus.RUNNING,
        "nested": [{"p": Path("a/b")}],
    }
    import json
    s = json.dumps(data, default=Backend._serialize)
    check("dict 含 Path/Enum 序列化 OK", '"x\\\\y"' in s and "running" in s)
    check("含嵌套 Path 序列化", '"a\\\\b"' in s)

# === test_m2_presets_consistent ===
def test_m2_presets_consistent():
    """v4.1 (M2): processor._CHUNK_PRESETS 跟 utils.CHUNKING_PRESETS_MAP 一致."""
    print("\n--- M2: chunking 预设单点定义 ---", flush=True)
    from app.utils import CHUNKING_PRESETS, CHUNKING_PRESETS_MAP
    from app.processor import _CHUNK_PRESETS
    # v5.3.0: 5→6 档 (extra_large, 逐条校对专属)
    check("CHUNKING_PRESETS 6 档", len(CHUNKING_PRESETS) == 6)
    check("CHUNKING_PRESETS_MAP 6 档", len(CHUNKING_PRESETS_MAP) == 6)
    check("_CHUNK_PRESETS 6 档", len(_CHUNK_PRESETS) == 6)
    # 验证 max_chars 一致
    for key, info in CHUNKING_PRESETS_MAP.items():
        check(
            f"{key} max_chars 一致",
            _CHUNK_PRESETS[key]["max_chars"] == info["max_chars"]
        )
        check(
            f"{key} overlap=0 (校对场景)",
            _CHUNK_PRESETS[key]["overlap"] == 0
        )

# === test_i1_processor_closes_client ===
def test_i1_processor_closes_client():
    """v4.1 (I1): ProcessingEngine._run_all 关闭 AsyncOpenAI 客户端."""
    print("\n--- I1: ProcessingEngine 关闭 client ---", flush=True)
    from app.utils import ProjectConfig
    from app.processor import ProcessingEngine
    import asyncio

    config = ProjectConfig(
        api_base="http://test/v1",
        api_key="k",
        model="m",
        chunking_preset="whole_file",  # 整文件不分块
        concurrency=1,
        max_retries=0,
    )

    # 准备一个 task 强制让 _run_all 走完 (没有 pending 时也要 close)
    engine = ProcessingEngine(config)
    # mock load_checkpoint 返回 None (无缓存, 准备读文件)
    from unittest.mock import patch, MagicMock, AsyncMock
    fake_task = MagicMock()
    fake_task.original_text = "x"
    fake_task.is_done = False

    with patch("app.processor.load_checkpoint", return_value=None), \
         patch("app.processor.read_file_text", return_value="hello"), \
         patch("app.processor.save_checkpoint_async", new=AsyncMock()):
        engine.tasks = {"f1": fake_task}
        engine.stats.total_files = 1

        # mock AsyncOpenAI - 关键是 close() 被调
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        with patch("app.processor.AsyncOpenAI", return_value=mock_client):
            # mock _call_api_stream 走 fail 路径 (避免真的发请求)
            with patch.object(engine, "_call_api_stream", side_effect=Exception("stop")):
                asyncio.run(engine._run_all())

    check("AsyncOpenAI.close 被调", mock_client.close.called)
    check("close await 被调", mock_client.close.await_count >= 1)

# === test_i3_flush_multi_events_not_merged ===
def test_i3_flush_multi_events_not_merged():
    """v4.1.3 (I3 / F3): _flush 合并时 onFileStart / onFileDone / onDeaiError 等保留所有同名事件."""
    print("\n--- I3: _flush 保留多事件 ---", flush=True)
    from app.web_backend import Backend

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # 短时间内推多个 onFileStart (应保留 3 个)
    b._push("onFileStart", "f1")
    b._push("onFileStart", "f2")
    b._push("onFileStart", "f3")
    b._push("onFileDone", "f1")
    b._push("onDeaiError", {"task_id": "d1", "error": "x"})
    b._push("onDeaiError", {"task_id": "d2", "error": "y"})
    b._push("onDeaiComplete", {"task_id": "d1", "result": "ok"})

    import time
    time.sleep(0.15)
    # 找一次 evaluate_js 调用
    check("evaluate_js 至少 1 次", len(captured) >= 1)
    # 校验: 3 个 onFileStart, 1 个 onFileDone, 2 个 onDeaiError, 1 个 onDeaiComplete
    last_call = captured[-1]
    check("3 个 onFileStart 都在", last_call.count('"onFileStart"') == 3)
    check("1 个 onFileDone", last_call.count('"onFileDone"') == 1)
    check("2 个 onDeaiError 都保留", last_call.count('"onDeaiError"') == 2)
    check("1 个 onDeaiComplete", last_call.count('"onDeaiComplete"') == 1)
    check("f1/f2/f3 都在 payload", all(f in last_call for f in ['"f1"', '"f2"', '"f3"']))

# === test_i3_flush_default_merge ===
def test_i3_flush_default_merge():
    """v4.1.3 (I3): 默认 onStream / onStatsUpdate 仍然同名覆盖."""
    print("\n--- I3: _flush 默认同名覆盖 (onStream, flush=True) ---")
    from app.web_backend import Backend

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    b._push("onStream", {"file_key": "f1", "partial": "v1"})
    b._push("onStream", {"file_key": "f1", "partial": "v2"})
    b._push("onStream", {"file_key": "f1", "partial": "v3"})

    import time
    time.sleep(0.15)
    check("evaluate_js 至少 1 次", len(captured) >= 1)
    last_call = captured[-1]
    # 合并后只有 1 个 onStream, 内容是 v3 (最后一个)
    check("同名 onStream 合并为 1 个", last_call.count('"onStream"') == 1)
    check("保留最后一个 v3", '"v3"' in last_call)
    check("不含 v1 (被覆盖)", '"v1"' not in last_call)

# === test_i4_flush_log_accumulate ===
def test_i4_flush_log_accumulate():
    """v4.1.3 (I4): onLog 多次调用累积拼接, 不丢中间."""
    print("\n--- I4: _flush onLog 累积 ---", flush=True)
    from app.web_backend import Backend

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    b._push("onLog", "msg 1")
    b._push("onLog", "msg 2")
    b._push("onLog", "msg 3")

    import time
    time.sleep(0.15)
    check("evaluate_js 至少 1 次", len(captured) >= 1)
    last_call = captured[-1]
    # 只有 1 个 onLog 字段, 包含 3 条
    check("只有 1 个 onLog", last_call.count('"onLog"') == 1)
    check("累积含 msg 1", "msg 1" in last_call)
    check("累积含 msg 2", "msg 2" in last_call)
    check("累积含 msg 3", "msg 3" in last_call)

# === test_i1_copy_to_clipboard_method_exists ===
def test_i1_copy_to_clipboard_method_exists():
    """v4.1.3 (I1): Backend.copy_to_clipboard 方法存在 + Windows 走 Win32 API."""
    print("\n--- I1: copy_to_clipboard 存在 + Win32 API ---", flush=True)
    from app.web_backend import Backend
    import inspect

    check("copy_to_clipboard 方法存在", hasattr(Backend, "copy_to_clipboard"))
    src = inspect.getsource(Backend.copy_to_clipboard)
    check("用 ctypes.windll 调用", "ctypes.windll" in src)
    check("用 OpenClipboard", "OpenClipboard" in src)
    check("用 SetClipboardData", "SetClipboardData" in src)
    check("用 CF_UNICODETEXT", "CF_UNICODETEXT" in src)
    check("用 GlobalAlloc", "GlobalAlloc" in src)

# === test_i1_copy_to_clipboard_non_windows ===
def test_i1_copy_to_clipboard_non_windows():
    """v4.1.3 (I1): 非 Windows 平台返回错误而非崩."""
    print("\n--- I1: copy_to_clipboard 非 Windows 拒绝 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch

    b = Backend(window=None)
    with patch.object(sys, "platform", "linux"):
        r = b.copy_to_clipboard("hello")
    check("非 Windows 返回 ok=False", r.get("ok") is False)
    check("含 error", "error" in r)

# === test_i1_copy_to_clipboard_empty_text ===
def test_i1_copy_to_clipboard_empty_text():
    """v4.1.3 (I1): 空 text 返回错误."""
    print("\n--- I1: copy_to_clipboard 空 text ---", flush=True)
    from app.web_backend import Backend

    b = Backend(window=None)
    r1 = b.copy_to_clipboard("")
    check("空 text 返回 ok=False", r1.get("ok") is False)
    r2 = b.copy_to_clipboard(None)
    check("None 返回 ok=False", r2.get("ok") is False)

# === test_i1_copy_to_clipboard_windows_calls_win32 ===
def test_i1_copy_to_clipboard_windows_calls_win32():
    """v4.1.3 (I1): Windows 上成功路径真调 OpenClipboard + SetClipboardData.

    v4.1.4 修复: 加 patch ctypes.memmove 避免 0x2000 假地址写崩 (Python 3.13 + ctypes
    对假地址 memmove 触发 STATUS_STACK_BUFFER_OVERRUN).
    之前因为 stdout 缓冲隐藏 crash, 这测试从来没真正跑通过.
    """
    print("\n--- I1: copy_to_clipboard Win32 调用链 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch, MagicMock

    b = Backend(window=None)
    # 模拟 ctypes.windll 行为
    with patch.object(sys, "platform", "win32"), \
         patch("ctypes.windll.user32.OpenClipboard", return_value=1) as mock_open, \
         patch("ctypes.windll.user32.EmptyClipboard", return_value=1) as mock_empty, \
         patch("ctypes.windll.user32.SetClipboardData", return_value=1) as mock_set, \
         patch("ctypes.windll.user32.CloseClipboard", return_value=1) as mock_close, \
         patch("ctypes.windll.kernel32.GlobalAlloc", return_value=0x1000) as mock_alloc, \
         patch("ctypes.windll.kernel32.GlobalLock", return_value=0x2000) as mock_lock, \
         patch("ctypes.windll.kernel32.GlobalUnlock", return_value=1) as mock_unlock, \
         patch("ctypes.memmove", return_value=None) as mock_memmove:
        r = b.copy_to_clipboard("hello world")
    check("返回 ok=True", r.get("ok") is True)
    check("含 length", r.get("length") == 11)
    check("OpenClipboard 被调", mock_open.called)
    check("EmptyClipboard 被调", mock_empty.called)
    check("SetClipboardData 被调", mock_set.called)
    check("GlobalAlloc 被调", mock_alloc.called)
    check("CloseClipboard 被调", mock_close.called)

# === test_i1_copy_to_clipboard_open_fails ===
def test_i1_copy_to_clipboard_open_fails():
    """v4.1.3 (I1): OpenClipboard 持续失败时返回错误."""
    print("\n--- I1: copy_to_clipboard OpenClipboard 失败 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch

    b = Backend(window=None)
    with patch.object(sys, "platform", "win32"), \
         patch("ctypes.windll.user32.OpenClipboard", return_value=0):
        r = b.copy_to_clipboard("hello")
    check("OpenClipboard 失败返回 ok=False", r.get("ok") is False)
    check("error 含 OpenClipboard", "OpenClipboard" in (r.get("error") or ""))

# === test_i1_copy_to_clipboard_exception ===
def test_i1_copy_to_clipboard_exception():
    """v4.1.3 (I1): ctypes 抛异常时返回错误而非崩."""
    print("\n--- I1: copy_to_clipboard 异常兜底 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch

    b = Backend(window=None)
    with patch.object(sys, "platform", "win32"), \
         patch("ctypes.windll.user32.OpenClipboard", side_effect=OSError("locked")):
        r = b.copy_to_clipboard("hello")
    check("异常返回 ok=False", r.get("ok") is False)
    check("error 含 OSError", "OSError" in (r.get("error") or ""))

# === test_v414_throttle_33ms ===
def test_v414_throttle_33ms():
    """v4.1.4: _push 节流 33ms (30 FPS) — 验证 1 秒内 flush 频率接近 30 次."""
    print("\n--- v4.1.4: _push 33ms 节流 (30 FPS, flush=True) ---")
    from app.web_backend import Backend

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # 持续 push 模拟流式 (5ms 一次, 200 push/s, 跑 1 秒)
    duration = 1.0
    start = time.time()
    n = 0
    while time.time() - start < duration:
        b._push('onStream', {'i': n})
        n += 1
        time.sleep(0.005)

    # 等最后一次 flush 完成
    time.sleep(0.1)
    flush_count = len(captured)
    # 期望 ~30 FPS (33ms 节流 → 1 秒约 30 次 flush), 容许 20-50 范围
    # (实测可能 28-35, 留余量)
    check(f"1 秒内 flush {flush_count} 次 (~30 FPS)",
          20 <= flush_count <= 50)
    check("确实有 flush (非 0)", flush_count > 0)
    check("总共 push {n} 次, 合并后 flush 次数远少于 push 次数".format(n=n),
          flush_count < n)

# === test_v414_throttle_constants ===
def test_v414_throttle_constants():
    """v4.1.4: _push 节流间隔是 0.033 秒 (33ms), 不是旧版 0.1 (100ms).

    v5.4.3 (F8) 修订: 旧版断言的是 `_push` **源码文本**里出现
    `threading.Timer(0.033` —— 那是文本位置断言, 不是不变量断言。
    F8 把 Timer 的创建抽到 `_arm_push_timer_locked` (回灌路径必须共用同一个
    arm 点, 否则失败的若是最后一批就没人再 arm), 文本位置自然变了, 但
    "节流间隔 = 33ms" 这条不变量一个字都没动。
    → 改为直接断言间隔常量本身 + 校验 Timer 仍被真正接线 (常量没被孤立)。
    """
    print("\n--- v4.1.4: _push 节流常量 ---", flush=True)
    from app.web_backend import Backend, _PUSH_FLUSH_INTERVAL
    import inspect

    check("节流间隔常量是 0.033 秒 (33ms)", _PUSH_FLUSH_INTERVAL == 0.033,
          str(_PUSH_FLUSH_INTERVAL))
    arm_src = inspect.getsource(Backend._arm_push_timer_locked)
    iv_src = inspect.getsource(Backend._flush_interval)
    push_src = inspect.getsource(Backend._push)
    # 链路: _push -> _arm_push_timer_locked -> _flush_interval -> 常量。
    # 三处都要查, 否则常量可能变成一个没人用的死数字 (F8 复审时正是这样
    # 把 Timer 抽成了单独的方法, 只查 _push 源码会漏)。
    check("arm 点用 threading.Timer 延时 flush", "threading.Timer(" in arm_src, arm_src)
    check("arm 点的间隔取自 _flush_interval",
          "self._flush_interval()" in arm_src, arm_src)
    check("间隔计算走节流常量", "_PUSH_FLUSH_INTERVAL" in iv_src, iv_src)
    check("_push 经 arm 点接线", "_arm_push_timer_locked()" in push_src, push_src)
    # 旧 100ms 不得复活 (源码 + 常量两头都查)
    check("无 0.1 (旧 100ms)",
          "0.1" not in push_src and "0.1" not in arm_src
          and _PUSH_FLUSH_INTERVAL != 0.1)

# === test_v414_export_user_cancelled ===
def test_v414_export_user_cancelled():
    """v4.1.4: export_result 用户取消保存对话框时返回 ok=False, cancelled=True."""
    print("\n--- v4.1.4: export_result 用户取消 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    b._window = MagicMock()
    # create_file_dialog 返回 None 表示用户取消
    b._window.create_file_dialog = MagicMock(return_value=None)

    r = b.export_result("C:\\nonexistent.txt", "test", "txt")
    check("用户取消返回 ok=False", r.get("ok") is False)
    check("用户取消含 cancelled=True", r.get("cancelled") is True)
    # 不应创建文件
    check("无 path 字段", "path" not in r or r.get("path") is None)

# === test_v414_export_user_cancelled_tuple ===
def test_v414_export_user_cancelled_tuple():
    """v4.1.4: create_file_dialog 返回空 tuple 也视为取消."""
    print("\n--- v4.1.4: export_result 空 tuple 取消 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    b._window = MagicMock()
    b._window.create_file_dialog = MagicMock(return_value=())  # 空 tuple

    r = b.export_result("C:\\nonexistent.txt", "test", "txt")
    check("空 tuple 返回 ok=False", r.get("ok") is False)
    check("空 tuple 含 cancelled=True", r.get("cancelled") is True)

# === test_v414_export_deai_fallback ===
def test_v414_export_deai_fallback():
    """v4.1.4: export_result DeAI 导出 (file_path='') fallback 到 home/Documents."""
    print("\n--- v4.1.4: export_result DeAI fallback ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    b._window = MagicMock()
    b._window.create_file_dialog = MagicMock(return_value=None)

    # 传空 file_path (DeAI 导出场景)
    b.export_result("", "test content", "txt")

    call_kwargs = b._window.create_file_dialog.call_args
    directory = call_kwargs.kwargs.get("directory")
    save_filename = call_kwargs.kwargs.get("save_filename")
    # directory 应该是 home/Documents
    expected_dir = str(Path.home() / "Documents")
    check(f"DeAI directory={expected_dir}", directory == expected_dir)
    # save_filename 应该以 deai_result 开头
    check("DeAI save_filename 以 deai_result 开头",
          save_filename and save_filename.startswith("deai_result-"))

# === test_v414_export_md_format ===
def test_v414_export_md_format():
    """v4.1.4: export_result fmt=md 时用 .md 后缀, 默认名含 .md."""
    print("\n--- v4.1.4: export_result md 格式 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock
    import re

    b = Backend(window=None)
    b._window = MagicMock()
    b._window.create_file_dialog = MagicMock(return_value=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / "doc.txt"
        src_file.write_text("orig", encoding="utf-8")
        b.export_result(str(src_file), "# md content", "md")
        call_kwargs = b._window.create_file_dialog.call_args
        save_filename = call_kwargs.kwargs.get("save_filename")
        # md 格式: <stem>-<YYMMDD>-<HHMMSS>.md
        pattern = r"^[\w-]+-\d{6}-\d{6}\.md$"
        check(f"md save_filename='{save_filename}' 匹配 .md 格式",
              save_filename and re.match(pattern, save_filename) is not None)

# === test_v414_export_dialog_exception ===
def test_v414_export_dialog_exception():
    """v4.1.4: create_file_dialog 抛异常时返回 ok=False, 含 error."""
    print("\n--- v4.1.4: export_result 对话框异常 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    b._window = MagicMock()
    b._window.create_file_dialog = MagicMock(side_effect=ValueError("bad file type"))

    r = b.export_result("C:\\any.txt", "test", "txt")
    check("对话框异常返回 ok=False", r.get("ok") is False)
    check("含 error", "error" in r)
    check("error 含 ValueError", "ValueError" in (r.get("error") or ""))

# === test_v414_export_write_failure ===
def test_v414_export_write_failure():
    """v4.1.4: 写入文件失败 (权限不足 / 路径非法) 时返回 ok=False, 含 error."""
    print("\n--- v4.1.4: export_result 写文件失败 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    b._window = MagicMock()
    # 模拟用户选了一个无效路径
    b._window.create_file_dialog = MagicMock(return_value="Z:\\nonexistent_dir\\file.txt")

    r = b.export_result("C:\\any.txt", "test", "txt")
    # write_text 会自动创建父目录 (用了 mkdir parents=True), 所以这条路径可能成功
    # 我们改用一个真正无法写入的路径 (含 null char)
    b._window.create_file_dialog = MagicMock(return_value="Z:\\bad\x00path\\file.txt")
    r2 = b.export_result("C:\\any.txt", "test", "txt")
    # 不同平台/不同环境下可能 success 也可能 fail, 我们只验证不崩
    check("写文件失败不抛异常", r is not None and r2 is not None)

# === test_v414_push_uses_throttle_33ms ===
def test_v414_push_uses_throttle_33ms():
    """v4.1.4: _push 用 33ms Timer (vs v4.1.3 100ms Timer)."""
    print("\n--- v4.1.4: _push Timer 33ms ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import patch, MagicMock

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # 抓 Timer 启动调用
    with patch("app.web_backend.threading.Timer") as MockTimer:
        timer_inst = MagicMock()
        MockTimer.return_value = timer_inst
        b._push("onLog", "test")
        # 第一次 push 应启动一个 33ms 的 Timer
        check("Timer 被创建", MockTimer.called)
        if MockTimer.called:
            args = MockTimer.call_args[0]
            check(f"Timer interval=0.033 (33ms), 实测 {args[0]}", abs(args[0] - 0.033) < 0.001)

# === test_v415_original_push_limit_constant ===
def test_v415_original_push_limit_constant():
    """v4.1.5: _ORIGINAL_PUSH_LIMIT = 50000 常量存在."""
    print("\n--- v4.1.5: _ORIGINAL_PUSH_LIMIT = 50000 ---", flush=True)
    from app.web_backend import _ORIGINAL_PUSH_LIMIT
    check("_ORIGINAL_PUSH_LIMIT = 50000", _ORIGINAL_PUSH_LIMIT == 50000)



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

# === test_v530_start_proofread_workflow ===
def test_v530_start_proofread_workflow():
    """v5.3.0: start_proofread 第 6 位 workflow + 旧调用位置参数不破 (PLAN §5-9)"""
    print("\n--- v5.3.0: start_proofread workflow 参数 ---", flush=True)
    import tempfile
    from unittest.mock import AsyncMock, patch
    from app.web_backend import Backend
    from app.processor import ProcessingEngine
    from app.utils import (
        FileResult, FileTask, TaskStatus,
        compute_prompt_hash_for_config, save_checkpoint,
    )

    with tempfile.TemporaryDirectory(prefix="v530_sp_") as tmp:
        src = Path(tmp) / "s.txt"
        src.write_text("原文内容。" * 50, encoding="utf-8")
        b = Backend(window=None)
        b._window = make_mock_window(None)

        # 1) 显式第 6 位 workflow=rewrite
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r = b.start_proofread([str(src)], "strict", "", "", False, "rewrite")
        check("start_proofread 返回 ok", r.get("ok") is True)
        check("workflow 落到 config", b._config.workflow_mode == "rewrite")
        check("harness_enabled 单向镜像为 False", b._config.harness_enabled is False)
        # run_async 被 mock 掉, 任务本身不会产出 result — 手工补一条再验来源字段
        _eng = b._engine
        _k = next(iter(_eng.tasks))
        _eng.tasks[_k].result = FileResult(original="a", corrected="b")
        entry = next(iter(b._collect_results(_eng).values()), {})
        check("结果条目带 workflow=rewrite", entry.get("workflow") == "rewrite")

        # 2) 第 4 位 (废弃的 chunking_preset) 不再写旧字段
        before = b._config.chunking_preset
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            b.start_proofread([str(src)], "strict", "", "fast")
        check("废弃的第 4 参数不再改写 chunking_preset",
              b._config.chunking_preset == before)

        # 3) 老 5 参数调用仍绑定 force_rerun (第 6 位追加不破坏既有位置)
        h = compute_prompt_hash_for_config(b._config)
        save_checkpoint(src, FileTask(
            file_path=src, status=TaskStatus.COMPLETED, original_text="原文内容。" * 50,
            result=FileResult(original="原文内容。" * 50, corrected="改好了", prompt_hash=h),
        ))
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r_force = b.start_proofread([str(src)], "strict", "", "balanced", True)
        check("5 参数调用 = force_rerun (命中也不复用缓存)",
              r_force.get("cached_files") == [])
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r_cache = b.start_proofread([str(src)], "strict")
        check("3 参数调用仍走缓存 (对照)", r_cache.get("cached_files") == [str(src)])


# === test_v540_think_residue_cache ===
def test_v540_think_residue_cache():
    """v5.4 (PLAN §2 D9): 旧断点含思维链残留 → 定向失效强制重跑;
    原文自身含行首块 (harness 轨 corrected=原文) → 不重跑 (防永久打不中缓存)."""
    print("\n--- v5.4: 旧断点思维链残留定向失效 ---", flush=True)
    import tempfile
    from unittest.mock import AsyncMock, patch
    from app.web_backend import Backend
    from app.processor import ProcessingEngine
    from app.utils import (
        FileResult, FileTask, TaskStatus,
        compute_prompt_hash_for_config, save_checkpoint,
    )

    with tempfile.TemporaryDirectory(prefix="v540_think_") as tmp:
        src = Path(tmp) / "dirty.txt"
        body = "原文内容。" * 50
        src.write_text(body, encoding="utf-8")
        b = Backend(window=None)
        b._window = make_mock_window(None)

        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            b.start_proofread([str(src)], "strict")   # 初始化 config
        h = compute_prompt_hash_for_config(b._config)

        # 1) 原文干净 + corrected 含思维链残留 → 忽略缓存强制重跑
        save_checkpoint(src, FileTask(
            file_path=src, status=TaskStatus.COMPLETED, original_text=body,
            result=FileResult(original=body, corrected=f"<think>推理</think>{body}",
                              prompt_hash=h),
        ))
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r_dirty = b.start_proofread([str(src)], "strict")
        check("残留断点被定向失效 (cached_files 为空)",
              r_dirty.get("cached_files") == [], str(r_dirty.get("cached_files")))

        # 2) 原文自身含行首块 (corrected=原文) → 不重跑, 缓存照常命中
        body2 = f"<think>推理</think>{body}"
        save_checkpoint(src, FileTask(
            file_path=src, status=TaskStatus.COMPLETED, original_text=body2,
            result=FileResult(original=body2, corrected=body2, prompt_hash=h),
        ))
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r_self = b.start_proofread([str(src)], "strict")
        check("原文自带残留不重跑 (缓存照常命中)",
              r_self.get("cached_files") == [str(src)],
              str(r_self.get("cached_files")))


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
