# 墨准 (MoZhun) v5.1.0 (pywebview + 水墨宣纸 / Win11 Fluent)

基于 LLM 的批量文本校对工具。**pywebview 6.2.1** 前端 + 原生 Web 设计令牌 + **Win11 Fluent 2 视觉**，支持流式输出、任意 OpenAI 兼容 API，以及**零 LLM 成本的本地标点修复**（v4.3.3+）。

## 特性

- **Web UI (v4.0+)** — pywebview + 原生 HTML/CSS/JS，零构建工具，秒开
- **Win11 Fluent 2 视觉 (v4.1.8)** — 17 颜色 token + 6 阴影 + 9 type ramp + Acrylic/Smoke 材料 + 完整暗色模式
- **7 视图分组导航 (v4.2.0)** — Win11 设置应用式侧边栏：校对 / 结果对比 / 去AI味 / 风格库 / API接口 / 校对参数 / 外观与关于
- **双皮肤 (v4.4.0+)** — 水墨宣纸（默认，贴合墨准：宣纸底 / 玄墨字 / 朱砂印 / 楷体品牌）与 Win11 Fluent，与深浅主题 2×2 自由组合
- **1px 单线图标 + 暗色模式 (v4.1.8)** — 13 SVG Segoe Fluent Icons 风格；主题 auto / light / dark 三态切换
- **本地标点修复 (v4.3.3 / v4.3.4)** — 纯规则脚本，**不调用 LLM、零成本、零 API 延迟**：中文引号自动配对（弯/直角两种风格）、省略号/破折号/波浪号归一、全角字母数字折叠、引号不平衡行号报告
- **Markdown 清洗 (v4.4.2)** — AI 产出的 .md / md 格式 txt 直接丢进来，产出一篇无标记、适宜人类阅读的文章（本地规则引擎 `md_strip`，零成本零延迟）；可选「送 LLM 前剥离 Markdown」让校对/去AI味不再读标记
- **Edit 工具链 harness (v5.1.0)** — 「严格校对 / 纠错+轻润色」模式默认改走 function calling：模型逐条返回编辑建议（改哪 / 改成什么 / 为什么），客户端精确匹配应用，**输出 token 大幅下降**；结果对比页「改动清单」逐条审计（已应用 / 未找到原文 / 匹配多处 / 级联失效），部分未采纳时文件标「完成（部分建议未采纳）」
- **流式输出** — 边生成边显示，实时预览校对结果
- **后台线程 + asyncio (v4.0+)** — 主线程跑 pywebview 事件循环，桥接 `window.pywebview.api.xxx`
- **5 档分块预设 (v3.0+)** — 2000/3000/4000/6000 字 + 整文件模式；**跨段上下文**自动注入前 N 段校对结果
- **去 AI 味 3 步工作流 (v3.1+)** — 检测 → 改写 → 评分；**整本书级长文本**（v4.3.0）分块处理、超 5 万字自动降级推送、完整结果落盘
- **断点续传** — 段级 schema v2，已完成文件自动跳过；支持**强制重跑**（v4.3.1）；CANCELLED 状态强制重跑
- **字符级 diff (v4.0+)** — `diff-match-patch` (Apache-2.0) 高亮修改处
- **暂停/恢复/取消 (v4.0+)** — `threading.Event` 跨线程安全
- **10 服务商 API 预设 (v4.3.2)** — LM Studio / OpenCodeGo / OpenRouter / MiniMax / 阿里百炼 / 智谱清言 / 火山引擎 / 硅基流动 / DeepSeek / 自定义；Model 单输入框 + datalist 补全

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
│  ├─ 7 视图 SPA (v4.2.0): 校对 / 结果对比 / 去AI味 /        │
│  │   风格库 / API接口 / 校对参数 / 外观与关于               │
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
| `Ctrl+.` | 切到去 AI 味 |

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

设置 → 校对参数 → **「启用 Edit 工具链 (harness 模式)」**（默认开，可关闭）。仅「严格校对」与「纠错+轻润色」两种模式生效，关闭或其它模式回退为模型整篇重输出。

- **工作方式**：模型不再输出修改后全文，而是逐条调用 `edit_text(old_text, new_text, reason)` 工具提交编辑建议；客户端按精确字符串匹配（唯一命中）串行应用，只发送/保存真正的改动
- **改动清单**：结果对比页底部折叠面板，逐条显示状态与理由 —— 已应用 / 未找到原文 / 匹配多处 / 已被前序编辑修改 / 无意义调用；未采纳的条目灰显，文件状态显示「完成（部分建议未采纳）」
- **安全边界**：old_text 匹配多处时**不猜**（跳过并报告）；换行符差异（\r\n/\n）自动归一匹配；单块超 50 条建议自动截断并告警；全部编辑未生效时整文件标失败（走既有重试链）
- **取消/断点语义不变**；harness 开关纳入缓存指纹，切换开关后旧断点自动失效重跑一次

## 去 AI 味 (v3.1+，独立视图)

侧边栏点击 **去AI味** 进入独立工作流视图。**3 步多步工作流**：

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

详见 `THIRD_PARTY_NOTICES.md`。

## 分块模式 (v3.0+)

设置 → 校对参数 → **分块模式**。5 档可选：

| 模式 | 块大小 | 适用场景 |
|------|-------|---------|
| 快速 (fast) | 2000 字 | 大文件快速处理 |
| **均衡 (balanced)** | 3000 字 | 默认推荐 |
| 高上下文 (high_context) | 4000 字 | 需要更强上下文 |
| 大块 (large) | 6000 字 | 短上下文模型适用 |
| 整文件 (whole_file) | 不分块 | 小于 2500 字的小文件 |

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
│   ├── index.html          # 7 视图骨架（校对/结果对比/去AI味/风格库/API接口/校对参数/外观关于）
│   ├── app.js              # 路由/状态/API 调用
│   ├── style.css           # 设计令牌 + Fluent 2 风格
│   ├── icons/              # Fluent UI System Icons (MIT) — 13 个 SVG
│   └── lib/                # diff-match-patch.js
├── app/                    # Python 后端
│   ├── web_backend.py      # v4.0+ Bridge API class
│   ├── processor.py        # async LLM 引擎 (v3.0 保留)
│   ├── punct_fix.py        # v4.3.3+ 本地标点修复规则引擎
│   ├── context_builder.py  # v3.0+ 跨段 prefix
│   ├── templates.py        # API 模板 (10 预设) + Prompt (6 模式 + deai)
│   ├── utils.py            # 数据模型 + 配置持久化 + 断点
│   └── logger.py           # RotatingFileHandler
├── build.spec              # PyInstaller 打包（v4.0 重写）
├── check_exe.py            # 打包后 exe 资源完整性校验
├── test_*.py               # 8 套件 1165 项
├── run_all_tests.py        # 一键跑全部
├── PLAN-*.md               # 各版本升级 plan（完成态存档）
├── CHANGELOG.md            # 版本日志
└── THIRD_PARTY_NOTICES.md  # 借鉴来源 + LICENSE
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
# 一键跑全部 8 套件（推荐）
python run_all_tests.py

# 或单独跑
python test_bugs.py
python test_components.py
python test_chunker_presets.py
python test_chunk_lifecycle.py
python test_context_builder.py
python test_punct_fix.py
python test_md_strip.py
python test_web_backend.py
```

当前状态：**8 个套件 1165 / 1165 通过**（v5.0.0）

## 打包

```bash
python -m PyInstaller build.spec --clean
python check_exe.py   # 校验 exe 内 web/ 资源与 style_profiles 完整性
```

输出 `dist/墨准.exe`（onefile，无控制台窗口）。

> 详见 `build.spec`。需在干净 venv 下运行，避免污染系统包。
> ⚠️ 打包后 exe 需要系统有 WebView2 Runtime（Win10 1803+ / Win11 默认带）。

## 借鉴来源

v3.0 → v5.1.0 共借鉴 **20 个开源项目 / 文档**，全部思路借鉴，代码自写：

- **业务层 (v3.0)**：tianhm/ollama-batch-processor / shreyan241/gpt-proofreader / Xueheng-Li/proofreading (MIT) + qasync (BSD-2)
- **GUI 层 (v4.0)**：pywebview (BSD-3) + diff-match-patch (Apache-2.0) + marked.js (MIT) + Fluent UI System Icons (MIT)
- **DeAI 升级 (v4.1.7)**：jianshuo/claude-skills (MIT) — 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评
- **Win11 重构 (v4.1.8)**：[Microsoft Learn 设计原则文档](https://learn.microsoft.com/zh-cn/windows/apps/design/)（致谢非协议）+ Fluent UI System Icons
- **标点修复调研 (v4.3.4)**：[woct0rdho/typeset](https://github.com/woct0rdho/typeset) (MIT) + [huacnlee/autocorrect](https://github.com/huacnlee/autocorrect) (MIT) + [yongzhuo/macro-correct](https://github.com/yongzhuo/macro-correct) (Apache-2.0) + [sparanoid/chinese-copywriting-guidelines](https://github.com/sparanoid/chinese-copywriting-guidelines) (MIT) + GB/T 15834-2011《标点符号用法》
- **Markdown 清洗 (v4.4.2)**：[commonmark/commonmark-spec](https://github.com/commonmark/commonmark-spec)（CC-BY-SA 4.0 spec 文本 + BSD-2 参考实现）— 围栏/强调边界/表格形态的结构语义引用
- **DeAI 后置三件套 (v5.0.2)**：[harshaneel/humanize](https://github.com/harshaneel/humanize) (MIT) — audit-revise 出戏句反馈循环 + 4 pass 法；[blader/humanizer](https://github.com/blader/humanizer) (MIT) — AI 痕迹分类语义（现行 v3.0 "five sections + 25 patterns"，本项目不用其编号）；[Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) (MIT) — 0-100 AI-tell 本地评分范式（分数是信号不是判定）
- **校对 harness (v5.1.0)**：[Claude Code Edit 工具](https://code.claude.com/docs/)（Anthropic 文档，致谢非协议）— old_text/new_text 精确匹配 + 唯一性要求 + 逐条状态回执的 Edit 工具设计范式

完整 LICENSE 副本见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 许可证

MIT
