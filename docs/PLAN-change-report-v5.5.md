# 墨准 v5.5 计划 — 校对反馈闭环三件套（改动报告 / 术语一致性表 / 校对侧 AI 味评分）

> 状态：**待评审**（2026-09-28 起草）
> 基线版本：v5.4.3（commit `5a46b34`）
> 关联：`AGENTS.md` §34/§36、`docs/ROADMAP.md`、`docs/PLAN-think-strip-v5.4.md`（plan 体例参考）

---

## 0. 背景（先诊断，后设计）

### 0.1 现状：本轮校对结束后，用户拿不到任何"这轮干得怎么样"的答案

跑完一轮校对，前端给用户的是：

| 已有 | 载体 | 信息量 |
|---|---|---|
| 运行指标 | `progress-stats` | 文件数 / token / 耗时 / ETA（`ProcessStats`，`utils.py:493`） |
| 逐条改动 | 「改动清单」`<details>` 折叠面板 | **仅 harness 轨**：每条的 status / reason / old→new 预览 |
| 内容差异 | 字符级 diff（`diff-match-patch`） | 原文 vs 结果，高亮变更处 |

**缺的是**：改动量、未采纳率、改动类型分布、"AI 味是升了还是降了"。

`ProcessStats` 只有**运行**指标，零**内容**指标。用户想知道的三件事——"改了多少"、"质量如何"、"是不是过度发挥"——一个都答不上。

### 0.2 现状：两条轨的信息量严重不对等

| | 逐条校对 (harness) | 整篇校对 (rewrite) |
|---|---|---|
| 逐条归因 | ✅ `engine.file_audits` 逐条 audit | ❌ **完全没有** |
| 用户可见 | 改动清单面板（index/status/reason/preview） | 只有 diff 视图 |
| 归因可行性 | 已具备 | 需新增归因机制（见 §9 Phase 2） |

`file_audits` 的单条结构（`app/harness.py:201-219`）：

```python
{
  "index":        int,   # -1 = 整轮级告警条目 (WARN_EDIT_CAP / WARN_RATIO)
  "status":       str,   # OK / SKIPPED_NOT_FOUND / ... / WARN_RATIO
  "reason":       str,   # LLM 自述的改动原因
  "old_preview":  str,   # ≤80 字符
  "new_preview":  str,   # ≤80 字符
  "old_len":      int,   # v5.4.3 F6 专为覆盖率计算而加（不截断）
  "note":         str,   # 可选，如"换行归一"
}
```

**关键观察**：`old_len` 是 v5.4.3 为 `WARN_RATIO`（单条替换 >50% 告警）专门加的，注释写明"拿预览长度算占比会失真"。即：**作者当时已在算覆盖率，但只用于单点告警，没有汇总成报告**。本计划的第一项功能正是把这类已算出的中间量提升为用户可见的产品输出。

### 0.3 现状：术语统一是跨块一致性盲区

`app/templates.py:163-208`（`tech_doc` 模式）已写明术语规范：

> 统一术语和大小写（"API"不要写成"api"、"Api"）
> 混排时在中文和西文之间加空格（"使用api接口" → "使用 API 接口"）

**但这些指令的执行范围是单个 chunk。** 5 万字按 `large=6000` 分 9 块时，chunk 3 与 chunk 7 是两次独立 API 调用：

- `ContextBuilder`（`processor.py:1118`）注入的是**已完成的块文本**（结果），不是**规范约束**（规则）
- 模型看到"前文长这样"，而非"术语表规定必须用 API"——**把确定性的规则问题交给了概率性的模型**
- harness 轨更严重：`TOOL_DISCIPLINE` 7 条纪律（`harness.py:97-111`）中**无一条涉及术语统一**

这是当前架构的结构性盲区，且 `extra_large=50000` 档把单块拉到 5 万字后**不缓解**（反而更依赖模型自律）。

### 0.4 现状：`ai_score_local` 是只用了三分之一的现成资产

`app/ai_score_local.py` 提供 0-100 六维 AI 味评分（权重和恒为 100，34 项测试背书），**目前仅在 DeAI rewrite 步后使用**（`web_backend.py:1196`）。

校对侧完全未接入。而对中文写作者，"改完之后 AI 味是升了还是降了"是核心关切之一。

### 0.5 附带发现：ROADMAP 版本号已与代码脱节（不属本计划范围，仅记录）

`docs/ROADMAP.md` 的 "v5.3 / v5.4 / v6.0" 待办标签与**代码实际版本语义冲突**：

- ROADMAP「v5.3 — docx 深度 + harness 覆盖扩展」↔ 实际 v5.3.0 是**工作流双入口拆分**
- ROADMAP「v5.4 — 校对→DeAI 联动扩展」↔ 实际 v5.4.0 是**思维链剥离**

`docs/ROADMAP.md:148-165` 需重新编号（如 v5.6 / v5.7）并与 AGENTS.md 的版本语义对齐。**本计划不修它**，避免范围蔓延；但实现期间若新增 ROADMAP 条目，**不得再复用已被占用的 v5.3/v5.4 标签**。

---

## 1. 目标与非目标

### 1.1 目标

1. **补上内容指标的空白**：一轮校对结束后，用户能立即知道"改了多少、质量如何、是否过度发挥"。
2. **补上跨块一致性盲区**：让确定性规则（术语表）而非概率模型负责术语统一。
3. **复用现成评分能力**：`ai_score_local` 接入校对侧，且以"校前/校后差值"而非"绝对分"为核心视角。
4. **不破坏既有设计**：新增能力全部走**旁路**（纯新增模块 + 新增字段 + 新增面板），不改动校对核心链路的语义。

### 1.2 非目标（明确不做）

- ❌ **不做校对历史/版本栈** — ROADMAP 长期项 + "校对/DeAI 历史对比"，与本计划重叠但优先级低于反馈闭环；且涉及断点 schema 变更，风险面大。
- ❌ **不给 rewrite 轨做逐条归因** — 需重构整篇重写链路为工具链模式（见 §9 Phase 2），本计划只做规模类统计。
- ❌ **不做自动术语替换** — 与 harness 唯一匹配语义直接冲突（见 §2.3 D3），本计划只做扫描报告。
- ❌ **不改 `compute_prompt_hash`** — 三项功能均不改送 LLM 前的输入内容（§35 同质裁定），理由见 §2.1 D2。
- ❌ **不碰性能优化 P0（前端增量 DOM）** — 独立事项，见 §9。

---

## 2. 方案决策

### D1 功能 1 = 改动统计报告

**决策**：新增纯函数模块 `app/change_report.py`（与 `ai_score_local.py` 同层同纪律），在 `onTaskComplete` 时**单次汇总推送**。

**理由**：

- 数据源**全部已在内存**（`file_audits` + `FileResult.original/corrected`），不需新数据结构
- 汇总放在任务收尾而非每文件完成 → 不进 per-file 热路径
- 报告是"跨文件的聚合视图"，per-file 推送天然做不到（需等全部完成）

**替代方案与否决**：

| 方案 | 否决理由 |
|---|---|
| 逐文件推送统计 | 报告天然是跨文件聚合；逐文件推送会让 N 个文件产生 N 份碎片报告 |
| 落断点持久化 | 见 D3 |
| 上 LLM 做归类 | 违反零成本原则；`reason` 关键词聚类足够 |

### D2 三项功能均不进 `compute_prompt_hash`

**决策**：术语表**不**纳入 `compute_prompt_hash`（即便 Phase 2 注入 prompt 后）。

**理由** — 这是与 §35 `md_strip_before_llm` 的**本质区别**，必须显式记录：

- `md_strip_before_llm`（进 hash，`|ms=`）：改变**送 LLM 前的输入内容** → 属校对生成语义 → 换配置必须重跑
- 术语表（不进 hash）：**只读附加的参考约束**，模型本就可能不完全遵守；把不确定的约束做成断点屏障，会造成「改了术语表 → 全部旧断点失效 → 重跑花 token」而实际结果几乎不变

**但**：若 Phase 2 术语表**为空**，则与不注入完全等价 → 无需失效。若术语表**非空**，为避免"旧结果是用空术语表跑的、现在术语表要求统一"这种错配，采用**温和标记**：报告与文件行显示「本次未应用术语表约束（指纹生成于术语表变更前）」，**不强制重跑**。用户自行决定。

> ⚠️ 术语表当前**不落 ProjectConfig**（见 D4），因此不进 hash 在实现上天然成立。若未来术语表落进 `ProjectConfig`（v2 形态），本决策需重新评估。

### D3 功能 2 = 术语表只做扫描报告，不做自动替换

**决策**：新增 `app/glossary_scan.py`，纯本地扫描偏离规范的出现位置，**复用 `punct_reports` 行号报告通道**，只报不改。

**理由 — 与 harness 核心设计直接冲突**：

`edit_text` 要求 `old_text` 在原文**恰好出现 1 次**，不满足即 `SKIPPED_NOT_UNIQUE` 拒绝应用（`harness.py` 边界 2）。而术语统一恰恰是**同词 N 处同义替换**的场景。

**强行绕过 = 破坏 §36 边界 2「匹配多处时不猜」的设计初衷**，且引入一个新的审计面（哪些词被全局替换了、替换了几处）。

**与项目既有调性一致**：`punct_fix` 四红线（§29）、`md_strip` 四红线（§32）都是"宁可漏报不可误改"。术语扫描沿用同一纪律。

**Phase 3 的 `replace_all` 工具是独立立项**，需重新评估 `MAX_EDITS_PER_ROUND` / `WARN_RATIO` / 审计面板语义。

### D4 术语表存独立 JSON，不进 ProjectConfig

**决策**：`~/.proofreader/glossary.json`，结构 `{entries: [{term, canonical, note?}]}`。

**理由**：

- `last_config.json` 当前已兼负 api_key 存储（`_obf` 混淆），术语表会显著加大可读性负担
- 术语表是**可复用资产**（多份技术文档应共享），与 `style_profiles/` 的产品形态一致（用户维护 → 全局复用 → 喂给 LLM）
- 天然规避 D2 的 hash 问题（不进 `ProjectConfig` 就不在 hash 输入里）

### D5 功能 3 = ai_score 走"差值"视角，且**不落 FileResult**

**决策**：
1. 每文件完成时对 `corrected` 评分（引擎线程内，会话内存态），对 `original` 评分作为基线
2. **两个分数均不写入 `FileResult`**，只挂在引擎的会话内存字典（与 `file_audits` 同生命周期）
3. UI 展示 `原始分 / 校后分 / 差值`，**不做"优秀/一般/差"文字评级**

**理由 — 不落 FileResult**：`FileResult` 会被写入断点并跨会话恢复。`ai_score` 的六维权重与阈值**全部标注"初始拍定值，未做真实样本校准"**（§34，且 v5.4.3 刚加了 `tools/calibrate_thresholds.py` 待跑）。若把分数落盘，一旦后续校准了权重，用户会看到**用旧权重算出的历史分数**被当成权威值展示——这正是 §35 反对的那类错配。**会话内存态天然免疫。**

**理由 — 差值优于绝对分**：

- 绝对分缺基线：`ai_score=62` 是好是坏？无参照
- 差值有诊断力：

| 差值 | 诊断 |
|---|---|
| 明显为正（+10 以上） | 校对应降 AI 味却升了 → 大概率模型把口语"规范化"成书面套话；**建议改用仅本地标点修复** |
| 明显为负（−15 以下） | 理想，校对确实在去 AI 味 |
| 接近 0 | 校对主要是机械修正，对 AI 味无影响 |

**差值为正**是一条**可执行的数据驱动建议**——这是绝对分给不了的。

### D6 报告口径：两轨信息量不对等时，**如实呈现而非拉平**

**决策**：harness 轨给完整报告；rewrite 轨只给规模类（字数变化 + diff 变更块数），并显式标注「本轨无逐条归因」。

**理由**：**拉平 = 制造虚假对等**。rewrite 轨本来就没有归因数据，凑一个"看起来有"的报告是自欺。

这个不对称本身是**产品信号**——报告反复显示「rewrite 轨改动量是 harness 轨的 N 倍但无归因」，用户会自己得出「该用逐条校对」的结论。**工具应呈现真相。**

---

## 3. 目标行为规格

### 3.1 改动报告 — 输出结构

```json
{
  "workflow": "harness",
  "totals": {
    "files_total": 12, "files_changed": 9, "files_failed": 1, "files_cached": 2,
    "char_delta": -847,
    "edits_total": 156
  },
  "status_breakdown": {
    "OK": 142,
    "SKIPPED_NOT_FOUND": 7,
    "SKIPPED_NOT_UNIQUE": 3,
    "SKIPPED_CASCADED": 2,
    "SKIPPED_NOOP": 1,
    "WARN_RATIO": 1
  },
  "adoption_rate": 0.910,
  "warnings_files": 4,
  "reason_clusters": [
    {"label": "错别字/字词误用", "count": 61, "keywords": ["错别字", "误用", "别字"]},
    {"label": "冗余表达", "count": 38, "keywords": ["冗余", "重复", "啰嗦"]},
    {"label": "标点/格式", "count": 29, "keywords": ["标点", "空格"]}
  ],
  "unclassified_reasons": 5,
  "has_attribution": true
}
```

rewrite 轨则：

```json
{
  "workflow": "rewrite",
  "totals": { "...": "...", "diff_hunks": 37 },
  "status_breakdown": null,
  "adoption_rate": null,
  "has_attribution": false,
  "note": "整篇校对为模型重写全文, 无逐条归因; 上述为规模类统计"
}
```

### 3.2 不变量（实现时逐条测试锁定）

**R1 报告为纯派生**：删除报告功能不影响校对结果的**字节级一致**。报告不得反向影响 `corrected`。
**R2 不抛异常**：`summarize()` 对空 audit / 空文本 / 全 SKIPPED 输入均返回合法结构，**不抛**（同 `apply_edits` 纪律）。
**R3 会话内存态**：报告与 `file_audits` 同生命周期，任务结束即失效，**不落盘**（导出除外）。
**R4 口径继承**：`adoption_rate` 的分母口径必须与 `audit_has_warnings`（`harness.py:389-402`）一致——`SKIPPED_NOOP` **不计入未采纳**（它没有丢失任何改动）。
**R5 空输入安全**：`ai_score("")` 返回 `{"score": 0, "dims": {}, "offenders": []}`（`ai_score_local.py:321`）。**score=0 在此语境意为"无 AI 味"而非"评分失败"**，报告与 UI 必须对「原文为空/剥后为空」显式标注，不得显示为"0 分（很干净）"造成误读。
**R6 阈值诚实**：所有新增阈值（关键词分类表、未采纳率告警线）**必须标注"初始拍定值，未做真实样本校准"**，遵守 §34 口径。**严禁**在文档/注释中编造"实测平均 N"之类来源（v5.4.3 F10 同纪律）。

### 3.3 边界表 — 改动报告

| # | 输入 | 输出 | 说明 |
|---|---|---|---|
| B1 | `audit=[]`（rewrite 轨） | `status_breakdown: null`, `has_attribution: false` | 不是"0 条改动"，是"无归因数据" |
| B2 | 全 `SKIPPED_*` 且无 `OK` | `adoption_rate: 0.0` + `warnings_files += 1` | 正常可达态（全失败已由调用方判 FAILED） |
| B3 | 含 `index=-1` 的 `WARN_*` | 计入 `status_breakdown`，**不计入** `edits_total` | 整轮级条目不是单条编辑 |
| B4 | `original=""` | `char_delta` 只算 corrected 侧，标注"原文为空" | R5 同源 |
| B5 | 文件失败/取消 | 不进 `status_breakdown`，只进 `files_failed` | 无 audit 可统计 |
| B6 | 缓存命中文件 | 不进报告（无本轮 audit），在 `files_cached` 计数 | 同 §36 audit 语义 |
| B7 | 混合两轨历史结果 | 只统计**本轮** `workflow` 的文件 | 报告带 `workflow` 字段，跨轨结果不混算（§41 同质） |

### 3.4 边界表 — 术语扫描

| # | 输入 | 输出 | 说明 |
|---|---|---|---|
| G1 | 术语表为空 | `{hits: [], scanned: N}`，不报错 | 冷启动合法态 |
| G2 | `term` 含正则元字符（`.` `*` `(`） | 按**字面量**匹配 | **必须转义**，否则 `C++`/`.NET` 会炸 |
| G3 | `canonical == term` | 跳过该条 | 无意义的约束 |
| G4 | 命中在代码围栏内 | **跳过，不报告** | 沿用 `md_strip`/`think_strip` 围栏纪律；术语约束不该管代码 |
| G5 | 同一行多次命中 | 全部报告（行号 + 全部列偏移） | 一次校对多个错都在一行是常态 |
| G6 | `canonical` 本身也含 `term` 子串 | 只报不构成"包含关系"的命中 | 避免 `API` 命中 `API Key` 造成噪音 |
| G7 | 超大文件（>5 万字） | 正常扫描，不截断 | 扫描是纯本地 O(n)，无模型成本 |

### 3.5 边界表 — 校对侧 ai_score

| # | 输入 | 输出 | 说明 |
|---|---|---|---|
| S1 | `corrected` 为空（剥后为空/取消） | 不评分，标 `null` | 空串评分=0 会被误读为"干净"（R5） |
| S2 | 本地模式（`punct_local`/`md_local`） | **仍评分**并展示 | 这是最有说服力的对照组：纯机械修正对 AI 味的影响 ≈ 0 |
| S3 | 缓存命中 | 展示基线分，差值标 `null` | 无本轮 corrected 可评 |
| S4 | 极长文本（>5 万字） | 正常评分，**记录耗时** | 双重评分 = 2× 本地 CPU；见 §6 R-3 |
| S5 | 分数相同 | 差值显示 `±0` | 不隐藏"没变化"这个信息 |

---

## 4. 逐模块变更清单

### 4.1 新增 `app/change_report.py`（约 200 行）

```
summarize(audit_all: dict[str, list[dict]],
          tasks: dict[str, FileTask],
          workflow: str) -> dict

# 内部：
#   - 遍历 audit_all, 分离 index>=0 (单条) 与 index<0 (整轮级)
#   - status 计数, adoption_rate = OK / (总数 - NOOP)
#   - char_delta = sum(len(corrected) - len(original)) for changed files
#   - reason 聚类: 关键词表匹配 (R6: 标注未校准)
#   - rewrite 轨: has_attribution=False, 仅规模类
```

**模块纪律（照 `ai_score_local.py`）**：

- 纯函数，无 IO，无 GUI，不 import openai/webview
- 不抛异常（R2）
- 阈值常量集中定义 + 标注未校准

### 4.2 新增 `app/glossary_scan.py`（约 150 行）

```
load_glossary() -> list[dict]              # 读 ~/.proofreader/glossary.json
save_glossary(entries) -> bool
scan(text: str, entries: list[dict]) -> dict
  # -> {"hits": [{"line": 142, "col": 8, "found": "apikey", "canonical": "API Key"}],
  #     "scanned_chars": N}
```

**模块纪律**：同上 + 围栏判定复用 `app/think_strip.py:40` 的 `_FENCE_CLOSE_RE` 同口径（**不重新实现一份围栏逻辑**）。

### 4.3 `app/web_backend.py`

| 位置 | 变更 | 风险 |
|---|---|---|
| `_collect_results` 收尾 | payload 追加 `"change_report"` | 低 |
| `onTaskComplete` 推送 | 同上（`_collect_results` 是唯一出口） | 低 |
| `onFileDone` payload | 追加 `"ai_score": {"before":…, "after":…, "delta":…}` | 低 |
| 新增 `get_glossary()` / `save_glossary()` | 术语表 CRUD | 低 |
| 新增 `scan_glossary(file_key)` | 复用 `punct_reports` 通道模式（`web_backend.py:638`） | 低 |
| `_collect_punct_reports` 附近 | 术语报告的推送点 | 低 |

**注意**：`_file_done_payload`（`web_backend.py:667`）**保持不动**——ai_score 走 engine 内存字典，在 payload 组装时读取，不改 `FileResult`。

### 4.4 `app/processor.py`

- `_process_file_async` 成功收尾处：对 `corrected` 与 `original` 各调一次 `ai_score_local`，存入 `self.file_ai_scores: dict[str, dict]`
- **不写 `FileResult`**（D5）
- 新增 `self.file_ai_scores: dict[str, dict] = {}`，与 `file_audits` 同生命周期（`prepare_tasks` 重置 / `_call_api_stream` 整文件重试时 pop，D36 同款）

### 4.5 前端 `web/index.html` + `web/app.js`

- 进度区下方新增「本轮报告」`<details>` 面板（复用 `.audit-*` 样式类）
- 术语表编辑面板（放「校对参数」页）
- 术语命中报告（复用 punct 报告的呈现模式）
- 文件行 ai_score 徽标（差值为正时用警告色）

**不改**：现有元素 id（§38 约定），`renderCompare` 增量分支不动。

### 4.6 文档

- `AGENTS.md` 加 §53/§54/§55 三条编号决策
- `README.md` 特性列表
- `CHANGELOG.md`
- `docs/ROADMAP.md`（新版本号，**不得复用 v5.3/v5.4 标签**）

---

## 5. 测试清单

照 `run_all_tests.py` 自动发现（`tests/test_*.py`），无 pytest 依赖。

### 5.1 `tests/test_change_report.py`（新建）

- 边界表 B1–B7 **逐条**
- 不变量 R1（报告不影响 corrected 字节）— 断言 `summarize` 前后 `FileResult.corrected` 哈希一致
- R4 口径：构造含 `SKIPPED_NOOP` 的 audit，断言 `adoption_rate` 分母**排除** NOOP
- R5 空输入：断言返回结构合法且 UI 展示层有"原文为空"标注路径
- R6 静态断言：新增阈值常量必须带未校准注释（**仿 `test_ai_score.py` 的权重和=100 断言**）
- 混合成功/失败/缓存命中/取消 四类文件的混合输入

### 5.2 `tests/test_glossary_scan.py`（新建）

- 边界表 G1–G7 **逐条**
- **G2 专项**：术语表含 `.NET` / `C++` / `a*b` / `(` 等元字符，断言不抛且不误匹配
- 幂等性：扫描是只读操作，跑两遍结果一致
- 围栏保护：代码块内的偏离写法**不报告**
- 围栏 CRLF 专项（`think_strip` 复审 V2 同款坑：`rstrip("\r")`）

### 5.3 扩展 `tests/test_web_backend_proofread.py`

- `onTaskComplete` payload 含 `change_report`，字段集完整
- `onFileDone` payload 含 `ai_score`，R5 边界 S1/S2/S3 逐条
- 缓存命中文件不污染报告计数（B6）
- 混合两轨历史结果只算本轮（B7）
- **回归**：报告存在时校对结果与 v5.4.3 字节一致（R1 端到端）

### 5.4 UI 冒烟

`tools/smoke_ui.py` 跑三视口（1440/1280/1000），断言新面板不挤破两栏布局。

### 5.5 门禁

`run_all_tests.py` 全量通过（当前基线 **1900 passed / 0 failed**，本计划后应 ≥ 1950）。

---

## 6. 风险与缓解

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R-1 | 报告口径与 `audit_has_warnings` 漂移 | 中 | R4 不变量 + 边界测试锁定；两处口径**同源引用**而非各写 |
| R-2 | 双重评分拖慢长文件 | 中 | S4 记录耗时；若 >200ms/万字则改为按需惰性评分（前端点击时算） |
| R-3 | `ai_score_local` 正则在超长文本上退化 | 中 | 借鉴 v5.4.2 F7「链接正则二次爆炸」教训，**必须实测** 5 万字耗时并加测试；必要时复用现有 `_EMOJI_RE` 等已优化正则口径 |
| R-4 | 术语表 UX 冷启动（空表） | 低 | G1 空表合法 + 后续版本做 LLM 提取（本计划外） |
| R-5 | 前端新增面板挤破布局 | 低 | UI 冒烟三视口断言 |
| R-6 | 报告/分数被误读为权威评级 | 中 | R6 阈值诚实 + D5 禁止文字评级 + 显式标注来源与口径 |
| R-7 | 范围蔓延到 rewrite 归因 | 中 | §1.2 明确非目标；rewrite 只做规模类 |

---

## 7. 依赖顺序（3 个 Session）

**Session 1 — 改动报告**（含 ai_score 接入）

1. `app/change_report.py` + `tests/test_change_report.py`
2. `processor.py`：加 `file_ai_scores` + 双评分
3. `web_backend.py`：两处 payload 追加
4. 前端报告面板 + 文件行徽标
5. UI 冒烟 + 全量测试

**Session 2 — 术语表（阶段 1+2）**

1. `app/glossary_scan.py` + `tests/test_glossary_scan.py`
2. `web_backend.py`：CRUD + 扫描推送
3. 前端术语表面板 + 命中报告
4. **阶段 2**：`GLOSSARY_DISCIPLINE` 注入 system prompt（仅非空术语表时）
5. UI 冒烟 + 全量测试

**Session 3 — 文档回填 + 校准**

1. AGENTS.md §53–§55 / README / CHANGELOG / ROADMAP
2. 跑 `tools/calibrate_thresholds.py`（拿真实语料校准 §34 阈值 + 本计划 R6 阈值）
3. 校准结果回填，删除"未校准"标注

> **Session 3 的校准是计划的一部分，不是可选后续。** §34 已把阈值标注为"待校准"，本计划新增了同类阈值，不校准就又多一批未验证数字。

---

## 8. 完成定义（DoD）

- [ ] `run_all_tests.py` 全量通过，**零新增 skip**
- [ ] 边界表 B1–B7 / G1–G7 / S1–S5 全部有对应测试
- [ ] 新增阈值全部带"未校准"标注（R6）
- [ ] `tools/smoke_ui.py` 三视口通过
- [ ] AGENTS.md 新增编号决策，README/CHANGELOG/ROADMAP 同步
- [ ] 校准器跑过真实语料，R6 标注已回填
- [ ] **校对结果与 v5.4.3 字节级一致**（本计划纯旁路，不得改变任何校对输出）

---

## 9. Phase 2 候选（不在本计划，立项需单独评审）

| 项 | 说明 | 为什么不在本计划 |
|---|---|---|
| rewrite 轨逐条归因 | 需把整篇重写也改造成工具链 | 改动核心链路，性质是 v5.3.0 级别的重构 |
| 术语表 LLM 提取 | 挂 tech_doc 检测顺带输出术语候选 | 依赖术语表先落地并被使用 |
| harness `replace_all` 工具 | 全局同词替换 | 需重设计 `MAX_EDITS_PER_ROUND` / `WARN_RATIO` / 审计语义 |
| 校对历史档案 | 跨任务累积报告 | ROADMAP 长期项；需落盘 + schema 变更 |
| 前端增量 DOM（P0 性能） | `app.js:2038` 全量 innerHTML | 纯性能项，与本计划正交 |

---

## 10. 待确认事项（需评审拍板）

1. **ai_score 是否在 `punct_local` / `md_local` 模式也展示**（S2）？
   倾向：是。纯机械修正对 AI 味的影响 ≈ 0，是最干净的对照组，能反衬 AI 校对的真实增益。
2. **术语表条目是否需要"作用域"**（仅某目录生效 / 全局）？
   倾向：v1 不做，全局。作用域会让扫描与报告逻辑复杂化，收益不明。
3. **报告是否落盘可选持久化**？
   倾向：v1 只做导出 Markdown，不做历史存储（呼应 §1.2 非目标）。
