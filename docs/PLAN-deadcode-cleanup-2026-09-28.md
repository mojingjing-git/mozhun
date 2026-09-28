# 墨准 死代码净化 + 文档归档计划（2026-09-28）

> 状态：**复审通过，按 v2 执行中**（2026-09-28）
> 基线版本：v5.4.3（commit `5a46b34`）
> 性质：**只做清理，不加功能**。本计划不改变任何业务语义、Prompt、输出形态。
> 关联：`AGENTS.md` §31（ink skin 镜像不变量）、§37/§39（workflow 双轨）、§46（UI 冒烟门禁）
>
> **v2 修订记录（两路独立 verifier 复审后）**
> - Phase 2「`app.js:583` 改 2 处」→ **改为单点改**，`:706`/`:2433` 明确禁改（P1，否则制造新哑控件）
> - Phase 2 新增 `setVal('cfg-timeout-compat', ...)` 填充，否则改名后控件空白
> - Phase 2 门禁删掉「反之亦然」——`sync()` 是单向的，该要求结构上不可达成
> - Phase 1 F2b 由 7 类修正为 **8 类**（漏 `.type-caption`），并加「禁正则删除」约束
> - Phase 1 新增 `tests/test_harness_split.py:55` 字段数断言（**32 → 29**，非 31）
> - Phase 1 新增三处无门禁兜底的文档同步项
> - Phase 4 归档清单**剔除 ROADMAP.md**（活文档，用户裁定）
> - Phase 4 归档清单**新增 `.workbuddy/`**（用户裁定；该目录不在 git 历史，原「决策记录随压缩包保存」是虚假承诺）
> - Phase 4 **保留 `Windows11-设计原则.md`**（THIRD_PARTY_NOTICES:590,596 以其为出处凭据，归档会自断合规链）

---

## 0. 背景

一次全仓静态扫描（AST 抽定义 + 全仓标识符引用计数 + Bridge 双向匹配 + DOM/CSS 可达性）
发现四类问题：死代码、过时兼容字段、过时 hash 规则、前后端重复派生逻辑。
三路独立 agent 只读评估后，**推翻了扫描清单里的两类假阳性**（见 §1.2），
本计划以复审后的结论为准。

### 0.1 扫描规模

49 个源文件 / 29244 行。核心：`web/app.js` 3547、`app/web_backend.py` 2273、
`app/processor.py` 1288、`app/utils.py` 859、`web/style.css` 1902。

---

## 1. 前置裁定（复审结论，不可再议）

### 1.1 明确**不做**的项（附理由）

| 项 | 理由 |
|---|---|
| `ProcessingEngine.is_paused / is_cancelled / is_running` | **高价值观察接口**。`tests/test_bugs.py:119` 的取消延迟回归断言全靠 `is_cancelled`；B1/B2/M5 三个已修 bug 全在取消暂停路径上。删等于在刚修完 bug 的区域撤哨兵。 |
| `_LEGACY_MODE_MAP`（`utils.py:347`） | **必须保留**。删了 v5.0.0 之前的旧配置会在 `templates.py PROMPT_MODES[mode]` 崩溃。且"存量用户是否已全部迁移"从代码不可判定。 |
| `--colorDiffSame`（定义 7 处，零 `var()` 引用） | **§31 镜像不变量的一部分**。`tests/test_web_backend_misc.py:490` 把它列入 27 个 core token 并断言 `css.count() >= 7`，实测恰好 7 处，删任一处即挂测试。 |
| `.status-*` / `.toast-*` 6 个 CSS 类 | **假阳性**。`app.js:292` / `app.js:2872` 运行时拼接 className，是活代码。 |
| `#nav-parent-deai` / `#nav-children-deai` | **假阳性**。`tools/smoke_ui.py:157-158` 用它们做父子展开态探测，删了冒烟测试失效。 |
| `ProjectConfig.schema_version` 的 `FileResult` / `TaskResult` 同名字段 | 承担真实的 v1→v2 断点迁移，由 `tests/test_chunk_lifecycle.py:53-120` 锁定。只删 `ProjectConfig` 那一个。 |

### 1.2 扫描假阳性记录（供下次清理参考）

1. **动态 className 拼接** → 字符串字面量匹配必然假阴性。任何"CSS 类零引用"结论都必须先排除 `X + var` 拼接。
2. **冒烟测试用 `getElementById` 探测 DOM** → 该 id 在 JS 里"零引用"但在 `tools/smoke_ui.py` 里是活契约。
3. **计数型回归测试会把死 token 撑成活的不变量** → `--colorDiffSame` 定义 7 处全是为满足计数断言，功能上零消费。

---

## 2. 执行批次

每批次独立可回滚，批次间不共享未提交的中间态。

### Phase 0 — 基线快照（**动手前必做**）✅ 已完成

| 动作 | 实测结果 | 用途 |
|---|---|---|
| `git tag backup/pre-cleanup-20260928` | ✅ tag 指向 `5a46b34` | 一键回滚锚点 |
| `python run_all_tests.py` | ✅ **1900 通过 / 0 失败**（21 套件） | 回归对比基准 |
| `python tools/smoke_ui.py` | ✅ **117 通过 / 0 失败** | §46 门禁基准 |

21 套件明细：`test_ai_score` 34 / `test_bugs` 25 / `test_chunk_lifecycle` 74 /
`test_chunker_presets` 32 / `test_components` 117 / `test_context_builder` 17 /
`test_harness` 162 / `test_harness_split` 35 / `test_md_strip` 126 /
`test_novel_splitter` 72 / `test_punct_fix` 84 / `test_push_channel` 97 /
`test_start` 30 / `test_think_strip` 70 / `test_web_backend_config` 114 /
`test_web_backend_deai` 344 / `test_web_backend_files` 89 / `test_web_backend_misc` 215 /
`test_web_backend_models` 19 / `test_web_backend_proofread` 130 / `test_web_backend_smoke` 14

> 基线不绿则**先停下报告**，不得在红基线上叠加清理。**基线为绿，允许继续。**

### Phase 1 — 零风险纯清理（难度 1，约 95 行）

互不依赖，可并行。**字段数 32 → 29**（三个字段一起删，不是 31）。

| 项 | 位置 | 预估 |
|---|---|---|
| `output_format` 字段 | `app/utils.py:367,415,456` + `app/web_backend.py:627` + 计数断言 | 7 |
| `output_dir` 字段 | `app/utils.py:371,419,460` + 计数断言 | 5 |
| `ProjectConfig.schema_version` | `app/utils.py:373,421,462` + `test_components.py:482` | 6 |
| `_BULLET_RES` | `app/ai_score_local.py:165-167` | 4 |
| `_RETRYABLE_ERRORS` | `app/processor.py:91-92`（连注释一起删，注释内容失实） | 2 |
| `SELF_AUDIT_AXES` | `app/style_profiles/loader.py:66-71` | 6 |
| A8 废弃形参传 `''` | `web/app.js:1456` | 1 |
| F1 删 2 个孤儿 id | `web/index.html:32` (`#sidebar`)、`:504` (`#deai-params`，**保留 class**) | 2 |
| F2b **8 个**零引用 `.type-*` 类 | `web/style.css`（**只删类定义行，不动 `--fontSize*` token**） | 8 |
| F3a 10 个零引用 token | 6 个 `--color*` 派生快捷 token + 4 个 `--space-*` | 10 |
| G 组 marked.js | `web/index.html:8` + `README.md:295,298` + `AGENTS.md:170,173` | 45 |

**A8 陷阱（已由 pywebview 源码验证）**：Bridge 调用是 `func(*func_params)` **纯位置传参**。
删掉第 4 位会让 `forceRerun` 落进 `chunking_preset` 槽、`workflow` 落进 `force_rerun` 槽 ——
**静默错位**，后者变成 truthy 字符串会让缓存永远被绕过且轨道丢失。**必须传 `''` 占位，不能删位。**
`app.js:1417` 的 `preset` 变量有第二处用途（`:1448` 日志），保留变量只改传参。

**F2b 删除方式硬约束**：`style.css:757` 是 `.type-body-large-strong{`（`strong` 与 `{` 之间**无空格**，
而该类在 `index.html:33` 正在用）。正则 `\.type-body\b` 的 `\b` 在 `y` 与 `-` 之间**成立**，
会连带误删。`.type-title\b` 同理会误伤 `.type-title-large`。
→ **必须按整行精确匹配删除，禁止用词边界正则。**

**计数断言同步（共 3 处，漏一处即红）**：
`tests/test_components.py:63`、`tests/test_web_backend_deai.py:1192`、`tests/test_harness_split.py:55`（`test_field_count_32`，原计划漏列）

**文档同步（无测试门禁兜底，必须手工做）**：
- `AGENTS.md:156`「字段数 32」→「字段数 29」
- `web/index.html:19` 头部注释逐字描述了将被删的 8 个 `.type-*` 类 —— 与同块 `:8` 的 marked.js 一并改
- `docs/THIRD_PARTY_NOTICES.md:428` §7 marked.js 仍写「直接使用」→ 加一行「已不直接使用，保留 LICENSE 备查」（章节重排仍挂起）

**门禁**：`run_all_tests.py` 全绿 + `smoke_ui.py` 通过数 ≥ Phase 0 基线。

### Phase 2 — 重复 DOM id 修复（真 bug，独立 commit）

`web/index.html:406` 的 `id="cfg-timeout"` 与 `:351` 重复，`getElementById` 恒命中 `:351`。
后果：`app.js:583` 的 compat 同步绑到**校对面**输入框，用户改「校对参数·超时」会反向改写
整篇轨 timeout；`:406` 那个标着"原 timeout"的控件**完全不可操作**（从不 populate / 从不 collect / 无 listener）。

**修法**：`:406` 改唯一 id `cfg-timeout-compat`，并补 `setVal` 填充。

| `web/app.js` 中 `cfg-timeout` 的 3 处 | 动作 |
|---|---|
| `:583` `sync('cfg-timeout', 'cfg-rewrite-request-timeout')` | ✅ **唯一该改处** → 源改 `cfg-timeout-compat` |
| `:706` `setVal('cfg-timeout', config.timeout)` | ❌ **禁改**（回填逐条字段） |
| `:2433` `getVal('cfg-timeout')` → `timeout` | ❌ **禁改**（收集逐条字段） |

> ⚠️ 多改 `:706`/`:2433` 会把逐条校对的超时框变成永不回填、永不上报的哑控件 ——
> 正好把 `:406` 现有的病复制一份过去。

**新增必补**：`app.js:706` 附近加 `setVal('cfg-timeout-compat', ...)`，否则改名后控件永远空白
（`cfg-chunking-preset` 有 `fillSelect` 而 timeout input 没有，两者不对称）。

**文案修正**：`index.html:397` summary「联动」暗示双向，`sync()` 是单向 —— 文案要改准。

**顺带**：`data-scope="deai"` 全仓无 JS 读取，是死属性，删 2 处。

**测试影响**：`test_web_backend_deai.py:619-624` 的 `cfg_ids` 用 `in html` **存在性**判断，
`:351` 仍在 → 无需同步。`:613-617` 的 id 唯一性清单**不含** `cfg-timeout`（现在 `count()==2`，加进去当场红）。
`tools/smoke_ui.py` 零引用 `cfg-timeout` ✅。

**门禁**：`grep -c 'id="cfg-timeout"' web/index.html` == 1；改「整篇校对请求超时」校对面**不应**变
（单向，**不要测反之亦然**）；`test_v420_nav_split`。

> ⚠️ 这是**行为变更不是清理**，独立 commit。

### Phase 3 — 需改测试的项（难度 2，约 35 行）

| 项 | 连带 |
|---|---|
| 3 个 motion token（`--curveFastOut` / `--curveLinear` / `--durationSlow`） | 撞 `tests/test_web_backend_misc.py:158,160,165` 三条字面量断言，需同步删 |
| `.elevation-*` 6 个类 | 撞 §21 |

**`.content-dialog` 前置条件 ✅ 已实测解决**：`web/style.css:1376-1382` 的 `.content-dialog`
**直接声明** `box-shadow: var(--shadow-128)`，不经 `.elevation-128` 类；
`misc:355` 的断言走 `css[css.find(".content-dialog"): +500]` 切片（`.content-dialog` 首现于 `:1376`，
`var(--shadow-128)` 在 `:1382`，落在窗口内），而 `.elevation-128` 在 `:645` **位于切片窗口之前**。
→ 删 6 个类对该断言零影响。

内存态删除实测（未落盘）：
```
BASELINE    : m158 PASS  m160 PASS  m165 PASS  m156 PASS  m355 PASS
删6类+3token : m158 FAIL  m160 FAIL  m165 FAIL  m156 PASS  m352 PASS  m355 PASS
```
即**恰好 3 条断言会红**（`misc:158/160/165`），删测试即可。

**三条连带同步**：
1. `misc:156` 的 `curveFastIn` 属**巧合存活** —— 它断言的是字面值 `cubic-bezier(0, 0, 0, 1)`，
   而 `--curveFastOut`（`:79`）与 `--curveFastIn`（`:77`）值完全相同。删 `:79` 后 `:77` 仍在 → 断言存活。
   写进 commit message，将来谁删 `:77`，`:156` 会跟着红。
2. `misc:151-153` docstring 写「5 类动画曲线 + 4 时长」，删后为 3 曲线 + 3 时长，需同步。
3. `AGENTS.md` §21 写「6 阴影档 (elevation 1/2/8/16/32/128)」描述的是被删的类，需同步。
   §31 镜像不变量是 **token 级**，删类不触发镜像回归。

**门禁**：`run_all_tests.py` 全绿，重点 `test_v440_ink_skin_css`（27 token 全集）
与 `test_v418_motion_tokens`（删后 3 曲线 + 3 时长）。

### Phase 4 — 文档归档打包

**归档清单**（7 个 docs 文件 + `plans/` 子目录 + `.workbuddy/`）：

- `docs/PLAN-defect-fix-2026-09-27.md`（65.1 KB / 1053 行）
- `docs/PLAN-workflow-split-v5.3.md`（42.1 KB / 401 行）
- `docs/PLAN-think-strip-v5.4.md`（40.9 KB / 577 行）
- `docs/PLAN-splitter-v5.2b.md`（17.6 KB / 397 行）
- `docs/archive/plans/`（8 个文件，178.7 KB）
- `.workbuddy/`（**12 份评审/调研文档 264 KB**，`plans/` + `reviews/` + `verifier/`）

**明确保留**：

| 文件 | 理由 |
|---|---|
| `docs/THIRD_PARTY_NOTICES.md` | 用户裁定 —— 唯一的合规权威副本，移走则新增依赖时无出处可查 |
| `docs/PLAN-change-report-v5.5.md` | 用户裁定 —— 未跟踪的待评审功能计划，原地不动 |
| `docs/ROADMAP.md` | 用户裁定 —— **活文档**：`AGENTS.md:199` 定位为"路线图与跨会话待办"，含 42 行 backlog + "明确不做（跨版本共识）"（AGENTS.md 未镜像） |
| `docs/Windows11-设计原则.md` | **自行裁定** —— `THIRD_PARTY_NOTICES.md:590,596` 以它为 Microsoft Learn 内容的出处凭据，归档等于让保留的合规文件自断出处链 |
| `docs/PLAN-deadcode-cleanup-2026-09-28.md`（本文档） | 执行期间需要 |
| 根目录 `AGENTS.md` / `README.md` / `CHANGELOG.md` | — |

**已验证的无风险前提**：

- `build.spec:62-70` 的 `datas` 只有 `('web','web')` 与 `('app/style_profiles/builtin', ...)`，
  **不含 `docs/`** → 归档不影响 exe 发布
- `tests/` 下**零处**读取 `docs/` 文件（所有命中均为 docstring 文字）→ 归档不会让测试变红
- `tests/test_web_backend_deai.py:613-617` 的 id 唯一性清单不含任何被归档文档相关 id

**执行步骤**：

1. **先建 MANIFEST** —— 每个归档文件记录：原路径 / 大小 / 行数 / 一句话摘要 / 为什么归档
2. 压缩包落 **`.local/docs-archive-20260928.zip`**（`.gitignore:24` 已忽略 `.local/`
   → 不把 400KB+ 二进制塞进 git 历史；`docs/` 下无 `*.zip` 规则，放那里会被跟踪）
   > ⚠️ **`.workbuddy/` 的内容只存在于这个 zip 里**（git 历史兜底不了）——
   > 执行完请把 zip 移到仓库外妥善保存
3. 写 `docs/archive/README.md` 归档索引，**必须吸收原 `plans/README.md` 的文件表 + "当前状态"块**
   （否则该层导航二次丢失）；注明 `plans/README.md:28` 的相对链接 `../../CHANGELOG.md` 在 zip 外失效
4. `git rm` 归档清单中的 `docs/` 文件（保留在 git 历史，可 `git checkout 5a46b34 -- <path>` 单文件恢复）
5. `.workbuddy/` 用普通删除（它本就在 gitignore，未入库）
6. **修全部引用**（共 33 处，见下表）
7. `git grep` 全仓确认无残留**路径**引用；重跑 `run_all_tests.py` + `tools/smoke_ui.py` 对比基线

**必须修的引用清单**（Phase 4 步骤 6）：

| 类别 | 位置 | 动作 |
|---|---|---|
| **AGENTS.md** | `:3` 指向 `docs/archive/plans/README.md` | 改指 `docs/archive/README.md` |
| **AGENTS.md** | `:156` 「字段数 32」 | 改「字段数 29」（Phase 1 同步项） |
| **AGENTS.md** | `:170` 「前端层（4 项）」对 5 bullet | 删 marked.js 后正好 4 条，**删除即修复** |
| **AGENTS.md** | `:173` marked.js 条目 | 删除 |
| **AGENTS.md** | `:199-203` 文档索引整块（计划原只列了 `:3`，**漏了整块**） | 重写为只列保留文件 + 归档索引 |
| **README.md** | `:247,248,250` 目录树 3 处 | 同步 |
| **README.md** | `:295` 「共借鉴 23 个」→ 22；`:298` 去 marked.js | Phase 1 同步项 |
| **源码注释 10 处** | `app/utils.py:176,402`；`app/web_backend.py:37,59,586`；`app/processor.py:38,67`；`app/harness.py:17`；`app/novel_splitter.py:39` | 改指 `docs/archive/README.md` 对应条目 |
| **测试 docstring 8 处** | `test_harness.py:5`、`test_harness_split.py:4`、`test_novel_splitter.py:4`、`test_start.py:4`、`test_push_channel.py:4`、`test_think_strip.py:4`、`test_web_backend_deai.py:1212`、`test_web_backend_misc.py:330` | 纯文字，不影响测试，可批量改 |
| **已遗失引用** | `AGENTS.md:103` + `app/harness.py:17` 指向 `.workbuddy/research/agent1-tech-feasibility.md` | **该文件确认不存在** → 标注「已遗失」而非指向压缩包 |
| **THIRD_PARTY（保留文件）** | `:590,596` 指向 `Windows11-设计原则.md` | ✅ 已保留，无需改 |
| **v5.5 计划（保留文件）** | `:5,72,74,75,77,92,347,424,438,451` 指向 ROADMAP / think-strip | ROADMAP 已保留；think-strip 指向改指归档索引 |

---

## 3. 明确挂起（不在本次执行范围）

| 项 | 挂起原因 |
|---|---|
| `timeout` / `chunking_preset` / `\|chunk=` / 旧签名收敛 | **必须原子落地** —— 7 处构造点、7 份复制的 `V416_CFG_FIELDS`、15 处 hash 调用点，中间态是崩溃不是断言失败。且 `\|chunk=` 清理会让全部断点一次性失效。 |
| `ProjectConfig.harness_enabled` | 删则老配置静默从逐条轨掉进整篇轨，需先出迁移方案。 |
| E 组（`_deriveTrack` / `_effectiveChunkPreset` / `presetsByTrack` / `20000` 魔数） | 需先定 Bridge 只读 API。`docs/PLAN-defect-fix-2026-09-27.md` D7 已提出但未决 —— 该文档本次会被归档，**决策记录随压缩包保存**。 |
| `get_distill_status` + `_distill_tasks` | 删则丢掉蒸馏 error 路径的可观测性。 |
| marked.js 章节重排（§8~§20） | 编号断层 + 交叉引用，建议独立 commit。 |

---

## 4. 验证总则

```powershell
python run_all_tests.py          # 全量回归
python tools/smoke_ui.py         # §46 门禁，改侧边栏/布局/被测调用签名后必跑
```

**判定标准**：全量测试通过数**不低于** Phase 0 基线，失败数 == 0；
`smoke_ui.py` 通过数 ≥ Phase 0 基线。

---

## 5. 交付物

- 3 个 commit（Phase 1 / Phase 2 / Phase 3-4，可再按 Phase 4 独立）
- 1 个 tag `backup/pre-cleanup-20260928`
- `docs/archive/docs-archive-20260928.zip` + `MANIFEST.md` + `docs/archive/README.md`
- CHANGELOG.md 一条清理记录
