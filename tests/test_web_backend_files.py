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


# === test_choose_files_uses_pywebview ===
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

# === test_choose_files_user_cancelled ===
def test_choose_files_user_cancelled():
    print("\n--- choose_files 用户取消 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)  # 用户取消
    backend._window = mock_window
    result = backend.choose_files()
    check("取消时返回 []", result == [])

# === test_choose_files_no_window ===
def test_choose_files_no_window():
    print("\n--- choose_files window=None 兜底 ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    # backend._window 还是 None
    result = backend.choose_files()
    check("window=None 时返回 []", result == [])

# === test_read_file ===
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

# === test_read_file_chinese ===
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

# === test_v530_get_file_char_counts ===
def test_v530_get_file_char_counts():
    """v5.3.0: 批量字符数只读接口 (整文件档超长告警用, 不回正文)。"""
    print("\n--- v5.3.0: get_file_char_counts ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    with tempfile.TemporaryDirectory(prefix="v530_counts_") as tmp:
        a = Path(tmp) / "a.txt"
        b = Path(tmp) / "b.txt"
        a.write_text("中文校对", encoding="utf-8")
        b.write_text("x" * 25001, encoding="utf-8")
        missing = Path(tmp) / "nope.txt"
        r = backend.get_file_char_counts([str(a), str(b), str(missing), "", None])
        check("返回 ok", r.get("ok") is True)
        counts = r.get("counts") or {}
        check("中文字符数正确", counts.get(str(a)) == 4, str(counts.get(str(a))))
        check("长文本字符数正确", counts.get(str(b)) == 25001, str(counts.get(str(b))))
        check("不存在的文件被跳过", str(missing) not in counts)
        check("非字符串入参不崩", "" not in counts)
        check("只回长度不回正文", all(isinstance(v, int) for v in counts.values()))
        empty = backend.get_file_char_counts([])
        check("空列表返回空 counts", empty == {"ok": True, "counts": {}})


# === test_drag_drop_files ===
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

# === test_remove_file ===
def test_remove_file():
    print("\n--- remove_file ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.remove_file("C:\\any\\path.txt")
    check("返回 ok=True", r.get("ok") is True)
    check("含 removed 字段", "removed" in r)

# === test_clear_files ===
def test_clear_files():
    print("\n--- clear_files ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.clear_files()
    check("返回 ok=True", r.get("ok") is True)

# === test_f1_choose_files_file_types_format ===
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

# === test_f1_choose_files_no_fallback_to_opendialog ===
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

# === test_f2_init_drag_drop_registers_loaded_event ===
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

# === test_f2_on_drag_drop_extracts_pywebviewfullpath ===
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

# === test_f2_on_drag_drop_empty_files ===
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

# === test_v414_export_filename_format ===
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

# === test_v415_on_file_start_with_original ===
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

# === test_v415_on_file_start_large_file_truncated ===
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

# === test_v417_list_style_profiles ===
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

# === test_v417_create_and_delete_profile ===
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

# === test_v417_distill_style_profile_mock ===
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
