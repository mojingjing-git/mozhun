# 墨准 (MoZhun) v5.4.0 (pywebview + 水墨宣纸 / Win11 Fluent)

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg) ![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078d4.svg) ![GUI: pywebview](https://img.shields.io/badge/GUI-pywebview-6DA55F.svg)

基于 LLM 的批量文本校对工具。**pywebview 6.2.1** 前端 + 原生 Web 设计令牌 + **Win11 Fluent 2 视觉**，支持流式输出、任意 OpenAI 兼容 API，以及**零 LLM 成本的本地标点修复**（v4.3.3+）。

## 特性

- **Web UI (v4.0+)** — pywebview + 原生 HTML/CSS/JS，零构建工具，秒开
- **Win11 Fluent 2 视觉 (v4.1.8)** — 17 颜色 token + 6 阴影 + 9 type ramp + Acrylic/Smoke 材料 + 完整暗色模式
- **7 视图分组导航 (v4.2.0 / v5.2b / v5.3)** — Win11 设置应用式侧边栏，三组分工：**工作区**（逐条校对 / 整篇校对 / 重写 → 去 AI 味）、**工具**（风格库 / 小说切分）、**设置**（API 接口 / 校对参数 / 外观与关于）
- **工作流双入口 (v5.3)** — 「逐条校对」(harness 工具链) 与「整篇校对」(模型重写全文) 拆成两个独立入口；结果自带来源标记，当前入口与结果来源不一致时给出提示条 + 一键「忽略缓存重跑」
- **双皮肤 (v4.4.0+)** — 水墨宣纸（默认，贴合墨准：宣纸底 / 玄墨字 / 朱砂印 / 楷体品牌）与 Win11 Fluent，与深浅主题 2×2 自由组合
- **1px 单线图标 + 暗色模式 (v4.1.8)** — 13 SVG Segoe Fluent Icons 风格；主题 auto / light / dark 三态切换
- **本地标点修复 (v4.3.3 / v4.3.4)** — 纯规则脚本，**不调用 LLM、零成本、零 API 延迟**：中文引号自动配对（弯/直角两种风格）、省略号/破折号/波浪号归一、全角字母数字折叠、引号不平衡行号报告
- **Markdown 清洗 (v4.4.2)** — AI 产出的 .md / md 格式 txt 直接丢进来，产出一篇无标记、适宜人类阅读的文章（本地规则引擎 `md_strip`，零成本零延迟）；可选「送 LLM 前剥离 Markdown」让校对/去AI味不再读标记
- **Edit 工具链 harness (v5.1.0)** — 「严格校对 / 纠错+轻润色」模式默认改走 function calling：模型逐条返回编辑建议（改哪 / 改成什么 / 为什么），客户端精确匹配应用，**输出 token 大幅下降**；右侧对比区「改动清单」逐条审计（已应用 / 未找到原文 / 匹配多处 / 级联失效），部分未采纳时文件标「完成（部分建议未采纳）」

### 思维链剥离 (v5.4)

部分端点会把模型的推理过程内联进正文（` <think>…</think>`），它会整段进入校对结果、diff、导出、断点、去 AI 味的改写与风格样本。v5.4 起**一律丢弃**：

- **只剥行首块**（`<` 之前同一行内只有空白，允许缩进），行内提及（如 `` `<think>` ``）属合法内容受保护；代码围栏 (``` / ~~~) 内不剥
- **白名单标签**: `think` / `thinking` / `reasoning` / `thought`（大小写不敏感、允许属性、同名嵌套按深度配对）
- **流式预览不闪现**：三次流式链路（整篇校对 / 去 AI 味分块+revise / 风格蒸馏）共用同一个过滤器，预览与最终结果严格一致
- **独立字段**（`reasoning_content` / `reasoning`）**永不读取**，只在日志记帧数
- **旧断点自动兜底**：命中缓存时若发现结果仍含残留（而原文本身不含），自动忽略缓存强制重跑一次，日志写明原因
- **边界**：同一行内出现的块不剥（肉眼可见，可强制重跑）；输出**只有**思维链时按空输出处理，走既有重试链 → 耗尽后标 FAILED
- **双轨分块/超时配置 (v5.2c / v5.3)** — 逐条校对默认 `large=6000` + 180s，整篇校对默认 `balanced=3000` + 120s，两条轨各自的配置只在对应入口生效，降低慢模型触发超时重试的概率
- **思维链剥离 (v5.4)** — 模型把推理过程内联进正文的 `<think>…` 块一律丢弃：整篇校对、去 AI 味（检测/改写/评分/revise）、风格蒸馏全覆盖，流式预览不闪现；旧断点若含残留会自动强制重跑一次
- **小说切分 (v5.2b)** — 独立视图，支持中英文章节/卷/特章识别、广告清理、相邻去重、超大章拆分、Gutenberg 头截断和批量落盘
- **流式输出** — 边生成边显示，实时预览校对结果
- **后台线程 + asyncio (v4.0+)** — 主线程跑 pywebview 事件循环，桥接 `window.pywebview.api.xxx`
- **6 档分块预设 (v3.0+ / v5.3)** — 2000/3000/4000/6000/50000 字 + 整文件模式（50000 为「逐条校对」专属）；**跨段上下文**自动注入前 N 段校对结果
- **去 AI 味 3 步工作流 (v3.1+)** — 检测 → 改写 → 评分；**整本书级长文本**（v4.3.0）分块处理、超 5 万字自动降级推送、完整结果落盘
- **断点续传** — 段级 schema v2，已完成文件自动跳过；支持**强制重跑**（v4.3.1）；CANCELLED 状态强制重跑
- **字符级 diff (v4.0+)** — `diff-match-patch` (Apache-2.0) 高亮修改处
- **暂停/恢复/取消 (v4.0+)** — `threading.Event` 跨线程安全
- **10 服务商 API 预设 (v4.3.2 / v5.3.1)** — LM Studio / OpenCodeGo / OpenRouter / MiniMax / 阿里百炼 / 智谱清言 / 火山引擎 / 硅基流动 / DeepSeek / 自定义；预设只填 API 地址（**不含模型示例**），Model 由你手填或点 ⟳ 从服务端拉取后从 datalist 选

### 主题使用建议 (v4.1.8)

- **白天 / 强光环境** — 推荐 **浅色模式 (light)** 或 **跟随系统 (auto)**: 浅色背景在阳光下反光少, 文本对比度高, 不刺眼
- **夜晚 / 暗房** — 推荐 **暗色模式 (dark)**: 暗色背景减少屏幕眩光, 保护眼睛, 适合长时间校对
- **跟随系统 (auto)** — 默认推荐, 系统切换深浅色时应用自动跟随, 无需手动调整

设置 → 外观与关于 → 主题切换 auto / light / dark, 即时生效并随配置持久化。

## 快速开始

### 环境要求

- Windows 10/11（**系统自带 WebView2 Runtime**，Edge 内核，无需额外安装）
- Python 3.10+
- macOS / Linux：pywebview 用系统 WebView 即可（理论支持，**未在 macOS/Linux 端测过**）

### 安装与运行

```bash
pip install -r requirements.txt
python start.py      # 统一启动器: dist 里有 exe 则启动 exe, 否则走开发模式
python main.py       # 或直接开发模式运行
```

或双击 `启动.bat`（Windows，start.py 的薄包装）。

## 架构

```
┌─ pywebview 窗口 (系统 WebView2) ─────────────────────────┐
│                                                            │
│  web/index.html + app.js + style.css                       │
│  ├─ 7 视图 SPA (v5.3 三维导航):                            │
│  │   工作区 逐条校对 / 整篇校对 / 重写(去AI味)              │
│  │   工具   风格库 / 小说切分                               │
│  │   设置   API接口 / 校对参数 / 外观与关于                 │
│  └─ Toast / ContentDialog / Acrylic 右键菜单               │
│                                                            │
│  调用: window.pywebview.api.xxx()                          │
└────────────────┬───────────────────────────────────────────┘
                 │  bridge (js_api)
┌────────────────▼───────────────────────────────────────────┐
│  Python 后端 (app/)                                          │
│  ├─ web_backend.py    ← Bridge API class (暴露给 JS)        │
│  ├─ processor.py      ← async LLM 引擎 (v3.0 保留)          │
│  ├─ punct_fix.py      ← 本地标点修复规则引擎 (v4.3.3+)      │
│  ├─ md_strip.py       ← 本地 Markdown 清洗引擎 (v4.4.2+)    │
│  ├─ ai_score_local.py ← 本地 AI 味评分 (v5.0.2+)            │
│  ├─ harness.py        ← Edit 工具链审计 (v5.1.0+)           │
│  ├─ novel_splitter.py ← 小说章节/卷切分 (v5.2b+)            │
│  ├─ context_builder.py ← 跨段 prefix 注入                   │
│  ├─ utils.py / templates.py / logger.py                     │
│  └─ main.py           ← webview.create_window + start()     │
└────────────────────────────────────────────────────────────┘
```

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+O` | 添加文件 |
| `Ctrl+Enter` | 开始处理 |
| `Ctrl+,` | 切到 API 接口 |
| `Ctrl+.` | 切到「重写 → 去 AI 味」(父项自动展开) |

> 快捷键由前端 JS 监听（`web/app.js`）。`Esc` 仅关闭弹窗；校对运行中，开始按钮本身变为「取消」。

## 校对模式

| 模式 | 说明 |
|------|------|
| 纯纠错 | 仅修正错别字、标点、语法硬伤 |
| 纠错+轻润色 | 修正错误 + 精简冗余、自然化表达 |
| 技术文档校对 | 术语统一、中英文间距、Markdown 格式 |
| 仅标点修复 (v4.3.3+) | **本地规则脚本，不调用 LLM**：引号配对 + 标点归一，秒级完成 |
| 仅 Markdown 清洗 (v4.4.2+) | **本地规则脚本，不调用 LLM**：AI 产出的 .md 直接丢进来，产出一篇无标记、适宜人类阅读的文章（代码内容保留，标题/表格/链接剥除） |
| 自定义 | 完全自定义 Prompt |

## 本地标点修复 (v4.3.3+)

「校对参数」页开启 **标点修复开关** 后，所有模式在送 LLM 前先跑一遍规则引擎（`app/punct_fix.py`）；选「仅标点修复」模式则完全不调 API。

**四条设计红线**：只动中文上下文（纯英文行不动）；引号只做成对修复（落单保守跳过并上报行号）；只做低危转换（分号永不转换，URL/邮箱整段掩蔽免疫）；幂等（修过的文本再修一遍不变）。

| 选项 | 默认 | 说明 |
|------|------|------|
| 引号风格 | 弯引号 `""` | 可切直角引号 `「」`（区间内单引号嵌套 `『』`） |
| 全角字母数字折叠 | 开 | `ＡＢＣ１２３` → `ABC123` |
| 破折号/波浪补齐 | 开 | `--`/单个`—` → `——`，`~` → `～`（GB/T 15834） |
| 重复标点压缩 | 关 | `？？？` → `？`（小说刻意强调场景可留） |

引号不平衡（落单/奇数）不改文本，只在日志输出**行号报告**供人工复核。

## Edit 工具链 harness (v5.1.0)

**入口即开关 (v5.3)**: 侧边栏「工作区 → 逐条校对」= 走工具链；「工作区 → 整篇校对」= 模型重写全文。原先校对参数页的「启用 Edit 工具链」复选框已移除，改由入口决定，无需再去设置页切模式。

「逐条校对」入口下, Prompt 模式只提供「纯纠错 / 纠错+轻润色」（白名单）与两个本地模式；若历史配置停在白名单外的模式（如自定义），引擎按整篇行为执行并在页头明示，不会静默降级、也不改写你的 Prompt 模式。

- **工作方式**：模型不再输出修改后全文，而是逐条调用 `edit_text(old_text, new_text, reason)` 工具提交编辑建议；客户端按精确字符串匹配（唯一命中）串行应用，只发送/保存真正的改动
- **改动清单**：右侧对比区底部折叠面板，逐条显示状态与理由 —— 已应用 / 未找到原文 / 匹配多处 / 已被前序编辑修改 / 无意义调用；未采纳的条目灰显，文件状态显示「完成（部分建议未采纳）」
- **安全边界**：old_text 匹配多处时**不猜**（跳过并报告）；换行符差异（\r\n/\n）自动归一匹配；单块超 50 条建议自动截断并告警；全部编辑未生效时整文件标失败（走既有重试链）
- **截断检测 (v5.3)**：模型返回 `finish_reason=length`（输出被截断）时结果带截断告警，不再静默当成完整结果
- **取消/断点语义不变**；入口轨纳入缓存指纹，切换入口后另一轨的断点不会命中（会重跑并覆盖 —— 单结果槽的已知取舍）
- **断点保护 (v5.3)**：失败/取消不再覆盖磁盘上已完成的结果；要覆盖旧结果走「重新校对（忽略缓存）」或结果来源提示条上的强制重跑按钮

v5.2c 起，校对参数页把两条轨的 chunking 与 timeout 分开保存：逐条校对默认 `large=6000` + 180s（工具链模式慢 2-5 倍），整篇校对默认 `balanced=3000` + 120s。两个入口共用同一个文件队列，同一文件只保留一份结果 —— 结果自带「逐条 / 整篇」来源标记，用另一个入口重跑前会先弹确认。

## 小说切分 (v5.2b+)

侧边栏「小说切分」用于把长篇小说文本拆成可继续校对/改写的章节文件。

- 自动识别中文章节、回、节、卷，以及英文 Chapter、罗马数字和序章/番外等特章
- 支持自定义正则、卷层级、最小/最大章字数与短章合并
- 可选广告/水印清理、相邻重复内容去重、Gutenberg 头部截断
- 预览不落盘；批量保存后输出到 `~/.proofreader/novel_splits/{slug}/`
- 包含 `blocks/`、`chapters.json`、`metadata.json`、`split_report.txt`

## 去 AI 味 (v3.1+；v5.3 起挂在「工作区 → 重写」下)

侧边栏「工作区 → 重写」展开后点击 **去AI味** 进入独立工作流视图（父项「重写」本身也可点，直接进入本视图）。**3 步多步工作流**：

| 步骤 | 作用 | 输出 |
|------|------|------|
| **Step 0: 风格 Profile** (v4.1.7+) | 选 builtin 3 套 / 蒸馏 custom profile | 9 轴风格指纹注入 Step 2/3 |
| **Step 1: 检测** | 扫 7 大类 AI 味 + AI 6 处 (V5) | 报告：哪几类命中 + 具体引文 |
| **Step 2: 改写** | 4 步法 + 9 轴 + 事实骨架 (V5) | 改写后文本 + 流式渲染 |
| **Step 3: 评分** | 三维 + 8 轴自评 + 摘出戏句 (V5) | 评分 + 残留 AI 味问题列表 |

**3 步独立运行**，每步都可单独"重跑"。

**后置三件套 (v5.0.2+)**：Step 2 改写完成后，可选三步客户端后处理（去AI味视图「输入」卡片下方折叠参数区，持久化保存）——
- **剥离 Markdown 标记**（默认开）：`md_strip` 本地规则剥掉改写结果里的井号/星号/列表符等装饰（空结果自动保留原文）；
- **本地 AI 味评分**（默认开）：`ai_score_local` 六维加权打 0-100 分（越高 AI 味越重），显示在 Step 3 输出区顶部；分数是**信号不是判定**，不进任何缓存；
- **自动修订一轮**（默认关）：评分超阈值时把"出戏句"反馈回 LLM 再改写一次（额外 1 次调用，仅 ≤2 万字），两轮取分低者。阈值为初始拍定值，上线后按真实样本校准。

**长文本支持 (v4.3.0+)**：待处理文本与 Few-shot 范文均支持**拖入 txt/md 文件或直接粘贴大段文本**；按当前分块预设切块逐块调用（块间自动衔接），超 5 万字自动降级为尾部预览推送（完整结果落盘 `deai_results/`，复制/导出/Step 3 引用均走后端直读），整本书也不会撑爆界面。

**借鉴来源**（思路借鉴，代码全自写）：
- [harshaneel/humanize](https://github.com/harshaneel/humanize) (MIT) — 4 pass 编辑法 + audit-revise 出戏句反馈循环 (v5.0.2)
- [blader/humanizer](https://github.com/blader/humanizer) (MIT) — AI 味分类语义（来自 Wikipedia: Signs of AI writing；上游现行 v3.0 为 "five sections + 25 patterns"，本项目不用其编号）
- **[jianshuo/claude-skills](https://github.com/jianshuo/claude-skills)** (MIT, v4.1.7+) — 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评
- [Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) (MIT) — ruthless editor 思路 + 0-100 AI-tell 本地评分范式 (v5.0.2)

详见 `docs/THIRD_PARTY_NOTICES.md`。

## 分块模式 (v3.0+)

设置 → 校对参数 → **长文本分块**。6 档可选，且按入口分轨（v5.3）：

| 模式 | 块大小 | 可选入口 | 适用场景 |
|------|-------|---------|---------|
| 快速 (fast) | 2000 字 | 两条轨 | 大文件快速处理 |
| **均衡 (balanced)** | 3000 字 | 两条轨 | 整篇校对默认 |
| 高上下文 (high_context) | 4000 字 | 两条轨 | 需要更强上下文 |
| 大块 (large) | 6000 字 | 两条轨 | 逐条校对默认 |
| **超大块 (extra_large)** | 50000 字 | 仅逐条校对 | 一次喂进大段（已烟测通过，10 万档才会失误） |
| 整文件 (whole_file) | 不分块 | 两条轨 | 小文件一次过 |

- **50000 档的依据**: 用户烟测确认逐条校对（harness）单块 50000 字符可用，10 万档才出现失误，故 50000 定为设计上限。具体模型与耗时未逐项留档；整篇入口看不到该档，误配会自动回退到「大块 (6000)」并记日志。
- **整文件告警 (v5.3)**: 「整篇校对」入口选「整文件」且单文件超 **20000** 字时先弹确认（与去 AI 味的整文件兜底阈值一致），避免一次性把整篇塞给模型导致上下文溢出或输出截断。

**注意**: 校对场景不使用 chunk overlap（重叠区会被改两次产生不一致）。跨段上下文通过下面的"上下文"功能注入 system prompt。

## 跨段上下文 (v3.0+)

启用分块后，自动注入前 N 个 chunk 的校对结果作为当前 chunk 的 system prompt 前缀：

- **默认**: 前 2 个 chunk，最多 800 字符
- **调整**: 设置 → 校对参数 → 上下文字符数 / 上下文 chunk 数

**token 开销估算**: 100KB 文件分 33 chunk，总额外 token 涨约 8 万 tokens，按 DeepSeek 0.14 元/M tokens 算约 0.01 元/文件，可忽略。

## 项目结构

```
墨准/
├── main.py                 # 入口（pywebview.start）
├── start.py                # 统一启动器（智能/exe/dev/check 四模式）
├── 启动.bat                # start.py 的双击薄包装
├── web/                    # 前端 (v4.0+)
│   ├── index.html          # 7 视图骨架（v5.3: 工作区双入口 + 工具组 + 设置组）
│   ├── app.js              # 路由/状态/API 调用
│   ├── style.css           # 设计令牌 + Fluent 2 风格
│   ├── icons/              # Fluent UI System Icons (MIT) — 17 个 SVG
│   ├── views/              # novel-splitter.js 等视图模块
│   └── lib/                # diff-match-patch.js
├── app/                    # Python 后端
│   ├── web_backend.py      # v4.0+ Bridge API class
│   ├── processor.py        # async LLM 引擎 (v3.0 保留)
│   ├── punct_fix.py        # v4.3.3+ 本地标点修复规则引擎
│   ├── md_strip.py         # v4.4.2+ Markdown 清洗
│   ├── ai_score_local.py   # v5.0.2+ 本地 AI 味评分
│   ├── harness.py          # v5.1.0+ Edit 工具链
│   ├── novel_splitter.py   # v5.2b+ 小说切分
│   ├── think_strip.py      # v5.4+ 思维链剥离 (纯函数 + 流式增量过滤器)
│   ├── context_builder.py  # v3.0+ 跨段 prefix
│   ├── templates.py        # API 模板 (10 预设) + Prompt (6 模式 + deai)
│   ├── utils.py            # 数据模型 + 配置持久化 + 断点
│   └── logger.py           # RotatingFileHandler
├── build.spec              # PyInstaller 打包（v4.0 重写）
├── check_exe.py            # 打包后 exe 资源完整性校验
├── run_all_tests.py        # 自动发现并一键跑全部测试
├── tools/smoke_ui.py       # v5.3+ Playwright 三视口 UI 冒烟（布局 + 截图）
├── tests/                  # 19 个测试套件
├── docs/                   # 文档
│   ├── archive/plans/      # 历史升级 plan 归档
│   ├── ROADMAP.md          # 当前路线图与跨会话待办
│   ├── THIRD_PARTY_NOTICES.md  # 借鉴来源 + LICENSE
│   └── Windows11-设计原则.md   # v4.1.8 重构参考 (Microsoft Learn 本地副本)
├── CHANGELOG.md            # 版本日志
└── README.md               # 本文件
```

## 配置文件

| 文件 | 说明 |
|------|------|
| `~/.proofreader/last_config.json` | 上次配置（含标点修复 4 选项、主题） |
| `~/.proofreader/checkpoints/` | 断点缓存（CANCELLED 自动重跑） |
| `~/.proofreader/deai_results/` | 去 AI 味长文本完整结果（超 5 万字降级时落盘） |
| `~/.proofreader/app.log` | 应用日志（5MB 滚动） |

## 开发测试

```bash
# 一键跑全部套件（推荐）
python run_all_tests.py

# 或单独跑
python tests/test_harness.py
python tests/test_novel_splitter.py
python tests/test_web_backend_proofread.py

# v5.3+: 前端布局冒烟（需 playwright + chromium, 截图落 .local/smoke-ui-v5.3/）
python tools/smoke_ui.py
```

当前状态：`run_all_tests.py` 自动发现 19 个套件，v5.4.0 报告 **1550 通过 / 0 失败**（另有 `tools/smoke_ui.py` 三视口 + 跨入口 + 阈值弹窗 + 思维链流式预览 + API 面板 96 项断言全绿）。

## 打包

```bash
python -m PyInstaller build.spec --clean
python check_exe.py   # 校验 exe 内 web/ 资源与 style_profiles 完整性
```

输出 `dist/墨准.exe`（onefile，无控制台窗口）。

> 详见 `build.spec`。需在干净 venv 下运行，避免污染系统包。
> ⚠️ 打包后 exe 需要系统有 WebView2 Runtime（Win10 1803+ / Win11 默认带）。

## 借鉴来源

v3.0 → v5.2c 共借鉴 **23 个开源项目 / 文档**，全部思路借鉴，代码自写：

- **业务层 (v3.0)**：tianhm/ollama-batch-processor / shreyan241/gpt-proofreader / Xueheng-Li/proofreading (MIT) + qasync (BSD-2)
- **GUI 层 (v4.0)**：pywebview (BSD-3) + diff-match-patch (Apache-2.0) + marked.js (MIT) + Fluent UI System Icons (MIT)
- **DeAI 升级 (v4.1.7)**：jianshuo/claude-skills (MIT) — 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评
- **Win11 重构 (v4.1.8)**：[Microsoft Learn 设计原则文档](https://learn.microsoft.com/zh-cn/windows/apps/design/)（致谢非协议）+ Fluent UI System Icons
- **标点修复调研 (v4.3.4)**：[woct0rdho/typeset](https://github.com/woct0rdho/typeset) (MIT) + [huacnlee/autocorrect](https://github.com/huacnlee/autocorrect) (MIT) + [yongzhuo/macro-correct](https://github.com/yongzhuo/macro-correct) (Apache-2.0) + [sparanoid/chinese-copywriting-guidelines](https://github.com/sparanoid/chinese-copywriting-guidelines) (MIT) + GB/T 15834-2011《标点符号用法》
- **Markdown 清洗 (v4.4.2)**：[commonmark/commonmark-spec](https://github.com/commonmark/commonmark-spec)（CC-BY-SA 4.0 spec 文本 + BSD-2 参考实现）— 围栏/强调边界/表格形态的结构语义引用
- **DeAI 后置三件套 (v5.0.2)**：[harshaneel/humanize](https://github.com/harshaneel/humanize) (MIT) — audit-revise 出戏句反馈循环 + 4 pass 法；[blader/humanizer](https://github.com/blader/humanizer) (MIT) — AI 痕迹分类语义（现行 v3.0 "five sections + 25 patterns"，本项目不用其编号）；[Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) (MIT) — 0-100 AI-tell 本地评分范式（分数是信号不是判定）
- **校对 harness (v5.1.0)**：[Claude Code Edit 工具](https://code.claude.com/docs/)（Anthropic 文档，致谢非协议）— old_text/new_text 精确匹配 + 唯一性要求 + 逐条状态回执的 Edit 工具设计范式
- **小说切分 (v5.2b)**：[novel-analyzer](https://github.com/mojingjing-git/novel-analyzer) (Apache-2.0) — 章节/卷识别、广告清理、去重、超大章拆分、Gutenberg 头截断；[zzk6780051/novel](https://github.com/zzk6780051/novel) (MIT) — 多格式章节正则与前 N 行打分；[oomol-lab/txt-to-epub-converter](https://github.com/oomol-lab/txt-to-epub-converter) (MIT) — 卷/章/节层级结构

完整 LICENSE 副本见 [`docs/THIRD_PARTY_NOTICES.md`](./docs/THIRD_PARTY_NOTICES.md)。

## 许可证

MIT
