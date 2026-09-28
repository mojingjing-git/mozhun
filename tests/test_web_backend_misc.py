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


# === test_v418_color_palette_tokens ===
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

# === test_v418_type_ramp_tokens ===
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

# === test_v418_corner_radius_tokens ===
def test_v418_corner_radius_tokens():
    """v4.1.8: 圆角 token (Win11 §3.5 4px/8px/0px + 内部 2px)."""
    print("\n--- v4.1.8: 圆角 token 命名 ---", flush=True)
    css = _read_style_css()
    check("--controlCornerRadius=4px", "--controlCornerRadius: 4px" in css)
    check("--overlayCornerRadius=8px", "--overlayCornerRadius: 8px" in css)
    check("--radiusSmall=2px (内部小元素)", "--radiusSmall: 2px" in css)

# === test_v418_motion_tokens ===
def test_v418_motion_tokens():
    """v4.1.8: 3 类动画曲线 + 3 时长 (Win11 §3.7.2).

    v5.4.4 清理: --curveFastOut / --curveLinear / --durationSlow 零引用已删,
    连带删除本函数对应的 3 条字面量断言。
    注: 下面 curveFastIn 断言的是字面值 `cubic-bezier(0, 0, 0, 1)`, 而被删的
    --curveFastOut 值与之完全相同 —— 它属**巧合存活**, 不是"曲线还在用"。
    将来谁删 --curveFastIn, 这条断言会跟着红。
    """
    print("\n--- v4.1.8: 动画曲线 3 类 + 3 时长 ---", flush=True)
    css = _read_style_css()
    # 3 cubic-bezier
    check("curveFastIn", "cubic-bezier(0, 0, 0, 1)" in css)
    check("curvePointToPoint", "cubic-bezier(0.55, 0.55, 0, 1)" in css)
    check("curveSoftOut", "cubic-bezier(1, 0, 1, 1)" in css)
    # 3 时长
    check("durationSubtle=83ms", "--durationSubtle: 83ms" in css)
    check("durationFast=167ms", "--durationFast: 167ms" in css)
    check("durationNormal=250ms", "--durationNormal: 250ms" in css)

# === test_v418_dark_mode_tokens ===
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

# === test_v418_icon_stroke_style ===
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

# === test_v418_accessibility_contrast ===
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

# === test_v418_diff_color_blind_shape ===
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

# === test_v418_no_11px_font_size ===
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

# === test_v418_no_italic ===
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

# === test_v418_no_bold_700 ===
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

# === test_v418_acrylic_and_smoke_classes ===
def test_v418_acrylic_and_smoke_classes():
    """v4.1.8: Acrylic (毛玻璃) + Smoke (模态遮罩) 材料类存在."""
    print("\n--- v4.1.8: Acrylic + Smoke 类存在 (Win11 §3.4) ---", flush=True)
    css = _read_style_css()
    check(".acrylic 类定义 (flyout/menu 毛玻璃)",
          ".acrylic {" in css and "backdrop-filter:" in css)
    check(".smoke-overlay 类定义 (模态遮罩)",
          ".smoke-overlay {" in css and "rgba(0, 0, 0, 0.32)" in css)

# === test_v419_win11_polish ===
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

# === test_v419_ui_theme_roundtrip ===
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

# === test_v440_ui_skin_roundtrip ===
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

# === test_v440_ink_skin_css ===
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

# === test_v442_md_local_ui ===
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

# ==================== v5.4.3 批次 1: F5 / F13 / D3 前端回归 ====================
# 三项均为纯前端渲染/状态缺陷, 静态源码断言在此锁定其**存在性**;
# 行为级覆盖另见 tools/smoke_ui.py 的 _check_provenance / _check_local_mode_display。


def test_v543_f5_local_mode_stale_streaming_cleared():
    """F5: 本地模式 (punct_local/md_local) 不发 onStream, 残留 streamingContent
    会让右栏显示上一轮文本, 而复制/导出取的是本轮 t.corrected。

    两处缺一不可:
      ① _runProofread 的 renderState 重建循环里 delete streamingContent (运行期清理)
      ② renderCompare 取值时按 t.status 判断 (终态兜底)
    """
    js = _read_app_js()
    check("F5: 启动时清 streamingContent",
          "delete this.streamingContent[p];" in js)
    check("F5: renderCompare 按 status 决定流式/结果优先级",
          "t.status === 'running' ? this.streamingContent[fileKey]" in js)
    # 负向断言必须看**代码语句**而不是全文子串 ——
    # 修复时写的说明注释里就含 `this.streamingContent[fileKey] || t.corrected`
    # 这段字面量, 用全文匹配会误判成"旧写法仍在"。
    _lines = [ln.strip() for ln in js.splitlines()]
    check("F5: 无遗留的 streamingContent 无条件优先赋值",
          not any(ln.startswith("const partial = this.streamingContent")
                  for ln in _lines))


def test_v543_f13_provenance_key_includes_filekey():
    """F13: _provenanceKey 只由 workflow+当前轨决定 -> 同轨两文件 key 相同 ->
    切到 B 时早退, 提示条文案与按钮闭包仍指向上一个文件 ->
    用户在 B 上点「用整篇重跑」实际重跑并覆盖 A (且 confirmOverride:false 跳确认)。
    """
    js = _read_app_js()
    check("F13: provenance key 含 fileKey",
          "${fileKey}|${t.workflow}|${cur}" in js)
    check("F13: 旧的只含 workflow+cur 的 key 已移除",
          "`${t.workflow}|${cur}`" not in js)


def test_v543_d3_provenance_after_selected_guard():
    """D3: _renderProvenance 必须在 fileKey !== selectedFileKey 守卫**之后**调用。

    旧版在 renderCompare 第一行无条件调用, 而 scheduleRender 用 RAF 排队,
    切文件后仍为上一个文件排队的回调会把提示条按旧 fileKey 重新打开 ——
    右栏是 B 的正文, 提示条却是 A 的来源 + 指向 A 的重跑按钮。
    """
    js = _read_app_js()
    i_body = js.find("renderCompare(fileKey) {")
    i_guard = js.find("if (fileKey !== this.selectedFileKey) return;")
    i_prov = js.find("this._renderProvenance(fileKey);", i_guard)
    check("D3: renderCompare 存在", i_body >= 0)
    check("D3: 选中守卫存在", i_guard >= 0)
    check("D3: _renderProvenance 出现在守卫之后",
          i_prov > i_guard > i_body >= 0,
          f"body={i_body} guard={i_guard} prov={i_prov}")



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
