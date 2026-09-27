# 「墨准」v6.0 整理 + 改名规划

> **归档说明**: 本计划于 2026-09-26 归档。双基线已合并到 `master`，
> Phase C0/C1 已完成；C2 `app.js`、C3 `style.css`、C4 `ARCHITECTURE.md`
> 仍未执行。文中旧版本号、旧路径和测试基线仅保留为历史记录，
> 当前状态以 `docs/ROADMAP.md` 为准。
>
> **分支 `cleanup/v6` 已于 2026-09-27 废弃并删除**。该分支 (tip `6921090`)
> 是 master 的严格祖先 (`git rev-list master..cleanup/v6` = 0), 且是合并提交
> `ea187e8` 的**第一父**, 内容与历史均已被 master 完整覆盖; 删除前已确认
> 其 tip 有备份 tag `backup/pre-consolidation-cleanup-v6-20260926`。
> 本文档 §2 Phase A-D 步骤表中出现的 `cleanup/v6` 属历史记录, 原文保留。

> 本文档是 **执行 backlog**,不是自动执行脚本。每完成一个 Phase,需更新本文档对应章节的"状态"。
>
> 创建: 2026-09-08
> 目标版本: v6.0
> 当前版本: v5.1.0 (基线)
> 基线测试: 10 套件 / 1334 通过 / 0 失败 (2026-09-08 实测)
>
> 修订记录:
> - v0.1 (2026-09-08 08:08)  初版
> - v0.2 (2026-09-08 08:18)  整合 verifier agent 反馈: 4 P0 + 5 P1 + 3 P2 全部闭环

---

## 0. 背景与目标

### 0.1 为什么做这次整理

「墨准」(原"新时代校对大师",v4.3.5 改名)经过 v3.0 → v5.1.0 共 36 个版本的设计决策叠加,代码体量、业务纪律、借鉴合规都到了**该做一次彻底清理**的临界点。

- 仓库名与产品名长期不一致(仓库 `新时代校对大师` / 产品 `墨准`)
- 3 个文件已超过"可读"临界(`test_web_backend.py` 2914 行,`web/app.js` 3080 行 / 141KB,`web/style.css` 1990 行 / 63KB)
- CHANGELOG 1094 行 / AGENTS 25KB / 借鉴合规 14 个仓库,**信息密度高但分散**
- 测试套件 10 个 / 1334 项,自动化覆盖完整,具备"边改边测"的安全网

### 0.2 目标

| 目标 | 度量 | 状态 |
|---|---|---|
| 仓库名 = 产品名 | `F:/AI/01_项目/墨准` 内 git 主仓 | 待 Phase A |
| 拆解 3 个巨型文件 | test_web_backend / app.js / style.css | 待 Phase C |
| 业务代码 0 改动 | 类名/函数名/Prompt 名不动 | 全部 Phase |
| 测试 100% 保持绿 | 1334/0 全绿 | 全部 Phase |
| 配置/断点/风格库 路径布局向后兼容 | `~/.proofreader/` 子目录结构保留 | 待 Phase B 确认 |

### 0.3 D4"允许破坏"细化范围 (verifier P0.3 闭环)

> D4 与 B7 / R4 之前存在表述矛盾。以下是**用户拍板的 D4 允许破坏**的细化边界:

| 范围 | 允许破坏? | 备注 |
|---|---|---|
| ProjectConfig 27 字段 | ❌ 不动 | 老用户配置不丢 |
| 配置文件 `~/.proofreader/last_config.json` 格式 | ❌ 不动 | schema_version 保留 3 |
| 断点 schema v3 | ❌ 不动 | 老断点继续可用 |
| 风格库路径 `~/.proofreader/styles/` | ❌ 不动 | 老 style profile 继续可用 |
| **代码层** (类名/函数名/Prompt 名) | ❌ 不动 | D3 决策 |
| **CHANGELOG 历史条目** | ✅ 允许改写 | 但 verifier 建议**不改历史**,顶部加"曾用名"段 |
| **启动器 dist 产物名** | ✅ 允许改 | v4.3.5 已是 `墨准.exe` |
| **3 个巨型文件结构** | ✅ 允许拆 | 本次核心 |
| **AGENTS.md 36 条决策** | ❌ 不动 | 历史锚点 |

### 0.4 非目标(明确不做)

- ❌ 删历史兼容代码(老断点 schema 迁移、`v3.0 → v4.0` 兼容补丁、审计锚点)
- ❌ 重构后端架构(改 async 模型、换 Pydantic / Poetry 等)
- ❌ 改类/函数/Prompt 名(中文名、缩写等)
- ❌ 改 git 提交历史(rebase、squash 等)
- ❌ 远端推送(本地仓,无远端)
- ❌ 改写 CHANGELOG 历史条目(只在顶部加"曾用名"段)
- ❌ 改 AGENTS.md 36 条决策

---

## 1. 现状数据(2026-09-08 调研)

### 1.1 巨型文件清单

| 文件 | 行 | 字节 | 结构特征 | 风险 |
|---|---:|---:|---|---|
| `test_web_backend.py` | 2914 | 159844 | 30+ `def test_xxx` 平铺,**零 class 分组** | 🟢 低 |
| `web/app.js` | 3080 | 141490 | `const App = {...}` L20-L3048 (~3028 行),L3049+ 是 bootstrap + pywebviewready 监听 | 🟡 中 |
| `web/style.css` | 1990 | 63437 | **42 个** `/* === xxx === */` 章节,含 fluent/ink 双皮肤 + 7 视图 | 🔴 高 |

### 1.2 关键业务文件(不拆)

| 文件 | 行 | 字节 | 角色 |
|---|---:|---:|---|
| `app/processor.py` | 1093 | 55327 | 异步 LLM 引擎,harness 化核心 |
| `app/web_backend.py` | 1816 | 89303 | Bridge API,89KB,集中管理 |
| `app/utils.py` | 661 | 28209 | 数据模型 + 断点 + 配置 + 27 字段 |
| `app/templates.py` | 610 | 31023 | API 10 预设 + 6 模式 Prompt + DeAI 5 prompt |
| `app/punct_fix.py` | 497 | 21632 | 本地标点修复(零 LLM) |
| `app/ai_score_local.py` | 363 | 17465 | 客户端 0-100 评分 |
| `app/harness.py` | 339 | 15722 | Edit 工具链 |
| `app/md_strip.py` | 225 | 11721 | 本地 Markdown 清洗 |

### 1.3 注释密度(基线)

| 文件 | 行 | 注释 | 占比 |
|---|---:|---:|---:|
| logger.py | 87 | 15 | 17% |
| templates.py | 610 | 97 | 16% |
| processor.py | 1093 | 167 | 15% |
| harness.py | 339 | 41 | 12% |
| web_backend.py | 1816 | 178 | 10% |
| punct_fix.py | 497 | 42 | 8% |
| ai_score_local.py | 363 | 28 | 8% |
| md_strip.py | 225 | 16 | 7% |
| utils.py | 661 | 44 | 7% |
| context_builder.py | 62 | 4 | 6% |

注释密度均在合理区间(6-17%),**全局不动**,只拆巨型文件。

### 1.4 测试基线 (10 套件 / 1334 项)

```
test_ai_score.py: 34 pass
test_bugs.py: 22 pass
test_chunk_lifecycle.py: 69 pass
test_chunker_presets.py: 32 pass
test_components.py: 107 pass
test_context_builder.py: 17 pass
test_harness.py: 110 pass
test_md_strip.py: 90 pass
test_punct_fix.py: 74 pass
test_web_backend.py: 779 pass
---
总计: 1334 pass / 0 fail
```

`run_all_tests.py:12-15` 用 `Path(__file__).parent.glob("test_*.py")` 自动发现,排除 `test_isolate.py`。**Phase C1 拆 5+1 文件后,run_all_tests.py 0 改动** (verifier 验证 ✓)。

### 1.5 配置目录引用 (verifier 调研)

`~/.proofreader/` 在 22 个文件里被引用,含子目录:
- `last_config.json` — 主配置
- `checkpoints/` — 断点缓存
- `deai_results/` — DeAI 长文本
- `styles/<slug>/` — 风格库
- `output/` — 导出结果
- `app.log` / `app-debug.log` — 日志

**全部子目录路径在 Phase A/B 中保持不动** (D4 细化)。

---

## 2. 执行计划

### Phase A: 仓库搬迁

**目标**: 在 `F:/AI/01_项目/墨准` 拥有独立 git 仓,在 `cleanup/v6` 分支上推。

| 步骤 | 操作 | 验证 |
|---|---|---|
| A1 | `git clone` 老仓 `F:/AI/01_项目/新时代校对大师` 到 `F:/AI\01_项目\墨准` | 目录有 .git |
| A2 | `cd 墨准 && git checkout -b cleanup/v6` | 分支创建 |
| A3 | 跑 `run_all_tests.py` | 1334/0 全绿 |
| A4 | `git status --short` | clean(只有 .gitignore 的) |
| **A5** | **`git remote remove origin`** (防误推老仓远端) | `git remote -v` 为空 |
| A6 | 跑 `run_all_tests.py` 二次验证 (clone 后独立运行) | 1334/0 全绿 |

**风险**: 🟢 极低 — clone 不影响老仓,A5 删 origin 防误推
**耗时**: 30 min
**状态**: ⬜ 待执行

### Phase B: 改名一致性核查

**目标**: 全栈产品/仓库名"墨准"一致,老用户配置不破坏。

> verifier P2 提示: v4.3.5 已完成 80% 工作,本 Phase 实际耗时 15-20 min,主要剩余:
> - CHANGELOG 顶部加"曾用名"段 (B8 重点)
> - 复核 4 处关键路径

| 步骤 | 操作 | 验证 |
|---|---|---|
| B1 | 检查 `main.py` 窗口标题 | "墨准" |
| B2 | 检查 `build.spec` `name=墨准.exe` | ✓ |
| B3 | 检查 `README.md` / `AGENTS.md` 顶部 | "墨准 (MoZhun) v5.1.0" |
| B4 | 检查 `web/index.html` `<title>` | "墨准 v5.1.0" |
| B5 | 检查侧栏品牌 (`web/index.html` `.sidebar-title`) | "墨准" |
| B6 | 关于页定位行 | "AI 稿件收尾工具" 类 |
| B7 | `~/.proofreader/` 目录结构 | 保留(向后兼容,D4 细化) |
| B8 | **CHANGELOG 顶部加"曾用名"段** (B 阶段主要工作) | "新时代校对大师 (2024 → 2026-09 改名为墨准)" |
| B9 | `start.py` 期望的 exe 路径 `dist/墨准.exe` | ✓ |
| B10 | 跑 `run_all_tests.py` | 1334/0 全绿 |

**风险**: 🟢 极低 — 主要是文档补漏
**耗时**: 15-20 min (verifier 修正)
**状态**: ✅ 完成 (commit 1c8af6a)

### Phase C0: 根目录重组 (B + C-改)

> 用户在 Phase A+B 完成后追加: "根目录太乱了, 先整理项目结构"。
> 用户拍板方案 C-改: README/AGENTS/CHANGELOG 留根, THIRD_PARTY_NOTICES + Windows11-设计原则 进 docs/。

**目标**: 收纳 10 个 test_*.py 进 tests/, 2 个参考文档进 docs/。

| 子任务 | 改动 | 验证 |
|---|---|---|
| C0.1 | 创建 `tests/` 目录 | 目录存在 |
| C0.2 | 移动 10 个 test_*.py + test_isolate.py 到 tests/ (git mv, 保留历史) | 文件就位 |
| C0.3 | 创建 `tests/__init__.py` (空文件, 让 `import test_isolate` 工作) | 文件存在 |
| C0.4 | 改 `run_all_tests.py` 的 glob 到 `tests/test_*.py`, 排除 test_isolate.py | 代码改 |
| C0.5 | `git mv THIRD_PARTY_NOTICES.md Windows11-设计原则.md` 到 docs/ | 文件就位 |
| C0.6 | 更新 `README.md` 项目结构块(如果引用了 THIRD_PARTY_NOTICES.md 路径) | 链接正确 |
| C0.7 | 更新 `AGENTS.md` 顶部"docs/archive/plans" 相对路径 (从 AGENTS.md 仍可见) | 链接正确 |
| C0.8 | 跑 `run_all_tests.py` | 1334/0 全绿 |
| C0.9 | `git add -A && git commit -m "refactor(v6.0): 根目录重组 (10 tests/ + 2 docs/)"` | commit 创建 |

**关键耦合点 (已调研)**:
- `run_all_tests.py:13` 写死 `Path(__file__).parent.glob("test_*.py")` → 改 L13
- 10 个 test_*.py 互相 `import test_isolate` → 同目录即可 (加 __init__.py 让 cwd=根 时 import 也工作)
- check_exe.py: 独立脚本, 无 import 依赖 (L17-18 用 `__file__` 定位 dist/) → 留根, 不动
- build.spec: 跟 test/check_exe 不直接耦合 (L86 `a.scripts` 是 PyInstaller 通用, 没显式 import) → 0 改动

**风险**: 🟢 低 — 改动小且边界清晰
**耗时**: 15-30 min
**状态**: ✅ 完成 (commit `8d26baf` 2026-09-08; 2026-09-27 核对回填 — 11 个 `test_*.py` 进 `tests/`, 2 个 `.md` 进 `docs/`, 改动 17 文件)

### Phase C1: 拆 `test_web_backend.py`

**目标**: 2914 行 / 779 tests 拆为 5 个文件 + `_misc.py`,按 Backend 方法分(verifier P1.3 闭环:无 compat 兜底)。

| 拆解后文件 | 测试函数 | tests 数量 |
|---|---|---:|
| `test_web_backend_smoke.py` | test_backend_imports / test_backend_no_pyside6 / test_backend_init | ~3 |
| `test_web_backend_config.py` | get_config / set_config / save_config / get_prompt_modes / get_api_templates / get_chunking_presets / type_coercion | ~20 |
| `test_web_backend_files.py` | choose_files / read_file / drag_drop / remove / clear | ~15 |
| `test_web_backend_proofread.py` | start / cancel / pause / resume / export | ~30 |
| `test_web_backend_deai.py` | step1 / step2 / step3 / build_prompts | ~10 |
| `test_web_backend_models.py` | fetch_models / test_connection | ~5 |
| `test_web_backend_misc.py` | **未归入以上 5 文件的余下 test**(每条需在 commit 描述里说明归属理由) | 余下 |

| 步骤 | 操作 | 验证 |
|---|---|---|
| C1.1 | 决定拆解边界(每个文件包含哪些 test) | 本文档已列 |
| C1.2 | 创建 6 个新文件,每文件独立 `if __name__ == "__main__"` 块 | 文件存在 |
| C1.3 | 跑 `run_all_tests.py` | 1334/0 全绿 |
| C1.4 | 删 `test_web_backend.py` | 文件删除 |
| C1.5 | `git commit -m "v6.0: 拆 test_web_backend.py → 6 文件"` | commit 创建 |

**风险**: 🟢 低 — 拆完重跑,出问题好定位
**耗时**: 1-2 h
**状态**: ✅ 完成 (commit `9e0c0a4` 2026-09-08, 拆为 7 个 `test_web_backend_*.py`; 2026-09-27 核对回填 — 当前 master 上仍是这 7 个, 自 C1 起未增减)

### Phase C2: 拆 `web/app.js`

**目标**: 3080 行 / `const App` 块 L20-L3048 + bootstrap 收尾 (L3049+),拆为 ES modules,按视图/职责分。

| 拆解后文件 | 角色 |
|---|---|
| `web/app.js` | bootstrap 入口 + 路由调度(变薄到 ~200 行) |
| `web/lib/state.js` | 全局 state(原 App.state) |
| `web/lib/router.js` | view 切换逻辑(原 App.switchView) |
| `web/lib/api-bridge.js` | `window.pywebview.api.xxx` 包装(原 App.api) |
| `web/lib/utils.js` | 通用工具(原 App.utils) |
| `web/lib/diff-match-patch.js` | **不动**(第三方 Apache-2.0) |
| `web/views/home.js` | 校对视图 |
| `web/views/results.js` | 结果对比 |
| `web/views/deai.js` | 去 AI 味 |
| `web/views/styles.js` | 风格库 |
| `web/views/api.js` | API 接口 |
| `web/views/params.js` | 校对参数 |
| `web/views/appearance.js` | 外观与关于 |

**C2 启动时序 (verifier P1.1 闭环)**:
- 现状 (`app.js:3049-3054`): `pywebviewready` 监听 + 5s 兜底超时
- ES module 异步加载会让 `<script type="module">` 在 DOMContentLoaded 时**还未解析完**
- 拆解后启动序列:
  ```
  1. <script type="module" src="app.js"> 触发
  2. app.js 静态 import 所有 views/lib
  3. 所有 module 解析完 → 触发 DOMContentLoaded
  4. pywebviewready 事件触发(若未触发则 5s 兜底)
  5. App.init() 执行
  ```
- 必须显式 `await import()` 链 + DOMContentLoaded 监听双保险

**C2 依赖图 (verifier P1.2 闭环) — 必须 C2.1 步先建**:

```
utils.js (底层)    ← 所有 view + lib 都可 import
state.js (单例)    ← router + views 都可读; views 可写
api-bridge.js     ← 所有 view 都可调
router.js         ← 依赖 state,被 app.js 调
views/*.js (7 个) ← 依赖 utils/state/api-bridge/router,被 app.js 调
app.js (薄壳)     ← 只调 router + views.init() + App.init()
```

**单向依赖原则**: `utils ↛ state`, `state ↛ router`, `views ↛ router` (router 调度 view,反过来 view 不调 router)。**任何反向依赖立刻报 cyclic 警告**。

| 步骤 | 操作 | 验证 |
|---|---|---|
| C2.1 | 建依赖图(本节已列) + 列出 const App 内每个方法/字段归属 | 映射表 |
| C2.2 | 创建 `web/lib/state.js` `router.js` `api-bridge.js` `utils.js` | 文件存在 |
| C2.3 | 创建 `web/views/*.js` 7 个视图文件 | 文件存在 |
| C2.4 | 改 `web/index.html`,`<script type="module" src="app.js">` | 引入 ES module |
| C2.5 | 重写 `web/app.js` 为薄壳,只做 `import` + bootstrap 启动序列(本节) | 文件 < 300 行 |
| C2.6 | 启动器 dry check,确认 WebView2 能加载 | 启动后界面正常 |
| C2.7 | 跑 `run_all_tests.py`(后端不变,只确保没破) | 1334/0 全绿 |
| C2.8 | `git commit -m "v6.0: 拆 web/app.js → 12 个 ES module"` | commit 创建 |

**风险**: 🟡 中 — ES module 重构,依赖图必须先建
**耗时**: 4-6 h
**状态**: ⬜ 待执行

### Phase C3: 拆 `web/style.css`

**目标**: 1990 行 / 42 章节 / 63KB 拆为 4 个 token/component/view 文件。

| 拆解后文件 | 内容 | 预计行 |
|---|---|---:|
| `web/style/tokens.css` | 33 个 CSS 变量定义(浅/深/水墨 3 套) | ~350 |
| `web/style/reset.css` | reset + 全局 | ~50 |
| `web/style/components.css` | 按钮/卡片/输入/对话框等 | ~600 |
| `web/style/views.css` | 7 视图布局 | ~400 |
| `web/style.css` | 仅 4 个 `@import` | ~10 |

**C3 ink 顺序硬规则 (verifier P1.4 闭环)**:
- `web/style.css:219` ink 浅色 token 块: `[data-skin=ink][data-theme=light]` 特异性 `(0,2,1)`
- `web/style.css:354` ink 装饰块(墨晕/楷体/朱砂印): **必须**在 ink 浅块**之后**才能 override 默认 token
- v4.4.0 已固化:"ink 深 manual 0,2,1 压过 fluent 手动深块 0,2,0",拆错会导致默认皮肤闪现
- **拆解后 @import 顺序**: `tokens.css` (含 ink 浅 219) → `components.css` (含 ink 装饰 354 + 视图级 token) → `views.css` → `reset.css` (兜底)

**C3 backup 必做 (verifier P1.4 闭环)**:
- C3.1 必做: 备份原 style.css 到 `web/.baseline-v510/style.css` (从"可选"升级为"必做")
- 备份文件加 .gitignore 排除,不进版本控制

| 步骤 | 操作 | 验证 |
|---|---|---|
| C3.1 | 备份 `web/style.css` 到 `web/.baseline-v510/style.css` + 加 .gitignore | 备份存在 |
| C3.2 | 列出 42 个章节的具体行范围(用 `re.findall(r'/\*+\s*=+', src)` 重新统计) | 依赖图 |
| C3.3 | 创建 `web/style/` 目录 + 4 个分文件 | 文件存在 |
| C3.4 | 重写 `web/style.css` 为 4 个 `@import`(按 ink 顺序硬规则) | 文件 < 20 行 |
| C3.5 | 启动器 dry check,确认默认皮肤(ink)正常显示 | 视觉对照 |
| C3.6 | 切换主题三态(light/dark/auto) | 视觉对照 |
| C3.7 | 切换皮肤(fluent/ink) | 视觉对照 |
| C3.8 | 跑 `run_all_tests.py` | 1334/0 全绿 |
| C3.9 | `git commit -m "v6.0: 拆 web/style.css → 4 个分文件"` | commit 创建 |

**风险**: 🔴 高 — 层叠规则 0 改动,要逐块验
**耗时**: 2-4 h
**状态**: ⬜ 待执行

### Phase C4: 新增 `docs/ARCHITECTURE.md`

**目标**: 把 AGENTS.md 的 36 条关键决策汇总成"新开发者 5 分钟读懂"。

| 内容 | 源 |
|---|---|
| 项目定位 | AGENTS.md 顶部 + README.md 简介 |
| 4 阶段演进史 (v3.0+/v4.0+/v4.1.7+/v4.1.8+/v4.1.9+/v4.2.0+/v4.3.0+/v4.3.1+/v4.3.3/v4.3.4+/v4.4.0/v4.4.2/v5.0.2/v5.1.0) | AGENTS.md §1-§36(压缩为 1 段) |
| 6 大本地零 LLM 引擎 | AGENTS.md §29-§32 + §34 |
| harness 化设计 | AGENTS.md §36 |
| 借鉴合规 14 个 GitHub 仓库 (verifier P2 闭环:实际 14 仓库,非"20 项") | THIRD_PARTY_NOTICES.md 索引 |
| 业务层纪律 | AGENTS.md"不要做的事"段 |
| 6 模式 + DeAI 3 步工作流 | AGENTS.md §10-§18 |

| 步骤 | 操作 | 验证 |
|---|---|---|
| C4.1 | 写 `docs/ARCHITECTURE.md` | 文档存在 |
| C4.2 | 在 README.md 加一行 `> 新开发者请先读 [docs/ARCHITECTURE.md]` | 链接可达 |
| C4.3 | AGENTS.md 顶部加一行 `> 决策依据见 [docs/ARCHITECTURE.md]` | 链接可达 |
| C4.4 | `git commit -m "v6.0: 新增 docs/ARCHITECTURE.md"` | commit 创建 |

**风险**: 🟢 低 — 新增不删,链接正确即可
**耗时**: 1 h
**状态**: ⬜ 待执行

### Phase D: 收尾

| 步骤 | 操作 | 验证 |
|---|---|---|
| D1 | 跑 `run_all_tests.py` | 1334/0 全绿 |
| D2 | 启动器 dry check (`python start.py check`) | 全部 OK |
| D3 | `git status --short` 确认改动可控 | 仅规划改动 |
| D4 | 出最终 diff 报告(行数变化 / 新增文件 / 删除文件) | 报告给用户 |
| D5 | `git log --oneline cleanup/v6` 列所有 commit | 6 个 commit (A/B/C1/C2/C3/C4 各一个) |

**耗时**: 30 min
**状态**: ⬜ 待执行

---

## 3. 时间估算 (verifier P2 修正)

| 节奏 | Phase | 累计 | 适合 |
|---|---|---|---|
| **最低** | A + B + C1 + D | 2.5-3 h | "只动测试,不动前端" |
| **中等** | A + B + C1 + C2 + D | 7-10 h | "测试 + 前端逻辑拆" |
| **完整** | A + B + C1 + C2 + C3 + C4 + D | 10-15 h | "彻底" |

**推荐节奏**: 分 3 次会话
- 会话 1: A + B + C1 + D1 (基线锁定) — **2.5-3.5 h** (verifier P2 修正)
- 会话 2: C2 (ES module 重构) — 5 h
- 会话 3: C3 + C4 + D (style.css 拆 + 文档) — 5 h

---

## 4. 风险登记 (verifier P1.5 新增 R7)

| # | 风险 | 等级 | 应对 |
|---|---|---|---|
| R1 | `style.css` 拆解层叠规则破坏,导致默认皮肤闪现 | 🔴 | 拆前备份 (C3.1 必做) + 严格按 ink 顺序硬规则 + 实跑视觉对照 |
| R2 | `app.js` ES module 重构引出循环依赖 | 🟡 | C2.1 先建依赖图 + 单向依赖原则,反向依赖立即报 cyclic |
| R3 | 测试 fixture 在拆分后丢失共享 setup | 🟢 | 现状本就平铺无 setUp (verifier 验证 ✓),新文件各自独立 |
| R4 | 用户配置 `~/.proofreader/last_config.json` 不兼容 | 🟢 | D4 细化:ProjectConfig 27 字段不动 + schema_version 保留 3 |
| R5 | 老仓 `新时代校对大师` 还在,误操作影响 | 🟢 | 全部操作在新仓 `墨准/`,老仓仅作只读源 |
| R6 | git 提交历史被误改 | 🟢 | 不做 rebase/squash,只 `commit` |
| **R7** | **每 Phase 出问题需要回滚 (verifier P1.5 新增)** | 🟢 | 每 Phase 一个独立 commit,出问题用 `git reset --hard HEAD~1` 回到 Phase 起点;若 Phase 内部分 commit 用 `git revert <hash>` |

---

## 5. 决策记录

| # | 决策 | 备选 | 选定 | 理由 |
|---|---|---|---|---|
| D1 | 起点 | clone / worktree / 重命名 / init | **clone 独立仓** | 用户拍板:实验性质,不怕污染主仓 |
| D2 | 整理范围 | 删兼容代码 / 重组结构 / 重构后端 / 只改名 | **重组结构** | 用户拍板:业务层不动,只结构 |
| D3 | 改名范围 | 仓库名 / 类名 / Prompt 名 / 不改 | **仓库名** | 用户拍板:类名/Prompt 名不动 |
| D4 | 兼容性 | 全部 / 配 / 全 | **允许破坏 (细化范围见 §0.3)** | 用户拍板:实验仓,不怕破坏 |
| D5 | 执行节奏 | 通扫 / 分阶段 | **分 3 次会话** | superpowers 默认:每次只动一类 |

---

## 6. Verifier 审查记录 (闭环)

### v0.2 已闭环

**P0 (4 项,已修复)**:
- [x] 套件数 8 → **10** (本档多处更新)
- [x] style.css 章节数 19 → **42**
- [x] D4 vs B7 矛盾 → **新增 §0.3 细化范围**
- [x] web/app.js 行数 3055 → **3080**,const App L20-L3054 → **L20-L3048**

**P1 (5 项,已修复)**:
- [x] C2 启动时序 → **C2 节加"启动序列 + 双保险"**
- [x] C2 依赖图缺失 → **C2.1 步新增"建依赖图 + 单向依赖原则"**
- [x] C1 compat 兜底反模式 → **改为 `test_web_backend_misc.py` + commit 描述每条归属**
- [x] C3 ink 装饰块顺序 + backup → **C3 节加"ink 顺序硬规则 + backup 必做"**
- [x] R6 非回滚预案 → **新增 R7 回滚预案**

**P2 (3 项,已修复)**:
- [x] B 阶段实际 15-20 min → **B 阶段表格顶部加"主要剩余工作"**
- [x] C4 借鉴合规 20 项 → **改为"14 个 GitHub 仓库"**
- [x] 会话 1 估 3h 偏乐观 → **改为 2.5-3.5h**

### 通过 (不需改,正向反馈)

- **D1-D5 决策逻辑自洽**,理由引用 superpowers/用户拍板
- **R1-R7 风险登记覆盖了主要场景**
- **C2 模块划分方向正确**:lib/(state/router/api-bridge/utils) + views/(7 视图) + 入口薄壳 = 标准 SPA ES module 模式
- **C3 @import 顺序方向正确**:"token → 装饰 → 组件 → 视图"
- **C4 ARCHITECTURE.md 内容来源映射**与 AGENTS.md §36 条决策**对齐**
- **B8 "CHANGELOG 不改历史,顶部加曾用名"** 是稳健做法
- **`run_all_tests.py` glob 自动发现** 经核实正确,Phase C1 拆 6 文件**0 改动**论断成立 ✓
- **Phase A 极低风险(纯 clone)**,作为基线锁定步骤正确
- **R3 "test_web_backend 现状本就平铺无 setUp"** 经核实正确 ✓

---

## 7. 状态追踪

| Phase | 状态 | 完成日期 | commit hash | 备注 |
|---|---|---|---|---|
| A 搬迁 | ✅ | 2026-09-08 | aca8085 (老仓) | 老仓 commit + 墨准/ clone + 切 cleanup/v6 + origin 改 https + 1334/0 基线 |
| B 改名 | ✅ | 2026-09-08 | 1c8af6a | CHANGELOG.md +4/-0, 7 处复核全部合格 |
| C0 根目录重组 | ✅ | 2026-09-08 | 8d26baf | 17 files: 11 test_*.py→tests/, 2 .md→docs/, 文档路径更新 |
| C1 拆测试 | ✅ | 2026-09-08 | 9e0c0a4 | 8 files: test_web_backend.py → 7 个 test_web_backend_*.py (116 tests) |
| C2 拆 app.js | ⬜ | | | |
| C3 拆 style.css | ⬜ | | | |
| C4 文档 | ⬜ | | | |
| D 收尾 | ⬜ | | | |

> 状态符号: ⬜ 待执行 / 🟡 进行中 / ✅ 完成 / ❌ 阻塞

### Phase C0 实际执行记录 (2026-09-08)

```
C0.1 mkdir tests/                                                            ✅
C0.2 git mv 11 个 test_*.py 到 tests/                                        ✅ (git 自动识别为 RM)
C0.3 创建 tests/__init__.py (空)                                             ✅
C0.4 改 run_all_tests.py 2 处 (glob + PYTHONPATH env)                         ✅
C0.5 git mv THIRD_PARTY_NOTICES.md / Windows11-设计原则.md 到 docs/          ✅ (R)
C0.6-C0.7 改 README.md (3 处) + AGENTS.md (2 处) 路径                          ✅
C0.8 跑测试 1334/0 全绿                                                     ✅
C0.9 git add -A + git commit -F _commit_msg_c0.txt → commit 8d26baf        ✅
```

**踩坑修复记录** (写在 commit message 警示未来):
1. **ModuleNotFoundError: No module named 'app'** (196 失败)
   - 原因: Python 跑 `python tests/test_xxx.py`(相对路径) 时, sys.path[0] = tests/ 目录, 不含 cwd = 根
   - 修复: run_all_tests.py 加 `env={**os.environ, 'PYTHONPATH': <项目根>}`
2. **9 个测试文件 sys.path.insert(0, str(Path(__file__).parent))** 失败
   - 原因: 原来指向"脚本目录 = 根", 现在指向"tests/ 父目录 = 根"
   - 修复: 改 9 个文件 `parent` → `parent.parent`
3. **test_bugs.py 3 处 + test_web_backend.py 1 处 path 引用** 失败
   - 原因: `Path(__file__).parent / "app"` 现在指向 `tests/app/` (不存在)
   - 修复: 改 4 处 `parent` → `parent.parent`
4. **commit message 文件 _commit_msg_c0.txt 第一次误进 commit** (278fc5a)
   - 原因: `git add -A` 把 _commit_msg_c0.txt 也 add 进 staged
   - 修复: `git reset --soft HEAD~1` + `git reset HEAD _commit_msg_c0.txt` + 重新 commit


### Phase A 实际执行记录 (2026-09-08)

```
A1 git clone F:/AI/01_项目/新时代校对大师 → F:/AI/01_项目/墨准      ✅ rc=0
A2 cd 墨准 && git checkout -b cleanup/v6                              ✅ 已切
A3 run_all_tests.py (clone 前)                                       ✅ 1334/0
A4 git status --short                                                ✅ clean (含 CLEANUP_PLAN.md untracked)
A5 git remote (实际执行: remove + add, 不是 plan 写的"删")
   1. git remote remove origin                                       ✅ rc=0
   2. git remote add origin https://github.com/mojingjing-git/mozhun.git ✅ rc=0
   ⚠️ ls-remote 揭示远端不是空: refs/heads/master = 5767171427f8fbe7bf4f8e9b00570f51611d6f85
      (与老仓本地 master f5bcde3 不同 — 可能是用户之前的初始 commit 或个人实验)
      决策: 用户拍板"覆盖" (Phase D 收尾时统一 push -f)
A6 run_all_tests.py (clone 后)                                       ✅ 1334/0
A7 (后续追加) 老仓 commit "chore: v5.1.0 整理 (临时文件清理 + PLAN 归档)" = aca8085
A8 墨准/ master fast-forward 到 aca8085, cleanup/v6 rebase 同步       ✅
```

**重要产出**:
- 墨准/ 是独立 git 仓,63 个 tracked file,27 commit (含 A7 老仓整理 commit),master 跟老仓 master 同步
- 当前在 cleanup/v6 分支 (含 A7 老仓整理)
- origin = https://github.com/mojingjing-git/mozhun.git (用户拍板"覆盖"远端 5767171)
- CLEANUP_PLAN.md 在工作树根目录,untracked
- git --local config 已 set: user.name=mojingjing-git, user.email=251359130+mojingjing-git@users.noreply.github.com

### Phase B 实际执行记录 (2026-09-08)

```
B1 main.py 窗口标题 = "墨准"                                        ✅ 合格
B2 build.spec L91 name='墨准' (PyInstaller 加 .exe)                ✅ 合格
B3 README.md 顶部 = "墨准 (MoZhun) v5.1.0"; AGENTS.md 含墨准         ✅ 合格
B4 web/index.html <title> = "墨准 v5.1.0"                            ✅ 合格
B5 侧栏品牌 (.sidebar-title) = "墨准"                                ✅ 合格
B6 view-appearance 定位 = "本地标点修复 + LLM 批量校对 + 去 AI 味"     ✅ 合格
B7 ~/.proofreader/ 路径保留 (D4 细化向后兼容)                        ✅ 合格
B8 CHANGELOG 顶部加"曾用名"段 (4 行)                                ✅ 已改 + commit 1c8af6a
B9 start.py EXE_PATH = 墨准.exe                                      ✅ 合格
B10 跑测试 1334/0 全绿                                              ✅
```

**唯一改动**: CHANGELOG.md +4/-0
**Commit**: 1c8af6a "docs(v6.0): Phase B 改名一致性核查 - CHANGELOG 顶部加曾用名段"

**未做的**:
- 未 push 到 origin (远端 5767171 覆盖决策推迟到 Phase D)
- 5 个 PLAN-*.md 在老仓已 commit 移到 docs/archive/plans/, 墨准/ 已同步 (通过 A7+A8)
