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
    from app.templates import API_TEMPLATES, PROMPT_MODES
    from app.utils import CHUNKING_PRESETS, ProjectConfig

    return {
        "config": ProjectConfig().to_dict(),
        "api_templates": [dict(t) for t in API_TEMPLATES],
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
    get_api_templates: async () => DATA.api_templates,
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


def _check_provenance(page, out: Path) -> None:
    """端到端: 逐条结果出现在整篇入口 → 来源提示条 + 强制重跑参数 (§4-1/§4-10)。"""
    print("\n--- 跨入口结果来源 + 强制重跑 ---", flush=True)
    page.set_viewport_size({"width": 1440, "height": 900})

    # 造一条"逐条校对已完成"的结果 (真实跑需要 API key, 这里只验 UI 契约)
    page.evaluate("""() => {
      App.workspaceTrack = 'harness';
      App.tasks = [{path: '/tmp/墨准冒烟.txt', status: 'completed', original: '原文一行',
                    corrected: '改后一行', error: '', workflow: 'harness', warnings: false}];
      App.selectedFileKey = null;
      App.renderFileList();
      App.setView('home');
      App.selectFile('/tmp/墨准冒烟.txt');
    }""")
    check("本轨结果不弹来源提示条",
          page.evaluate("() => document.getElementById('result-provenance').hidden"))
    check("本轨徽标不高亮",
          page.evaluate("""() => {
            const el = document.querySelector('.file-track');
            return !!el && el.textContent.trim() === '逐条'
                   && !el.classList.contains('is-other');
          }"""))

    # 切到整篇入口: 结果仍是逐条产的 → 提示条 + 徽标标黄
    page.click('.nav-item[data-nav-key="rewrite"]')
    check("跨入口时提示条出现",
          page.evaluate("() => !document.getElementById('result-provenance').hidden"))
    check("提示条说清两个入口",
          page.evaluate("""() => {
            const txt = document.getElementById('result-provenance').textContent;
            return txt.includes('逐条校对') && txt.includes('整篇校对');
          }"""))
    check("徽标标黄提示来源不一致",
          page.evaluate("""() => {
            const el = document.querySelector('.file-track');
            return !!el && el.classList.contains('is-other') && el.textContent.trim() === '逐条';
          }"""))
    check("文件行仍显示另一轨的结果", page.evaluate(
        "() => App.tasks[0].status === 'completed' && App.tasks[0].corrected === '改后一行'"))
    page.screenshot(path=str(out / "1440x900-4-provenance.png"))

    # 点「用整篇校对重跑（忽略缓存）」→ 必须走 force_rerun + 当前入口轨
    page.evaluate("""() => {
      for (const [id, val] of [['cfg-api-base', 'http://smoke.local/v1/'],
                               ['cfg-api-key', 'sk-smoke'],
                               ['cfg-model', 'smoke-model']]) {
        const el = document.getElementById(id);
        if (el) el.value = val;
      }
      window.__startArgs = null;
      window.pywebview.api.start_proofread = async (...a) => {
        window.__startArgs = a;
        return {ok: true, task_id: 'smoke-task', total_files: 1, cached_files: []};
      };
    }""")
    page.click("#btn-provenance-rerun")
    page.wait_for_function("() => window.__startArgs !== null", timeout=5000)
    args = page.evaluate("() => window.__startArgs")
    check("重跑带 force_rerun=True", len(args) >= 5 and args[4] is True, str(args))
    check("重跑带当前入口轨 workflow", len(args) >= 6 and args[5] == "rewrite", str(args))


def _check_whole_file_warning(page, out: Path) -> None:
    """端到端: 整篇入口 + 整文件档 + 超 20000 字 → 先弹确认 (§4-9 / §5-18)。"""
    print("\n--- 整文件档 20000 字告警 ---", flush=True)
    page.click('.nav-item[data-nav-key="rewrite"]')
    page.evaluate("""() => {
      App.tasks = [{path: '/tmp/超长稿.txt', status: 'pending', original: '',
                    corrected: '', error: ''}];
      App.selectedFileKey = null;
      App.renderFileList();
      App.config.chunking_preset_rewrite = 'whole_file';
      window.pywebview.api.get_file_char_counts = async (paths) => ({
        ok: true,
        counts: Object.fromEntries((paths || []).map(p => [p, 30000])),
      });
    }""")
    check("整篇轨生效档为整文件", page.evaluate(
        "() => App._effectiveChunkPreset() === 'whole_file'"))

    page.evaluate("""() => {
      window.__cfResult = null;
      App._confirmWholeFileRewrite(['/tmp/超长稿.txt'])
         .then(r => { window.__cfResult = r; });
    }""")
    page.wait_for_selector("#dialog-root:not([hidden])", timeout=5000)
    check("超 20000 字弹确认框", page.evaluate(
        "() => !document.getElementById('dialog-root').hidden"))
    check("确认框写明阈值 20000", page.evaluate(
        "() => document.getElementById('dialog-body-text').textContent.includes('20000')"))
    page.screenshot(path=str(out / "1440x900-5-wholefile-warning.png"))
    page.click("#dialog-btn-secondary")          # 返回改档
    page.wait_for_function("() => window.__cfResult !== null", timeout=5000)
    check("选「返回改档」→ 取消本次启动", page.evaluate(
        "() => window.__cfResult === false"))

    # 阈值以内的文件不打扰
    page.evaluate("""() => {
      window.pywebview.api.get_file_char_counts = async (paths) => ({
        ok: true,
        counts: Object.fromEntries((paths || []).map(p => [p, 5000])),
      });
      window.__cfResult = null;
      App._confirmWholeFileRewrite(['/tmp/超长稿.txt'])
         .then(r => { window.__cfResult = r; });
    }""")
    page.wait_for_function("() => window.__cfResult !== null", timeout=5000)
    check("20000 字以内直接放行", page.evaluate("() => window.__cfResult === true"))
    check("放行时不弹框", page.evaluate(
        "() => document.getElementById('dialog-root').hidden"))


def _check_think_strip_stream(page, out: Path) -> None:
    """v5.4 (PLAN §5-10 / 审计 B5-i): 流式预览不含思维链 + 前端前缀单调渲染。

    前端本身没有过滤逻辑 (N5), 所以用真实 app.think_strip 预生成剥后 partial 序列
    再推给 App.handleEventBatch — 若只推含 <think> 的原文, 这里是假 E2E。
    """
    print("\n--- v5.4: 流式预览无思维链 ---", flush=True)
    from app.think_strip import ThinkFilter

    raw_parts = ["<think>这一段是", "模型的推理过程</think>", "\n\n正文开始。", "正文继续。"]
    flt = ThinkFilter()
    frames = []
    for part in raw_parts:
        flt.feed(part)
        frames.append(flt.take())
    frames.append(flt.flush())
    visible = "".join(frames)
    prefixes = []
    acc = ""
    for f in frames:
        acc += f
        prefixes.append(acc)
    check("预生成: 剥后文本不含思维链",
          "<think>" not in visible and "推理过程" not in visible, repr(visible))
    check("预生成: 前缀序列单调", all(
        prefixes[i + 1].startswith(prefixes[i]) for i in range(len(prefixes) - 1)),
        str(prefixes))

    page.click('.nav-item[data-nav-key="rewrite"]')
    page.evaluate("""(frames) => {
      window.__rendered = [];
      App.workspaceTrack = 'rewrite';
      App.tasks = [{path: '/tmp/思维链冒烟.txt', status: 'running',
                    original: '原文一行', corrected: '', error: ''}];
      App.selectedFileKey = null;
      App.renderFileList();
      App.setView('home');
      App.selectFile('/tmp/思维链冒烟.txt');
      // 渲染走 RAF (scheduleRender), 每帧后等一帧再读 DOM
      window.__rendered = [];
      return frames.reduce((chain, p) => chain.then(() => {
        App.handleEvent('onStream', {file_key: '/tmp/思维链冒烟.txt', partial: p});
        return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => {
          const el = document.getElementById('compare-revised');
          window.__rendered.push(el ? (el.textContent || '') : '');
          r();
        })));
      }), Promise.resolve());
    }""", prefixes)
    rendered = page.evaluate("() => window.__rendered")
    check("前端渲染不含思维链",
          all("<think>" not in r and "推理过程" not in r for r in rendered),
          str(rendered)[:200])
    check("前端最终文本 = 剥后结果",
          rendered and "正文开始。" in rendered[-1] and "正文继续。" in rendered[-1],
          str(rendered[-1])[:200] if rendered else "(空)")
    check("前端渲染单调 (不回缩)",
          bool(rendered) and all(len(rendered[i + 1]) >= len(rendered[i])
                                 for i in range(len(rendered) - 1)),
          str([len(r) for r in rendered]))
    page.screenshot(path=str(out / "1440x900-7-think-strip.png"))


def _check_api_panel(page, out: Path) -> None:
    """v5.3.1: API 面板不含模型示例, 选预设不覆盖用户已填的模型名。"""
    print("\n--- API 面板无模型示例 ---", flush=True)
    page.click('.nav-item[data-nav-key="api"]')
    page.wait_for_timeout(200)

    opts = page.evaluate("""() => [...document.querySelectorAll('#cfg-template option')]
        .map(o => ({value: o.value, text: o.textContent.trim()}))""")
    real = [o for o in opts if o["value"]]
    check("预设下拉有服务商项", len(real) >= 3, str(len(real)))
    check("下拉只显示服务商名 (无 (模型名) 后缀)",
          all("(" not in o["text"] and "（" not in o["text"] for o in real),
          str([o["text"] for o in real]))
    banned = ("MiniMax-M2", "qwen-plus", "glm-4-flash", "DeepSeek-V3",
              "deepseek-chat", "deepseek-reasoner", "openrouter/auto")
    check("下拉不含已知模型示例", not any(
        b in o["text"] for b in banned for o in real), str([o["text"] for o in real]))
    check("Model datalist 初始为空",
          page.evaluate("() => document.querySelectorAll('#model-datalist option').length") == 0)

    # 选预设只填 API 地址, 不动 Model / 不清空已填模型名
    before = page.evaluate("""() => {
      document.getElementById('cfg-model').value = 'my-own-model';
      return true;
    }""")
    check("预置一个模型名用于对照", before is True)
    target = real[1]["value"] if len(real) > 1 else real[0]["value"]
    page.select_option("#cfg-template", target)
    page.wait_for_timeout(200)
    check("选预设后模型名保持不变", page.input_value("#cfg-model") == "my-own-model",
          page.input_value("#cfg-model"))
    check("选预设确实填了 API 地址",
          page.evaluate("() => (document.getElementById('cfg-api-base').value || '').length > 0"))
    page.screenshot(path=str(out / "1280x760-6-api-panel.png"))


def _check_splitter_progress(page, out: Path) -> None:
    """v5.4.3 (F9 / F15): 切分进度事件真的渲染 + splitter 日志真的落到 UI。

    F9 修之前后端推 onSplitterProgress, 但 app.js 的 dispatch 没有对应 case,
    事件落 `default: console.warn` —— 进度条只能 0% 直接跳 100%。
    修法是走 default: 分支委派给 splitter.onEvent, 所以这里从
    App.handleEvent 注入, 验的是**真实委派链路**而不是直接调 splitter 方法。
    """
    print("\n--- v5.4.3: 切分进度事件 + splitter 命名空间 ---", flush=True)
    page.click('.nav-item[data-nav-key="splitter"]')
    page.wait_for_timeout(150)

    check("F15 splitter 挂在 window.app 上 (不是大写孤儿对象)",
          page.evaluate("() => !!(window.app && window.app.splitter)"))
    check("F15 大写 window.App 不再被创建",
          page.evaluate("() => typeof window.App === 'undefined'"))

    # processing 形态: 宽度非 0 且非 100% (夹具 3 本, current=1 → 33%)
    page.evaluate("""() => window.app.handleEvent('onSplitterProgress',
        {stage: 'processing', current: 1, total: 3, book_name: '第一本'})""")
    st = page.evaluate("""() => {
      const box = document.getElementById('splitter-progress');
      const fill = document.getElementById('splitter-progress-fill');
      const stats = document.getElementById('splitter-progress-stats');
      return {hidden: box ? box.hidden : null,
              width: fill ? fill.style.width : '',
              stats: stats ? stats.textContent : ''};
    }""")
    check("F9 processing 事件让进度条显形", st["hidden"] is False, str(st))
    check("F9 processing 宽度非 0 且非 100%", st["width"] not in ("", "0%", "100%"),
          f"width={st['width']}")
    check("F9 processing 显示当前书名与计数", "第一本" in st["stats"] and "1/3" in st["stats"],
          st["stats"])

    # done 形态: 固定 100% + 成功/失败统计 (不能用 current/total, 否则失败本会拉不满)
    page.evaluate("""() => window.app.handleEvent('onSplitterProgress',
        {stage: 'done', current: 3, total: 3, success: 2, fail: 1})""")
    st = page.evaluate("""() => {
      const fill = document.getElementById('splitter-progress-fill');
      const stats = document.getElementById('splitter-progress-stats');
      return {width: fill ? fill.style.width : '',
              stats: stats ? stats.textContent : ''};
    }""")
    check("F9 done 事件宽度 100%", st["width"] == "100%", f"width={st['width']}")
    check("F9 done 事件显示 2 成功 / 1 失败",
          "2" in st["stats"] and "1" in st["stats"] and "成功" in st["stats"],
          st["stats"])

    # F15: splitter.log / toast 必须真的走到 App, 而不是恒假的守卫
    before = page.evaluate("() => document.getElementById('log-output').textContent")
    page.evaluate("() => window.app.splitter.log('冒烟日志行')")
    after = page.evaluate("() => document.getElementById('log-output').textContent")
    check("F15 splitter.log 真的写进 #log-output",
          after != before and "[小说切分] 冒烟日志行" in after,
          f"新增={after[len(before):]!r}")

    # 未认领的事件仍落 console.warn, 不能被委派分支静默吞掉
    warned = page.evaluate("""() => {
      const orig = console.warn;
      let seen = null;
      console.warn = (...a) => { if (seen === null) seen = String(a[0]); };
      try { window.app.handleEvent('onSomethingUnknown', {}); }
      finally { console.warn = orig; }
      return seen;
    }""")
    check("F9 未知事件仍告警 (未被静默吞)", "未知事件" in (warned or ""), repr(warned))
    page.screenshot(path=str(out / "1440x900-8-splitter-progress.png"))


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
                _check_provenance(page, out)
                _check_whole_file_warning(page, out)
                _check_think_strip_stream(page, out)
                _check_api_panel(page, out)
                _check_splitter_progress(page, out)
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
