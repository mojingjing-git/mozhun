# AGENTS.md — 项目约定

## 技术栈

- **GUI**: pywebview 6.2.1+ + 原生 HTML/CSS/JS（**Fluent 2 风格**，设计令牌手写，无第三方 UI 库）
- **WebView**: 系统 WebView2（Win10/11 默认带）
- **后端**: `threading.Thread` + `asyncio.run_coroutine_threadsafe` + AsyncOpenAI 流式调用
- **Python**: 3.10+
- **依赖**: openai, requests, pywebview

## 架构 (v4.0+)

```
main.py (webview.start)
├── webview.create_window(js_api=Backend)
│   └── 加载 web/index.html (7 视图 SPA: 校对/结果对比/去AI味/风格库/API接口/校对参数/外观关于)
│       ├── 校对/结果对比  (文件列表 / 进度 / diff / 流式)
│       ├── 去AI味/风格库  (3 步工作流 + Step 0 Profile 管理)
│       └── API接口/校对参数/外观关于  (.content-narrow 窄栏设置组)
└── Backend (app/web_backend.py)
    ├── window.pywebview.api.xxx ← JS 调用入口
    ├── 校对任务: threading.Thread + asyncio.new_event_loop
    │   ├── ProcessingEngine.run_async() (v3.0 保留)
    │   ├── Chunker (5 档分块)
    │   ├── ContextBuilder (跨段 prefix 注入)
    │   └── _stream_single() × N chunks (串行)
    ├── DeAI 3 步工作流 (Phase 3): 独立 AsyncOpenAI + 流式推送
    ├── 标点修复 (v4.3.3+): prepare_tasks 前置 fix_punctuation_ex / punct_local 模式零 LLM
    └── _push() 50ms 节流: window.evaluate_js 推送到前端
```

- **入口/启动**: `main.py`；统一启动器 `start.py`（智能/exe/dev/check 四模式）+ `启动.bat` 薄包装
- **GUI/前端**: `web/index.html` / `web/app.js` / `web/style.css` / `web/icons/` / `web/lib/`
- **Bridge 层**: `app/web_backend.py`（**唯一** 暴露给 JS 的 Python 类）
- **引擎层**: `app/processor.py`（纯 async，无 GUI 依赖），`app/context_builder.py`（v3.0+），`app/punct_fix.py`（v4.3.3+ 标点规则引擎，纯函数无 IO 无 GUI）
- **数据层**: `app/utils.py`（数据模型 + 持久化），`app/templates.py`（Prompt 定义）

## 关键设计决策

### v3.0+ 保留（业务逻辑与 UI 解耦，业务层完全不变）
1. **流式节流** (v2.0+): `processor.py` 每 5 token 或 50ms 才 emit 一次 `on_stream`，避免 UI 卡顿
2. **客户端复用** (v2.0+): `AsyncOpenAI` 在 `_run_all` 中创建一次，共享给所有文件
3. **配置防抖** (v2.0+): 前端 JS 用 `setTimeout(500)` 延迟调 `set_config` + `save_config`
4. **输入验证** (v2.0+): 前端实时校验 URL（正则），无效红框提示
5. **5 档 chunking 预设** (v3.0+): fast(2000) / balanced(3000) / high_context(4000) / large(6000) / whole_file(0)；overlap=0（校对场景不重叠）
6. **跨段上下文** (v3.0+): `ContextBuilder` 把已完成的相邻 chunk 拼成 system prompt prefix（前 N 段 + max_chars 限制），消除 chunk 级别处理下的段落孤岛
7. **chunk 失败语义** (v3.0+): 可重试（RateLimit/Timeout/Connection）→ 整文件重试 N 次；不可重试（Auth/Permission/NotFound/BadRequest）→ 立即标 FAILED
8. **取消语义 v0.2 选项 A** (v3.0+): 取消时不保留中间 chunk 断点，丢弃 chunks_results，整文件标 CANCELLED，下次重跑从 chunk 0 重新开始
9. **断点 schema v2** (v3.0+): 旧 v1 断点无 `schema_version` 字段，加载时自动迁移；CANCELLED 状态断点强制重跑
10. **去 AI 味 3 步工作流** (v3.1+): 检测 → 改写 → 评分，每步独立 LLM 调用；借鉴自 harshaneel/humanize (MIT) 的 4 pass 法和 blader/humanizer (MIT) 的 7 大类 AI 味分类

### v4.0 新增（pywebview 重写）
11. **Bridge 模式** (v4.0+): Python 类 `Backend` 通过 `js_api=backend` 注入到 `webview.create_window`，前端用 `window.pywebview.api.xxx()` 同步调；规避 HTTP overhead
12. **流式 50ms 节流** (v4.0+): `web_backend._push()` 用 `threading.Lock` 保护 buffer，50ms 内高频 push 累积后批量 flush 单个 `evaluate_js` 调用，避免卡 WebView
13. **后台线程 + asyncio** (v4.0+): 校对任务在 `threading.Thread(daemon=True)` 跑，线程内 `asyncio.new_event_loop()` + `loop.run_until_complete()`，**不再**依赖 qasync
14. **pause/cancel 用 `threading.Event`** (v4.0+): 替代 v3.0 `asyncio.Event`，跨线程安全；`cancel_proofread()` 从 bridge 主线程调 `engine.cancel()` 不需要 await
15. **文件选择用 `create_file_dialog`** (v4.0+): pywebview 原生多选文件对话框，**完全替代** v3.0 PySide6 `QFileDialog`
16. **Web 设计令牌** (v4.0+): CSS 自定义属性（`--colorBrandBackground`, `--shadow4` 等）借鉴自 [Fluent UI 2](https://fluent2.microsoft.design/) (MIT)，无 Tailwind/UnoCSS

### v4.1.7 新增（蒸馏文风融入 DeAI）
17. **9 轴风格指纹** (v4.1.7+): 借鉴 [jianshuo/claude-skills](https://github.com/jianshuo/claude-skills) (MIT) 蒸馏文风 skill 思路，把"句子节奏/段落/词汇/语气/论证/比喻/情绪/起收/雷区" 9 维指纹存为 style-card.md。3 个抽象化预置 profile (plain_tech / narrative_general / daily_colloquial) + 用户可加 custom profile 蒸馏
18. **事实骨架纪律** (v4.1.7+): 改写前先抽 3-8 条 bullet, 改写不增不减事实, 借鉴思路 (9 轴只管"怎么写", 不管"想什么")
19. **AI 6 处反制** (v4.1.7+): 借鉴 i-tells 思路, 把 "缺真实专名 / 结尾太圆 / 推进太顺 / 鸡汤化 / 批次指纹 / 原型不匹配" 6 条反制写进 V5 detect + rewrite + audit prompt
20. **8 轴自评** (v4.1.7+): 单模型场景用内联 8 轴 1-5 评分 + 摘出戏句 替代 jianshuo 推荐的"独立判官盲测" (本项目无异模型, 满足度足够)

### v4.1.8 新增（前端按 Win11 Fluent 2 完整重构）
21. **Win11 设计原则落地** (v4.1.8+): 按 [Microsoft Learn 设计原则文档](https://learn.microsoft.com/zh-cn/windows/apps/design/) (Microsoft Terms of Use, 致谢非协议) 的 5 原则 + 7 签名体验**完全重构**前端 — 17 Win11 色板 token + 5 accent 档 + 6 阴影档 (elevation 1/2/8/16/32/128) + 3 圆角 token (`--controlCornerRadius=4px` / `--overlayCornerRadius=8px` / `--radiusSmall=2px`) + 9 type ramp + 5 动画曲线 + 4 时长 + 完整暗色模式 (`@media (prefers-color-scheme: dark)` 独立块) + Acrylic (`.acrylic` `backdrop-filter: blur(20px) saturate(180%)`) + Smoke (`.smoke-overlay` `rgba(0,0,0,0.32)`)。12 SVG 全部重画为 1px 单线 `stroke="currentColor"` Segoe Fluent Icons 风格 (path 全部项目语言手写)。Settings 页加三态主题切换 (auto/light/dark)。可访问性: diff 加 `border-left` 形状标记 (色盲补救 §3.1.4), 11px → 12px 字号修正, F5/F6/F7 修补 (italic/Bold/border-left)。业务逻辑 0 改动。

### v4.1.9 新增（Win11 视觉完全体：材料/动效/个性化落地）
22. **三种材料真实使用** (v4.1.9+): Mica 以中性色 radial-gradient 近似（body 基层，侧边栏=基层/卡片=内容层，Card 阴影升 shadow-8）；Acrylic 用于文件右键菜单（`.menu-flyout.acrylic`）；Smoke + ContentDialog 替代原生 confirm（底部等宽双按钮 + shadow-128）
23. **页面转换 + 动效无障碍** (v4.1.9+): `.view.active` 上滑入场（167ms point-to-point）；全部动画包 `prefers-reduced-motion` 守卫；`:focus-visible` 键盘焦点环
24. **主题持久化** (v4.1.9+): `ProjectConfig.ui_theme` (auto/light/dark) 随配置落盘，启动恢复；主题逻辑统一在 `applyTheme()`

### v4.2.0 新增（信息架构重构: 3 视图 -> 7 视图）
25. **Win11 设置应用式分组导航** (v4.2.0+): 侧边栏分「工作区/设置」两组 7 页 — 校对 (文件+任务) / 结果对比 (diff 独立页, 点文件跳转) / 去 AI 味 (纯工作流) / 风格库 (Step 0 Profile 管理独立页) / API 接口 / 校对参数 / 外观与关于; 关键元素 id 拆分前后保持不变, JS 绑定零迁移; 设置组三页用 `.content-narrow` 窄栏居中

### v4.3.0 新增（DeAI 长文本: 分块/取消/降级推送 + 拖入）
26. **DeAI 分块与降级推送** (v4.3.0+): `split_text` 单点在 utils (校对/DeAI 共用); `_deai_run` 按分块预设切块, rewrite 纯拼接 + 块间衔接, whole_file 超 2 万字兜底回退 large; partial 超 5 万字只推尾部预览, 完整结果落盘 `deai_results/`, 复制/导出/step3 引用走后端直读 (`deai_copy_result`/`deai_save_result`/`source_task_id`), 全文不过 IPC; 取消用 `cancelled:true` 结构化 payload 与失败区分, 语义同校对 (丢弃重跑)

### v4.3.1 / v4.3.2 新增（UX 直觉批次 + API 预设重写）
27. **UX 直觉性修复批次** (v4.3.1+): 全局 toast 替代静默失败、错误信息人性化 (`_humanizeError`)、结果缓存 + **强制重跑** (`start_proofread(force_rerun)`, 缓存命中返回 `cached_files`)、活动感知 watchdog、风格库列表/删除/查看补全、连接测试内联反馈
28. **API 预设 10 项 + Model 单框** (v4.3.2+): 预设清单按用户指定 10 项重写 (接入地址逐一查证); 语义约定 **model 留空 = 服务端模型名动态** (提示 ⟳ 拉取), **api_key 留空 = 必须用户自填** (不预填占位); Model 输入框 + 原生 datalist 合一 (移除拉取后出现的第二个下拉)

### v4.3.3 / v4.3.4 新增（本地标点修复规则引擎）
29. **标点修复 v1 红线** (v4.3.3+): 纯规则脚本零 LLM 成本。四条红线 — 只动中文上下文 (纯英文行不动) / 引号只做成对修复 (落单保守跳过 + 行号报告, 不臆造) / 只做低危转换 (分号永不转换, URL/邮箱掩蔽免疫) / 幂等。`punct_local` 校对模式完全不调 API, 原文作 diff 基线
30. **标点修复 v2 调研吸收** (v4.3.4+): 省略号权重法 (…=3, ≥3 归一 `……`, GB/T 吞尾 `。`)、撇号三分类 (缩略/属格 → `’` 字形不参配对)、全角字母数字折叠 (macro-correct q2b)、逗号低危档 (autocorrect 两档)、破折号/波浪补齐、直角引号风格开关 (「」/『』嵌套)、引号不平衡检测 (只报不改)。选项 4 字段入 ProjectConfig 且全部纳入 `compute_prompt_hash` 缓存指纹; `fix_punctuation_ex` 返回 `{total, imbalance}`, `fix_punctuation` 旧签名兼容

### v4.4.0 新增（水墨宣纸皮肤: 贴合「墨准」品牌）
31. **双皮肤 token 轴** (v4.4.0+): `data-skin` (fluent 默认 / ink 水墨) 与 `data-theme` (auto/light/dark) 正交, `ProjectConfig.ui_skin` 持久化, 前端 `applySkin`/`_persistSkin`/`bindSkinSwitcher` 与主题三件套同构。ink 用 3 个 `html[data-skin="ink"]` 覆盖块 (浅色分组含 `[data-theme=light]` 档) 镜像 fluent 全部 33 个 token — **漏项会按 per-token 层叠串回 fluent 冷色**, 回归项 `test_v440_ink_skin_css` 按 token 定义计数 ≥7 兜底。层叠两条硬规则: ① ink 深 manual (0,2,1) 必须压过 fluent 手动深块 (0,2,0), ② ink 浅块与 ink 深 media 同特异性靠源序 (浅块在前)。装饰件 (印章/墨晕/楷体) 全部带 skin 守卫且取色走 token; `letter-spacing:0.25em` 为排版相对值豁免。acrylic 原 4 行硬编码 rgba 已令牌化 `--colorAcrylicBg`。新增皮肤时以此为模板: 全 token 镜像 + html 前缀统一 + 计数回归

## 文件命名

### 主代码
- 入口: `main.py`；启动器: `start.py`（统一启动器）+ `启动.bat`（双击薄包装）
- Bridge: `app/web_backend.py`
- 引擎: `app/processor.py` / `app/punct_fix.py`（v4.3.3+） / `app/context_builder.py` / `app/utils.py` / `app/templates.py` / `app/logger.py`
- 前端: `web/index.html` / `web/app.js` / `web/style.css` / `web/icons/*.svg` / `web/lib/*.js`
- 打包: `build.spec` / `check_exe.py`（exe 资源校验）/ `dist/墨准.exe`
- 测试:
  - `test_bugs.py`（回归测试）
  - `test_components.py`（组件 + 冒烟测试）
  - v3.0+ 测试: `test_chunker_presets.py` / `test_chunk_lifecycle.py` / `test_context_builder.py`
  - v4.0+ 测试: `test_web_backend.py`（Bridge API 单元 + 集成测试，**替代** v3.x 的 `test_qasync_smoke.py`）
  - v4.3.3+ 测试: `test_punct_fix.py`（标点规则引擎全规则回归，含跨行降级/不平衡报告/幂等）
- 一键跑: `run_all_tests.py`
- 无 pytest 依赖，纯脚本运行

### 借鉴来源（v3.0+ 业务层 + v4.0+ 前端层）
业务层（4 项，v3.0 引入，v4.0 保留）：
- 去 AI 味 4 pass 法: https://github.com/harshaneel/humanize (MIT)
- 7 大类 AI 味分类: https://github.com/blader/humanizer (MIT) — 来源 Wikipedia: Signs of AI writing
- ruthless editor 思路: https://github.com/Aboudjem/humanizer-skill (MIT)
- chunking / context / checkpoint 思路: tianhm/ollama-batch-processor / shreyan241/gpt-proofreader / Xueheng-Li/proofreading (MIT)
- 异步事件循环: qasync (BSD-2-Clause) — **v4.0 已不再使用，仅 requirements.txt 历史记录**

前端层（4 项，v4.0 新增）：
- Bridge 模式: https://pywebview.flowrl.com/ (BSD-3-Clause)
- 字符级 diff: https://github.com/google/diff-match-patch (Apache-2.0)
- Markdown 渲染: https://github.com/markedjs/marked (MIT)
- 设计令牌: https://fluent2.microsoft.design/ (MIT)
- SVG 图标: https://github.com/microsoft/fluentui-system-icons (MIT)

标点修复层（4 项，v4.3.4 新增）：
- 省略号归一: https://github.com/woct0rdho/typeset (MIT)
- 规则两档设计 / PATH_RE 掩蔽 / 分号原则: https://github.com/huacnlee/autocorrect (MIT)
- 引号不平衡检测 / 全角字母数字 q2b: https://github.com/yongzhuo/macro-correct (Apache-2.0)
- 直角引号争议 / 标点形态规范: https://github.com/sparanoid/chinese-copywriting-guidelines (MIT) + GB/T 15834-2011

### 文档
- `README.md` — 用户向文档（特性、快速开始、快捷键、配置、架构）
- `AGENTS.md` — 本文件（开发约定）
- `PLAN-chunking.md` — v3.0 升级 plan（已完成）
- `PLAN-pywebview.md` — v4.0 升级 plan（已完成）
- `CHANGELOG.md` — 版本日志
- `THIRD_PARTY_NOTICES.md` — 借鉴来源 + LICENSE 全文 (§12-15: typeset/autocorrect/macro-correct/排版指北)
- `PLAN-distill-style.md` — v4.1.7 蒸馏文风升级 plan
- `PLAN-win11-redesign.md` / `PLAN-v4.1.5-ui-redesign.md` — 前端重构 plan（完成态存档）

## import 顺序约定

v4.0 移除 PySide6 / qasync 后的约定：

```python
# 标准顺序
import asyncio
import json
import threading
from pathlib import Path
import webview  # 唯一 GUI 依赖
from openai import AsyncOpenAI  # LLM
```

无强制顺序，pywebview 6.x 没有 shiboken 那种 import 顺序坑。

## 不要做的事

- 不要引入 PyQt6 / PyQt5 / PySide2（已统一到 pywebview）
- 不要引入 qfluentwidgets / qasync（不支持 Python 3.13 / 已被 threading 替代）
- 不要引入 React / Vue / Tailwind（v4.0 零构建工具原则，违反会破坏 `python main.py` 直开）
- 不要在 `processor.py` / `context_builder.py` / `punct_fix.py` / `utils.py` / `templates.py` 中引入任何 GUI 依赖（v3.0 原则，v4.0 延续）
- 不要在 `web_backend.py` 中 `await`（v4.0 改成 sync bridge，async 通过 `asyncio.run_coroutine_threadsafe` 跨线程跑）
- 不要引入 chunk overlap（>0），校对场景下重叠区会被改两次
- 不要在 `load_checkpoint` 中返回 CANCELLED 状态的断点（强制重跑）
- 不要用 `asyncio.Event` 实现 pause/cancel（v4.0 改 `threading.Event`，跨线程安全）
- 不要在 `web_backend.py` 直接 `import requests`（除非 webview 走 proxy，**目前不需要**）
- 不要在 `app/style_profiles/` 硬编码具体真人作家名或 jianshuo 仓库真迹链接（抽象化预置 + 致谢在 THIRD_PARTY_NOTICES）
- 不要从借鉴项目复制代码（仅借鉴思路，所有代码自写并加注释；完整 LICENSE 在 `THIRD_PARTY_NOTICES.md`）
- 不要在 `.btn-*` / `.card` / `.deai-step` / `.nav-item` 等组件上硬编码颜色/间距/圆角/字号（v4.1.8 token 体系, 全部走 `--colorNeutral*` / `--colorBrand*` / `--space-*` / `--controlCornerRadius` / `--fontSize*` token, 改 token 即可全站调整）
- 不要放宽 `punct_fix.py` 的四条红线（纯英文上下文不动 / 落单引号只报不改 / 分号不转换 / 幂等）——调研结论是我们比同类项目更保守才安全的，放宽会引入不可逆误伤

## 借鉴合规要求（MIT / BSD / Apache-2.0 协议）

每个借鉴思路的源文件首部加注释：

```python
# 借鉴自 <URL> (<License>)
# 借鉴内容: <一句话>
# 借鉴方式: 思路借鉴,无代码复制
# Copyright (c) <year> <author>
```

完整 LICENSE 副本见 `THIRD_PARTY_NOTICES.md`。
