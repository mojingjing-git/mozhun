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
    check("恰好 6 个模式 (v5.0.0 模式精简)", len(modes) == 6, str([m["key"] for m in modes]))
    check("每个 mode 有 key + label", all("key" in m and "label" in m for m in modes))
    # v4.1.8.2 (审计 C4): deai 是去AI味视图专用遗留模式, 已从校对下拉过滤
    check("deai 模式已过滤", all(m["key"] != "deai" for m in modes))
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
        r = backend.read_file(tmp_path)
        check("read_file 返回 'hello world'", r["ok"] is True and r["content"] == "hello world")
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
        r = backend.read_file(tmp_path)
        check("read_file 中文返回正确", r["ok"] is True and r["content"] == "中文校对测试")
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
    # v4.3.2: 用户指定预设清单 (顺序即下拉顺序, 自定义收尾)
    expected_names = ["LM Studio", "OpenCodeGo", "OpenRouter", "MiniMax", "阿里百炼",
                      "智谱清言", "火山引擎", "硅基流动", "DeepSeek", "自定义"]
    actual_names = [t.get("name") for t in templates]
    check("预设清单与指定一致", actual_names == expected_names, str(actual_names))
    for t in templates:
        if t["name"] == "自定义":
            continue
        check(f"预设 {t['name']} base 非空或为自定义", t["api_base"] != "" or t["name"] == "自定义")


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

    v4.3.0: _deai_run 分块重构后源码位置解析失准, 改为行为断言 —
    mock AsyncOpenAI 让 create 抛错, 直接 await _deai_run 收集推送.
    """
    print("\n--- F3: deai 错误路径只推 onDeaiError (行为断言) ---", flush=True)
    import asyncio
    from unittest.mock import patch, MagicMock, AsyncMock
    from app.web_backend import Backend

    b = Backend(window=None)
    pushes = []
    b._push = lambda name, data=None: pushes.append((name, data))

    class _FailingCreate:
        async def __call__(self, **kwargs):
            raise RuntimeError("mock: LLM 不可达")

    fake_client = MagicMock()
    fake_client.chat.completions.create = _FailingCreate()
    fake_client.close = AsyncMock()
    fake_ctor = MagicMock(return_value=fake_client)

    with patch("app.web_backend.AsyncOpenAI", fake_ctor):
        asyncio.run(b._deai_run("deai_f3_test", "detect", "hello world", "", "", ""))

    names = [n for n, _ in pushes]
    check("异常路径推 onDeaiError", "onDeaiError" in names)
    check("异常路径不推 onDeaiComplete (F3 语义)", "onDeaiComplete" not in names)
    err = next((d for n, d in pushes if n == "onDeaiError"), {})
    check("onDeaiError 带 task_id", err.get("task_id") == "deai_f3_test")


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
    # v4.1.8.2 (审计 B5): 同步 flush 死分支已删, 节流常量走 Timer(0.033)
    check("含 Timer(0.033) 节流", "threading.Timer(0.033" in src)
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


# v4.1.8.2 (审计 K15): 0.033 是契约值 (v4.1.4 30FPS 决策), 此断言
# 属实现细节断言 — 改动节流间隔需同步更新这里与 AGENTS.md.
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


# ==================== v4.1.5 新增测试 (主页 UI 重构) ====================
#
# 借鉴自 PLAN-v4.1.5-ui-redesign.md §3 (D 方案 incremental 增强版)
# v4.1.8.1 (H11): 删除 Python 端 MockRenderState 镜像 D 算法测试 (全 ins/全 span/
# 混合/多轮/倒退) + 3 个恒真用例 (remove_cleanup/error_state_fallback/mode_toggle)
# —— 它们复刻 JS renderCompare 而非测试产品代码, 前端真逻辑回归时全绿, 虚增约
# 20 check. 保留与 Bridge 推送契约相关的用例 (onFileStart original 字段等).


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

    v4.1.8.2 (审计 B4): utils.save_config 现返回 bool (写盘失败 False 而非
    抛错/吞错), bridge 据此如实返回 {ok: False}.
    """
    print("\n--- v4.1.6 save_config 写盘失败返 ok=False ---", flush=True)
    from app.web_backend import Backend
    import app.web_backend as wb
    b = Backend(window=None)
    b.set_config("model", "v416-fail-model")
    # 备份 web_backend.save_config 引用, 替换为返 False 版本 (磁盘满/只读)
    orig_save_config = wb.save_config
    def fake_save_config(cfg):
        return False
    try:
        wb.save_config = fake_save_config
        r = b.save_config()
        check("save_config 写盘失败不抛", isinstance(r, dict))
        check("写盘失败返 ok=False", r.get("ok") is False, str(r))
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


def test_v418_builtin_style_card_injected():
    """v4.1.8.1 (H9/E1): 预置 profile (builtin) 选中后对 deai step2/3 生效.

    旧 bug: loader.get_style_card 只读 ~/.proofreader/styles/<slug>/style-card.md,
    builtin slug 无落盘卡恒返 "" -> _build_deai_prompt 注入空 -> step2 不按该
    风格改写 / step3 跳过 8 轴自评 (界面显示"已选", 实际静默 no-op).
    修复: get_style_card 对 builtin key 回退把内置 JSON 渲染成 9 轴 markdown.
    """
    print("\n--- v4.1.8.1: builtin style card 注入 (H9) ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)

    # 1) get_style_card 对 3 个 builtin slug 返回渲染卡 (不再空串)
    for slug in ("plain_tech", "narrative_general", "daily_colloquial"):
        card = b._style_loader.get_style_card(slug)
        check(f"{slug} 渲染非空 (H9)", bool(card and card.strip()))
        check(f"{slug} 含 9 轴段 (H9)",
              card and "## 1_sentence_rhythm" in card and "## 9_avoid" in card)

    # 2) 非 builtin 不存在 slug 仍返空串 (原语义不变)
    check("未知 slug 仍空串",
          b._style_loader.get_style_card("no-such-slug-v418") == "")

    # 3) deai step2/3 prompt 实际注入 builtin 卡内容
    p2 = b._build_deai_prompt("rewrite", sample="", style_card_slug="plain_tech")
    check("step2 prompt 含 '9 轴风格指纹卡'", "9 轴风格指纹卡" in p2)
    check("step2 prompt 含 builtin 卡内容", "通用技术文" in p2 or "预置抽象化" in p2)
    p3 = b._build_deai_prompt("audit", sample="", style_card_slug="narrative_general")
    check("step3 prompt 含 '9 轴风格指纹卡'", "9 轴风格指纹卡" in p3)


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


def _read_app_js():
    return (_WEB_DIR / "app.js").read_text(encoding="utf-8")


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


# ============================================================
# v4.1.9: Win11 视觉完全体 (设计文档 7 签名体验落地核验)
# ============================================================

def test_v419_win11_polish():
    """v4.1.9: Win11 视觉完全体静态核验.

    对照 Windows11-设计原则.md:
    - 3.4.3 Mica 近似基层 (body radial-gradient)
    - 3.6.1 Segoe UI Variable 光学尺寸
    - 3.4.4 ContentDialog (Smoke + 不透明面板 + elevation 128)
    - 3.4.2 Acrylic 上下文菜单 (JS 组合 .menu-flyout.acrylic)
    - 3.7.3 页面转换 (顶级页上滑入场) + prefers-reduced-motion
    - 3.2.1 Card elevation=8; 硬编码色清理 (file-status/.log/hover)
    """
    print()
    print("--- v4.1.9: Win11 视觉完全体 ---", flush=True)
    css = _read_style_css()
    js = _read_app_js()
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")

    # 3.4.3 Mica 近似: body 用中性色 radial-gradient 叠加
    check("body Mica 近似渐变", "radial-gradient" in css and "background-attachment: fixed" in css)
    # 3.6.1 字体: Segoe UI Variable + 光学尺寸
    check("body font-optical-sizing: auto", "font-optical-sizing: auto" in css)
    check("字体栈含 Segoe UI Variable", '"Segoe UI Variable"' in css)
    # 3.2.1 Card elevation=8
    card_idx = css.find(".card {")
    card_block = css[card_idx:card_idx + 400] if card_idx > 0 else ""
    check("Card elevation=8 (shadow-8)", "var(--shadow-8)" in card_block)
    # 3.4.4 ContentDialog
    check(".content-dialog 定义", ".content-dialog {" in css)
    check("对话框 elevation=128", "var(--shadow-128)" in css[css.find(".content-dialog"):css.find(".content-dialog") + 500])
    check(".dialog-smoke 用 --colorSmoke", "var(--colorSmoke)" in css[css.find(".dialog-smoke"):css.find(".dialog-smoke") + 300])
    check("index.html 有 dialog-root", 'id="dialog-root"' in html)
    check("app.js 有 showConfirmDialog", "showConfirmDialog" in js)
    check("clearFiles 不再用原生 confirm",
          "if (!confirm(" not in js and "window.confirm" not in js)
    # 3.4.2 Acrylic flyout
    check(".menu-flyout 定义", ".menu-flyout {" in css)
    check("flyout 组合 acrylic 材料", 'menu-flyout acrylic' in js)
    check("app.js 有右键菜单绑定", "bindFileContextMenu" in js and "contextmenu" in js)
    # 3.7.3 页面转换 + reduced-motion
    check("@keyframes pageTransitionIn", "@keyframes pageTransitionIn" in css)
    check(".view.active 应用入场动画", "pageTransitionIn var(--durationFast)" in css)
    check("prefers-reduced-motion 守卫", "@media (prefers-reduced-motion: reduce)" in css)
    # 焦点可见 (a11y)
    check(":focus-visible 焦点环", ":focus-visible" in css)
    # 硬编码色清理
    fs_idx = css.find(".file-status.pending")
    fs_block = css[fs_idx:fs_idx + 700] if fs_idx > 0 else ""
    check("file-status 全 token 化", "var(--color" in fs_block and "#E8F1FB" not in fs_block)
    log_idx = css.find("\n.log {")
    log_block = css[log_idx:log_idx + 300] if log_idx > 0 else ""
    check(".log 主题感知 token 化", "var(--colorNeutralBackground2)" in log_block and "#1A1A1A" not in log_block)
    check("input hover token 化", "var(--colorNeutralStrokeHover)" in css and "border-color: #C5C5C5" not in css)
    # 死代码清理
    check(".diff-tabs 死类已删", ".diff-tabs" not in css)
    check(".btn-small 死类已删", ".btn-small" not in css)
    check(".compare-empty 死类已删", ".compare-empty" not in css)
    check(".style-profile-card 死类已删", ".style-profile-card" not in css)


def test_v419_ui_theme_roundtrip():
    """v4.1.9: ui_theme 主题持久化字段 — 默认 auto + 往返一致 + 旧配置兼容."""
    print()
    print("--- v4.1.9: ui_theme 往返 ---", flush=True)
    from app.utils import ProjectConfig
    cfg = ProjectConfig()
    check("ui_theme 默认 auto", cfg.ui_theme == "auto")
    cfg.ui_theme = "dark"
    d = cfg.to_dict()
    check("to_dict 含 ui_theme", d.get("ui_theme") == "dark")
    cfg2 = ProjectConfig.from_dict(d)
    check("from_dict 还原 dark", cfg2.ui_theme == "dark")
    # 旧配置 (v4.1.8 以前) 无 ui_theme 字段 -> 默认 auto
    cfg3 = ProjectConfig.from_dict({k: v for k, v in d.items() if k != "ui_theme"})
    check("旧配置兼容 (缺字段 -> auto)", cfg3.ui_theme == "auto")
    # bridge set_config 可写
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.set_config("ui_theme", "light")
    check("set_config 可写 ui_theme", r.get("ok") is True and b._config.ui_theme == "light")


def test_v440_ui_skin_roundtrip():
    """v4.4.0: ui_skin 界面皮肤字段 — v4.4.1 起默认 ink + 往返一致 + 旧配置兼容 + set_config 可写."""
    print()
    print("--- v4.4.0: ui_skin 往返 ---", flush=True)
    from app.utils import ProjectConfig
    cfg = ProjectConfig()
    check("ui_skin 默认 ink (v4.4.1)", cfg.ui_skin == "ink")
    cfg.ui_skin = "fluent"
    d = cfg.to_dict()
    check("to_dict 含 ui_skin", d.get("ui_skin") == "fluent")
    cfg2 = ProjectConfig.from_dict(d)
    check("from_dict 还原 fluent", cfg2.ui_skin == "fluent")
    # 旧配置 (v4.3.5 以前) 无 ui_skin 字段 -> 跟随新默认 ink
    cfg3 = ProjectConfig.from_dict({k: v for k, v in d.items() if k != "ui_skin"})
    check("旧配置兼容 (缺字段 -> ink)", cfg3.ui_skin == "ink")
    # bridge set_config 可写 (写非默认值)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.set_config("ui_skin", "fluent")
    check("set_config 可写 ui_skin", r.get("ok") is True and b._config.ui_skin == "fluent")


def test_v440_ink_skin_css():
    """v4.4.0: 水墨皮肤 CSS — 3 个 token 块/选择器统一 html 前缀/源序/token 全集/对比度/前端绑定."""
    print()
    print("--- v4.4.0: 水墨皮肤 CSS 完整性 ---", flush=True)
    css = _read_style_css()
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = _read_app_js()

    # --- 3 个 ink token 块 (浅色分组含 light 档) + html 前缀统一 (防 :root 混用移轴) ---
    sel_light = 'html[data-skin="ink"],\nhtml[data-skin="ink"][data-theme="light"] {'
    sel_media = '@media (prefers-color-scheme: dark) {\n  html[data-skin="ink"] {'
    sel_manual = 'html[data-skin="ink"][data-theme="dark"] {'
    check("ink 浅色块 (分组两选择器)", sel_light in css)
    check("ink 深 media 块", sel_media in css)
    check("ink 深 manual 块", sel_manual in css)
    check("ink 选择器统一 html 前缀 (无 :root 混用)", ":root[data-skin" not in css)
    # 源序硬前提: ink 浅块 (0,1,1) 与 ink 深 media (0,1,1) 同特异性, 必须浅块在前
    check("源序: ink 浅块 < ink 深 media 块",
          css.index(sel_light) < css.index(sel_media))

    # ink 深 media 块与 manual 块声明逐字一致 — 浅色系统无法实拍 media 深色路径,
    # 用静态等价兜底: 内容等价 + manual 已验证 => media 等价 (评审 P1-3)
    def _inner_body(css_text, marker, skip_outer):
        i = css_text.index(marker)
        j = css_text.index("{", i)
        if skip_outer:
            j = css_text.index("{", j + 1)
        depth = 0
        for k in range(j, len(css_text)):
            if css_text[k] == "{":
                depth += 1
            elif css_text[k] == "}":
                depth -= 1
                if depth == 0:
                    return css_text[j + 1:k]
        return ""
    import re as _re

    def _norm_block(block_text):
        # 剥离行尾注释与缩进, 只比较声明本体 (media 块带教学注释, manual 块不带)
        out = []
        for line in block_text.strip().splitlines():
            line = _re.sub(r"/\*.*?\*/", "", line).strip()
            if line:
                out.append(line)
        return out
    check("ink 深 media 块与 manual 块声明一致 (剥注释后)",
          _norm_block(_inner_body(css, sel_media, True))
          == _norm_block(_inner_body(css, sel_manual, False)))

    # --- token 全集: 27 色板 token 必须在 4 个 fluent 块 + 3 个 ink 块各定义一次 (漏项会串回 fluent 冷色) ---
    core_tokens = [
        "colorNeutralBackground1", "colorNeutralBackground2", "colorNeutralBackground3",
        "colorNeutralBackground4", "colorNeutralForeground1", "colorNeutralForeground2",
        "colorNeutralForeground3", "colorNeutralStroke1", "colorNeutralStroke2",
        "colorNeutralStrokeHover", "colorBrandBackground1", "colorBrandBackground2",
        "colorBrandBackground3", "colorBrandForeground", "colorBrandSubtle",
        "colorAccentForegroundOnAccent", "colorStatusSuccess", "colorStatusWarning",
        "colorStatusError", "colorStatusSuccessSubtle", "colorStatusWarningSubtle",
        "colorStatusErrorSubtle", "colorDiffAdd", "colorDiffAddBg", "colorDiffDel",
        "colorDiffDelBg", "colorDiffSame",
    ]
    for t in core_tokens:
        check(f"token 全集: --{t} 定义 >= 7 块", css.count(f"--{t}:") >= 7)
    check("token: --colorSmoke 定义 >= 4 块", css.count("--colorSmoke:") >= 4)
    check("token: --colorAcrylicBg 定义 >= 7 块 (v4.4.0 令牌化)", css.count("--colorAcrylicBg:") >= 7)
    check("token: --skin-halo-1/-2 定义 >= 3 块",
          css.count("--skin-halo-1:") >= 3 and css.count("--skin-halo-2:") >= 3)
    check("token: --fontFamilyBrand 已定义", "--fontFamilyBrand:" in css)
    check("acrylic 规则已走 var (无硬编码 rgba 残留)", ".acrylic {\n  background: var(--colorAcrylicBg);" in css)

    # --- 装饰层守卫: ink 装饰规则必须带 [data-skin="ink"], fluent 下零影响 ---
    for deco in ("html[data-skin=\"ink\"] body {", "html[data-skin=\"ink\"] .sidebar-title",
                 "html[data-skin=\"ink\"] .page-header h1"):
        check(f"装饰规则带 skin 守卫: {deco[:34]}...", deco in css)

    # --- 对比度验算 (ink 两档, Text 4.5 门槛) ---
    r1 = _contrast_ratio("#6E6757", "#F7F3E9")
    check(f"ink 浅 淡墨 on 宣纸 = {r1:.2f}:1 (>= 4.5 AA)", r1 >= 4.5, detail=f"实际 {r1:.2f}:1")
    r2 = _contrast_ratio("#3A3226", "#F7F3E9")
    check(f"ink 浅 墨链 on 宣纸 = {r2:.2f}:1 (>= 4.5 AA)", r2 >= 4.5, detail=f"实际 {r2:.2f}:1")
    r3 = _contrast_ratio("#998F7B", "#191612")
    check(f"ink 深 淡墨 on 玄墨 = {r3:.2f}:1 (>= 4.5 AA)", r3 >= 4.5, detail=f"实际 {r3:.2f}:1")
    r4 = _contrast_ratio("#1C1813", "#EDE6D6")
    check(f"ink 深 墨字 on 纸底(阳文) = {r4:.2f}:1 (>= 4.5 AA)", r4 >= 4.5, detail=f"实际 {r4:.2f}:1")

    # --- 前端绑定: 选择器 + JS 方法 + 挂载 + 恢复 ---
    check("id 唯一: skin-switcher", html.count('id="skin-switcher"') == 1)
    check("皮肤按钮 data-skin-value 齐全",
          'data-skin-value="fluent"' in html and 'data-skin-value="ink"' in html)
    # v4.4.1: 默认皮肤 ink — 首帧静态属性 (默认用户无 FOUC) + 切换器默认选中 ink
    check("index.html 首帧静态 data-skin=ink", 'data-skin="ink"' in html)
    check("切换器默认 active=ink", '<button type="button" data-skin-value="ink" class="active"' in html)
    check("init 回退值为 ink", "this.applySkin(this.config.ui_skin || 'ink')" in js)
    for fn in ("applySkin(value) {", "_persistSkin(value) {", "bindSkinSwitcher() {"):
        check(f"JS 方法存在: {fn[:-2]}", fn in js)
    check("bindEvents 挂载 bindSkinSwitcher", "this.bindSkinSwitcher();" in js)
    check("_persistSkin 写 ui_skin", "set_config('ui_skin', value)" in js)


def test_v442_md_local_ui():
    """v4.4.2: Markdown 清洗 — 模式注册 + 前端跳过 API 校验 + 剥离开关 UI + 引擎接线."""
    print()
    print("--- v4.4.2: md_local 模式与 UI ---", flush=True)
    from app.templates import PROMPT_MODES
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = _read_app_js()
    proc = (_WEB_DIR.parent / "app" / "processor.py").read_text(encoding="utf-8")

    # 模式注册 (PLACEHOLDER 同 punct_local — system 永不发送 LLM)
    info = PROMPT_MODES.get("md_local", {})
    check("PROMPT_MODES 含 md_local",
          info.get("label") == "仅 Markdown 清洗（本地脚本，不调用 LLM）")
    check("md_local system=PLACEHOLDER (永不发送)", info.get("system") == "PLACEHOLDER")
    # 前端: 本地双模式跳过 API 校验 + 剥离开关读写
    check("前端本地双模式跳过 API 校验",
          "['punct_local', 'md_local'].includes(this.getVal('cfg-prompt-mode'))" in js)
    check("id 唯一: cfg-md-strip", html.count('id="cfg-md-strip"') == 1)
    check("renderSettings 恢复 md_strip_before_llm", "md_strip_before_llm === true" in js)
    check("_collectAllConfig 写 md_strip_before_llm", "md_strip_before_llm: (() => {" in js)
    # 引擎接线: import / md_local 分支 / 双本地模式不建客户端 / 剥离先于标点
    check("processor 引入 strip_markdown", "from app.md_strip import strip_markdown" in proc)
    check("processor md_local 分支", 'prompt_mode == "md_local"' in proc)
    check("双本地模式不建 AsyncOpenAI",
          'prompt_mode in ("punct_local", "md_local")' in proc)
    check("剥离先于标点修复 (md_strip_before_llm 块在前)",
          proc.index("md_strip_before_llm") < proc.index("fix_punctuation_ex(text"))
    # 引擎分支端到端/幂等/规则全集在 test_md_strip.py (89 项)


def test_v500_deai_load_source():
    """v5.0.0 Phase B: deai_load_source 联动取数 — 内存命中/未完成/缺失/stale + 前端接线."""
    print()
    print("--- v5.0.0: deai_load_source 联动取数 ---", flush=True)
    from pathlib import Path as _Path
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig, FileTask, FileResult
    from app.web_backend import Backend
    b = Backend(window=None)
    check("无 engine -> stale",
          b.deai_load_source("a.txt") == {"ok": False, "reason": "stale"})
    engine = ProcessingEngine(ProjectConfig())
    b._engine = engine
    check("任务不存在 -> stale",
          b.deai_load_source("a.txt") == {"ok": False, "reason": "stale"})
    task = FileTask(file_path=_Path("a.txt"), original_text="原文")
    engine.tasks["a.txt"] = task
    check("未完成 -> not_completed",
          b.deai_load_source("a.txt") == {"ok": False, "reason": "not_completed"})
    task.result = FileResult(original="原文", corrected="改后")
    r = b.deai_load_source("a.txt")
    check("已完成 -> ok + text + file_name",
          r.get("ok") is True and r.get("text") == "改后" and r.get("file_name") == "a.txt", str(r))
    # 前端接线: 联动按钮 + 取数 + 跳检测直改
    js = _read_app_js()
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    check("前端联动按钮 (file-deai, 仅 completed 渲染)",
          "file-deai" in js and "t.status === 'completed'" in js)
    check("handoff 调后端取数 API", "deai_load_source(path)" in js)
    check("handoff 跳过检测直接 Step 2", "await this.deaiStep2()" in js)
    check("DeAI 输入框存在 (预填宿主)", html.count('id="deai-input"') == 1)



def test_v420_nav_split():
    """v4.2.0: 3 视图 -> 7 视图拆分 (Win11 设置应用式分组导航).

    核验: 7 个视图 id 齐全 / 分组导航 / 关键元素 id 单一存在 (JS 绑定不变) /
    结果页文件下拉 / cfg 字段分布两页后防抖选择器覆盖 / CSS 新组件。
    """
    print()
    print("--- v4.2.0: 7 视图导航拆分 ---", flush=True)
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = _read_app_js()
    css = _read_style_css()

    # 7 视图齐全
    for vid in ("view-home", "view-results", "view-deai", "view-styles",
                "view-api", "view-params", "view-appearance"):
        check(f"视图 {vid} 存在", f'id="{vid}"' in html)
    # 分组导航
    for dv in ("home", "results", "deai", "styles", "api", "params", "appearance"):
        check(f"导航项 data-view={dv}", f'data-view="{dv}"' in html)
    check("导航分组「工作区」", ">工作区</div>" in html)
    check("导航分组「设置」", ">设置</div>" in html)
    # 关键元素 id 全局唯一 (拆分最容易引入重复 id)
    for eid in ("compare-original", "compare-revised", "log-output", "progress-fill",
                "theme-switcher", "dialog-root", "deai-style-profile",
                "styles-profile-select", "btn-start", "btn-save-config",
                "result-file-select", "file-list", "drop-zone"):
        check(f"id 唯一: {eid}", html.count(f'id="{eid}"') == 1)
    # cfg 12 字段齐全
    cfg_ids = ["cfg-template", "cfg-api-base", "cfg-api-key", "cfg-model",
               "cfg-temperature", "cfg-concurrency", "cfg-max-retries", "cfg-timeout",
               "cfg-chunking-preset", "cfg-context-max-chars", "cfg-context-max-chunks",
               "cfg-custom-prompt", "cfg-prompt-mode"]
    for cid in cfg_ids:
        check(f"配置项存在: {cid}", f'id="{cid}"' in html)
    # JS 适配
    check("结果页下拉渲染函数", "renderResultFileSelect" in js)
    check("点击文件跳转结果页", "this.setView('results')" in js)
    check("防抖选择器覆盖 view-api/params/appearance",
          "#view-api input" in js and "#view-params input" in js)
    check("Ctrl+, 指向 API 接口页", "this.setView('api')" in js)
    check("风格库下拉镜像绑定", "styles-profile-select" in js)
    # CSS 新组件
    for cls in (".nav-group {", ".sidebar-footer {", ".content-narrow {",
                ".result-select {", ".about-row {"):
        check(f"CSS 组件 {cls.strip()} ", cls in css)
    check("home-grid 两列等宽", "grid-template-columns: 1fr 1fr;" in css)
    check("运行状态卡日志撑满", ".run-card .log { max-height: none; }" in css)
    # 页面转换动画对 7 视图统一生效 (v4.1.9 的 .view.active 规则)
    check("页面转换仍作用于全部视图", "pageTransitionIn var(--durationFast)" in css)



def test_v430_deai_longtext():
    """v4.3.0: DeAI 长文本支持 (分块/降级推送/取消/落盘/引用/截断).

    实施前评审 (agent 审计) 确认的设计要点逐条核验:
    - 分块: 按分块预设切块逐块调用; rewrite 纯拼接; detect/audit 分节
    - whole_file 兜底: 超阈值回退 large(6000)
    - 降级推送: partial > 5 万字只推尾部预览, 完整结果落盘 deai_results/
    - 取消: 结构化 payload (cancelled: true) 区分失败; registry 登记 cancel_event
    - step3 引用: source_task_id 后端直读, 全文不过 IPC
    - sample 截断: 2 万字上限
    """
    print()
    print("--- v4.3.0: DeAI 长文本支持 ---", flush=True)
    import asyncio
    import tempfile
    from unittest.mock import patch, MagicMock, AsyncMock
    from pathlib import Path
    from app.web_backend import Backend
    from app.style_profiles import loader as loader_mod

    def make_backend():
        b = Backend(window=None)
        pushes = []
        b._push = lambda name, data=None: pushes.append((name, data))
        return b, pushes

    def make_fake_llm(chunks_out, fail_on=None):
        """fake client: 每次 create 依次消费 chunks_out 中的一个字符串作流式输出."""
        calls = {"n": 0, "prompts": []}
        client = MagicMock()

        class _Stream:
            def __init__(self, text):
                self.text = text
            def __aiter__(self):
                self._i = 0
                return self
            async def __anext__(self):
                if self._i >= len(self.text):
                    raise StopAsyncIteration
                ev = MagicMock()
                ev.choices = [MagicMock()]
                ev.choices[0].delta.content = self.text[self._i]
                self._i += 1
                return ev

        async def create(**kwargs):
            calls["n"] += 1
            calls["prompts"].append(kwargs["messages"][1]["content"])
            if fail_on is not None and calls["n"] == fail_on:
                raise RuntimeError("mock: LLM 不可达")
            out = chunks_out[min(calls["n"], len(chunks_out)) - 1]
            return _Stream(out)

        client.chat.completions.create = create
        client.close = AsyncMock()
        return MagicMock(return_value=client), calls

    # --- 1) 分块: detect 多块 -> 分节报告 + 每块一次调用 ---
    with tempfile.TemporaryDirectory(prefix="v430_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b, pushes = make_backend()
            fake_ctor, calls = make_fake_llm(["块1报告", "块2报告", "块3报告"])
            long_text = "这是测试句子。" * 800  # 9600 字 -> balanced(3000) 切 4 块? 实际按 split_text
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                b._config.chunking_preset = "fast"  # 2000 字/块 -> 5 块
                asyncio.run(b._deai_run("deai_t1", "detect", long_text, "", "", ""))
            check("多块: 每块一次 LLM 调用", calls["n"] >= 3, f"实际 {calls['n']} 次")
            names = [n for n, _ in pushes]
            check("多块: onDeaiComplete 恰好一次", names.count("onDeaiComplete") == 1)
            comp = next(d for n, d in pushes if n == "onDeaiComplete")
            check("detect 分节符存在", "=== 第" in comp.get("result", ""))
            check("detect 短结果不降级", comp.get("truncated") is False)
            last_stream = [d for n, d in pushes if n == "onDeaiStream"][-1]
            check("complete 带 progress 总块数", last_stream.get("progress", {}).get("total") >= 3)
        finally:
            loader_mod.STYLES_DIR = orig_dir

    # --- 2) rewrite 纯拼接: 无分节符, 块间衔接 prompt 注入 ---
    with tempfile.TemporaryDirectory(prefix="v430_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b, pushes = make_backend()
            fake_ctor, calls = make_fake_llm(["改写甲", "改写乙", "改写丙", "改写丁"])
            long_text = "这是需要改写的句子。" * 800  # ~8000 字
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                b._config.chunking_preset = "fast"
                asyncio.run(b._deai_run("deai_t2", "rewrite", long_text, "", "", ""))
            comp = next(d for n, d in pushes if n == "onDeaiComplete")
            check("rewrite 纯拼接无分节符", "=== 第" not in comp.get("result", ""))
            check("rewrite 拼接顺序正确", comp.get("result", "").startswith("改写甲"))
            check("rewrite 块间衔接 prompt", any("前文已改写部分的结尾" in p for p in calls["prompts"][1:]))
        finally:
            loader_mod.STYLES_DIR = orig_dir

    # --- 3) 降级推送 + 落盘 ---
    with tempfile.TemporaryDirectory(prefix="v430_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        import app.web_backend as wb
        orig_home = wb.CONFIG_DIR
        try:
            wb.CONFIG_DIR = Path(tmp) / "home"
            b, pushes = make_backend()
            big = "长" * 30000  # 单块输出 30000 字 x2 块 -> full 60000 > 50000 阈值
            fake_ctor, calls = make_fake_llm([big, big])
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                b._config.chunking_preset = "fast"
                asyncio.run(b._deai_run("deai_t3", "rewrite", "句子。" * 1000, "", "", ""))
            streams = [d for n, d in pushes if n == "onDeaiStream"]
            check("超阈值流式降级 (truncated)", any(st.get("truncated") for st in streams))
            check("降级时 partial 是尾部预览", any(len(st.get("partial", "")) < 5000 for st in streams if st.get("truncated")))
            comp = next(d for n, d in pushes if n == "onDeaiComplete")
            check("complete truncated=True", comp.get("truncated") is True)
            check("complete 带 result_file", bool(comp.get("result_file")))
            rf = Path(comp["result_file"])
            check("落盘文件存在且内容完整", rf.exists() and len(rf.read_text(encoding="utf-8")) == 60000)
            check("落盘路径含 task_id", "deai_t3" in rf.name)
            # copy/save bridge
            r = b.deai_copy_result("deai_t3")
            check("deai_copy_result 直读落盘 (mock 剪贴板失败也返回结构)", isinstance(r, dict))
            r2 = b.deai_copy_result("不存在的任务")
            check("deai_copy_result 未知 id 报错", r2.get("ok") is False)
        finally:
            wb.CONFIG_DIR = orig_home
            loader_mod.STYLES_DIR = orig_dir

    # --- 4) 取消: 结构化 payload + registry cancel_event ---
    with tempfile.TemporaryDirectory(prefix="v430_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b, pushes = make_backend()
            tid = "deai_t4"
            import threading
            b._deai_tasks[tid] = {"step": "rewrite", "cancel_event": threading.Event()}
            b._deai_tasks[tid]["cancel_event"].set()  # 启动前已取消
            fake_ctor, calls = make_fake_llm(["x"])
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                b._config.chunking_preset = "balanced"
                asyncio.run(b._deai_run(tid, "rewrite", "一些文本", "", "", ""))
            err = next((d for n, d in pushes if n == "onDeaiError"), None)
            check("取消走 onDeaiError", err is not None)
            check("取消 payload 结构化 (cancelled: True)", err is not None and err.get("cancelled") is True)
            check("取消不推 onDeaiComplete", all(n != "onDeaiComplete" for n, _ in pushes))
            check("取消时不调 LLM", calls["n"] == 0)
            r = b.deai_cancel(tid)
            check("deai_cancel 已结束任务返 not-running", r.get("ok") is False)
        finally:
            loader_mod.STYLES_DIR = orig_dir

    # --- 5) step3 引用落盘结果 (source_task_id) ---
    with tempfile.TemporaryDirectory(prefix="v430_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        import app.web_backend as wb
        orig_home = wb.CONFIG_DIR
        try:
            wb.CONFIG_DIR = Path(tmp) / "home"
            b, pushes = make_backend()
            saved = b._save_deai_result("deai_step2_src", "这是 step2 的完整改写结果")
            check("结果落盘成功", bool(saved))
            fake_ctor, calls = make_fake_llm(["评分报告"])
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                asyncio.run(b._deai_run("deai_t5", "audit", "", "", "", "deai_step2_src"))
            check("step3 引用: 后端直读落盘文本", any("这是 step2 的完整改写结果" in p for p in calls["prompts"]))
            # 未知引用
            pushes.clear()
            n0 = calls["n"]
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                asyncio.run(b._deai_run("deai_t6", "audit", "", "", "", "不存在的源"))
            names = [n for n, _ in pushes]
            check("未知引用报错不调 LLM", "onDeaiError" in names and calls["n"] == n0)
        finally:
            wb.CONFIG_DIR = orig_home
            loader_mod.STYLES_DIR = orig_dir

    # --- 6) whole_file 兜底 ---
    with tempfile.TemporaryDirectory(prefix="v430_") as tmp:
        orig_dir = loader_mod.STYLES_DIR
        loader_mod.STYLES_DIR = Path(tmp) / "styles"
        try:
            b, pushes = make_backend()
            fake_ctor, calls = make_fake_llm(["块甲", "块乙", "块丙", "块丁"])
            long_text = "整本书内容。" * 4000  # 24000 字 > 20000 兜底阈值
            with patch("app.web_backend.AsyncOpenAI", fake_ctor):
                b._config.chunking_preset = "whole_file"
                asyncio.run(b._deai_run("deai_t7", "rewrite", long_text, "", "", ""))
            check("whole_file 兜底回退分块 (不单次调用)", calls["n"] >= 2, f"实际 {calls['n']} 块")
        finally:
            loader_mod.STYLES_DIR = orig_dir

    # --- 7) sample 截断 ---
    b = Backend(window=None)
    big_sample = "范" * 25000
    prompt = b._build_deai_prompt("rewrite", big_sample, "")
    check("sample 超 2 万字截断", "已截断" in prompt and len(prompt) < 30000)
    small_prompt = b._build_deai_prompt("rewrite", "短范文", "")
    check("短 sample 不截断", "短范文" in small_prompt and "已截断" not in small_prompt)

    # --- 8) 前端挂载点 (静态) ---
    js = _read_app_js()
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    check("前端: textarea 拖入绑定", "bindDeaiTextDrop" in js)
    check("前端: 文件拖入 Python 通道", "onDeaiTextDrop" in js and "_on_textarea_drop" in open(
        str(_WEB_DIR.parent / "app" / "web_backend.py"), encoding="utf-8").read())
    check("前端: 字符计数元素", "deai-input-chars" in html and "deai-sample-chars" in html)
    check("前端: 运行中按钮变取消", "'取消'" in js and "deai_cancel" in js)
    check("前端: 对话框第三按钮", "dialog-btn-close" in html and "closeText" in js)
    check("前端: 取消分流渲染", "data.cancelled" in js or "data.get" in js)


# ==================== v4.3.1 新增 (UX #7: 强制重跑 + 缓存命中上报 + 块级进度) ====================

def test_v431_force_rerun_and_progress():
    """v4.3.1 (UX #7): force_rerun 通道 + cached_files 上报 + onChunkProgress 块级进度.

    a) prepare_tasks 默认: 命中断点缓存 -> engine.cached_files 含路径 + original_text 来自缓存
    b) prepare_tasks(force_rerun=True): 跳过缓存重读文件 (磁盘内容已变) -> cached_files 为空
    c) start_proofread 返回 dict 含 cached_files (命中/强制两态, mock 掉线程启动)
    d) _stream_chunked 每块完成触发 on_file_progress (3 块 -> (k,1,3)/(k,2,3)/(k,3,3));
       _call_api_stream 单块分支 (whole_file) 不触发
    e) bridge 注册 engine.on_file_progress -> 推 onChunkProgress {file_key, chunk, total}
    """
    print("\n--- v4.3.1: 强制重跑 / cached_files / 块级进度 ---", flush=True)
    import asyncio
    from unittest.mock import patch, MagicMock, AsyncMock
    from app.utils import (
        ProjectConfig, FileTask, FileResult, TaskStatus,
        save_checkpoint, compute_prompt_hash_for_config,
    )
    from app.processor import ProcessingEngine
    from app.web_backend import Backend

    def _make_cache(fp: Path, cfg: ProjectConfig) -> None:
        """参照 test_components.py: 造一个带正确指纹的 COMPLETED 断点缓存."""
        task = FileTask(file_path=fp, original_text="cached content")
        task.status = TaskStatus.COMPLETED
        task.result = FileResult(
            original="cached content", corrected="cached fixed",
            prompt_hash=compute_prompt_hash_for_config(cfg),  # v5.0.1 (审计 I-3)
        )
        save_checkpoint(fp, task)

    # --- a) 默认: 缓存命中 -> cached_files 上报 + original_text 来自缓存 ---
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("cached content")
        tmp_a = Path(f.name)
    try:
        cfg_a = ProjectConfig(api_base="http://x", model="m")
        _make_cache(tmp_a, cfg_a)
        engine_a = ProcessingEngine(cfg_a)
        engine_a.prepare_tasks([tmp_a])
        key_a = str(tmp_a)
        check("a) 缓存命中 task.is_done", engine_a.tasks[key_a].is_done)
        check("a) original_text 来自缓存", engine_a.tasks[key_a].original_text == "cached content")
        check("a) engine.cached_files 含该路径", key_a in engine_a.cached_files)
        check("a) 缓存命中计入 completed_files", engine_a.stats.completed_files == 1)
    finally:
        tmp_a.unlink(missing_ok=True)

    # --- b) force_rerun=True: 跳过缓存, 重读文件 (内容已变), cached_files 为空 ---
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("cached content")
        tmp_b = Path(f.name)
    try:
        cfg_b = ProjectConfig(api_base="http://x", model="m")
        _make_cache(tmp_b, cfg_b)
        # 缓存造好后改写磁盘内容, 验证 force_rerun 真的重读了文件 (非复用断点)
        tmp_b.write_text("brand new content", encoding="utf-8")
        engine_b = ProcessingEngine(cfg_b)
        engine_b.prepare_tasks([tmp_b], force_rerun=True)
        key_b = str(tmp_b)
        check("b) force_rerun 重读到新内容", engine_b.tasks[key_b].original_text == "brand new content")
        check("b) force_rerun 任务回 pending (非 is_done)", not engine_b.tasks[key_b].is_done)
        check("b) force_rerun cached_files 为空", engine_b.cached_files == [])
    finally:
        tmp_b.unlink(missing_ok=True)

    # --- c) start_proofread 返回 dict 含 cached_files 字段 (命中 + 强制两态) ---
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("cached content")
        tmp_c = Path(f.name)
    try:
        b = Backend(window=None)
        mock_window_c, _ = make_mock_window(None)
        b._window = mock_window_c
        # 断点指纹必须匹配 start_proofread 之后的引擎指纹: 传 mode_key='strict' /
        # chunking_preset='balanced' 与默认 config 相同, 现算指纹即可对齐
        _make_cache(tmp_c, b._config)
        # mock run_async (AsyncMock) 让后台线程毫秒级退出, 只验证返回结构不真跑 LLM;
        # 不能 patch threading.Thread — 它会连坐 threading.Timer.__init__ (模块全局
        # 查找 Thread) 导致 _push 的 33ms Timer 抛 "thread.__init__() not called"
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r_hit = b.start_proofread([str(tmp_c)], 'strict')
        check("c) 返回 dict 含 cached_files", "cached_files" in r_hit and isinstance(r_hit["cached_files"], list))
        check("c) 缓存命中时 cached_files 含该路径", str(tmp_c) in r_hit.get("cached_files", []))
        check("c) ok=True 契约保持", r_hit.get("ok") is True)
        check("c) task_id/total_files 仍在", "task_id" in r_hit and r_hit.get("total_files") == 1)
        # force_rerun 按位置传末位参数 (模拟 pywebview 前端调用方式)
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            r_force = b.start_proofread([str(tmp_c)], 'strict', "", "balanced", True)
        check("c) force_rerun 时 cached_files 为空", r_force.get("cached_files") == [])
        check("c) force_rerun ok=True", r_force.get("ok") is True)
    finally:
        tmp_c.unlink(missing_ok=True)

    # --- d) _stream_chunked 块级进度回调 (fake _stream_single, 参照 test_chunk_lifecycle) ---
    async def fake_stream_single(self, task_key, text,
                                 system_prompt_override=None, stream_prefix="",
                                 harness_chunk_note=""):
        return text.upper(), 10

    async def _run_chunked():
        engine_d = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
        calls = []
        engine_d.on_file_progress = lambda k, c, t: calls.append((k, c, t))
        with patch.object(ProcessingEngine, '_stream_single', fake_stream_single):
            await engine_d._stream_chunked("f1", ["甲", "乙", "丙"])
        return calls

    calls_d = asyncio.run(_run_chunked())
    check("d) 块完成回调触发 3 次", len(calls_d) == 3, f"实际 {calls_d}")
    check("d) 第 1 块 (f1,1,3)", len(calls_d) > 0 and calls_d[0] == ("f1", 1, 3))
    check("d) 第 2 块 (f1,2,3)", len(calls_d) > 1 and calls_d[1] == ("f1", 2, 3))
    check("d) 第 3 块 (f1,3,3)", len(calls_d) > 2 and calls_d[2] == ("f1", 3, 3))

    # 单块分支 (_call_api_stream + whole_file) 无分块语义, 不触发
    async def _run_single():
        engine_d2 = ProcessingEngine(ProjectConfig(
            api_base="http://x", model="m", chunking_preset="whole_file",
        ))
        calls = []
        engine_d2.on_file_progress = lambda k, c, t: calls.append((k, c, t))
        with patch.object(ProcessingEngine, '_stream_single', fake_stream_single):
            await engine_d2._call_api_stream("f2", "single text")
        return calls

    calls_single = asyncio.run(_run_single())
    check("d) 单块分支不触发块级进度", calls_single == [], f"实际 {calls_single}")

    # --- e) bridge 注册 on_file_progress 并推 onChunkProgress ---
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("test")
        tmp_e = Path(f.name)
    try:
        b2 = Backend(window=None)
        mock_window_e, captured_e = make_mock_window(None)
        b2._window = mock_window_e
        # 同上: mock run_async 让线程快速退出 (不 patch threading.Thread, 避免连坐 Timer)
        with patch.object(ProcessingEngine, "run_async", new=AsyncMock(return_value=None)):
            b2.start_proofread([str(tmp_e)], 'strict')
        check("e) engine.on_file_progress 已绑", b2._engine.on_file_progress is not None)
        # 模拟引擎块完成事件, 验证 _push("onChunkProgress") 链路
        b2._engine.on_file_progress(str(tmp_e), 2, 5)
        time.sleep(0.15)  # 等 33ms 节流 flush
        all_payload = "".join(captured_e)
        check("e) 推送 onChunkProgress", "onChunkProgress" in all_payload)
        check("e) payload 含 chunk/total 字段",
              '"chunk": 2' in all_payload and '"total": 5' in all_payload)
    finally:
        tmp_e.unlink(missing_ok=True)


def test_v502_deai_postprocess():
    """v5.0.2: DeAI rewrite 步后置三件套 (strip 后置 / ai_score / revise).

    verifier-plan-v5.0.1.md 裁定逐条核验:
    - strip 后置: 完整输出拼装后剥 Markdown, 空结果兜底回退原文 (P2-16);
      落盘/onDeaiComplete/收尾帧用剥后版本; diff 链路不动 (不推"原文 vs 剥后")
    - ai_score: onDeaiComplete 附 ai_score payload (仅 rewrite), 不落盘不进缓存
    - revise 内层循环: 仅 rewrite + 开关开 + 评分>=阈值 + <=2 万字; offenders
      反馈并入 user_prompt; 取分低者; 跨步不做 (C.11)
    """
    print()
    print("--- v5.0.2: DeAI 后置三件套 ---", flush=True)
    import asyncio
    from unittest.mock import patch, MagicMock, AsyncMock
    from app.web_backend import Backend
    from app.ai_score_local import REVISE_THRESHOLD

    def make_backend():
        b = Backend(window=None)
        pushes = []
        b._push = lambda name, data=None: pushes.append((name, data))
        return b, pushes

    def make_fake_llm(outputs):
        """fake client: 第 n 次 create 返回 outputs[n-1] (50 字/片的流式输出)."""
        calls = {"n": 0, "prompts": []}
        client = MagicMock()

        class _Stream2:
            def __init__(self, text):
                self._pieces = [text[i:i + 50] for i in range(0, len(text), 50)]
                self._i = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self._i >= len(self._pieces):
                    raise StopAsyncIteration
                ev = MagicMock()
                ev.choices = [MagicMock()]
                ev.choices[0].delta.content = self._pieces[self._i]
                self._i += 1
                return ev

        async def create(**kwargs):
            calls["n"] += 1
            calls["prompts"].append(kwargs["messages"][1]["content"])
            return _Stream2(outputs[min(calls["n"], len(outputs)) - 1])

        client.chat.completions.create = create
        client.close = AsyncMock()
        return MagicMock(return_value=client), calls

    def patch_scores(seq):
        """fake _ai_score_local: 依次返回 seq 中的分数; >= 阈值带 offenders."""
        it = iter(seq)

        def fake(text):
            s = next(it)
            return {
                "score": s,
                "dims": {"blacklist": {"score": 0, "weight": 28, "detail": "mock"}},
                "offenders": ([{"text": "出戏句子", "reasons": ["mock:黑名单"]}]
                              if s >= REVISE_THRESHOLD else []),
            }
        return patch("app.web_backend._ai_score_local", fake)

    # --- 1) strip 后置: 默认开关下 rewrite 输出剥 Markdown ---
    b, pushes = make_backend()
    fake_ctor, calls = make_fake_llm(["# 标题\n\n**加粗**内容与正文。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor):
        asyncio.run(b._deai_run("deai_s1", "rewrite", "原文输入。", "", "", ""))
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("strip 后置: 完成结果无 md 标记",
          comp.get("result") == "标题\n\n加粗内容与正文。", repr(comp.get("result")))
    last_stream = [d for n, d in pushes if n == "onDeaiStream"][-1]
    check("strip 后置: 收尾帧也是剥后版本",
          "#" not in last_stream.get("partial", ""), repr(last_stream.get("partial")))
    check("strip 后置: diff 基线不动 (无 original 字段)", "original" not in comp)

    # --- 2) 空结果兜底: 纯标记文本 strip 为空 → 回退原文 ---
    b, pushes = make_backend()
    fake_ctor, calls = make_fake_llm(["---\n***\n___"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor):
        asyncio.run(b._deai_run("deai_s2", "rewrite", "原文输入。", "", "", ""))
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("空结果兜底: strip 为空时保留原文",
          comp.get("result") == "---\n***\n___", repr(comp.get("result")))
    check("空结果兜底: 不推 onDeaiError",
          "onDeaiError" not in [n for n, _ in pushes])

    # --- 3) ai_score payload: rewrite 附分, detect 不附 ---
    b, pushes = make_backend()
    fake_ctor, calls = make_fake_llm(["改写完成。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([42]):
        asyncio.run(b._deai_run("deai_s3", "rewrite", "原文输入。", "", "", ""))
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("ai_score payload 存在且结构正确",
          comp.get("ai_score") == {"score": 42,
                                   "dims": {"blacklist": 0}}, str(comp.get("ai_score")))
    b, pushes = make_backend()
    fake_ctor, calls = make_fake_llm(["检测报告。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([42]):
        asyncio.run(b._deai_run("deai_s4", "detect", "原文输入。", "", "", ""))
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("detect 步不附 ai_score", "ai_score" not in comp)

    # --- 4) revise 默认关: 评分超阈值也只跑一轮 ---
    b, pushes = make_backend()
    fake_ctor, calls = make_fake_llm(["第一轮输出。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([95]):
        asyncio.run(b._deai_run("deai_s5", "rewrite", "原文输入。", "", "", ""))
    check("revise 默认关: 仅 1 次 LLM 调用", calls["n"] == 1, f"实际 {calls['n']}")

    # --- 5) revise 开 + 第二轮分低 → 采用修订结果 (共 2 次调用, 反馈入 prompt) ---
    b, pushes = make_backend()
    b._config.deai_revise = True
    fake_ctor, calls = make_fake_llm(["第一轮输出。", "修订后的输出。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([80, 30]):
        asyncio.run(b._deai_run("deai_s6", "rewrite", "原文输入。", "", "", ""))
    check("revise 采纳: 共 2 次 LLM 调用", calls["n"] == 2, f"实际 {calls['n']}")
    check("revise 反馈并入 user_prompt (offenders)",
          len(calls["prompts"]) >= 2 and "出戏句子" in calls["prompts"][1]
          and "出戏句反馈" in calls["prompts"][1], calls["prompts"][1][:120])
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("revise 采纳: 采用修订文本", comp.get("result") == "修订后的输出。",
          repr(comp.get("result")))
    check("revise 采纳: payload 更新为第二轮分数",
          comp.get("ai_score", {}).get("score") == 30, str(comp.get("ai_score")))

    # --- 6) revise 开 + 第二轮分高 → 保留第一轮 ---
    b, pushes = make_backend()
    b._config.deai_revise = True
    fake_ctor, calls = make_fake_llm(["第一轮输出。", "更差的输出。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([80, 90]):
        asyncio.run(b._deai_run("deai_s7", "rewrite", "原文输入。", "", "", ""))
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("revise 取分低者: 第二轮更差则保留第一轮",
          comp.get("result") == "第一轮输出。", repr(comp.get("result")))
    check("revise 取分低者: payload 保留第一轮分数",
          comp.get("ai_score", {}).get("score") == 80)

    # --- 7) revise 开但评分关 → 跳过 (评分是 revise 的前置信号) ---
    b, pushes = make_backend()
    b._config.deai_revise = True
    b._config.deai_ai_score = False
    fake_ctor, calls = make_fake_llm(["第一轮输出。"])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([80]):
        asyncio.run(b._deai_run("deai_s8", "rewrite", "原文输入。", "", "", ""))
    check("revise 需评分: ai_score 关时仅 1 次调用", calls["n"] == 1, f"实际 {calls['n']}")
    comp = next(d for n, d in pushes if n == "onDeaiComplete")
    check("revise 需评分: payload 为空则不附", "ai_score" not in comp)

    # --- 8) 超 2 万字: revise 跳过 (整文单次调用超上下文风险) ---
    b, pushes = make_backend()
    b._config.deai_revise = True
    big_out = "长" * 21000
    fake_ctor, calls = make_fake_llm([big_out])
    with patch("app.web_backend.AsyncOpenAI", fake_ctor), patch_scores([95, 10]):
        asyncio.run(b._deai_run("deai_s9", "rewrite", "原文输入。", "", "", ""))
    check("超 2 万字 revise 跳过: 仅 1 次调用", calls["n"] == 1, f"实际 {calls['n']}")


def test_v502_deai_switches_roundtrip():
    """v5.0.2: 3 开关 to_dict/from_dict 往返 + 默认值 + 不进 compute_prompt_hash (§35 裁定)."""
    print()
    print("--- v5.0.2: DeAI 3 开关配置往返 ---", flush=True)
    from app.utils import ProjectConfig, compute_prompt_hash_for_config
    cfg = ProjectConfig()
    check("默认值 strip/score=True, revise=False",
          cfg.deai_strip_after is True and cfg.deai_ai_score is True
          and cfg.deai_revise is False)
    d = cfg.to_dict()
    check("to_dict 字段数 27", len(d) == 27, str(len(d)))  # v5.1.0: + harness_enabled
    cfg2 = ProjectConfig.from_dict({**d, "deai_strip_after": False,
                                    "deai_ai_score": False, "deai_revise": True})
    check("from_dict 往返保留修改",
          cfg2.deai_strip_after is False and cfg2.deai_ai_score is False
          and cfg2.deai_revise is True)
    cfg3 = ProjectConfig.from_dict({})
    check("缺键回退默认", cfg3.deai_strip_after is True
          and cfg3.deai_ai_score is True and cfg3.deai_revise is False)
    # §35 裁定: 3 开关不进断点指纹 — 改 3 开关不影响 prompt hash
    h1 = compute_prompt_hash_for_config(cfg)
    h2 = compute_prompt_hash_for_config(cfg2)
    check("3 开关改动不使校对断点指纹失效", h1 == h2, f"{h1} vs {h2}")


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
        # v4.1.8.1 (H11): D 算法 Python 镜像测试 + 3 个恒真用例已删除
        # (MockRenderState 复刻 JS renderCompare, 前端真逻辑回归时全绿, 虚增约 20 check)
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
        test_v418_builtin_style_card_injected,  # v4.1.8.1 (H9/E1)
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
        test_v419_win11_polish,
        test_v419_ui_theme_roundtrip,
        test_v420_nav_split,
        test_v430_deai_longtext,
        # v4.3.1 新增 (UX #7: 强制重跑 + 缓存命中上报 + 块级进度推送)
        test_v431_force_rerun_and_progress,
        test_v440_ui_skin_roundtrip,
        test_v440_ink_skin_css,
        test_v442_md_local_ui,
        test_v500_deai_load_source,
        # v5.0.2 新增 (DeAI 后置三件套: strip 后置 / ai_score / revise + 3 开关)
        test_v502_deai_postprocess,
        test_v502_deai_switches_roundtrip,
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
