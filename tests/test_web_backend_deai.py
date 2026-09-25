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


# === test_deai_step1_stub ===
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

# === test_deai_step2_with_sample ===
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

# === test_deai_step2_no_sample ===
def test_deai_step2_no_sample():
    print("\n--- deai step2 无 sample ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    result = backend.deai_step2_rewrite("原文", "")
    check("返回 string", isinstance(result, str))
    check("返回 task_id", "deai_rewrite_" in result)

# === test_deai_step3_stub ===
def test_deai_step3_stub():
    print("\n--- deai step3 task_id ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    mock_window, _ = make_mock_window(None)
    backend._window = mock_window
    result = backend.deai_step3_audit("改写后文本")
    check("返回 string", isinstance(result, str))
    check("返回 task_id (含 deai_audit_)", "deai_audit_" in result)

# === test_deai_build_prompts ===
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

# === test_f3_deai_error_no_complete ===
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

# === test_f3_deai_top_level_no_complete ===
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

# === test_v417_delete_builtin_rejected ===
def test_v417_delete_builtin_rejected():
    """v4.1.7: delete_style_profile 拒删 builtin."""
    print("\n--- v4.1.7: delete 拒删 builtin ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.delete_style_profile("plain_tech")
    check("拒删 builtin 返回 ok=False", r.get("ok") is False)
    check("error 含 'builtin'", "builtin" in (r.get("error") or ""))

# === test_v417_add_sample_increments_count ===
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

# === test_v417_save_and_get_style_card ===
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

# === test_v417_distill_too_few_samples ===
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

# === test_v417_deai_step2_with_style_card_prompt ===
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

# === test_v417_deai_step2_without_style_card_backward_compat ===
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

# === test_v418_builtin_style_card_injected ===
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

# === test_v417_deai_step3_audit_8_axis_prompt ===
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

# === test_v417_style_card_path_traversal ===
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

# === test_v417_distill_concurrent_no_interference ===
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

# === test_v500_deai_load_source ===
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

# === test_v420_nav_split ===
def test_v420_nav_split():
    """v4.2.0 分组导航 + v5.2 校对/对比单页合并.

    核验: 7 个视图 id 齐全 / 校对与对比不再各占一页 / 分组导航 /
    关键元素 id 单一存在 (JS 绑定不变) / cfg 字段分布两页后防抖选择器覆盖 /
    CSS 新组件。
    """
    print()
    print("--- v4.2.0 分组导航 + v5.2 校对/对比合并 ---", flush=True)
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = _read_app_js()
    css = _read_style_css()

    # 7 视图齐全
    for vid in ("view-home", "view-deai", "view-styles", "view-splitter",
                "view-api", "view-params", "view-appearance"):
        check(f"视图 {vid} 存在", f'id="{vid}"' in html)
    check("结果对比不再是独立视图", 'id="view-results"' not in html)
    check("结果对比元素在主页内",
          html.find('id="view-home"') < html.find('id="compare-original"')
          < html.find('id="view-deai"'))
    # 分组导航
    for dv in ("home", "deai", "styles", "splitter", "api", "params", "appearance"):
        check(f"导航项 data-view={dv}", f'data-view="{dv}"' in html)
    check("已移除结果对比导航项", 'data-view="results"' not in html)
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
    check("对比区下拉渲染函数", "renderResultFileSelect" in js)
    check("点击文件不再跳转旧结果页", "this.setView('results')" not in js)
    check("防抖选择器覆盖 view-api/params/appearance",
          "#view-api input" in js and "#view-params input" in js)
    check("Ctrl+, 指向 API 接口页", "this.setView('api')" in js)
    check("风格库下拉镜像绑定", "styles-profile-select" in js)
    # CSS 新组件
    for cls in (".nav-group {", ".sidebar-footer {", ".content-narrow {",
                ".result-select {", ".about-row {"):
        check(f"CSS 组件 {cls.strip()} ", cls in css)
    check("home-grid 左侧任务流 + 右侧对比",
          "minmax(300px, 0.85fr) minmax(0, 1.45fr)" in css)
    check("工作区左栏纵向排列", ".workspace-column {" in css)
    check("运行状态卡日志撑满", ".run-card .log {" in css and "flex: 1;" in css)
    check("窄窗口降级为纵向布局", "@media (max-width: 1100px)" in css)
    # v5.2 UI 收口: 窄屏单列下网格须按内容撑开, 否则卡片 min-height 会撑破
    # 行轨道互相覆盖 (由 Playwright 冒烟实测发现)
    narrow = css.split("@media (max-width: 1100px)", 1)[1].split("\n}\n", 1)[0]
    check("窄屏网格按内容撑开", "flex: 0 0 auto;" in narrow)
    check("窄屏对比卡 min-height 覆盖 .card 归零",
          ".content-grid.home-grid .compare-card" in narrow
          and "min-height: 480px;" in narrow)
    # 页面转换动画对 7 视图统一生效 (v4.1.9 的 .view.active 规则)
    check("页面转换仍作用于全部视图", "pageTransitionIn var(--durationFast)" in css)

# === test_v430_deai_longtext ===
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

# === test_v431_force_rerun_and_progress ===
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

# === test_v502_deai_postprocess ===
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

# === test_v502_deai_switches_roundtrip ===
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
    check("to_dict 字段数 31", len(d) == 31, str(len(d)))  # v5.1.0: + harness_enabled; v5.2c (D 方案): + chunking_preset_harness/rewrite + harness/rewrite_request_timeout (4 字段)
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
