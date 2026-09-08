# 新时代校对大师 v4.1.8 (pywebview + Win11 Fluent 2)

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg) ![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078d4.svg) ![GUI: pywebview](https://img.shields.io/badge/GUI-pywebview-6DA55F.svg)

基于 LLM 的批量文本校对工具。**pywebview 6.2.1** 前端 + 原生 Web 设计令牌 + **Win11 Fluent 2 完整重构 (v4.1.8)**, 支持流式输出与任意 OpenAI 兼容 API。

## 特性

- **Web UI (v4.0+)** — pywebview + 原生 HTML/CSS/JS，零构建工具，秒开
- **Win11 Fluent 2 视觉 (v4.1.8 重构)** — 17 颜色 token + 6 阴影 + 9 type ramp + 5 动画曲线 + Acrylic/Smoke 材料 + 完整暗色模式
- **1px 单线图标 (v4.1.8)** — 13 SVG 重画为 Segoe Fluent Icons 风格
- **暗色模式 (v4.1.8)** — 跟随系统 + Settings 三态切换 (auto / light / dark)
- **流式输出** — 边生成边显示，实时预览校对结果
- **后台线程 + asyncio** (v4.0+) — 主线程跑 pywebview 事件循环，桥接 `window.pywebview.api.xxx`
- **5 档分块预设** (v3.0+) — 2000/3000/4000/6000 字 + 整文件模式
- **跨段上下文** (v3.0+) — `ContextBuilder` 自动注入前 N 段校对结果
- **去 AI 味 3 步工作流** (v3.1+) — 检测 → 改写 → 评分，每步独立 LLM 调用
- **断点续传** — 段级 schema v2，已完成文件自动跳过；CANCELLED 状态强制重跑
- **字符级 diff** (v4.0+) — `diff-match-patch` (Apache-2.0) 高亮修改处
- **暂停/恢复/取消** (v4.0+) — `threading.Event` 跨线程安全
- **多服务商模板** — DeepSeek / Ollama / vLLM / 智谱 / 通义千问

### 主题使用建议 (v4.1.8)

- **白天 / 强光环境** — 推荐 **浅色模式 (light)** 或 **跟随系统 (auto)**: 浅色背景在阳光下反光少, 文本对比度高, 不刺眼
- **夜晚 / 暗房** — 推荐 **暗色模式 (dark)**: 暗色背景减少屏幕眩光, 保护眼睛, 适合长时间校对
- **跟随系统 (auto)** — 默认推荐, 系统切换深浅色时应用自动跟随, 无需手动调整

设置 → 外观主题 → 切换 auto / light / dark, 即时生效 (250ms 过渡).

## 快速开始

### 环境要求

- Windows 10/11（**系统自带 WebView2 Runtime**，Edge 内核，无需额外安装）
- Python 3.10+
- macOS / Linux：pywebview 用系统 WebView 即可（理论支持，**未在 macOS/Linux 端测过**）

### 安装与运行

```bash
pip install -r requirements.txt
python main.py
```

或双击 `start.bat`（Windows）。

## 架构

```
┌─ pywebview 窗口 (系统 WebView2) ─────────────────────────┐
│                                                            │
│  web/index.html + app.js + style.css                       │
│  ├─ 主页视图 (文件列表 / 进度 / diff)                       │
│  ├─ 设置视图 (API / Prompt / chunking 5 档)                 │
│  └─ 去 AI 味视图 (3 步工作流)                                │
│                                                            │
│  调用: window.pywebview.api.xxx()                          │
└────────────────┬───────────────────────────────────────────┘
                 │  bridge (js_api)
┌────────────────▼───────────────────────────────────────────┐
│  Python 后端 (app/)                                          │
│  ├─ web_backend.py   ← Bridge API class (暴露给 JS)        │
│  ├─ processor.py     ← async LLM 引擎 (v3.0 不变)            │
│  ├─ context_builder.py ← 跨段 prefix 注入                   │
│  ├─ utils.py / templates.py / logger.py                     │
│  └─ main.py          ← webview.create_window + start()     │
└────────────────────────────────────────────────────────────┘
```

**v4.0 关键变化**：
- 移除 PySide6 6.11 + QSS 手写主题
- 移除 qasync 异步事件循环
- 改用 pywebview `js_api` bridge + `threading.Thread` + `asyncio.run_coroutine_threadsafe`
- 跨段上下文、断点续传、5 档 chunking 等业务逻辑**完全保留**

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+O` | 添加文件 |
| `Ctrl+Enter` | 开始处理 |
| `Esc` | 取消当前任务 |
| `Ctrl+,` | 切到设置 |
| `Ctrl+.` | 切到去 AI 味 |

> 快捷键由前端 JS 监听（`web/app.js`），不依赖 Qt。

## 校对模式

| 模式 | 说明 |
|------|------|
| 纯纠错 | 仅修正错别字、标点、语法硬伤 |
| 纠错+轻润色 | 修正错误 + 精简冗余、自然化表达 |
| 纠错+重润色 | 修正错误 + 实质性优化句式和用词 |
| 纠错+去流水账 | 针对 AI 生成文本，砍废话、重组结构 |
| 技术文档校对 | 术语统一、中英文间距、Markdown 格式 |
| 自定义 | 完全自定义 Prompt |

## 去 AI 味 (v3.1+，独立视图)

侧边栏点击 **🧽 去AI味** 进入独立工作流视图。**3 步多步工作流**：

| 步骤 | 作用 | 输出 |
|------|------|------|
| **Step 0: 风格 Profile** (v4.1.7+) | 选 builtin 3 套 / 蒸馏 custom profile | 9 轴风格指纹注入 Step 2/3 |
| **Step 1: 检测** | 扫 7 大类 AI 味 + AI 6 处 (V5) | 报告：哪几类命中 + 具体引文 |
| **Step 2: 改写** | 4 步法 + 9 轴 + 事实骨架 (V5) | 改写后文本 + 流式渲染 |
| **Step 3: 评分** | 三维 + 8 轴自评 + 摘出戏句 (V5) | 评分 + 残留 AI 味问题列表 |

**3 步独立运行**，每步都可单独"重跑"。

**借鉴来源**（MIT 协议，思路借鉴，代码全自写）：
- [harshaneel/humanize](https://github.com/harshaneel/humanize) — 4 pass 编辑法
- [blader/humanizer](https://github.com/blader/humanizer) — 7 大类 AI 味分类（来自 Wikipedia: Signs of AI writing）
- **[jianshuo/claude-skills](https://github.com/jianshuo/claude-skills)** (v4.1.7+) — 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评
- [Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) — ruthless editor 思路

详见 `THIRD_PARTY_NOTICES.md`。

## 分块模式 (v3.0+)

设置 → 处理参数 → **分块模式**。5 档可选：

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
- **调整**: 设置 → 处理参数 → 上下文字符数 / 上下文 chunk 数

**token 开销估算**: 100KB 文件分 33 chunk，总额外 token 涨约 8 万 tokens，按 DeepSeek 0.14 元/M tokens 算约 0.01 元/文件，可忽略。

## 项目结构

```
新时代校对大师/
├── main.py                 # 入口（pywebview.start）
├── web/                    # 前端 (v4.0+ 新增)
│   ├── index.html          # 3 视图骨架（主页/设置/去AI味）
│   ├── app.js              # 路由/状态/API 调用
│   ├── style.css           # 设计令牌 + Fluent 2 风格
│   ├── icons/              # Fluent UI System Icons (MIT) — 13 个 SVG
│   └── lib/                # diff-match-patch.js / marked.min.js
├── app/                    # Python 后端
│   ├── web_backend.py      # v4.0+ Bridge API class
│   ├── processor.py        # async LLM 引擎 (v3.0 保留)
│   ├── context_builder.py  # v3.0+ 跨段 prefix
│   ├── templates.py        # API 模板 + Prompt (7 模式 + deai)
│   ├── utils.py            # 数据模型 + 配置持久化 + 断点
│   └── logger.py           # RotatingFileHandler
├── requirements.txt        # pywebview + openai + requests
├── build.spec              # PyInstaller 打包（v4.0 重写）
├── start.bat / start.ps1   # Windows 启动脚本
├── test_*.py               # 6 套件 360 项
├── run_all_tests.py        # 一键跑全部
├── PLAN-pywebview.md       # v4.0 升级 plan
├── CHANGELOG.md            # 版本日志
└── THIRD_PARTY_NOTICES.md  # 借鉴来源 + LICENSE
```

## 配置文件

| 文件 | 说明 |
|------|------|
| `~/.proofreader/last_config.json` | 上次配置（schema v2） |
| `~/.proofreader/checkpoints/` | 断点缓存（CANCELLED 自动重跑） |
| `~/.proofreader/app.log` | 应用日志（5MB 滚动） |

## 开发测试

```bash
# 一键跑全部 6 套件（推荐）
python run_all_tests.py

# 或单独跑
python test_bugs.py
python test_components.py
python test_chunker_presets.py
python test_chunk_lifecycle.py
python test_context_builder.py
python test_web_backend.py
```

当前状态：**6 个套件 360 / 360 通过**（v4.0）

## 打包

```bash
python -m PyInstaller build.spec --clean
```

输出 `dist/新时代校对大师.exe`（onefile，无控制台窗口）。

> 详见 `build.spec`。需在干净 venv 下运行，避免污染系统包。
> ⚠️ 打包后 exe 需要系统有 WebView2 Runtime（Win10 1803+ / Win11 默认带）。

## 借鉴来源

v3.0 + v4.0 + v4.1.7 + v4.1.8 共借鉴 11 个开源项目 / 文档（4 业务 + 4 前端/库 + 1 DeAI 升级 + 2 Win11 重构），全部思路借鉴，代码自写：

- **业务层**：tianhm/ollama-batch-processor / shreyan241/gpt-proofreader / Xueheng-Li/proofreading (MIT) + qasync (BSD-2)
- **GUI 层 (v4.0)**：pywebview (BSD-3) + diff-match-patch (Apache-2.0) + marked.js (MIT) + Fluent UI System Icons (MIT)
- **DeAI 升级 (v4.1.7)**：jianshuo/claude-skills (MIT) — 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评
- **Win11 重构 (v4.1.8)**：
  - [Microsoft Learn 设计原则文档](https://learn.microsoft.com/zh-cn/windows/apps/design/) — 5 原则 + 7 签名体验的数值与命名约定 (Microsoft Terms of Use, 致谢非协议)
  - [Fluent UI System Icons (MIT)](https://github.com/microsoft/fluentui-system-icons) — 1px 单线 / 24×24 网格 / round cap 风格 (path 全部项目语言手写)

完整 LICENSE 副本见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 许可证

MIT
