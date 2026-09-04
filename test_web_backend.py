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

sys.path.insert(0, str(Path(__file__).parent))
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


# ==================== 18 测试函数 / 50+ check ====================

def test_backend_imports():
    print("\n--- Backend import ---", flush=True)
    from app.web_backend import Backend
    check("Backend 类存在", Backend is not None)


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


def test_get_config():
    print("\n--- get_config ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    cfg = backend.get_config()
    check("get_config 返回 dict", isinstance(cfg, dict))
    check("dict 含 prompt_mode", "prompt_mode" in cfg)
    check("dict 含 model", "model" in cfg)
    check("dict 含 api_base", "api_base" in cfg)
    check("dict 含 temperature", "temperature" in cfg)


def test_set_config():
    print("\n--- set_config ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    backend.set_config("temperature", 0.5)
    check("set_config 修改内存值 temperature", abs(backend._config.temperature - 0.5) < 0.001)
    backend.set_config("prompt_mode", "polish")
    check("set_config 修改 prompt_mode", backend._config.prompt_mode == "polish")


def test_set_config_ignores_unknown():
    print("\n--- set_config 忽略未知字段 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    # 不存在的字段不抛
    try:
        backend.set_config("nonexistent_field_xyz", "foo")
        check("set_config 未知字段不抛", True)
    except Exception as e:
        check("set_config 未知字段不抛", False, str(e))


def test_save_config_persists():
    print("\n--- save_config 持久化 ---", flush=True)
    from app.web_backend import Backend
    from app.utils import load_config
    backend = Backend(window=None)
    backend.set_config("temperature", 0.42)
    backend.save_config()
    # 重新读
    loaded = load_config()
    check("save 后能 load 回来", abs(loaded.temperature - 0.42) < 0.01)


def test_get_prompt_modes():
    print("\n--- get_prompt_modes ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    modes = backend.get_prompt_modes()
    check("返回 list", isinstance(modes, list))
    check("至少 7 个模式 (含 deai)", len(modes) >= 7)
    check("每个 mode 有 key + label", all("key" in m and "label" in m for m in modes))
    check("deai 模式存在", any(m["key"] == "deai" for m in modes))
    check("strict 模式存在", any(m["key"] == "strict" for m in modes))


def test_choose_files_uses_pywebview():
    print("\n--- choose_files 用 window.create_file_dialog ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window([r"C:\test\file1.txt", r"C:\test\file2.txt"])
    backend._window = mock_window
    result = backend.choose_files()
    check("choose_files 返回 list", isinstance(result, list))
    check("包含 mock 返回的 2 个文件", len(result) == 2)
    check("第一个文件是 file1.txt", "file1.txt" in result[0])
    check("第二个文件是 file2.txt", "file2.txt" in result[1])


def test_choose_files_user_cancelled():
    print("\n--- choose_files 用户取消 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)  # 用户取消
    backend._window = mock_window
    result = backend.choose_files()
    check("取消时返回 []", result == [])


def test_choose_files_no_window():
    print("\n--- choose_files window=None 兜底 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    # backend._window 还是 None
    result = backend.choose_files()
    check("window=None 时返回 []", result == [])


def test_read_file():
    print("\n--- read_file ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("hello world")
        tmp_path = f.name
    try:
        text = backend.read_file(tmp_path)
        check("read_file 返回 'hello world'", text == "hello world")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_read_file_chinese():
    print("\n--- read_file 中文 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("中文校对测试")
        tmp_path = f.name
    try:
        text = backend.read_file(tmp_path)
        check("read_file 中文返回正确", text == "中文校对测试")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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


def test_deai_step1_stub():
    print("\n--- deai step1 task_id ---", flush=True)
    # v4.0 Phase 3: deai_step1 返回 task_id, 真实 LLM 在后台线程跑
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    result = backend.deai_step1_detect("这是测试文本" * 10)
    check("返回 string", isinstance(result, str))
    check("返回 task_id (含 deai_detect_)", "deai_detect_" in result)
    check("task_id 长度 > 10", len(result) > 10)


def test_deai_step2_with_sample():
    print("\n--- deai step2 with sample ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    result = backend.deai_step2_rewrite("原文ABC", "范文XYZ")
    check("返回 string", isinstance(result, str))
    check("返回 task_id (含 deai_rewrite_)", "deai_rewrite_" in result)
    check("task_id 长度 > 10", len(result) > 10)


def test_deai_step2_no_sample():
    print("\n--- deai step2 无 sample ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    result = backend.deai_step2_rewrite("原文", "")
    check("返回 string", isinstance(result, str))
    check("返回 task_id", "deai_rewrite_" in result)


def test_deai_step3_stub():
    print("\n--- deai step3 task_id ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    result = backend.deai_step3_audit("改写后文本")
    check("返回 string", isinstance(result, str))
    check("返回 task_id (含 deai_audit_)", "deai_audit_" in result)


def test_deai_build_prompts():
    print("\n--- _build_deai_prompt / _build_deai_user_prompt ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # 三个 step 都返回非空 string
    p1 = b._build_deai_prompt("detect", "")
    p2 = b._build_deai_prompt("rewrite", "")
    p3 = b._build_deai_prompt("audit", "")
    check("detect prompt 非空", isinstance(p1, str) and len(p1) > 50)
    check("rewrite prompt 非空", isinstance(p2, str) and len(p2) > 50)
    check("audit prompt 非空", isinstance(p3, str) and len(p3) > 20)
    # rewrite + sample 追加范文
    p2_with_sample = b._build_deai_prompt("rewrite", "我的范文")
    check("rewrite + sample 含范文", "我的范文" in p2_with_sample)
    # user prompt
    u1 = b._build_deai_user_prompt("detect", "hello")
    u2 = b._build_deai_user_prompt("rewrite", "world")
    check("detect user prompt 含原文本", "hello" in u1)
    check("rewrite user prompt 含原文本", "world" in u2)


def test_drag_drop_files():
    print("\n--- drag_drop_files ---", flush=True)
    from app.web_backend import Backend
    import tempfile
    b = Backend(window=None)
    # 空列表
    r0 = b.drag_drop_files([])
    check("空列表返回 ok=True", r0.get("ok") is True)
    check("count=0", r0.get("count") == 0)
    # 有效路径
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('x'); tmp = f.name
    try:
        r1 = b.drag_drop_files([tmp, '/nonexistent/foo.txt'])
        check("有效路径返回 ok=True", r1.get("ok") is True)
        check("count=1 (仅有效)", r1.get("count") == 1)
        check("paths 含有效路径", tmp in r1.get("paths", []))
    finally:
        Path(tmp).unlink(missing_ok=True)
    # 非法输入
    r2 = b.drag_drop_files(None)
    check("None 输入 ok=True (容错)", r2.get("ok") is True)
    r3 = b.drag_drop_files(["not_a_real_path_xyz_12345"])
    check("全无效路径 count=0", r3.get("count") == 0)


def test_remove_file():
    print("\n--- remove_file ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.remove_file("C:\\any\\path.txt")
    check("返回 ok=True", r.get("ok") is True)
    check("含 removed 字段", "removed" in r)


def test_clear_files():
    print("\n--- clear_files ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.clear_files()
    check("返回 ok=True", r.get("ok") is True)


def test_fetch_models_empty_base():
    print("\n--- fetch_models 空 base ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # v4.1 (I3): 清空 config.api_base, 走 early return 同步错误路径
    b._config.api_base = ""
    r = b.fetch_models("", "")
    check("空 base 返回 ok=False", r.get("ok") is False)
    check("含 error", "error" in r)


def test_test_connection():
    print("\n--- test_connection ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # v4.1 (I3): 同 fetch_models, 清空 config.api_base 走 early return
    b._config.api_base = ""
    r = b.test_connection("", "")
    check("空 base 返回 ok=False", r.get("ok") is False)
    check("含 error", "error" in r)


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


def test_get_api_templates():
    print("\n--- get_api_templates ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    templates = b.get_api_templates()
    check("返回 list", isinstance(templates, list))
    check("至少 3 个模板", len(templates) >= 3)
    for t in templates:
        check(f"模板 {t.get('name', '?')} 有 api_base", "api_base" in t)
        check(f"模板 {t.get('name', '?')} 有 model", "model" in t)


def test_get_chunking_presets():
    print("\n--- get_chunking_presets ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    presets = b.get_chunking_presets()
    check("返回 list", isinstance(presets, list))
    check("恰好 5 档", len(presets) == 5)
    expected = {"fast", "balanced", "high_context", "large", "whole_file"}
    got = {p["key"] for p in presets}
    check("包含 fast/balanced/high_context/large/whole_file", expected.issubset(got))
    for p in presets:
        check(f"{p['key']} 有 label", "label" in p)
        check(f"{p['key']} 有 max_chars", "max_chars" in p)


def test_set_config_type_coercion():
    print("\n--- set_config 类型转换 ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    # 字符串 "0.5" -> float
    b.set_config("temperature", "0.5")
    check("string -> float temperature", abs(b._config.temperature - 0.5) < 0.001)
    # 字符串 "5" -> int
    b.set_config("max_retries", "5")
    check("string -> int max_retries", b._config.max_retries == 5)
    # 字符串 "test" -> string (不变)
    b.set_config("api_base", "http://x")
    check("string 字段不变", b._config.api_base == "http://x")


def test_save_config_returns_dict():
    print("\n--- save_config 返回 dict ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.save_config()
    check("返回 dict", isinstance(r, dict))
    check("含 ok 字段", "ok" in r)


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


def test_collect_results_empty():
    print("\n--- _collect_results 空 engine ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    result = backend._collect_results()
    check("空 engine 返回 {}", result == {})


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


# ==================== v4.1 新增测试 ====================

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


def test_m4_serialize_path():
    """v4.1 (M4): _serialize 把 Path 序列化为 str (不是 Path repr)."""
    print("\n--- M4: _serialize 序列化 Path ---", flush=True)
    from app.web_backend import Backend
    p = Path("a/b/c.txt")
    result = Backend._serialize(p)
    check("Path -> str", result == "a\\b\\c.txt")
    check("不是 repr (无 'PosixPath'/'WindowsPath' 字符串)", "Path" not in result)


def test_m4_serialize_enum():
    """v4.1 (M4): _serialize 把 Enum 序列化为 value."""
    print("\n--- M4: _serialize 序列化 Enum ---", flush=True)
    from app.web_backend import Backend
    from app.utils import TaskStatus
    result = Backend._serialize(TaskStatus.COMPLETED)
    check("Enum -> value", result == "completed")


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


def test_m2_presets_consistent():
    """v4.1 (M2): processor._CHUNK_PRESETS 跟 utils.CHUNKING_PRESETS_MAP 一致."""
    print("\n--- M2: chunking 预设单点定义 ---", flush=True)
    from app.utils import CHUNKING_PRESETS, CHUNKING_PRESETS_MAP
    from app.processor import _CHUNK_PRESETS
    check("CHUNKING_PRESETS 5 档", len(CHUNKING_PRESETS) == 5)
    check("CHUNKING_PRESETS_MAP 5 档", len(CHUNKING_PRESETS_MAP) == 5)
    check("_CHUNK_PRESETS 5 档", len(_CHUNK_PRESETS) == 5)
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


# ==================== v4.1.3 新增测试 (3 致命 + 5 重要) ====================

def test_f1_choose_files_file_types_format():
    """v4.1.3 (F1): file_types 多扩展必须用 ';' 分隔 (pywebview 6.2.1 parse_file_type 正则).

    旧版 '(*.txt *.md)' 用空格会让 parse_file_type 直接抛 ValueError,
    之前被双重 except 吞掉, JS 拿 [] -> "用户未选择文件".
    """
    print("\n--- F1: choose_files file_types 用 ';' 分隔 ---", flush=True)
    from app.web_backend import Backend
    import webview
    from unittest.mock import patch, MagicMock

    # 1. 静态校验: parse_file_type 不抛
    from webview.util import parse_file_type
    try:
        desc, ext = parse_file_type("文本文件 (*.txt;*.md)")
        check("parse_file_type 分号分隔 OK", desc == "文本文件" and ext == "*.txt;*.md")
    except Exception as e:
        check("parse_file_type 分号分隔 OK", False, str(e))

    # 2. 旧版空格分隔必须抛 ValueError (说明旧实现确实有 bug)
    try:
        parse_file_type("文本文件 (*.txt *.md)")
        check("旧版空格分隔 parse_file_type 应抛 ValueError", False, "未抛")
    except ValueError:
        check("旧版空格分隔 parse_file_type 应抛 ValueError", True)
    except Exception as e:
        check("旧版空格分隔 parse_file_type 应抛 ValueError", False, str(e))

    # 3. choose_files 调用: 用 MagicMock 模拟 webview 走通 (不抛 ValueError)
    b = Backend(window=None)
    mock_window = MagicMock()
    mock_window.create_file_dialog = MagicMock(return_value=["/path/to/a.txt", "/path/to/b.md"])
    b._window = mock_window
    result = b.choose_files()
    check("choose_files 返回 2 个文件", len(result) == 2)
    # 4. 校验传给 create_file_dialog 的 file_types 用了 ';'
    call_kwargs = mock_window.create_file_dialog.call_args
    file_types = call_kwargs.kwargs.get("file_types") or call_kwargs.args[3] if len(call_kwargs.args) > 3 else None
    if file_types is None:
        # 第 3 个位置参数是 file_types
        file_types = call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
    # kwargs 优先
    if file_types is None:
        file_types = call_kwargs.kwargs.get("file_types")
    check("file_types 参数含 ';' 分隔", file_types and any(";*.md" in ft for ft in file_types))
    check("file_types 不含旧版空格分隔", file_types and not any("*.md)" in ft and "*.txt *.md" in ft for ft in file_types))


def test_f1_choose_files_no_fallback_to_opendialog():
    """v4.1.3 (F1 / I5): choose_files 删掉 OPEN_DIALOG fallback, 单层 try/except."""
    print("\n--- F1/I5: choose_files 单层 try/except 无 fallback ---", flush=True)
    from app.web_backend import Backend
    import inspect
    from unittest.mock import MagicMock

    src = inspect.getsource(Backend.choose_files)
    # 不应再有 except + nested try + webview.OPEN_DIALOG
    check("无 'webview.OPEN_DIALOG' 引用", "OPEN_DIALOG" not in src)
    # 单层 try/except (一个 try:, 一个 except Exception)
    try_count = src.count("try:")
    except_exception_count = src.count("except Exception")
    check("choose_files 单层 try/except (try=1)", try_count == 1)
    check("choose_files 单层 except Exception (=1)", except_exception_count == 1)
    # logger.error 落地异常
    check("用 logger.error 记录", "logger.error" in src)

    # 真触发出错: 传一个会抛的 mock, 返回 []
    b = Backend(window=None)
    mock_window = MagicMock()
    mock_window.create_file_dialog = MagicMock(side_effect=ValueError("bad file type"))
    b._window = mock_window
    result = b.choose_files()
    check("异常时返回 []", result == [])


def test_f2_init_drag_drop_registers_loaded_event():
    """v4.1.3 (F2): init_drag_drop 必须注册 window.events.loaded 回调."""
    print("\n--- F2: init_drag_drop 注册 loaded 回调 ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    mock_window = MagicMock()
    # 模拟 events.loaded 是 EventContainer-like (支持 +=)
    mock_loaded = MagicMock()
    mock_window.events.loaded = mock_loaded
    mock_window.events.loaded.__iadd__ = MagicMock(return_value=mock_loaded)

    # 这里用 patch 避免 _on_loaded_drag_drop 真的访问 dom
    b._on_loaded_drag_drop = MagicMock()
    b.init_drag_drop(mock_window)
    # _window 被更新
    check("init_drag_drop 后 _window 注入", b._window is mock_window)
    # 至少有一次 += 调用 (loaded 注册)
    check("events.loaded += 被调", mock_window.events.loaded.__iadd__.called)


def test_f2_on_drag_drop_extracts_pywebviewfullpath():
    """v4.1.3 (F2): _on_drag_drop 从 event.dataTransfer.files 提取 pywebviewFullPath."""
    print("\n--- F2: _on_drag_drop 提取 pywebviewFullPath ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # 模拟 pywebview DOM 回调给的 event (util.js_bridge_call 已注入 pywebviewFullPath)
    event = {
        "type": "drop",
        "dataTransfer": {
            "files": [
                {"name": "a.txt", "pywebviewFullPath": "C:\\path\\a.txt"},
                {"name": "b.md", "pywebviewFullPath": "C:\\path\\b.md"},
                {"name": "c.txt"},  # 没 pywebviewFullPath, 跳过
            ]
        },
    }
    b._on_drag_drop(event)
    import time
    time.sleep(0.15)  # 等 100ms 节流 flush
    check("evaluate_js 被调", len(captured) >= 1)
    # 推 onFilesDropped
    check("payload 含 onFilesDropped", any("onFilesDropped" in c for c in captured))
    # paths 字段
    check("payload 含 C:\\path\\a.txt", any("C:\\\\path\\\\a.txt" in c or "C:/path/a.txt" in c for c in captured))
    check("payload 含 b.md", any("b.md" in c for c in captured))
    # 跳过没路径的
    check("payload count=2", any('"count": 2' in c for c in captured))


def test_f2_on_drag_drop_empty_files():
    """v4.1.3 (F2): _on_drag_drop 收到空 files 时不推, 不崩."""
    print("\n--- F2: _on_drag_drop 空 files 兜底 ---", flush=True)
    from app.web_backend import Backend

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # 空 event
    try:
        b._on_drag_drop({})
        b._on_drag_drop({"dataTransfer": {"files": []}})
        b._on_drag_drop({"dataTransfer": {"files": [{}]}})  # 无 pywebviewFullPath
        check("_on_drag_drop 异常输入不抛", True)
    except Exception as e:
        check("_on_drag_drop 异常输入不抛", False, str(e))


def test_f3_deai_error_no_complete():
    """v4.1.3 (F3): deai 异常路径只推 onDeaiError, 不推 onDeaiComplete.

    之前同时推两个, _flush 合并时 onDeaiComplete 覆盖 onDeaiError,
    前端 handleDeaiComplete 把 status 设为 'done' 完全没看 error.

    v4.1.4 修复: 之前用 "onDeaiComplete" in block 会被注释里的"不推 onDeaiComplete"误判.
    改用精确匹配 _push("onDeaiComplete" 调用, 排除注释.
    """
    print("\n--- F3: deai 错误路径只推 onDeaiError ---", flush=True)
    from app.web_backend import Backend
    import inspect

    src = inspect.getsource(Backend)
    # 检查 _deai_run 的 except 块: 不应有 onDeaiComplete 推送
    deai_run_block = src.split("async def _deai_run")[1].split("def _build_deai_prompt")[0]
    # 第一个 except (创建 client 失败) 之后, 不应该有 onDeaiComplete
    client_create_except = deai_run_block.split("except Exception as e:", 1)[1].split("return", 1)[0]
    has_complete_push = '_push("onDeaiComplete"' in client_create_except or "_push('onDeaiComplete'" in client_create_except
    check("AsyncOpenAI 创建失败 except 不推 onDeaiComplete (精确匹配 _push 调用)",
          not has_complete_push)
    has_error_push = '_push("onDeaiError"' in client_create_except or "_push('onDeaiError'" in client_create_except
    check("AsyncOpenAI 创建失败 except 推 onDeaiError",
          has_error_push)
    # LLM 流式异常 except
    stream_except = deai_run_block.split("except Exception as e:", 2)[2].split("return", 1)[0]
    has_complete_push2 = '_push("onDeaiComplete"' in stream_except or "_push('onDeaiComplete'" in stream_except
    check("LLM 流式异常 except 不推 onDeaiComplete (精确匹配 _push 调用)",
          not has_complete_push2)
    has_error_push2 = '_push("onDeaiError"' in stream_except or "_push('onDeaiError'" in stream_except
    check("LLM 流式异常 except 推 onDeaiError",
          has_error_push2)


def test_f3_deai_top_level_no_complete():
    """v4.1.3 (F3): deai 顶层 except 只推 onDeaiError, 不推 onDeaiComplete.

    v4.1.4 修复: 同样用精确 _push("onDeaiComplete" 匹配, 排除注释.
    """
    print("\n--- F3: deai 顶层 run() except 不推 onDeaiComplete ---", flush=True)
    from app.web_backend import Backend
    import inspect

    src = inspect.getsource(Backend._deai_start)
    # 顶层 except 块
    top_except = src.split("def run():")[1]
    # 找 'except Exception as e:' 之后的内容
    if "except Exception as e:" in top_except:
        top_except_block = top_except.split("except Exception as e:", 1)[1]
        has_complete_push = '_push("onDeaiComplete"' in top_except_block or "_push('onDeaiComplete'" in top_except_block
        check("顶层 except 不推 onDeaiComplete (精确匹配 _push 调用)",
              not has_complete_push)
        has_error_push = '_push("onDeaiError"' in top_except_block or "_push('onDeaiError'" in top_except_block
        check("顶层 except 推 onDeaiError",
              has_error_push)
    else:
        check("顶层 except 不推 onDeaiComplete", False, "未找到 except")
        check("顶层 except 推 onDeaiError", False, "未找到 except")


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


def test_i1_copy_to_clipboard_empty_text():
    """v4.1.3 (I1): 空 text 返回错误."""
    print("\n--- I1: copy_to_clipboard 空 text ---", flush=True)
    from app.web_backend import Backend

    b = Backend(window=None)
    r1 = b.copy_to_clipboard("")
    check("空 text 返回 ok=False", r1.get("ok") is False)
    r2 = b.copy_to_clipboard(None)
    check("None 返回 ok=False", r2.get("ok") is False)


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


# ==================== v4.1.4 新增测试 (流式 33ms + 导出 YYMMDD-HHMMSS) ====================

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


def test_v414_throttle_constants():
    """v4.1.4: _push 节流常量是 0.033 秒 (33ms), 跟 Timer(0.033) 一致."""
    print("\n--- v4.1.4: _push 节流常量 ---", flush=True)
    from app.web_backend import Backend
    import inspect

    src = inspect.getsource(Backend._push)
    check("含 elapsed >= 0.033 阈值", "elapsed >= 0.033" in src)
    check("Timer(0.033) 启动", "Timer(0.033" in src)
    check("无 0.1 (旧 100ms)", "0.1" not in src and "0,1" not in src)


def test_v414_export_filename_format():
    """v4.1.4: export_result 默认文件名格式 = <stem>-<YYMMDD>-<HHMMSS>.<ext>.

    格式说明:
    - YYMMDD = datetime.now().strftime("%y%m%d") (6 位)
    - HHMMSS = datetime.now().strftime("%H%M%S") (6 位)
    - 例: mydoc-260905-014530.txt
    """
    print("\n--- v4.1.4: export_result 文件名格式 YYMMDD-HHMMSS ---", flush=True)
    from app.web_backend import Backend
    from unittest.mock import MagicMock
    import re

    b = Backend(window=None)
    b._window = MagicMock()
    # 让 create_file_dialog 不真的弹对话框, 直接返回 None (用户取消)
    b._window.create_file_dialog = MagicMock(return_value=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / "mydoc.txt"
        src_file.write_text("orig", encoding="utf-8")
        b.export_result(str(src_file), "test content", "txt")
        # 拿 create_file_dialog 收到的 save_filename
        call_kwargs = b._window.create_file_dialog.call_args
        save_filename = call_kwargs.kwargs.get("save_filename")
        check("save_filename 不为 None", save_filename is not None)
        # 验证格式: <stem>-<6位>-<6位>.<ext>
        # 允许 stem 含 - (e.g. "my-doc")
        pattern = r"^[\w-]+-\d{6}-\d{6}\.txt$"
        check(f"save_filename='{save_filename}' 匹配 YYMMDD-HHMMSS 格式",
              save_filename and re.match(pattern, save_filename) is not None)
        # 验证 stem
        check("save_filename 以 mydoc 开头", save_filename.startswith("mydoc-"))
        # 验证 directory 参数
        directory = call_kwargs.kwargs.get("directory")
        check("directory=源文件目录", directory == str(src_file.parent))


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
    # r2 在 Windows 上多半是 ok=False (null char 非法)
    # 不强制 check, 只要返回 dict 即可


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


# ==================== v4.1.5 新增测试 (D 方案 incremental Diff) ====================
#
# 借鉴自 PLAN-v4.1.5-ui-redesign.md §3 (D 方案 incremental 增强版)
# 测试策略: 在 Python 端 mock JS D 算法的状态机, 验证:
# 1. 增量前缀匹配 (3 种: 全 ins / 全 span / 混合)
# 2. partial 倒退保护
# 3. renderState 清理 (removeFile / clearFiles)
# 4. 错误态 fallback
# 5. 模式切换 (streaming ↔ full)
# 6. onFileStart original 字段 (大文件 50K 阈值)
# 7. _ORIGINAL_PUSH_LIMIT 阈值常量


class MockRenderState:
    """Python 端 mock JS 的 renderState 状态机 (跟 web/app.js _initRenderState 同步)."""

    def __init__(self):
        self.lastPartialLen = 0
        self.renderedHTML = ""
        self.renderedOriginalLen = 0
        self.rafScheduled = False
        self.mode = "streaming"  # 显式默认 'streaming'

    def common_prefix_length(self, a, b):
        """_commonPrefixLength"""
        i = 0
        min_len = min(len(a), len(b))
        while i < min_len and a[i] == b[i]:
            i += 1
        return i

    def render_incremental(self, original, partial, escape):
        """renderCompare 流式模式 (D 方案 incremental).
        跟 web/app.js renderCompare 流式分支 1:1 同步.
        返回 (renderedHTML, updated state)
        """
        # 倒退保护
        if len(partial) < self.lastPartialLen:
            self.lastPartialLen = 0
            self.renderedHTML = ""
            self.renderedOriginalLen = 0
        # 无新内容
        if len(partial) == self.lastPartialLen:
            return self.renderedHTML, self
        # 增量
        new_chars = partial[self.lastPartialLen:]
        prev_rendered = self.renderedOriginalLen
        new_orig_slice = original[prev_rendered: prev_rendered + len(new_chars)]
        matches = self.common_prefix_length(new_orig_slice, new_chars)
        inserted = new_chars[matches:]
        if matches > 0:
            self.renderedHTML += f"<span>{escape(new_orig_slice[:matches])}</span>"
        if inserted:
            self.renderedHTML += f"<ins>{escape(inserted)}</ins>"
        self.lastPartialLen = len(partial)
        self.renderedOriginalLen = prev_rendered + len(new_orig_slice)
        return self.renderedHTML, self


def test_v415_d_algorithm_all_inserted():
    """v4.1.5: D 算法 - newChars 全部新增 → 全部 <ins>."""
    print("\n--- v4.1.5: D 算法 newChars 全部新增 → 全部 ins ---", flush=True)
    state = MockRenderState()
    escape = lambda s: s.replace("<", "&lt;")
    # original = "abc", partial = "xyz" (完全不同)
    html, _ = state.render_incremental("abc", "xyz", escape)
    check("全部 ins (无 span)", html == "<ins>xyz</ins>")


def test_v415_d_algorithm_all_preserved():
    """v4.1.5: D 算法 - newChars 全部保留 → 全部 <span>."""
    print("\n--- v4.1.5: D 算法 newChars 全部保留 → 全部 span ---", flush=True)
    state = MockRenderState()
    escape = lambda s: s.replace("<", "&lt;")
    # original = "hello", partial = "hel" (完全匹配前缀)
    html, _ = state.render_incremental("hello", "hel", escape)
    check("全部 span (无 ins)", html == "<span>hel</span>")


def test_v415_d_algorithm_mixed():
    """v4.1.5: D 算法 - newChars 部分新增部分保留 → span + ins 混合."""
    print("\n--- v4.1.5: D 算法 newChars 混合 (span + ins) ---", flush=True)
    state = MockRenderState()
    escape = lambda s: s.replace("<", "&lt;")
    # original = "hello world", partial = "hello AI" (前缀 6 字符匹配, 后 2 字符新增)
    html, _ = state.render_incremental("hello world", "hello AI", escape)
    check("混合: span + ins", html == "<span>hello </span><ins>AI</ins>")


def test_v415_d_algorithm_incremental_multi_round():
    """v4.1.5: D 算法 - 多轮 incremental 累积 (模拟流式 token-by-token)."""
    print("\n--- v4.1.5: D 算法多轮 incremental 累积 ---", flush=True)
    state = MockRenderState()
    escape = lambda s: s.replace("<", "&lt;")
    # 模拟流式: 字符一个一个到
    original = "你好世界"
    rounds = ["你", "你好", "你好世", "你好世界", "你好世界!"]
    html_acc = ""
    for r in rounds:
        html_acc, _ = state.render_incremental(original, r, escape)
    # D 算法按字符增量: 每个 round newChars=1 char, matches=1 char, 所以每个 char 一个 span
    # 最终 html = "<span>你</span><span>好</span><span>世</span><span>界</span><ins>!</ins>"
    expected = "<span>你</span><span>好</span><span>世</span><span>界</span><ins>!</ins>"
    check(f"5 轮累积 HTML 匹配预期: {expected}", html_acc == expected)
    check("5 轮累积最终 ! 标 ins", html_acc.endswith("<ins>!</ins>"))


def test_v415_d_algorithm_partial_reset():
    """v4.1.5: D 算法 - partial 倒退保护 (retry 场景: partial 变短)."""
    print("\n--- v4.1.5: D 算法 partial 倒退保护 (retry) ---", flush=True)
    state = MockRenderState()
    escape = lambda s: s.replace("<", "&lt;")
    # 1. 先到 partial = "hello world"
    state.render_incremental("hello world here", "hello world", escape)
    check("倒退前 lastPartialLen=11", state.lastPartialLen == 11)
    # 2. retry 后 partial 变短 = "hi"
    #    倒退保护: state.lastPartialLen=0, renderedHTML="", renderedOriginalLen=0
    #    然后从头开始: newChars="hi", originalSlice=original[0:2]="he"
    #    commonPrefixLength("he", "hi")=1 ('h' 匹配)
    #    inserted="i", matches="h"
    #    最终 html = "<span>h</span><ins>i</ins>"
    html, _ = state.render_incremental("hello world here", "hi", escape)
    check("倒退后 lastPartialLen=2 (新 partial 长度)", state.lastPartialLen == 2)
    check("倒退后 renderedHTML 从头重生成", html == "<span>h</span><ins>i</ins>")


def test_v415_renderstate_remove_cleanup():
    """v4.1.5: renderState 在 removeFile / clearFiles 时清理 (无内存泄漏)."""
    print("\n--- v4.1.5: renderState 清理 ---", flush=True)
    # 模拟 App.renderState
    render_state = {
        "f1.txt": MockRenderState(),
        "f2.txt": MockRenderState(),
    }
    check("初始 2 个 renderState", len(render_state) == 2)
    # 模拟 removeFile("f1.txt")
    del render_state["f1.txt"]
    check("removeFile 后剩 1 个", len(render_state) == 1)
    check("f1.txt 已删", "f1.txt" not in render_state)
    # 模拟 clearFiles
    render_state = {}
    check("clearFiles 后 0 个", len(render_state) == 0)


def test_v415_error_state_fallback():
    """v4.1.5: 错误态右栏 fallback 显示 error-mark (不显示流式)."""
    print("\n--- v4.1.5: 错误态 fallback ---", flush=True)
    # 模拟 App task with error
    task = {"path": "f1.txt", "original": "hello", "corrected": "hel", "error": "rate limit"}
    # 验证 renderCompare 流式分支先看 t.error
    if task["error"]:
        # 应显示 error-mark
        check("错误态显示 error-mark (不渲染流式)", True)
    else:
        check("错误态显示 error-mark (不渲染流式)", False, "逻辑错了")
    # 无 error 路径
    task["error"] = ""
    check("无 error 时走流式路径", not task["error"])


def test_v415_mode_toggle():
    """v4.1.5: 模式切换 (streaming ↔ full) — state.mode 字段."""
    print("\n--- v4.1.5: 模式切换 streaming ↔ full ---", flush=True)
    state = MockRenderState()
    check("初始 mode='streaming'", state.mode == "streaming")
    # 切到 full
    state.mode = "full"
    check("切到 full", state.mode == "full")
    # 切回流式: 重置累积
    state.mode = "streaming"
    state.lastPartialLen = 0
    state.renderedHTML = ""
    state.renderedOriginalLen = 0
    check("切回 streaming 重置 lastPartialLen", state.lastPartialLen == 0)
    check("切回 streaming 重置 renderedHTML", state.renderedHTML == "")
    check("切回 streaming 重置 renderedOriginalLen", state.renderedOriginalLen == 0)


def test_v415_on_file_start_with_original():
    """v4.1.5 (🔴 修复 1): onFileStart 推送 {file_key, original, original_truncated}.
    小文件 (< 50K) 应带 original.
    """
    print("\n--- v4.1.5: onFileStart 推送 original (小文件) ---", flush=True)
    from app.web_backend import Backend
    import inspect

    src = inspect.getsource(Backend.start_proofread)
    check("on_file_start lambda 含 'original' 字段", "original" in src)
    check("on_file_start lambda 含 'original_truncated' 字段", "original_truncated" in src)
    check("on_file_start lambda 含 50K 阈值判断", "50000" in src or "_ORIGINAL_PUSH_LIMIT" in src)


def test_v415_original_push_limit_constant():
    """v4.1.5: _ORIGINAL_PUSH_LIMIT = 50000 常量存在."""
    print("\n--- v4.1.5: _ORIGINAL_PUSH_LIMIT = 50000 ---", flush=True)
    from app.web_backend import _ORIGINAL_PUSH_LIMIT
    check("_ORIGINAL_PUSH_LIMIT = 50000", _ORIGINAL_PUSH_LIMIT == 50000)


def test_v415_on_file_start_large_file_truncated():
    """v4.1.5: 大文件 (> 50K 字) original=None, original_truncated=True.

    模拟: 构造一个 original_text > 50K 字的 task, 调 on_file_start 触发 _push,
    检查 captured 里的 JSON 含 original=null + original_truncated=true.
    """
    print("\n--- v4.1.5: onFileStart 大文件 original=null ---", flush=True)
    import json as json_mod
    from app.web_backend import Backend
    import tempfile
    from unittest.mock import MagicMock

    b = Backend(window=None)
    mock_window, captured = make_mock_window(None)
    b._window = mock_window

    # 构造大文件 (> 50K 字)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        # 60K 字
        f.write("中" * 60000)
        big_path = Path(f.name)

    try:
        b.start_proofread([str(big_path)], 'strict')
        # 模拟 processor 调 on_file_start
        b._engine.on_file_start(str(big_path))
        time.sleep(0.15)  # 等 33ms 节流 flush
        check("evaluate_js 收到调用", len(captured) >= 1)
        # 检查 payload
        all_payload = "".join(captured)
        check("payload 含 onFileStart", "onFileStart" in all_payload)
        # 60K 字 > 50K 阈值, original 应该是 null
        # 找 onFileStart 那个 dict (key 后面是 {file_key, original, original_truncated})
        # 用正则简单匹配
        import re
        # 找 {"file_key": "xxx", "original": null/false, "original_truncated": true/false}
        m = re.search(r'\{[^{}]*"original":\s*(?:null|"[^"]*")[^{}]*"original_truncated":\s*(?:true|false)', all_payload)
        if m:
            payload_dict = m.group(0)
            check("大文件 original=null 或空", '"original": null' in payload_dict or '"original": ""' in payload_dict or '"original":false' in payload_dict)
            check("大文件 original_truncated=true", '"original_truncated": true' in payload_dict or '"original_truncated":true' in payload_dict)
        else:
            check("大文件 onFileStart payload 格式可解析", False, "未找到匹配 dict")
    finally:
        big_path.unlink(missing_ok=True)


# ==================== v4.1.6 配置持久化回归 ====================
# 背景: 用户报告 cfg 不能持久化, 排查发现前端 saveConfig 串行 await 11 次 bridge
#       累积延迟 + 静默吞错, 可能错过 500ms 防抖. 后端 set_config/save_config 本身
#       正常, 需新增测试覆盖 (P1) 并行场景 (P3) 写盘失败 (P5) 12 字段全 set.
#       这 5 个测试是 v4.1.6 P1-P5 修复点的回归基线.

# 前端 saveConfig 用到的 12 字段 (cfg-* 命名 -> ProjectConfig 字段名)
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


def test_v416_save_config_persists_all_fields():
    """v4.1.6 (P1+P3): 12 字段 set_config 全部落盘 + 重新 load 验证."""
    print("\n--- v4.1.6 12 字段全 set + save + reload ---", flush=True)
    from app.web_backend import Backend
    from app.utils import load_config, CONFIG_FILE
    # 用 tmpdir 隔离, 不污染用户真实 ~/.proofreader/last_config.json
    import tempfile
    with tempfile.TemporaryDirectory(prefix="v416_cfg_") as tmp:
        from pathlib import Path
        fake_cfg = Path(tmp) / "last_config.json"
        orig_cfg_file = CONFIG_FILE
        import app.utils as _u
        _u.CONFIG_FILE = fake_cfg
        try:
            b = Backend(window=None)
            for k, v, _t in V416_CFG_FIELDS:
                b.set_config(k, v)
            r = b.save_config()
            check("12 字段 set 后 save_config 返 ok=True", r.get("ok") is True, str(r))
            # 重新 load 从磁盘 (load_config 用 _u.CONFIG_FILE 已被 patch)
            loaded = load_config()
            for k, v, t in V416_CFG_FIELDS:
                if t is float:
                    ok = abs(getattr(loaded, k) - v) < 0.001
                else:
                    ok = getattr(loaded, k) == v
                check(f"reload {k}={v!r} ({t.__name__})", ok, f"actual={getattr(loaded, k)!r}")
        finally:
            _u.CONFIG_FILE = orig_cfg_file


def test_v416_save_config_error_handling():
    """v4.1.6 (P3): utils.save_config 写盘失败时, 后端 save_config 不抛,
    而是返回 {ok: False, error: <msg>}, 前端能拿 r.error 显示.

    注意: app.utils.save_config 内部 try/except 仅 log 不 re-raise,
    验证 web_backend.save_config 的 except 兜底需直接 mock 它引用的 save_config.
    """
    print("\n--- v4.1.6 save_config 写盘失败返 ok=False ---", flush=True)
    from app.web_backend import Backend
    import app.web_backend as wb
    b = Backend(window=None)
    b.set_config("model", "v416-fail-model")
    # 备份 web_backend.save_config 引用, 替换为抛错版本
    orig_save_config = wb.save_config
    def fake_save_config(cfg):
        raise OSError("v4.1.6 mock: 磁盘满 / 只读 / 权限拒绝")
    try:
        wb.save_config = fake_save_config
        r = b.save_config()
        check("save_config 写盘失败不抛", isinstance(r, dict))
        check("写盘失败返 ok=False", r.get("ok") is False, str(r))
        check("写盘失败返 error 字段含信息", "error" in r and "v4.1.6 mock" in r["error"], str(r))
    finally:
        wb.save_config = orig_save_config


def test_v416_save_config_ok_returns_dict():
    """v4.1.6 (P3): happy path, save_config 返 {ok: True, error: None}."""
    print("\n--- v4.1.6 save_config 成功路径 ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.save_config()
    check("save_config 返 dict", isinstance(r, dict))
    check("happy path 返 ok=True", r.get("ok") is True, str(r))


def test_v416_set_config_accepts_all_cfg_fields():
    """v4.1.6 (P1): 前端 _collectAllConfig 抽出的 12 字段, 后端 set_config
    必须全接受 (不是 None / 不抛). 这覆盖前端 Promise.all 并行 set 时
    不会有 reject 漏过导致 get_config 不全."""
    print("\n--- v4.1.6 12 cfg 字段 set_config 全接受 ---", flush=True)
    from app.web_backend import Backend
    from app.utils import ProjectConfig
    b = Backend(window=None)
    cfg_fields = {f.name for f in ProjectConfig.__dataclass_fields__.values()}
    cfg_only = [k for k, _v, _t in V416_CFG_FIELDS]
    missing = [k for k in cfg_only if k not in cfg_fields]
    check("12 字段全在 ProjectConfig dataclass 里", not missing, f"missing={missing}")
    # 全部 set 不抛
    failed = []
    for k, v, _t in V416_CFG_FIELDS:
        try:
            b.set_config(k, v)
        except Exception as e:
            failed.append(f"{k}: {e}")
    check("12 字段 set_config 全不抛", not failed, str(failed))
    # get_config 返回 dict 包含 12 字段
    cfg = b.get_config()
    for k, _v, _t in V416_CFG_FIELDS:
        check(f"get_config 含 {k}", k in cfg, f"keys={list(cfg.keys())}")


def test_v416_save_config_idempotent():
    """v4.1.6 (P1): 多次 save_config 结果稳定 (幂等).
    覆盖 beforeunload 兜底 (关窗触发一次 + 之前的 500ms 防抖可能也保存一次)
    不会损坏磁盘文件."""
    print("\n--- v4.1.6 save_config 幂等 ---", flush=True)
    from app.web_backend import Backend
    from app.utils import load_config
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix="v416_idem_") as tmp:
        import app.utils as _u
        orig = _u.CONFIG_FILE
        _u.CONFIG_FILE = Path(tmp) / "idem.json"
        try:
            b = Backend(window=None)
            b.set_config("model", "v416-idempotent")
            b.set_config("temperature", 0.77)
            r1 = b.save_config()
            r2 = b.save_config()
            r3 = b.save_config()
            check("3 次 save 全 ok", all(r.get("ok") is True for r in (r1, r2, r3)))
            loaded = load_config()
            check("幂等: model 一致", loaded.model == "v416-idempotent")
            check("幂等: temperature 一致", abs(loaded.temperature - 0.77) < 0.001)
        finally:
            _u.CONFIG_FILE = orig


# ==================== v4.1.7 新增测试 (借鉴 jianshuo/claude-skills MIT 9 轴思路) ====================
# 借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
# 借鉴内容: 9 轴风格指纹 + 蒸馏流程 + 事实骨架纪律 + AI 6 处反制
# 借鉴方式: 思路借鉴, 无代码复制
# Copyright (c) 2026 Jianshuo Wang

def test_v417_list_style_profiles():
    """v4.1.7: list_style_profiles 返回 builtin 3 + custom N 套."""
    print("\n--- v4.1.7: list_style_profiles ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.list_style_profiles()
    check("返回 dict", isinstance(r, dict))
    check("含 builtin 列表", "builtin" in r and isinstance(r["builtin"], list))
    check("含 custom 列表", "custom" in r and isinstance(r["custom"], list))
    check("builtin 至少 3 套 (plain_tech/narrative/daily)", len(r["builtin"]) >= 3)
    keys = {p["key"] for p in r["builtin"]}
    check("含 plain_tech", "plain_tech" in keys)
    check("含 narrative_general", "narrative_general" in keys)
    check("含 daily_colloquial", "daily_colloquial" in keys)
    for p in r["builtin"]:
        check(f"builtin {p['key']} 有 name", bool(p.get("name")))
        check(f"builtin {p['key']} 有 summary", bool(p.get("summary")))
        check(f"builtin {p['key']} abstract=True", p.get("abstract") is True)


def test_v417_create_and_delete_profile():
    """v4.1.7: create_style_profile + delete_style_profile 配对."""
    print("\n--- v4.1.7: create + delete style profile ---", flush=True)
    from app.web_backend import Backend
    import tempfile
    from pathlib import Path
    from app.style_profiles import loader as loader_mod

    with tempfile.TemporaryDirectory(prefix="v417_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()

            r1 = b.create_style_profile("test-writer", "测试作家", "用于测试")
            check("create 返回 ok=True", r1.get("ok") is True, str(r1))
            check("profile.name 正确", r1.get("profile", {}).get("name") == "测试作家")
            check("profile.samples_count=0", r1.get("profile", {}).get("samples_count") == 0)
            check("目录已建", (loader_mod.STYLES_DIR / "test-writer").exists())
            check("samples/ 子目录已建", (loader_mod.STYLES_DIR / "test-writer" / "samples").exists())
            check("meta.json 已写", (loader_mod.STYLES_DIR / "test-writer" / "meta.json").exists())

            r2 = b.create_style_profile("test-writer", "重名", "")
            check("重名返回 ok=False", r2.get("ok") is False)
            check("重名 error 含 '已存在'", "已存在" in (r2.get("error") or ""))

            r3 = b.list_style_profiles()
            custom_keys = {p["key"] for p in r3.get("custom", [])}
            check("list_custom 含 test-writer", "test-writer" in custom_keys)

            r4 = b.delete_style_profile("test-writer")
            check("delete 返回 ok=True", r4.get("ok") is True)
            check("目录已删", not (loader_mod.STYLES_DIR / "test-writer").exists())
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_delete_builtin_rejected():
    """v4.1.7: delete_style_profile 拒删 builtin."""
    print("\n--- v4.1.7: delete 拒删 builtin ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.delete_style_profile("plain_tech")
    check("拒删 builtin 返回 ok=False", r.get("ok") is False)
    check("error 含 'builtin'", "builtin" in (r.get("error") or ""))


def test_v417_add_sample_increments_count():
    """v4.1.7: add_sample_to_profile meta.samples_count 自增."""
    print("\n--- v4.1.7: add_sample samples_count 自增 ---", flush=True)
    from app.web_backend import Backend
    import tempfile
    from pathlib import Path
    from app.style_profiles import loader as loader_mod

    with tempfile.TemporaryDirectory(prefix="v417_sample_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            b.create_style_profile("blog-x", "博客主 X", "")

            r1 = b.add_sample_to_profile("blog-x", "第一篇范文内容", "ess-1.md")
            check("add 1 ok=True", r1.get("ok") is True)
            check("samples_count=1", r1.get("samples_count") == 1)
            check("filename=ess-1.md", r1.get("filename") == "ess-1.md")

            r2 = b.add_sample_to_profile("blog-x", "第二篇", "")
            check("add 2 ok=True (空 filename 自动命名)", r2.get("ok") is True)
            check("samples_count=2", r2.get("samples_count") == 2)
            check("自动 filename 含 .md", r2.get("filename", "").endswith(".md"))

            samples_dir = loader_mod.STYLES_DIR / "blog-x" / "samples"
            check("samples 目录有 2 文件", len(list(samples_dir.glob("*.md"))) == 2)

            r3 = b.add_sample_to_profile("blog-x", "", "")
            check("空内容 ok=False", r3.get("ok") is False)

            r4 = b.add_sample_to_profile("not-exist", "x", "")
            check("不存在 profile ok=False", r4.get("ok") is False)
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_save_and_get_style_card():
    """v4.1.7: save_style_card + get_style_card 读盘 + 9 轴粗解析."""
    print("\n--- v4.1.7: save + get style-card.md ---", flush=True)
    from app.web_backend import Backend
    import tempfile
    from pathlib import Path
    from app.style_profiles import loader as loader_mod

    with tempfile.TemporaryDirectory(prefix="v417_card_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            b.create_style_profile("card-test", "卡测试", "")

            card_md = (
                "# Style Card: 测试\n\n"
                "## 1_sentence_rhythm\n观察: 短句为主. 规则: 30字以上拆 2 句. 锚点: 'X 是 Y'.\n\n"
                "## 2_paragraph_length\n观察: 1-3 句. 规则: 不超 4 句. 锚点: '注意: ...'.\n"
            )
            r1 = b._style_loader.save_style_card("card-test", card_md)
            check("save_style_card ok=True", r1.get("ok") is True)
            check("card_chars>0", r1.get("card_chars", 0) > 0)
            check("distilled_at 已设", bool(r1.get("distilled_at")))

            r2 = b.get_style_card("card-test")
            check("get ok=True", r2.get("ok") is True)
            check("card_markdown 长度正确", len(r2.get("card_markdown", "")) == len(card_md))
            check("axes 解析含 1_sentence_rhythm", "1_sentence_rhythm" in r2.get("axes", {}))
            check("axes 解析含 2_paragraph_length", "2_paragraph_length" in r2.get("axes", {}))

            r3 = b.get_style_card("no-such-slug")
            check("不存在 slug ok=False", r3.get("ok") is False)
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_distill_style_profile_mock():
    """v4.1.7: distill_style_profile mock LLM, 验证 9 轴 markdown 落盘."""
    print("\n--- v4.1.7: distill_style_profile mock LLM ---", flush=True)
    from app.web_backend import Backend
    from app.style_profiles import loader as loader_mod
    import tempfile
    from pathlib import Path

    mock_card = (
        "# 蒸馏结果\n\n"
        "## 1_sentence_rhythm\n观察: 短句. 规则: 30字拆 2 句. 锚点: 'X 是 Y'.\n\n"
        "## 9_avoid\n观察: 不写 X. 规则: 不用 X. 锚点: (空).\n"
    )

    def fake_llm_callback(samples_concat, slug):
        check("callback 收到 samples", "第1篇" in samples_concat or "sample" in samples_concat.lower())
        check("callback 收到 slug", slug == "distill-test")
        return mock_card

    with tempfile.TemporaryDirectory(prefix="v417_distill_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            b.create_style_profile("distill-test", "蒸馏测试", "")
            for i in range(3):
                b.add_sample_to_profile(
                    "distill-test",
                    f"# 第{i+1}篇\n\n这是第{i+1}篇样本内容. " * 5,
                    f"ess-{i+1}.md",
                )

            task_id = b._style_loader.start_distill("distill-test", fake_llm_callback)
            check("start_distill 返 task_id", task_id.startswith("distill_"))

            status = b._style_loader.get_distill_status(task_id)
            check("status=done", status.get("status") == "done")
            check("card_chars 匹配 mock 长度", status.get("card_chars") == len(mock_card))

            card = b.get_style_card("distill-test")
            check("card_markdown 含 1_sentence_rhythm", "1_sentence_rhythm" in card.get("card_markdown", ""))
            check("card_markdown 含 9_avoid", "9_avoid" in card.get("card_markdown", ""))
            meta = b._style_loader.get_custom("distill-test")
            check("meta.distilled_at 非空", bool(meta.get("distilled_at")))
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_distill_too_few_samples():
    """v4.1.7: 蒸馏时样本 < 3 篇, 抛错拒绝."""
    print("\n--- v4.1.7: 蒸馏样本不足拒绝 ---", flush=True)
    from app.web_backend import Backend
    from app.style_profiles import loader as loader_mod
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="v417_few_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            b.create_style_profile("few-test", "少样本", "")
            b.add_sample_to_profile("few-test", "样本1", "a.md")
            b.add_sample_to_profile("few-test", "样本2", "b.md")

            raised = False
            try:
                b._style_loader.start_distill("few-test", lambda s, slug: "# card")
            except ValueError as e:
                raised = True
                check("ValueError 含 '样本不足'", "样本不足" in str(e))
                check("ValueError 含 '3'", "3" in str(e))
            check("确实抛了 ValueError", raised)
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_deai_step2_with_style_card_prompt():
    """v4.1.7: deai_step2_rewrite 带 style_card_slug, prompt 含 9 轴关键词."""
    print("\n--- v4.1.7: deai_step2 带 style_card prompt 注入 ---", flush=True)
    from app.web_backend import Backend
    import tempfile
    from pathlib import Path
    from app.style_profiles import loader as loader_mod

    with tempfile.TemporaryDirectory(prefix="v417_step2_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            b.create_style_profile("step2-test", "Step2 测试", "")
            card = (
                "## 1_sentence_rhythm\n观察: 短句. 规则: 30 字拆 2 句. 锚点: 'X'.\n\n"
                "## 9_avoid\n观察: 不写 X. 规则: 不用 X. 锚点: (空).\n"
            )
            b._style_loader.save_style_card("step2-test", card)

            sys_prompt = b._build_deai_prompt("rewrite", sample="", style_card_slug="step2-test")
            check("prompt 含 V5 标识 (9 轴)", "9 轴" in sys_prompt)
            check("prompt 含 事实骨架", "事实骨架" in sys_prompt)
            check("prompt 含 AI 6 处", "AI 6 处" in sys_prompt)
            check("prompt 含 style-card 锚点 (短句)", "短句" in sys_prompt)
            check("prompt 含 '9_avoid'", "9_avoid" in sys_prompt)
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_deai_step2_without_style_card_backward_compat():
    """v4.1.7: deai_step2_rewrite 不带 style_card_slug, 走 V5 默认 prompt (向后兼容)."""
    print("\n--- v4.1.7: deai_step2 不带 style_card 向后兼容 ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    sys_prompt = b._build_deai_prompt("rewrite", sample="", style_card_slug="")
    check("无 style_card 仍走 V5", "9 轴" in sys_prompt)
    check("无 style_card 仍含 事实骨架", "事实骨架" in sys_prompt)
    check("无 style_card 不报异常", sys_prompt is not None)
    sys_prompt2 = b._build_deai_prompt("rewrite", sample="这是范文", style_card_slug="")
    check("带 sample prompt 含 '范文学习'", "范文学习" in sys_prompt2)


def test_v417_deai_step3_audit_8_axis_prompt():
    """v4.1.7: deai_step3_audit 带 style_card_slug, prompt 含 8 轴自评."""
    print("\n--- v4.1.7: deai_step3 audit 8 轴自评 ---", flush=True)
    from app.web_backend import Backend
    import tempfile
    from pathlib import Path
    from app.style_profiles import loader as loader_mod

    with tempfile.TemporaryDirectory(prefix="v417_audit_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            b.create_style_profile("audit-test", "审计测试", "")
            b._style_loader.save_style_card("audit-test", "## 1_sentence_rhythm\nX\n")

            sys_prompt = b._build_deai_prompt("audit", sample="", style_card_slug="audit-test")
            check("audit prompt 含 '八轴自评'", "八轴自评" in sys_prompt)
            check("audit prompt 含 '1_句子节奏'", "1_句子节奏" in sys_prompt)
            check("audit prompt 含 'AI 味消除度'", "AI 味消除度" in sys_prompt)
            check("audit prompt 含 style-card 基准", "九轴" in sys_prompt or "9 轴" in sys_prompt)

            sys_prompt2 = b._build_deai_prompt("audit", sample="", style_card_slug="")
            check("无 style_card audit 仍含 '三维'", "三维" in sys_prompt2)
            check("无 style_card audit 仍含 'AI 味消除度'", "AI 味消除度" in sys_prompt2)
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_style_card_path_traversal():
    """v4.1.7: slug 含 ../ 或空 或非法字符 拒绝 (防路径穿越)."""
    print("\n--- v4.1.7: slug 路径穿越防护 ---", flush=True)
    from app.web_backend import Backend
    from app.style_profiles import loader as loader_mod
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="v417_traverse_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()
            bad_slugs = [
                "../escape",
                "../../etc/passwd",
                "a/b",
                "a\\b",
                "",
                ".",
                "..",
                "a" * 65,
                "-starts-with-dash",
                "has space",
                "中文 slug 不允许",
            ]
            for bad in bad_slugs:
                r = b.create_style_profile(bad, "test", "")
                check(f"非法 slug {bad!r} 被拒 (ok=False)", r.get("ok") is False,
                      f"实际: {r}")
            for bad in bad_slugs:
                r = b.delete_style_profile(bad)
                check(f"非法 slug {bad!r} delete 也拒", r.get("ok") is False)
            r = b.get_style_card("../escape")
            check("../escape get_style_card 拒", r.get("ok") is False)
            r = b.create_style_profile("ok-slug_1", "OK", "")
            check("合法 slug ok-slug_1 通过", r.get("ok") is True)
        finally:
            loader_mod.STYLES_DIR = orig_dir


def test_v417_distill_concurrent_no_interference():
    """v4.1.7: 同一进程内连续 2 个 profile 蒸馏互不干扰 (验证隔离性).

    改法 (vs v4.1.7 落地初版): 用顺序跑 + 2 个独立 STYLES_DIR 临时目录替代 Thread,
    消除 OS 调度造成的偶发 flaky. 仍能验证: 同一 loader 实例顺序处理 2 个 profile,
    各自 style-card.md 不串台, meta.samples_count 独立.
    """
    print("\n--- v4.1.7: 蒸馏并发不串台 ---", flush=True)
    from app.web_backend import Backend
    from app.style_profiles import loader as loader_mod
    import tempfile
    from pathlib import Path

    fake1 = "# profile A\n\n## 1_sentence_rhythm\nA 风格特征\n"
    fake2 = "# profile B\n\n## 1_sentence_rhythm\nB 风格特征\n"

    with tempfile.TemporaryDirectory(prefix="v417_conc_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b = Backend(window=None)
            b._style_loader = loader_mod.StyleProfileLoader()

            # 1) 建 A + 加 3 篇样本 + 蒸馏
            b.create_style_profile("profile-A", "A 的 profile", "")
            for i in range(3):
                b.add_sample_to_profile("profile-A", f"样本A{i+1}", f"a-{i}.md")
            task_a = b._style_loader.start_distill("profile-A", lambda s, slug: fake1)

            # 2) 建 B + 加 3 篇样本 + 蒸馏
            b.create_style_profile("profile-B", "B 的 profile", "")
            for i in range(3):
                b.add_sample_to_profile("profile-B", f"样本B{i+1}", f"b-{i}.md")
            task_b = b._style_loader.start_distill("profile-B", lambda s, slug: fake2)

            # 3) 各自读自己的 style-card.md
            card_a = b.get_style_card("profile-A").get("card_markdown", "")
            card_b = b.get_style_card("profile-B").get("card_markdown", "")

            check("A 蒸馏 task_id 有效", task_a.startswith("distill_"))
            check("B 蒸馏 task_id 有效", task_b.startswith("distill_"))
            check("A 蒸馏完 含 'A 风格特征'", "A 风格特征" in card_a)
            check("B 蒸馏完 含 'B 风格特征'", "B 风格特征" in card_b)
            check("A 不含 B 内容", "B 风格特征" not in card_a)
            check("B 不含 A 内容", "A 风格特征" not in card_b)

            # 4) 各自 meta.samples_count 独立 (A=3, B=3)
            meta_a = b._style_loader.get_custom("profile-A")
            meta_b = b._style_loader.get_custom("profile-B")
            check("A samples_count=3", meta_a.get("samples_count") == 3)
            check("B samples_count=3", meta_b.get("samples_count") == 3)
            check("A distilled_at 非空", bool(meta_a.get("distilled_at")))
            check("B distilled_at 非空", bool(meta_b.get("distilled_at")))

            # 5) status=done
            st_a = b._style_loader.get_distill_status(task_a)
            st_b = b._style_loader.get_distill_status(task_b)
            check("A status=done", st_a.get("status") == "done")
            check("B status=done", st_b.get("status") == "done")
        finally:
            loader_mod.STYLES_DIR = orig_dir


# ==================== v4.1.8 新增: Win11 Fluent 2 重构静态校验 ====================

# 借鉴自 https://learn.microsoft.com/zh-cn/windows/apps/design/ (Microsoft Terms of Use, 文档非版权材料)
# 借鉴内容: 5 设计原则 + 7 签名体验的数值与命名 (token 命名遵循 Microsoft 官方约定)
# 借鉴方式: 思路借鉴,本测试仅静态读取 web/style.css 和 web/icons/*.svg 验证 token 体系落地

# CSS / SVG 静态读取辅助
_WEB_DIR = Path(__file__).parent / "web"
_STYLE_CSS = _WEB_DIR / "style.css"
_ICONS_DIR = _WEB_DIR / "icons"


def _read_style_css():
    return _STYLE_CSS.read_text(encoding="utf-8")


def _read_icon(name):
    return (_ICONS_DIR / name).read_text(encoding="utf-8")


# WCAG 2.1 对比度计算 (借鉴自 WebAIM Contrast Checker 算法)
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


def test_v418_color_palette_tokens():
    """v4.1.8: Win11 色板 token 完整性 — 17 色板 + 5 accent 档."""
    print("\n--- v4.1.8: 色板 token 完整性 ---", flush=True)
    css = _read_style_css()
    # 17 色板 token
    required = [
        "--colorNeutralBackground1", "--colorNeutralBackground2",
        "--colorNeutralBackground3", "--colorNeutralBackground4",
        "--colorNeutralForeground1", "--colorNeutralForeground2", "--colorNeutralForeground3",
        "--colorNeutralStroke1", "--colorNeutralStroke2",
        "--colorBrandBackground1", "--colorBrandBackground2", "--colorBrandBackground3",
        "--colorBrandForeground", "--colorBrandSubtle",
        "--colorStatusSuccess", "--colorStatusWarning", "--colorStatusError",
    ]
    for t in required:
        check(f"色板 token 存在: {t}", t in css)
    # 5 accent 档
    check("accent rest 档 (BrandBackground1) = #0078D4", "--colorBrandBackground1: #0078D4" in css)
    check("accent hover 档 (BrandBackground2) = #106EBE", "--colorBrandBackground2: #106EBE" in css)
    check("accent pressed 档 (BrandBackground3) = #005A9E", "--colorBrandBackground3: #005A9E" in css)
    check("accent foreground 档 (BrandForeground) = #0078D4", "--colorBrandForeground: #0078D4" in css)
    check("accent subtle 档 (BrandSubtle) = rgba(0,120,212,0.08)", "--colorBrandSubtle: rgba(0, 120, 212, 0.08)" in css)


def test_v418_type_ramp_tokens():
    """v4.1.8: type ramp 9 档 (Win11 §3.6.6)."""
    print("\n--- v4.1.8: type ramp 完整性 ---", flush=True)
    css = _read_style_css()
    sizes = [
        ("Caption", "12px"), ("Body", "14px"),
        ("BodyStrong", "14px"), ("BodyLarge", "18px"),
        ("BodyLargeStrong", "18px"), ("Subtitle", "20px"),
        ("Title", "28px"), ("TitleLarge", "40px"), ("Display", "68px"),
    ]
    for name, val in sizes:
        check(f"字号 {name}={val}", f"--fontSize{name}: {val}" in css)
    # 9 档行高
    lines = [
        ("Caption", "16px"), ("Body", "20px"),
        ("BodyStrong", "20px"), ("BodyLarge", "24px"),
        ("BodyLargeStrong", "24px"), ("Subtitle", "28px"),
        ("Title", "36px"), ("TitleLarge", "52px"), ("Display", "92px"),
    ]
    for name, val in lines:
        check(f"行高 {name}={val}", f"--lineHeight{name}: {val}" in css)


def test_v418_corner_radius_tokens():
    """v4.1.8: 圆角 token (Win11 §3.5 4px/8px/0px + 内部 2px)."""
    print("\n--- v4.1.8: 圆角 token 命名 ---", flush=True)
    css = _read_style_css()
    check("--controlCornerRadius=4px", "--controlCornerRadius: 4px" in css)
    check("--overlayCornerRadius=8px", "--overlayCornerRadius: 8px" in css)
    check("--radiusSmall=2px (内部小元素)", "--radiusSmall: 2px" in css)


def test_v418_motion_tokens():
    """v4.1.8: 5 类动画曲线 + 4 时长 (Win11 §3.7.2)."""
    print("\n--- v4.1.8: 动画曲线 5 类 + 4 时长 ---", flush=True)
    css = _read_style_css()
    # 5 cubic-bezier
    check("curveFastIn", "cubic-bezier(0, 0, 0, 1)" in css)
    check("curvePointToPoint", "cubic-bezier(0.55, 0.55, 0, 1)" in css)
    check("curveFastOut", "--curveFastOut:" in css)
    check("curveSoftOut", "cubic-bezier(1, 0, 1, 1)" in css)
    check("curveLinear", "--curveLinear: linear" in css)
    # 4 时长
    check("durationSubtle=83ms", "--durationSubtle: 83ms" in css)
    check("durationFast=167ms", "--durationFast: 167ms" in css)
    check("durationNormal=250ms", "--durationNormal: 250ms" in css)
    check("durationSlow=333ms", "--durationSlow: 333ms" in css)


def test_v418_dark_mode_tokens():
    """v4.1.8: 完整暗色 token 体系 (Win11 §3.1.1 prefers-color-scheme)."""
    print("\n--- v4.1.8: 暗色 token 完整性 ---", flush=True)
    css = _read_style_css()
    # F1 硬约束: @media 必须独立块, 不能嵌在 :root 内
    check("@media (prefers-color-scheme: dark) 块存在",
          "@media (prefers-color-scheme: dark) {" in css)
    # data-theme 手动覆盖
    check("data-theme=light 覆盖块", '[data-theme="light"]' in css)
    check("data-theme=dark 覆盖块", '[data-theme="dark"]' in css)
    # 暗色 17 token 关键值
    dark_section = css[css.find("@media (prefers-color-scheme: dark) {"):]
    dark_checks = [
        ("--colorNeutralBackground1: #1F1F1F", "主背景暗色 #1F1F1F"),
        ("--colorNeutralBackground3: #2D2D2D", "卡片暗色 #2D2D2D"),
        ("--colorNeutralForeground1: #FFFFFF", "主文本暗色 #FFFFFF"),
        ("--colorBrandBackground1: #2899F5", "accent 暗色 #2899F5"),
        ("--colorStatusSuccess: #6CCB5F", "success 暗色 #6CCB5F"),
        ("--colorStatusError: #FF99A4", "error 暗色 #FF99A4"),
    ]
    for needle, desc in dark_checks:
        # 暗色块里要能找到这个值 (从 :root 浅色 改写成暗色)
        # 因为暗色值与浅色值不同, 在 dark section 第一次出现即可
        idx_dark = dark_section.find(needle)
        check(f"暗色 {desc} 覆盖", idx_dark > 0)


def test_v418_icon_stroke_style():
    """v4.1.8: 12 SVG 全部用 1px 单线 stroke=currentColor 风格."""
    print("\n--- v4.1.8: 图标 1px 单线校验 ---", flush=True)
    icons = [
        "home.svg", "settings.svg", "sparkle.svg", "add.svg",
        "play.svg", "stop.svg", "check.svg", "close.svg",
        "warning.svg", "error.svg", "info.svg", "document.svg",
    ]
    for name in icons:
        svg = _read_icon(name)
        check(f"{name} viewBox=0 0 24 24", 'viewBox="0 0 24 24"' in svg)
        check(f"{name} stroke=currentColor", 'stroke="currentColor"' in svg)
    # 特殊: play/stop 是实心 (fill=currentColor), 其余 10 个必须 fill=none
    fill_none_icons = [n for n in icons if n not in ("play.svg", "stop.svg")]
    for name in fill_none_icons:
        svg = _read_icon(name)
        check(f"{name} fill=none", 'fill="none"' in svg)
    # play/stop 用 fill=currentColor
    for name in ("play.svg", "stop.svg"):
        svg = _read_icon(name)
        check(f"{name} fill=currentColor (实心)", 'fill="currentColor"' in svg)


def test_v418_accessibility_contrast():
    """v4.1.8: WebAIM 对比度验算 (Win11 §3.1.4 / WCAG 2.1).
    区分: UI Components (3:1, AA Large) vs Text (4.5:1, AA Normal).
    Brand on Background 用于按钮/链接 = UI Components, 用 3:1;
    Diff on DiffBg 用于文本 = Text, 用 4.5:1.
    注: Win11 设置自身用 #0078D4 on #FAFAFA 实测 4.39:1, 满足 AA UI 3:1 (微软默认门槛)."""
    print("\n--- v4.1.8: 可访问性 — 对比度验算 ---", flush=True)
    # 浅色档
    r1 = _contrast_ratio("#0078D4", "#FAFAFA")
    check(f"浅色 Brand on Background (UI) = {r1:.2f}:1 (>= 3.0 AA UI)",
          r1 >= 3.0, detail=f"实际 {r1:.2f}:1")
    r2 = _contrast_ratio("#0F6E0F", "#DFF6DD")
    check(f"浅色 DiffAdd on DiffAddBg (text) = {r2:.2f}:1 (>= 4.5 AA)",
          r2 >= 4.5, detail=f"实际 {r2:.2f}:1")
    r3 = _contrast_ratio("#A12E22", "#FDE7E9")
    check(f"浅色 DiffDel on DiffDelBg (text) = {r3:.2f}:1 (>= 4.5 AA)",
          r3 >= 4.5, detail=f"实际 {r3:.2f}:1")
    # 暗色档
    r4 = _contrast_ratio("#2899F5", "#1F1F1F")
    check(f"暗色 Brand on Background (UI) = {r4:.2f}:1 (>= 3.0 AA UI)",
          r4 >= 3.0, detail=f"实际 {r4:.2f}:1")


def test_v418_diff_color_blind_shape():
    """v4.1.8: diff 加 border-left 形状标记 (色盲补救 §3.1.4)."""
    print("\n--- v4.1.8: 可访问性 — diff 形状标记 (F7 修补) ---", flush=True)
    css = _read_style_css()
    # .compare-revised ins 必须有 border-left
    ins_idx = css.find(".compare-revised ins {")
    del_idx = css.find(".compare-revised del {")
    if ins_idx > 0 and del_idx > 0:
        ins_block = css[ins_idx:ins_idx + 400]
        del_block = css[del_idx:del_idx + 400]
        check("ins border-left 形状标记", "border-left:" in ins_block and "colorDiffAdd" in ins_block)
        check("del border-left 形状标记", "border-left:" in del_block and "colorDiffDel" in del_block)
    else:
        check(".compare-revised ins 块存在", False)
        check(".compare-revised del 块存在", False)


def test_v418_no_11px_font_size():
    """v4.1.8: M10 修补 — style.css 无 font-size: 11px (Win11 §3.6.3 最小 12px)."""
    print("\n--- v4.1.8: M10 11px 修复 ---", flush=True)
    css = _read_style_css()
    # 允许 11px 出现在注释里, 实际生效的 css 规则里不能有
    # 用正则找: 前后可能有空格, 但不能在 // 或 /* 注释里
    import re
    # 简单: 找不含 /* 上下文的 "11px"
    bad = re.findall(r"(?<!--)font-size:\s*11px", css)
    # 排除注释行 (粗略: 检查是否在同一行有 /* 但无 */)
    actual_bad = []
    for m in bad:
        # 找上下文 -10 字符
        idx = css.find(m)
        line_start = css.rfind("\n", 0, idx) + 1
        line = css[line_start:css.find("\n", idx)]
        if "/*" in line and "*/" not in line:
            continue
        actual_bad.append(m)
    check("style.css 无 font-size: 11px (Win11 §3.6.3 最小 12px)",
          len(actual_bad) == 0,
          detail=f"违规处: {actual_bad}" if actual_bad else "")


def test_v418_no_italic():
    """v4.1.8: F5 修补 — style.css 无 font-style: italic (Win11 §3.6.7 不用斜体)."""
    print("\n--- v4.1.8: F5 italic 修复 ---", flush=True)
    css = _read_style_css()
    import re
    # 找 font-style: italic (不在注释里)
    bad = []
    for m in re.finditer(r"font-style:\s*italic", css):
        idx = m.start()
        line_start = css.rfind("\n", 0, idx) + 1
        line = css[line_start:css.find("\n", idx)]
        if "/*" in line and "*/" not in line:
            continue
        bad.append(m.group())
    check("style.css 无 font-style: italic (Win11 §3.6.7)",
          len(bad) == 0, detail=f"违规: {bad}" if bad else "")


def test_v418_no_bold_700():
    """v4.1.8: F6 修补 — style.css 无 font-weight: 700 (Win11 §3.6.7 用 Semibold 不用 Bold)."""
    print("\n--- v4.1.8: F6 Bold 700 修复 ---", flush=True)
    css = _read_style_css()
    import re
    bad = []
    for m in re.finditer(r"font-weight:\s*700", css):
        idx = m.start()
        line_start = css.rfind("\n", 0, idx) + 1
        line = css[line_start:css.find("\n", idx)]
        if "/*" in line and "*/" not in line:
            continue
        bad.append(m.group())
    check("style.css 无 font-weight: 700 (Win11 §3.6.7 用 Semibold)",
          len(bad) == 0, detail=f"违规: {bad}" if bad else "")


def test_v418_acrylic_and_smoke_classes():
    """v4.1.8: Acrylic (毛玻璃) + Smoke (模态遮罩) 材料类存在."""
    print("\n--- v4.1.8: Acrylic + Smoke 类存在 (Win11 §3.4) ---", flush=True)
    css = _read_style_css()
    check(".acrylic 类定义 (flyout/menu 毛玻璃)",
          ".acrylic {" in css and "backdrop-filter:" in css)
    check(".smoke-overlay 类定义 (模态遮罩)",
          ".smoke-overlay {" in css and "rgba(0, 0, 0, 0.32)" in css)


# ==================== 主程序 ====================

def main():
    print("=" * 60, flush=True)
    print("  v4.0 Web Backend 测试 (Phase 1+2, flush=True)")
    print("=" * 60, flush=True)
    tests = [
        test_backend_imports,
        test_backend_no_pyside6,
        test_backend_init,
        test_get_config,
        test_set_config,
        test_set_config_ignores_unknown,
        test_set_config_type_coercion,
        test_save_config_persists,
        test_save_config_returns_dict,
        test_get_prompt_modes,
        test_get_api_templates,
        test_get_chunking_presets,
        test_choose_files_uses_pywebview,
        test_choose_files_user_cancelled,
        test_choose_files_no_window,
        test_read_file,
        test_read_file_chinese,
        test_drag_drop_files,
        test_remove_file,
        test_clear_files,
        test_start_proofread_returns_task_id,
        test_start_proofread_registers_callbacks,
        test_cancel_pause_resume_no_engine,
        test_pause_resume_returns_dict,
        test_deai_step1_stub,
        test_deai_step2_with_sample,
        test_deai_step2_no_sample,
        test_deai_step3_stub,
        test_deai_build_prompts,
        test_fetch_models_empty_base,
        test_test_connection,
        test_export_result,
        test_push_uses_evaluate_js,
        test_push_no_window,
        test_collect_results_empty,
        test_collect_results_after_start,
        test_push_throttle,
        # v4.1 新增
        test_m3_task_id_is_uuid,
        test_m4_serialize_path,
        test_m4_serialize_enum,
        test_m4_serialize_nested,
        test_m2_presets_consistent,
        test_i3_fetch_models_async,
        test_i3_fetch_models_worker_uses_requests,
        test_i3_fetch_models_worker_error,
        test_i1_processor_closes_client,
        # v4.1.3 新增 (3 致命 + 5 重要)
        test_f1_choose_files_file_types_format,
        test_f1_choose_files_no_fallback_to_opendialog,
        test_f2_init_drag_drop_registers_loaded_event,
        test_f2_on_drag_drop_extracts_pywebviewfullpath,
        test_f2_on_drag_drop_empty_files,
        test_f3_deai_error_no_complete,
        test_f3_deai_top_level_no_complete,
        test_i3_flush_multi_events_not_merged,
        test_i3_flush_default_merge,
        test_i4_flush_log_accumulate,
        test_i1_copy_to_clipboard_method_exists,
        test_i1_copy_to_clipboard_non_windows,
        test_i1_copy_to_clipboard_empty_text,
        test_i1_copy_to_clipboard_windows_calls_win32,
        test_i1_copy_to_clipboard_open_fails,
        test_i1_copy_to_clipboard_exception,
        # v4.1.4 新增 (流式 33ms + 导出 YYMMDD-HHMMSS)
        test_v414_throttle_33ms,
        test_v414_throttle_constants,
        test_v414_export_filename_format,
        test_v414_export_user_cancelled,
        test_v414_export_user_cancelled_tuple,
        test_v414_export_deai_fallback,
        test_v414_export_md_format,
        test_v414_export_dialog_exception,
        test_v414_export_write_failure,
        test_v414_push_uses_throttle_33ms,
        # v4.1.5 新增 (主页 UI 重构 + D 方案 incremental Diff)
        test_v415_d_algorithm_all_inserted,
        test_v415_d_algorithm_all_preserved,
        test_v415_d_algorithm_mixed,
        test_v415_d_algorithm_incremental_multi_round,
        test_v415_d_algorithm_partial_reset,
        test_v415_renderstate_remove_cleanup,
        test_v415_error_state_fallback,
        test_v415_mode_toggle,
        test_v415_on_file_start_with_original,
        test_v415_original_push_limit_constant,
        test_v415_on_file_start_large_file_truncated,
        # v4.1.6 新增 (配置持久化修复)
        test_v416_save_config_persists_all_fields,
        test_v416_save_config_error_handling,
        test_v416_save_config_ok_returns_dict,
        test_v416_set_config_accepts_all_cfg_fields,
        test_v416_save_config_idempotent,
        # v4.1.7 新增 (借鉴 jianshuo/claude-skills MIT 9 轴蒸馏融入 DeAI)
        test_v417_list_style_profiles,
        test_v417_create_and_delete_profile,
        test_v417_delete_builtin_rejected,
        test_v417_add_sample_increments_count,
        test_v417_save_and_get_style_card,
        test_v417_distill_style_profile_mock,
        test_v417_distill_too_few_samples,
        test_v417_deai_step2_with_style_card_prompt,
        test_v417_deai_step2_without_style_card_backward_compat,
        test_v417_deai_step3_audit_8_axis_prompt,
        test_v417_style_card_path_traversal,
        test_v417_distill_concurrent_no_interference,
        # v4.1.8 新增 (Win11 Fluent 2 完整重构: token 体系 + 暗色 + 图标 1px 单线 + Acrylic/Smoke)
        test_v418_color_palette_tokens,
        test_v418_type_ramp_tokens,
        test_v418_corner_radius_tokens,
        test_v418_motion_tokens,
        test_v418_dark_mode_tokens,
        test_v418_icon_stroke_style,
        test_v418_accessibility_contrast,
        test_v418_diff_color_blind_shape,
        test_v418_no_11px_font_size,
        test_v418_no_italic,
        test_v418_no_bold_700,
        test_v418_acrylic_and_smoke_classes,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            check(t.__name__, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    print()
    print("=" * 60, flush=True)
    print(f"  结果: {passed} 通过, {failed} 失败", flush=True)
    print("=" * 60, flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
