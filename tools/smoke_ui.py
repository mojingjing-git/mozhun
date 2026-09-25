"""v5.3.0 前端冒烟: Playwright 三视口布局核验 + 侧边栏双入口截图。

用法:
    python tools/smoke_ui.py                  # 三视口, 截图落 .local/smoke-ui-v5.3/
    python tools/smoke_ui.py --headed         # 看着跑 (调试布局用)
    python tools/smoke_ui.py --out D:\\shots   # 自定义截图目录

为什么需要它: 本项目零构建 (python main.py 直开 web/), 侧边栏双入口这类布局
问题在单元测试里看不出来 (test_web_backend_deai.py 只能做静态断言)。

本脚本用 http.server 静态托管 web/, 用桩注入 window.pywebview.api
(不联网、不读用户配置、不写任何文件), 在三条视口上断言:
  1. 无横向溢出; 侧边栏 200px 不被挤压、不越界
  2. 每个导航项单行 (高度 <= 40px), 相邻项不重叠
  3. 工作区左右两栏 (文件/状态 vs 结果对比) 不重叠
  4. 双入口切换: 标题 + data-nav-key 高亮 + 活动视图正确
  5. 「重写」父项: 箭头展开子项; 子项激活时父项行有层级提示

每条视口输出 3 张截图 (逐条校对 / 整篇校对 / 去 AI 味) 供人工复核。

依赖: playwright (Python) + chromium。缺失时打印安装命令并以退出码 2 结束。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
sys.path.insert(0, str(ROOT))

VIEWPORTS = ((1440, 900), (1280, 720), (1000, 760))
NAV_KEYS = ("harness", "rewrite", "deai", "styles", "splitter",
            "api", "params", "appearance")
NAV_ITEM_MAX_HEIGHT = 40      # 单行导航项实测 ~36px; 换行会到 ~56px

_failures: list[str] = []
_checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    if ok:
        print(f"  [PASS] {name}", flush=True)
    else:
        _failures.append(name)
        print(f"  [FAIL] {name}{(' -> ' + detail) if detail else ''}", flush=True)


class _QuietHandler(SimpleHTTPRequestHandler):
    """静态托管 web/, 但不把每个请求打到 stdout。"""

    def log_message(self, *args):  # noqa: D102
        pass


def _serve(directory: Path):
    handler = partial(_QuietHandler, directory=str(directory))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.html"


def _stub_payload() -> dict:
    """桩数据直接取后端定义, 避免与 app/utils.py 的档位/模式漂移。"""
    from app.templates import PROMPT_MODES
    from app.utils import CHUNKING_PRESETS, ProjectConfig

    return {
        "config": ProjectConfig().to_dict(),
        "prompt_modes": [
            {"key": k, "label": v["label"]}
            for k, v in PROMPT_MODES.items() if k != "deai"
        ],
        "chunking_presets": [dict(p) for p in CHUNKING_PRESETS],
    }


def _init_script(payload: dict) -> str:
    return """
(() => {
  const DATA = %s;
  const base = {
    get_config: async () => DATA.config,
    get_prompt_modes: async () => DATA.prompt_modes,
    get_api_templates: async () => [],
    get_chunking_presets: async (track) => {
      const all = DATA.chunking_presets;
      if (!track) return all;
      return all.filter(p => !p.tracks || p.tracks.includes(track));
    },
    list_style_profiles: async () => ({ builtin: [], custom: [] }),
    set_config: async () => ({ ok: true }),
    save_config: async () => ({ ok: true }),
    get_file_char_counts: async (paths) => ({
      ok: true,
      counts: Object.fromEntries((paths || []).map(p => [p, 100])),
    }),
  };
  window.pywebview = {
    api: new Proxy(base, {
      get(t, k) { return (k in t) ? t[k] : (async () => ({ ok: true })); },
    }),
  };
})();
""" % json.dumps(payload, ensure_ascii=False)


_SIDEBAR_JS = """
() => {
  const sb = document.querySelector('.sidebar').getBoundingClientRect();
  const items = [...document.querySelectorAll('.sidebar .nav-item')].map(el => {
    const r = el.getBoundingClientRect();
    return {key: el.dataset.navKey || '', top: r.top, bottom: r.bottom,
            left: r.left, right: r.right, height: r.height,
            parentItem: el.dataset.navParentItem || '',
            text: el.textContent.trim()};
  });
  return {
    sidebar: {left: sb.left, right: sb.right, width: sb.width},
    items,
    overflowX: document.documentElement.scrollWidth - window.innerWidth,
    bodyTextLen: document.body.innerText.length,
  };
}
"""

_GRID_JS = """
() => {
  const g = document.querySelector('.home-grid');
  if (!g) return null;
  const kids = [...g.children].map(el => {
    const r = el.getBoundingClientRect();
    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom};
  });
  return {kids};
}
"""


def _active_state(page) -> dict:
    return page.evaluate("""() => {
      const nav = document.querySelector('.nav-item.active');
      const kids = document.getElementById('nav-children-deai');
      const parent = document.getElementById('nav-parent-deai');
      const title = document.getElementById('home-title');
      const view = document.querySelector('.view.active');
      return {
        navKey: nav ? (nav.dataset.navKey || '') : '',
        title: title ? title.textContent : '',
        activeView: view ? view.id : '',
        childrenOpen: kids ? kids.classList.contains('is-open') : null,
        parentChildActive: parent ? parent.classList.contains('is-child-active') : null,
      };
    }""")


def _run_viewport(page, page_url: str, w: int, h: int, out: Path) -> None:
    print(f"\n--- 视口 {w}x{h} ---", flush=True)
    page.set_viewport_size({"width": w, "height": h})
    page.goto(page_url, wait_until="load")
    page.wait_for_selector(".nav-item.active", timeout=10000)

    # 1) 侧边栏 / 导航项布局
    box = page.evaluate(_SIDEBAR_JS)
    check("无横向溢出", box["overflowX"] <= 1, f"overflowX={box['overflowX']}")
    check("页面有可见内容", box["bodyTextLen"] > 80, f"len={box['bodyTextLen']}")
    check("侧边栏宽 200px", abs(box["sidebar"]["width"] - 200) < 1.5,
          f"width={box['sidebar']['width']}")
    # 「重写」父项本身不是导航目标 (它和子项共用 view-deai), 故按 nav-key 判覆盖
    keys = [it["key"] for it in box["items"] if it["key"]]
    check("导航项覆盖 7 视图 + 两入口",
          set(keys) == set(NAV_KEYS), str(sorted(keys)))
    check("「重写」父项可点击进入 (有 parent-item 标记)",
          any(it["parentItem"] == "deai" for it in box["items"]))
    tall = [it["text"] for it in box["items"] if it["height"] > NAV_ITEM_MAX_HEIGHT]
    check("导航项均为单行", not tall, str(tall))
    out_of_box = [it["text"] for it in box["items"]
                  if it["left"] < box["sidebar"]["left"] - 1
                  or it["right"] > box["sidebar"]["right"] + 1]
    check("导航项不越出侧边栏", not out_of_box, str(out_of_box))
    # 收起的子项高度为 0, 不参与重叠判定
    overlaps = []
    sits = sorted([it for it in box["items"] if it["height"] > 0], key=lambda it: it["top"])
    for a, b in zip(sits, sits[1:]):
        if a["bottom"] > b["top"] + 0.5:
            overlaps.append(f"{a['text']}/{b['text']}")
    check("相邻导航项不重叠", not overlaps, str(overlaps))

    # 2) 启动恢复: 默认 config (workflow_mode 空 + strict) 派生逐条入口
    st = _active_state(page)
    check("启动恢复到逐条入口", st["navKey"] == "harness", str(st))
    check("标题为逐条校对", st["title"] == "逐条校对", st["title"])
    check("去 AI 味子项默认收起", st["childrenOpen"] is False, str(st["childrenOpen"]))
    # author 样式里的 display:flex 会盖掉 UA 的 [hidden]{display:none} — 必须显式收回,
    # 否则空提示条会占一条高度 (v5.3.0 实机截图抓到过)
    check("无来源不一致时提示条不占位",
          page.evaluate("""() => {
            const el = document.getElementById('result-provenance');
            return getComputedStyle(el).display === 'none'
                   || el.getBoundingClientRect().height < 1;
          }"""))
    page.screenshot(path=str(out / f"{w}x{h}-1-harness.png"))

    # 3) 工作区两栏不重叠
    grid = page.evaluate(_GRID_JS)
    if grid and len(grid["kids"]) >= 2:
        a, b = grid["kids"][0], grid["kids"][1]
        # 宽视口是左右两栏, 窄视口 (<1100px) 降级为上下堆叠 — 两种都不许重叠
        separated = (a["right"] <= b["left"] + 1 or b["right"] <= a["left"] + 1
                     or a["bottom"] <= b["top"] + 1 or b["bottom"] <= a["top"] + 1)
        check("工作区两栏不重叠", separated, f"{a} vs {b}")
        check("两栏都在视口内", b["right"] <= w + 1 and a["left"] >= -1)

    # 4) 切到「整篇校对」
    page.click('.nav-item[data-nav-key="rewrite"]')
    st = _active_state(page)
    check("整篇入口高亮唯一", st["navKey"] == "rewrite", str(st))
    check("标题切为整篇校对", st["title"] == "整篇校对", st["title"])
    check("仍在共用视图 view-home", st["activeView"] == "view-home", st["activeView"])
    check("整篇入口下 mode-dependent 轮到 rewrite",
          page.evaluate("""() => {
            const rows = [...document.querySelectorAll('.mode-dependent')];
            return rows.some(r => r.dataset.mode === 'rewrite'
                                  && r.style.display !== 'none');
          }"""))
    page.screenshot(path=str(out / f"{w}x{h}-2-rewrite.png"))

    # 5) 「重写」父项展开 + 子项激活
    page.click('.nav-expander[data-nav-expand="deai"]')
    st = _active_state(page)
    check("箭头点击后子项展开", st["childrenOpen"] is True, str(st["childrenOpen"]))
    check("展开态写进 aria-expanded",
          page.get_attribute('.nav-expander[data-nav-expand="deai"]', "aria-expanded") == "true")
    page.click('.nav-item[data-nav-key="deai"]')
    st = _active_state(page)
    check("去 AI 味子项激活", st["navKey"] == "deai", str(st))
    check("切到 view-deai", st["activeView"] == "view-deai", st["activeView"])
    check("父项行标记子项激活", st["parentChildActive"] is True, str(st))
    page.screenshot(path=str(out / f"{w}x{h}-3-deai.png"))

    # 切回逐条入口, 供下一视口从干净状态开始
    page.click('.nav-item[data-nav-key="harness"]')


def main() -> int:
    parser = argparse.ArgumentParser(description="墨准 v5.3 前端三视口冒烟")
    parser.add_argument("--out", default=str(ROOT / ".local" / "smoke-ui-v5.3"),
                        help="截图输出目录 (默认 .local/smoke-ui-v5.3)")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright: pip install playwright && python -m playwright install chromium",
              file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    srv, url = _serve(WEB_DIR)
    print(f"静态服务: {url}\n截图输出: {out}", flush=True)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=not args.headed)
            except Exception as e:                                  # pragma: no cover
                print(f"启动 chromium 失败: {e}\n"
                      f"请先执行: python -m playwright install chromium", file=sys.stderr)
                return 2
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                ctx.add_init_script(_init_script(_stub_payload()))
                page = ctx.new_page()
                errs: list[str] = []
                page.on("pageerror", lambda e: errs.append(str(e)))
                for w, h in VIEWPORTS:
                    _run_viewport(page, url, w, h, out)
                check("页面无 JS 异常", not errs, str(errs[:3]))
            finally:
                browser.close()
    finally:
        srv.shutdown()

    print(f"\n  {_checks - len(_failures)} pass, {len(_failures)} fail", flush=True)
    if _failures:
        print("  失败项: " + "; ".join(_failures), flush=True)
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
