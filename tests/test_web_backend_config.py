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


# === test_get_config ===
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

# === test_set_config ===
def test_set_config():
    print("\n--- set_config ---", flush=True)
    from app.web_backend import Backend
    backend = Backend(window=None)
    backend.set_config("temperature", 0.5)
    check("set_config 修改内存值 temperature", abs(backend._config.temperature - 0.5) < 0.001)
    backend.set_config("prompt_mode", "polish")
    check("set_config 修改 prompt_mode", backend._config.prompt_mode == "polish")

# === test_set_config_ignores_unknown ===
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

# === test_save_config_persists ===
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

# === test_get_prompt_modes ===
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

# === test_get_api_templates ===
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

# === test_get_chunking_presets ===
def test_get_chunking_presets():
    print("\n--- get_chunking_presets ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    presets = b.get_chunking_presets()
    check("返回 list", isinstance(presets, list))
    # v5.3.0: 5→6 档 (extra_large, 逐条校对专属)
    check("恰好 6 档", len(presets) == 6)
    expected = {"fast", "balanced", "high_context", "large", "extra_large", "whole_file"}
    got = {p["key"] for p in presets}
    check("包含 fast/balanced/high_context/large/extra_large/whole_file", expected.issubset(got))
    for p in presets:
        check(f"{p['key']} 有 label", "label" in p)
        check(f"{p['key']} 有 max_chars", "max_chars" in p)


# === test_v530_workflow_mode ===
def test_v530_workflow_mode_and_track_presets():
    """v5.3.0: workflow 一等字段 + 按轨档位过滤 + 单向兼容 (PLAN §2 D4/D7/D10)"""
    print("\n--- v5.3.0: workflow_mode / 按轨预设 / set_config 兼容 ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)

    # --- 按轨过滤 ---
    all_keys = {p["key"] for p in b.get_chunking_presets()}
    harness_keys = {p["key"] for p in b.get_chunking_presets("harness")}
    rewrite_keys = {p["key"] for p in b.get_chunking_presets("rewrite")}
    check("空参 = 全量 6 档", len(all_keys) == 6)
    check("harness 轨含 extra_large", "extra_large" in harness_keys)
    check("rewrite 轨不含 extra_large (逐条校对专属)", "extra_large" not in rewrite_keys)
    check("rewrite 轨仍含 whole_file", "whole_file" in rewrite_keys)

    # --- set_config: workflow_mode 是唯一真值, harness_enabled 单向跟随 ---
    r = b.set_config("workflow_mode", "rewrite")
    check("写 workflow_mode=rewrite 返回 ok", r.get("ok") is True)
    check("harness_enabled 单向镜像为 False", b._config.harness_enabled is False)
    r2 = b.set_config("harness_enabled", True)
    check("老客户端写 harness_enabled=True → workflow 跟随", r2.get("ok") is True
          and b._config.workflow_mode == "harness")
    r3 = b.set_config("workflow_mode", "bogus")
    check("非法 workflow_mode 被拒", r3.get("ok") is False)
    check("非法值不落地 (仍是 harness)", b._config.workflow_mode == "harness")

    # --- 前端新 payload 不含 harness_enabled → 改别的字段不会翻轨 ---
    b.set_config("workflow_mode", "rewrite")
    for k, v in (("temperature", 0.3), ("concurrency", 4), ("chunking_preset", "fast")):
        b.set_config(k, v)
    check("改其它字段不翻转轨道", b._config.workflow_mode == "rewrite")

    # --- 双轨 timeout 后端钳制 (此前只有前端 JS 挡) ---
    b.set_config("harness_request_timeout", 5)
    check("harness_request_timeout 下限钳到 60", b._config.harness_request_timeout == 60)
    b.set_config("harness_request_timeout", 9999)
    check("harness_request_timeout 上限钳到 600", b._config.harness_request_timeout == 600)
    b.set_config("rewrite_request_timeout", 1)
    check("rewrite_request_timeout 下限钳到 60", b._config.rewrite_request_timeout == 60)

# === test_set_config_type_coercion ===
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

# === test_save_config_returns_dict ===
def test_save_config_returns_dict():
    print("\n--- save_config 返回 dict ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.save_config()
    check("返回 dict", isinstance(r, dict))
    check("含 ok 字段", "ok" in r)

# === test_v416_save_config_persists_all_fields ===
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

# === test_v416_save_config_error_handling ===
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

# === test_v416_save_config_ok_returns_dict ===
def test_v416_save_config_ok_returns_dict():
    """v4.1.6 (P3): happy path, save_config 返 {ok: True, error: None}."""
    print("\n--- v4.1.6 save_config 成功路径 ---", flush=True)
    from app.web_backend import Backend
    b = Backend(window=None)
    r = b.save_config()
    check("save_config 返 dict", isinstance(r, dict))
    check("happy path 返 ok=True", r.get("ok") is True, str(r))

# === test_v416_set_config_accepts_all_cfg_fields ===
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

# === test_v416_save_config_idempotent ===
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
