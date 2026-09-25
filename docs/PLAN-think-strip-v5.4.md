# 墨准 v5.4 思维链剥离 (think block strip) — 实施计划 (v2.1 · 两轮审计后修订)

> 状态: **两轮审计完成 · V1/V2 已修订 (待复审确认后开工)**
> 基线: `master @ cc2617c` (v5.3.1) — 回归 1463 通过 / 0 失败, 冒烟 91 项 / 0 失败
> 入库: v1 `68f3030` / v2 `1aaf60b`; 本文已并入两轮审计的全部阻塞项 (B1-B5 + V1/V2) 与采纳的非阻塞建议 (见 §13)
> 本计划只做一件事: **模型输出的思维链一律丢弃, 不进任何用户可见结果**

---

## 0. 四条前提 (v2 已按审计修正口径)

### 0.1 现状: 代码目录零处理

代码目录 (`app/` `web/` `tests/` `tools/` `main.py` `start.py`) 检索 `think|thinking|reasoning_content|reasoning`:
**零命中**; 文档层另有 `CHANGELOG.md:72` (v5.1.0 烟测结论) 与 `AGENTS.md:189` / `docs/ROADMAP.md:10-17`
(计划索引) 及本计划自身。
全仓也**没有** `max_tokens` / `reasoning_effort` / `thinking` 参数: 参数 rg 零命中, `processor.py:812`
注释另证 `max_tokens` 从前完全静默。

当前不出事, 靠的是两个巧合:

1. **harness 路径压根不读 `message.content`** — `app/processor.py:909-910` 只把 `message` 交给
   `app/harness.py` 的 `parse_tool_calls()`, 该函数只遍历 `message.tool_calls`。
2. **主流厂商把思维链放独立字段** (`reasoning_content` / `reasoning`), 而四条流式链路都只取
   `delta.content` (`app/processor.py:798`; `app/web_backend.py:1075` / `:1303` / `:1693`), 等于天然丢弃。

两个巧合都不覆盖"内联式思维链" (§0.2 第 3 类)。

### 0.2 会漏的是"内联式"思维链 — 四形态矩阵 (v2 按路径限定)

| # | 形态 | 代表 | 今天的结果 (按路径) |
|---|---|---|---|
| 1 | 独立字段 `reasoning_content` | DeepSeek-R1 系 / Kimi / GLM thinking | 不进结果 (只读 `content`); 本版升级为显式契约 + 测试锁死 (D7) |
| 2 | 独立字段 `reasoning` / `reasoning_details` | OpenRouter 归一化格式 (含 `redacted_reasoning`) | 同上 |
| 3 | **内联成对标签** `<think>…</think>` | MiniMax M2/M3 部分端点、部分自建 Qwen/GLM、把 reasoning 合并进 content 的中转网关 | **整篇校对轨 + DeAI 会整段进入 `corrected`** (harness 轨不受影响: content 不参与结果) |
| 4 | 内联无标签 | 少数端点直接拼接 | 无标记可切, 只能靠 prompt 约束; 不做 |

第 3 类的污染面 (限整篇轨 / DeAI):
`corrected` → 字符级 diff 右栏 → 「复制」→ 「导出」→ 断点落盘 → 「→ 去AI味」送去改写 → `ai_score_local` 当正文打分
→ DeAI 蒸馏把思维链当风格样本。

**本计划覆盖第 3 类**; 第 1/2 类从"隐式不读"升级为"显式契约 + 测试锁死" (D7); 第 4 类不做。

### 0.3 既有后处理链路不会替我们清 (已实测)

- `strip_markdown("前言\n<think>推理</think>\n\n# 标题\n正文 **加粗**")`
  → `"前言\n<think>推理</think>\n\n标题\n正文 加粗"` — 标签与内容**原样保留**
  (`app/md_strip.py:27` 的既定原则: HTML 标签不动; 审计实跑复核)。
- `ai_score_local` (`app/ai_score_local.py:318`) 把思维链当正文打分。
- 前端只渲染 diff, 没有任何折叠/隐藏思维链的渲染分支。

所以"靠 md_strip / 评分 / 前端兜底"不成立, 必须在产出侧剥离。

### 0.4 已知边界 (本版不处理): harness 的静默 no-op

`app/processor.py:917-918` 在 `edits` 为空时 `corrected = 原文`, `:950-951` 记
`[harness] <file>: 模型未提交编辑 (无需修改)` 并**判成功**; `:941-942` 存空 audit;
`audit_has_warnings([])` = False (`harness.py:291-304`) → 判 COMPLETED。
`TOOL_DISCIPLINE` (`harness.py:107`) 规定"全文没有错误时回复**无需修改**", 所以 `0 tool_calls` +
正文在正常场景是**合法路径** (`tests/test_harness.py:399-412` 已锁)。

真正的静默风险只发生在窄场景: **服务端接受 `tools` 参数但模型不产生 tool_calls / 把编辑写进 content**
(端点完全不支持 tools 时通常直接抛 `BadRequestError` → `processor.py:567-573` 立即 FAILED, 不是静默 no-op)。
v1 曾计划附一条 `WARN_EDIT_IN_CONTENT` 收口, **审计裁定移出本版** (B4: 与思维链无因果、判据无真实样本、
引入误报面且占一个 session) → 移入 §9 Phase 2。本版只把它留作已知边界。

---

## 1. 目标与非目标

### 目标

- **G1** 内联思维链块一律丢弃; 需要接线的两条链路全闭环: **整篇校对 (流式)** / **去 AI 味 (分块 + revise + 蒸馏)**。
  harness 轨不进 results 的原因 (content 不参与) 由负向测试锁死, 不接线。
- **G2** 流式预览**不闪现**思维链, 且满足不变式: `累计 take + flush == strip_thinking(原文输出)`
  (前端增量渲染依赖"累计文本前缀单调", 见 `web/app.js:1777-1778` 与回缩保护 `:1934-1935`)。
- **G3** 独立字段形态 (`reasoning_content` / `reasoning`) 显式不进入结果, 并有测试锁死。
- **G4** 剥离可观测: 每次剥离记一条日志 (块数 + 字符数), 独立字段按帧计数 (debug), 不做静默删除。

### 非目标

- **N1** 不做思维链展示面板 / 不落档 (用户明确"直接丢")
- **N2** 不加"保留思维链"开关 (Phase 2 候选, §9)
- **N3** 不改 prompt、不改请求参数 (不引入 `max_tokens` / `reasoning_effort` / `thinking` 字段)
- **N4** 不碰断点 schema 与 `compute_prompt_hash` (旧断点走定向失效, 见 D9)
- **N5** 不改前端渲染逻辑 (UI 零新增元素; 只在 `tools/smoke_ui.py` 增加一条端到端断言)

---

## 2. 决策表 (v2)

### D1 新建单点模块 `app/think_strip.py` (纯函数 + 增量过滤器, 无 IO 无 GUI)

与 `app/md_strip.py` / `app/punct_fix.py` 同层同纪律。对外暴露:

```python
THINK_TAGS = ("think", "thinking", "reasoning", "thought")  # D2, 小写

def strip_thinking(text: str) -> str:
    """一次性剥离 (非流式路径 / flush 基准 / 测试基准)。"""

class ThinkFilter:
    def feed(self, delta: str) -> None: ...   # O(len(delta)) 追加, 不计算
    def take(self) -> str: ...                # 在节流点求值, 返回"新增可显示文本"
    def flush(self) -> str: ...               # 收尾 (eof 语义), 幂等

def has_think_residue(result) -> bool:
    """D9: 扫断点 corrected / chunks_results 是否含行首白名单开标签。"""
```

- **理由**: 两条链路 4 处接线必须共用同一份语义, 否则必然漂移 (v4.1.8.1 审计 C2 就是"两处派生不一致"的教训)。
- **否**: 在 `processor.py` / `web_backend.py` 各写一份 (4 份重复, 改标签集合必漏);
  **否**: 扩展 `md_strip` (它的契约是 Markdown 装饰, 且明确保留 HTML 标签 — 语义冲突)。

### D2 标签集合: `think` / `thinking` / `reasoning` / `thought` (v2 缩表)

- 大小写不敏感; 标签名后可跟属性; **只剥白名单**, 其余 `<foo>` 一律不动。
- `analysis` **移入 Phase 2** (审计 R-A: `<analysis>` 在 Web Components / 前端教程里是合法自定义元素,
  "有真实端点使用"的证据等级低于前四个词; 误删面更宽)。
- **否**: `scratchpad` / `<|think|>` / `<|begin_of_thought|>` 等变体 — 无本仓库证据, 入 Phase 2。

### D3 剥离范围: 行首规则 + 围栏豁免 + 未闭合丢弃 + 头部清理 (v2 改判 B1)

**剥**:

1. 成对块 `<tag …>…</tag>`: 开标签位于**行首** 且位于围栏外; 闭标签同名 (大小写不敏感);
   同名嵌套按深度计数配对, 外层整块丢弃。
   **行首 (v2.1 钉死, 复审 V1)**: 在**已剥离的可见文本**中, 该 `<` 之前同一行内只有空白 —
   已剥除区段视为不存在, 头部级联块按同一口径递归。于是 `<think>a</think><think>b</think>正文`
   的第二个块也算行首 (剥除第一块后, 其前只剩行首空白)。
2. 流结束时仍未配对的块 → 从开标签起**整段丢弃**; 块处于头部时连块前空白一并丢 (与 D3-3 一致),
   正文中间的未闭合块只丢块自身起的部分 (截断场景: 模型还在思考, 没来得及输出正文)。
3. **头部块清空白**: 若首个块之前只有空白 (即块处于头部), 剥块时连同"块前空白 + 块后连续空行"一并丢弃
   (保留第一个非空行的行首缩进); 块在正文中间时只剥块本身, 不动前后换行。

**不剥**:

4. 围栏代码块 (```` ``` ```` / `~~~`) 内的一切 (含围栏行本身) — 围栏只"保护", 从不删除。
   **围栏行判定同样走可见文本坐标** (行内可见前缀仅 0-3 个空格); 行尾先 `rstrip("\r")` 再判定
   (复审 V2: md_strip 的闭围栏正则不含 `\r`, 直接照抄会让 CRLF 文本的围栏永不闭合 → 之后整段漏剥)。
   **块内不感知围栏** — 块配对只数同名标签, 围栏行/围栏内的标签既不开启也不闭合块。
5. **非行首的标签** (行内提及、行内反引号内、正文同一行中间的块) — v2 不再感知反引号配对 (见下)。
6. 白名单外标签。

**B1 反例与修法 (本版最关键的设计改判)**: v1 的"行内反引号豁免"依赖反引号 run 的跨 delta 配对,
而配对可被后续 delta 翻转 → 审计复现打穿反例: deltas = `["` + "<think>secret</think>TAIL", "`"]`,
第一帧已产出 `` "`TAIL" ``, 而最终 `strip_thinking` 应为整段原样 → 已 emit 文本不是最终结果前缀,
前缀单调与不变式不可兼得。

v2 砍掉该豁免, 改用**行首规则**: 判定只依赖"该 `<` 之前同一行内是否只有空白" — 这是**已消费字符的单调性质**,
新 delta 只能追加, 不可能在已消费标签之前插入非空白字符, 因此任何已消费标签的"是否可剥"判定**永久稳定**,
前缀单调不变式因此成立 (这是 D4 安全前缀策略的地基)。

**代价 (明写)**: ① 正文同一行内的块 (如 `前言<think>…</think>`) 不剥 → 产生肉眼可见脏结果, 用户可强制重跑;
② 跨越换行的行内 code span 里、恰好位于行首的标签会被误剥 (概率低, 见 §7 R2)。
**否**: 保留 v1 行内豁免 (需要额外的"反引号 run 悬置", 复杂度与回归面更大);
**否**: 全量剥 (会吃掉文档里合法的行内 `<think>` 提及)。

### D4 流式: 安全前缀重算 + 惰性 take (v2 修 B1/B2)

API 从 v1 的 `feed(delta) -> str` 拆成 append 与求值两步 (见 D1), 求值只在既有节流点发生。

每次 `take()`:

1. `visible, hold = scan(raw, eof=False)` — 对**全量 raw** 重算, 只取 hold 之前的稳定区。
2. 返回 `visible[len(emitted):]`, 更新 `emitted`。

**scan 的 hold 必须覆盖全部"可被未来输入改写"的位置, 共三类 (v1 只列了第 2、3 类)**:

| # | 悬置来源 | 说明 |
|---|---|---|
| H1 | **头部未定** | 尚未产出任何字符时, "头部空白 + 可能的头部块 + 后继空行"尚未落定: 块前空白可能被清、块后空白行可能继续延长。v1 未列此项, 是 §3.3 不变式的隐性破口 |
| H2 | **未闭合块** | 围栏外、行首 (可见文本口径, 见 D3-1) 的合法白名单开标签尚无配对闭标签 → 从开标签的 `<` 起全部悬置 (块内 + 其后), 等闭标签或 flush |
| H3 | **行首半截标签** | 围栏外、行首 (同一可见文本口径) 存在"可能是白名单开标签"的未完成标签 (`<` / `<thi` / `<think foo="1"`) → 从 `<` 起悬置 |

> **V1 复现 (复审实跑)**: 若 H3 用"原文行首"而剥离用"可见文本行首",
> deltas = ["<think>a</think><thi", "nk>b</think>正文"] 第一帧会 emit `<thi`, 最终结果 `正文` →
> 前缀单调与不变式同时破。两处必须同坐标; 钉死后复审跑了 637 例全切点/全前缀 property 测试 0 破例。

**明确不悬置** (这些位置永远不会被剥, 提前产出安全):

- 非行首的半截标签 (即使后续补全, 也不满足行首规则);
- 围栏标记 / 围栏内容 (围栏从不删除文本, 围栏态歧义只影响"未来"的剥除判定, 不会回溯已产出文本);
- 白名单外标签; 行内反引号内的标签 (已无豁免逻辑, 靠行首规则天然保护)。

**flush() (B2 修法)**:

- `final = scan(raw, eof=True).visible`; 返回 `final[len(emitted):]` — 即
  "`strip_thinking(raw)` 与已 emit 的**差额**";
- **裸半截标签按字面补齐** (`<thi` → `<thi`, 不静默删内容);
- **围栏豁免优先于未闭合丢弃** (围栏内的未闭合标签原样保留, 例: 未闭合围栏内 `<think>x` → 原样);
- 围栏外未闭合块整体丢弃; 第二次 flush 返回 `""` (幂等)。

**不变式 (测试锁定)**: `"".join(take 序列) + flush() == strip_thinking(raw)`; 且累计 take 单调前缀延长。

**性能口径**: `take()` 是 O(len(raw)) 全量重算, 所以**只在既有节流点调用**
(processor 5 token/50ms → `processor.py:803-810`; DeAI 50ms → `web_backend.py:1079-1081` 等),
调用频率被 UI 节流钳制; 50K 文本单次 < 200ms 为 DoD (v1 的 50ms 断言太紧, 采纳审计建议放宽)。
**否**: 字符级状态机 (状态多、跨帧 bug 面大、两处实现易漂移)。

### D5 剥后为空 → 复用"空输出"语义 (不变)

- 整篇轨: `corrected` 为空判据 (`processor.py:825-827`) 改为**剥后**为空; 错误文案区分"仅含思维链, 无有效输出"。
- DeAI: 分块空块判据 (`web_backend.py:1086-1087`) / revise (`:1317-1318`) 改剥后判空;
  **蒸馏收尾是新增判据** (复审: 该路径现无任何空判据, 空/纯思维链卡会被直接落盘) —
  剥后为空 → 推 `onDeaiError`, 空卡不落盘。
- 截断标记 (`:829-834`) 先记录再走 raise, 维持 v5.3.0 语义。
- **理由**: 复用一个已经验证过的失败/重试路径, 不新增语义。

### D6 (v1 的 harness `WARN_EDIT_IN_CONTENT`) → 移出本版 (B4)

见 §0.4 已知边界; 实现项、用例、session 一并移入 §9 Phase 2。

### D7 独立字段: 不进入结果 + 存在性可观测 (v2 加 R-E 兜底)

- `reasoning_content` / `reasoning` / `reasoning_details` 一律**不进入** corrected / 前端 / 落盘;
  新增负向测试: 造带这些字段的假 delta, 断言结果不含其内容。
- 可观测 (采纳审计 R-E): 若 delta 携带上述字段且非空, 只累加"出现帧数", 收尾时 debug 级记一行
  `[思维链] <文件>: 忽略独立字段 N 帧` (**不含内容**)。
- **理由**: 把今天"因为没写代码所以没漏"变成"有测试证的显式行为", 且厂商换字段名时用户侧可发现。

### D8 DeAI 三处接线 + 消费点不变式 (B3)

顺序固定为 **think_strip → md_strip → ai_score**。

**不变式 (写死)**: **DeAI 只保留剥后累积器; raw 仅存在于 ThinkFilter 内部**。
即接线时把 `chunk_out += content` / `out += content` / `partial += content` 换成经过滤器的累积,
**不是只在 push 点过滤**。这样以下 6 组下游消费点自动干净 (审计逐条核出的漏列, 本版全部覆盖):

| 消费点 | 行号 |
|---|---|
| 块间衔接 prompt `partial[-400:]` | `app/web_backend.py:1052` |
| 错误 payload `_deai_preview(partial)` + 落盘 | `:1099-1101` |
| 取消 payload + 落盘 (前端取消时展示) | `:1127-1131` (`web/app.js:2885-2886`) |
| 超长降级落盘 / 预览 | `:1150-1154` |
| `ai_score_local` 输入 | `:1200` / `:1243` |
| style-card 落盘 + 收尾帧 | `:1727-1729` |

接线点: `:1074-1080` (detect/rewrite/score 共用的分块流) / `:1302-1308` (revise 轮) / `:1692-1702` (蒸馏)。
蒸馏路径**要剥** (审计 R7 裁定采纳: style-card 是后续全部改写的长期风格样本, 思维链入卡是长期污染;
教学示例通常天然落在围栏/行内码里, 由 D3-4 保住)。

### D9 不动断点 hash/schema + 定向失效 (采纳审计建议)

- `compute_prompt_hash` 不加版本位, `schema_version` 保持 2。
- **定向失效 (新增, v2.1 收敛)**: `has_think_residue(result) := strip_thinking(result.corrected_full) != result.corrected_full
  and strip_thinking(result.original) == result.original` — 单点口径 (复审建议: 直接复用 `strip_thinking`,
  自动继承围栏豁免, 不写第二套"行首"实现); 命中 → 记日志
  `[思维链] <文件>: 旧断点含思维链残留, 忽略缓存强制重跑` + 按未命中处理 (`processor.py:283-291` 之间)。
  零 LLM 成本, 只烧脏文件。
- **边界 (复审新增)**: 原文**自身**含行首块的语料不强制重跑 (否则 harness 轨 `corrected=原文` 会永久打不中缓存,
  每次开始都重烧 token) — 由 `strip_thinking(original) == original` 条件排除; CHANGELOG 照写症状。
- 出口保留: 手动强制重跑 (v5.3.0 已就位); CHANGELOG 写**症状** (`结果里出现 <think>` / 推理段落) 与处理。
- **否**: `|ts=1` 让全部历史断点一次性失效 — 用户已校对过的每个文件都要重新烧一遍 token,
  代价远大于收益 (与 v5.3.0 `|wm=` 不同: 那次是**轨道正确性**, 必须失效)。

### D10 可观测: 日志 (v2 加独立字段计数)

- `[思维链] <文件名>: 丢弃 N 块 / M 字符` (N=0 时不打, 避免噪音)
- `[思维链] <文件名>: 忽略独立字段 N 帧` (debug 级, D7)
- 不改 UI 布局, 不加统计面板。

---

## 3. 目标行为规格 (边界逐条)

### 3.1 块的定义 (v2.1)

- **开标签候选**: 行首 + `<` + 白名单标签名 + 可选属性 + `>`, 且位于围栏外。
  **行首 = 已剥离可见文本中, 该 `<` 之前同一行内只有空白** (已剥除区段视为不存在; 头部级联块同口径递归 — 复审 V1 钉死)。
- **闭标签**: `</` + 同名 + 可选空白 + `>`; 大小写不敏感; 属性值内部的 `>` / `</tag>` 字样不算边界
  (词法扫描跳过引号内内容 — 审计已证 naive `[^>]*` 扫描会在该处漏出残留)。
- **配对**: 必须同名; 同名嵌套按深度计数只配到最外层; 不同名闭标签不构成配对 (该块按未闭合处理)。
- **围栏**: 与 `app/md_strip.py` 的围栏规则同口径 (行首 ```` ``` ```` / `~~~`, 闭围栏长度不小于开围栏),
  但**行尾先 `rstrip("\r")`** (复审 V2 修: 否则 CRLF 文本围栏永不闭合); 围栏行判定走可见文本坐标;
  围栏内全文 (含标签、含未闭合标签) 原样保留; 块内不感知围栏 (配对只数同名标签)。

### 3.2 边界表 (测试逐条覆盖; 流式一致性另由 §6.1 全切点遍历锁定)

| # | 输入 | 期望输出 |
|---|---|---|
| T1 | `<think>a</think>正文` | `正文` |
| T2 | `<THINK>a</THINK>\n\n正文` | `正文` (大小写不敏感 + 头部块后空行清理) |
| T3 | `<think foo="1">a</think>正文` | `正文` (带属性) |
| T4a | `<think>a</think><think>b</think>正文` | `正文` (头部连排: 剥除第一块后第二块仍在可见文本行首 — 复审 V1 口径) |
| T4b | `前言\n<think>a</think><think>b</think>正文` | `前言\n正文` (正文中间连排, 同口径; 复审 V1 新增) |
| T5 | `前言<think>a</think>正文` (同一行, 非行首) | 原样 (行首规则; v1 曾定"剥", 已改判) |
| T6 | `前言\n<think>a</think>\n正文` (行首, 正文中间) | `前言\n\n正文` (只剥块, 不动前后换行) |
| T7 | `  <think>a</think>正文` (行首带缩进, 头部) | `正文` (头部块 + 前导空白一并清) |
| T8 | `<think>a` (EOF 未闭合) | (空) — 整段丢弃 |
| T9 | `<thi` (EOF 裸半截标签) | `<thi` (按字面补齐, 不静默删内容) |
| T10 | `<think>a</thinking>正文` (闭标签不同名) | (空) — 开标签有效、未配对 → 按未闭合整段丢弃; v1 此条期望"原样", 与 D3-2 自相矛盾, v2 统一 |
| T11 | 围栏块内含 `<think>样例</think>` (固定件 F1) | 原样 (围栏内不剥) |
| T12 | 未闭合围栏 (`` ``` `` 开、EOF 未闭合) 内含 `<think>x` | 原样 (围栏豁免优先于未闭合丢弃 — B2 修法①) |
| T13 | `<think a="x>1">a</think>正文` (属性值含 `>`) | `正文` |
| T14 | `<think a="x></think>2">BODY</think>TAIL` (属性值含闭标签字样) | `TAIL` (属性值正确跳过, 不提前配对) |
| T15 | `<think>outer<think>inner</think>middle</think>TAIL` (同名嵌套) | `TAIL` (深度配对) |
| T16 | 行内反引号内标签 (反引号 + `<think>a</think>` + 反引号, 同行) | 原样 (`<` 前有反引号 → 非行首) |
| T17 | **B1 回归反例**: deltas = ["`<think>secret</think>TAIL", "`"] | 全程原样, 无前缀翻转 |
| T18 | `<think>a</think>\r\n\r\n正文` (CRLF) | `正文`; delta 切在 `\r` / `\n` 之间结果一致 |
| T18b | `"```\r\ncode\r\n```\r\n<think>a</think>正文"` (CRLF + 围栏) | `"```\r\ncode\r\n```\r\n正文"` (围栏闭合后块要剥 — 复审 V2 新增) |
| T19 | `<analysis>a</analysis>正文` (白名单外, Phase 2) | 原样 |
| T20 | `正文 <think>a</think> 正文` (同行中间块) | 原样 (行首规则的明写代价) |
| T21 | 空串 / 纯空白 / 纯正文 (含中文标点、换行、无 `<`) | 逐字节原样 |
| T22 | `<thought>a</thought>正文` / `<reasoning>a</reasoning>正文` | `正文` |
| T23 | 属性跨帧: deltas = ["<think data=\"1", "\">a</think>正文"] | `正文` |
| T24 | `  <think>a` (头部未闭合块 + 前导空白) | (空) — 未闭合块在头部连块前空白一并丢 (复审钉死) |
| T25 | `<think>a<think>b</think>TAIL` (同名嵌套未闭合) | (空) — 外层未配对 → 从外开标签丢弃 (复审新增) |
| T26 | `"<think>a\n```\n</think>TAIL"` (块内围栏) | `"TAIL"` — 块内不感知围栏, 首个同名闭标签即配对 (复审新增) |
| T27 | `"<think>a</think>```\n<think>b</think>\n```TAIL"` (围栏按可见文本坐标) | `"```\n<think>b</think>\n```TAIL"` — 剥除首块后该行成为围栏开行, 第二个块受围栏保护 (复审新增) |
| T28 | **V1 混合坐标反例**: deltas = ["<think>a</think><thi", "nk>b</think>正文"] | 两帧可见输出为 "" + "正文", 无前缀翻转 (同口径后 0 破例) |

### 3.3 流式契约 (写进模块 docstring, 测试锁定)

1. **前缀单调**: 任意时刻"累计 take"是上一时刻的前缀延长, 永不回缩。
2. **完整性**: `"".join(take 序列) + flush() == strip_thinking(raw)`。
3. **幂等**: `flush()` 二次调用返回 `""`; `feed("")` 无副作用; 未 feed 直接 flush 返回 `""`。
4. **切分无关**: 标签被切开、属性跨帧、多块连续、CRLF 中间切 — 结果不得依赖切分方式 (全切点遍历测试)。
5. **判定不翻转 (地基)**: 已消费的标签, 其"是否属于可剥块"的判定不会再被后续 delta 改变
   (行首性只依赖已消费字符; 围栏态只依赖完整行; v1 的反引号配对状态已移除)。

### 3.4 日志格式

`[思维链] <文件名>: 丢弃 N 块 / M 字符` (N=0 时不打) + `[思维链] <文件名>: 忽略独立字段 N 帧` (debug)

---

## 4. 路径 × 形态 行为矩阵 (改造后)

| 路径 | 代码位置 | 独立字段 (1/2 类) | 内联标签 (3 类) |
|---|---|---|---|
| 逐条校对 (harness, 非流式) | `processor.py:868-956` | 不读, 不进结果 (测试锁死) | content 整体不参与结果; 已知边界见 §0.4 (本版不处理) |
| 整篇校对 (流式) | `processor.py:780-838` | 不读, 不进结果 | `ThinkFilter` 实时剥离 (预览 + 最终 + 断点) |
| 去 AI 味 · 全步 (detect/rewrite/score) 分块流 | `web_backend.py:1074-1080` | 同上 | 同上 (逐块剥离, 进入累积器前) |
| 去 AI 味 · revise 轮 | `web_backend.py:1302-1308` | 同上 | 同上 |
| 去 AI 味 · 风格蒸馏 | `web_backend.py:1692-1702` | 同上 | 同上 (style-card 不含思维链) |
| 本地模式 (`punct_local` / `md_local`) | 不调 LLM | 不适用 | 不适用 |

---

## 5. 改动清单

| # | 类型 | 文件 | 内容 | 估计行 | 风险 |
|---|---|---|---|---|---|
| 1 | 新增 | `app/think_strip.py` | `THINK_TAGS` + `strip_thinking()` + `ThinkFilter` (惰性 take / 三悬置 / 头部清理 / 围栏豁免) + `has_think_residue()` | +170 | 高 |
| 2 | 新增 | `tests/test_think_strip.py` | §3.2 全表 + 全切点遍历 + 不变式 + 幂等 + 惰性/性能断言 | +220 | 中 |
| 3 | 改 | `app/processor.py` | 整篇流式接线 (`:798-838`): feed/take + 收尾 flush; 空判据 (`:825-827`) 改剥后; D10 日志 | +35/-8 | 高 |
| 4 | 改 | `app/processor.py` | D9 定向失效 (`:283-291` 之间: 命中缓存但含残留 → 强制重跑) | +15 | 低 |
| 5 | 改 | `app/web_backend.py` | DeAI 三处接线 (`:1074-1080` / `:1302-1308` / `:1692-1702`) + 消费点不变式 (D8) + 空判据 + 日志 | +45/-10 | 高 |
| 6 | 改 | `tests/test_chunk_lifecycle.py` | 假 delta 流含 `<think>` + `reasoning_content` → `corrected` 干净、预览链单调; 剥后为空 → 重试耗尽 FAILED | +70 | 中 |
| 7 | 改 | `tests/test_web_backend_deai.py` | 三处剥离 + 6 组消费点断言 (衔接 prompt / 错误 / 取消 / 降级落盘 / 评分 / style-card) + 负向字段 | +90 | 中 |
| 8 | 改 | `tests/test_components.py` | 纯函数模块入库断言 (`THINK_TAGS` / 幂等 / 空输入) + 既有流用例回归 | +20 | 低 |
| 9 | 改 | `tests/test_web_backend_proofread.py` | D9: 断点含残留 → 忽略缓存强制重跑; 干净断点 → 仍命中 | +35 | 中 |
| 10 | 改 | `tools/smoke_ui.py` | B5-i 修法: import `app.think_strip` **预生成剥后 partial 序列**再推, 断言前端单调渲染且不含思维链 | +35 | 低 |
| 11 | 改 | `README.md` / `AGENTS.md` / `CHANGELOG.md` / `docs/ROADMAP.md` | 特性说明 + 决策条目 + v5.4.0 条目 (含症状提示) + 进度; README 套件计数 18→19, AGENTS 测试清单补 `test_think_strip.py` | +65 | 低 |

**合计**: 2 新增 + 9 改, 净增约 795 行。

---

## 6. 测试计划

### 6.0 既有断言必须逐个复核 (实施时逐条过; 行号已由审计验证)

| 位置 | 为什么会被碰 | 要做什么 |
|---|---|---|
| `tests/test_chunk_lifecycle.py:479` (`test_m4_stream_monotonic_fulltext`; `:489-492` 已 `harness_enabled=False`) | 假 delta 流经过新增过滤器 | 断言链不变; 补含 think 的对照组 |
| `tests/test_components.py:261-287` (空流 content=None) / `:291-329` (`"Hello"+" World"` 逐字节) / `:331-361` (`finish_reason=length` 截断标记) | 过滤器需容忍 None/空; 纯正文与截断语义不得被 strip 影响 | 全绿 + 必要时补断言 |
| `tests/test_bugs.py:105` (`delta.content = None` 桩) | 同上 | 全绿 |
| `tests/test_web_backend_deai.py:1086-1097` (strip 后置 + 收尾帧) / `:753-775` (60000 字落盘/降级) / `:730-731` `:767-769` (progress/truncated) | 推送文本与落盘经过滤器 | 纯正文长度/内容逐字节不变 |
| `tests/test_harness.py:399-412` (`content="无需修改"` 判成功无 warnings) / `:441-450` (max_retries=0 all-fail → FAILED) | harness 无改动, 但 D5 空判据共用重试链 | 全绿 (D5 用例直接复用 441-450 范式) |
| `tools/smoke_ui.py` 既有项 | 前端无改动 | 作为回归基线全绿 |

### 6.1 必须新增

- **T 表全表**: §3.2 T1-T28 逐条 (含围栏/嵌套/属性词法/CRLF+围栏/行内码/连排块/块内围栏/可见文本坐标)。
- **全切点遍历**: 对每个 fixture, 在**所有 2 段切点** (外加若干 3 段切点) 上 feed/take/flush,
  断言 §3.3-2 完整性与 §3.3-1 前缀单调; T16/T17 的 `len-1` 切点必须覆盖 (B1 回归);
  T28 (V1 混合坐标反例) 的切点必须逐帧断言, 第一帧不得 emit `<thi`。
- **纯正文属性测试 (B5-iii)**: 一组无 `<` 文本 (含换行/中文/空白) 按所有切点 feed → `join+flush` 逐字节等于原文。
- **惰性锁**: 连续 N 次 feed 不调用 take → 再 take 一次即得全部 (证明计算点只在 take; 结构性断言, 不做挂钟断言)。
- **性能**: 50K 字符含 5 块, `strip_thinking` 单次 < 200ms; 50K→100K 单次耗时比 < 3 倍 (防二次退化)。
- **引擎级**: `_stream_single` 假流 (含 `<think>` + `reasoning_content`) → `corrected` 干净、预览链单调、
  日志含 `[思维链]`; 纯思维链输出 → 剥后为空 → 走既有重试链, 耗尽后 FAILED (不静默成功)。
- **DeAI 三处**: 分块 / revise / 蒸馏各一条剥离断言; 6 组消费点各一条 (重点: 取消 payload 与落盘不含思维链)。
- **D9**: 旧断点 `corrected` 含行首 `<think>` → 缓存被拒 + 强制重跑日志; 干净断点仍命中。
- **冒烟 (B5-i)**: smoke 脚本 import `app.think_strip` 生成剥后 partial 序列推送, 断言前端前缀单调渲染、不出现标签。

### 6.2 必须回归

- `run_all_tests.py` 全绿 (基线 **1463 / 0**; 期望净增)
- `tools/smoke_ui.py` 91 项全绿 + 新增端到端项
- 纯正文输出**逐字节不变** (最重要的回归: 过滤器不能动正常结果)

### 6.3 手工冒烟 (不可省)

1. 真机接一个内联 `<think>` 的端点 (或本地 mock): 整篇校对 → 结果与 diff 均无思维链, 日志有 `[思维链]` 一行
2. 同一文本流式预览全程不闪思维链
3. 去 AI 味 3 步 → 三处输出与 style-card 均无思维链
4. 故意让输出在 think 块中途截断 → 剥后为空 → 走重试/失败, 不产出半截思维链
5. 已有旧断点的文件 → 命中残留扫描 → 自动强制重跑一次

---

## 7. 风险表

| # | 风险 | 概率 | 影响 | 处置 |
|---|---|---|---|---|
| R1 | 误删: 行首 (允许缩进) 的合法 `<think>` 块被吃 (文档/教程文本) | 中 | 高 (静默丢内容) | 行首规则 + 白名单 + 围栏豁免 + D10 日志 + T11/T16/T19 测试; 行内提及天然受保护 |
| R2 | 漏剥/误剥: 同行中间块 (T5/T20)、围栏内块 (T11)、跨行 code span 里恰好行首的标签 | 中 | 中 (可见脏结果, 可重跑) | 明写为代价; 日志 + 强制重跑出口兜底 |
| R3 | 流式与最终结果不一致 (预览闪回/残留) | 低 | 中 | D4 不变式 + 全切点遍历 + T17 回归 |
| R4 | 性能: take 全量重算 | 低 | 中 | 惰性 API + 只在节流点调用 + 200ms 预算 + 规模比测试 |
| R5 | 旧断点复用脏结果 | 高 | 中 | D9 定向失效 (零 LLM 成本) + CHANGELOG 症状提示 |
| R6 | 独立字段形态无可观测性 (厂商换字段名) | 低 | 低 | D7 帧计数 debug 日志 (不落内容) |
| R7 | 蒸馏教学示例含 `<think>` 字样 | 低 | 中 | 蒸馏路径照剥; 示例通常落在围栏/行内码, 由 D3-4 保住; 测试复核样本 |
| R8 | 词法: 嵌套同名 / 属性值含 `>` 或 `</think>` | 中 | 中 | T13-T15 测试锁死 (审计已证 naive 实现会漏) |
| R9 | `\r\n` 与行级判定交互 (含围栏闭合) | 低 | 中 | T18/T18b 锁定; 围栏行判定前 `rstrip("\r")` (复审 V2 已修) |
| R10 | harness `new_text` 里含标签 → 经 apply_edits 落进 corrected | 极低 | 低 | 本版只记录不处理 (Phase 2); 剥后扫描 (D9) 会在下次加载时兜住 |
| R11 | 性能断言 flaky (CI/低配) | 中 | 低 | 断言放宽至 200ms + 相对比值; 不做 50ms 硬断言 |

---

## 8. Session 划分 (v2: 4 个, v1 的 harness session 已移出)

| Session | 内容 | 工时 | 产出 |
|---|---|---:|---|
| S1 | `app/think_strip.py` + `tests/test_think_strip.py` (纯函数 + 过滤器 + 全切点/性能, 不接线) | 4h | 可独立验证的剥离内核 |
| S2 | 引擎接线: `processor.py` 流式 + 空判据 + D9 定向失效 + D10 日志; 引擎级测试 | 3-4h | 整篇校对干净 + 断点兜底 |
| S3 | DeAI 三处接线 + 6 组消费点断言 + 相关测试 | 3-4h | 去 AI 味干净 |
| S4 | 冒烟 (B5-i 修法) + 文档四件套 + 全量回归 | 2-3h | 可发布 |

每个 session 独立可回滚; S1 不接线, 零行为变化。测试映射: 改动 #2/#8 → S1 (纯净内核与入库断言)、
#3/#4/#6/#9 → S2 (含 `tests/test_web_backend_proofread.py`)、#5/#7 → S3、#10/#11 → S4。

---

## 9. Phase 2 候选 (本版不做)

1. **思维链留档**: 丢到独立面板 / 落盘 `think_log/`, 不污染结果 (需 UI)
2. **开关**: `think_strip: bool = True` 配置项 + 参数页复选框
3. **更多标签变体**: `<analysis>` (R-A 裁定降级) / `<scratchpad>` / `<|think|>` (拿到真实样本再加)
4. **content 里的编辑 JSON 解析**: content 含可解析的编辑对象时直接当编辑用
5. **harness 收口 (v1 D6 移入)**: `0 tool_calls` + content 含 `old_text`/`new_text` 字面量 → `WARN_EDIT_IN_CONTENT`
6. **harness `new_text` 防御** (R10): 模型把标签写进编辑文本
7. **无标签内联思维链**: 需模型侧 prompt 约束或启发式切分, 风险高
8. **围栏内思维链强化**: 若真实网关把 reasoning 包进代码围栏再输出 (R2), 考虑"围栏内白名单标签也剥"的可选档

---

## 10. 验收标准 (DoD)

- [ ] `strip_thinking` / `ThinkFilter` §3.2 T1-T28 全表 + §3.3 全切点不变式全绿 (含 T17/T28 反例回归, T18b CRLF+围栏)
- [ ] 两条链路 4 处接线: 整篇校对 / DeAI 分块 / revise / 蒸馏 输出不含内联思维链
- [ ] DeAI 6 组消费点 (衔接 prompt / 错误 / 取消 / 降级落盘 / 评分 / style-card) 全部为剥后文本
- [ ] 流式预览全程无思维链闪现, 且预览累计 == 最终结果
- [ ] `reasoning_content` / `reasoning` 负向测试锁死 (不进 corrected / 前端 / 落盘)
- [ ] 纯正文输出逐字节不变 (回归硬要求)
- [ ] 纯思维链输出 → 判失败 (不静默成功), 日志明示原因
- [ ] 旧断点含残留 → 定向忽略缓存强制重跑 (D9); 干净断点仍命中
- [ ] 每次剥离有日志; 围栏内标签不被剥; 行首规则代价 (T5/T20) 有测试锁定
- [ ] `run_all_tests.py` 全绿 (≥ 基线 1463) + 冒烟 91 + 新增项全绿
- [ ] 文档四件套更新; CHANGELOG 明示旧断点症状与自动重跑行为

---

## 11. 决策记录 (v2 已拍板, 取代 v1 §11 待拍板)

| # | 事项 | v2 决定 | 依据 |
|---|---|---|---|
| 1 | 正文中间的行首块 | **剥** | 模型"先检查再开块"常见; 日志兜底 |
| 2 | 围栏豁免 | **保留** | 防静默丢文档内容; 漏剥由日志/重跑兜底 |
| 3 | 行内反引号豁免 | **取消** → 行首规则 | B1 打穿反例; 行首性判定单调稳定 |
| 4 | 旧断点 | **不失效 + 定向失效扫描** | D9; 全量失效 token 代价不可接受 |
| 5 | harness 收口 (D6) | **移出本版** → Phase 2 | B4 |
| 6 | `<analysis>` | **移出白名单** → Phase 2 | R-A 误删面 |
| 7 | 蒸馏路径 | **剥** | R7 长期污染裁定 |
| 8 | 性能断言 | **200ms 预算 + 惰性 take** | B5/R11 防 flaky |
| 9 | "行首"坐标 (复审 V1) | **可见文本口径** (已剥除区段不存在) | 钉死后 637 例 property 0 破例 |
| 10 | 围栏 CRLF (复审 V2) | **行尾 rstrip("\r") 再判定** | 否则 CRLF 围栏永不闭合 → 之后整段漏剥 |

无遗留阻塞拍板项; 修订后 S1 可独立开跑。

---

## 12. 执行记录 (按 session 回填)

| Session | 状态 | commit | 备注 |
|---|---|---|---|
| S1 剥离内核 | ✅ 完成 | `b4d527a` | `app/think_strip.py` + `tests/test_think_strip.py` 62 项; T 表 T1-T28 全绿 + 全切点 0 破例 + 50K 19ms |
| S2 引擎接线 | ✅ 完成 | `0395f82` | 整篇流式剥离 + 剥后空判据 + D9 定向失效 + D10 日志; 引擎级 / 断点级测试 |
| S3 DeAI 接线 | ✅ 完成 | `59350d9` | 分块/revise/蒸馏三处 + 消费点不变式 + 空卡不落盘; 顺带修蒸馏 `_samples_dir` 真 bug |
| S4 冒烟 + 文档 | ✅ 完成 | (本批) | smoke 96 项 (91→96, 用真实模块预生成 partial); 文档四件套; 全量 1550 / 0 |

**实施期偏离 (如实记录)**:

1. **T10 期望按 D3-2 统一**: `<think>a</thinking>正文` → 空 (开标签有效未配对 → 整段丢弃), 与 v2 T 表一致, 未出现分歧。
2. **`take()` 实现为可续扫前向扫描器**: 语义与"全量重算 + 安全前缀"等价 (全切点 property 锁死), 但计算量只付在新增文本上 — 比 D4 原文设想的"每帧 O(n) 全量重算"更省; 惰性契约由结构性测试锁定。
3. **蒸馏路径有既有 bug**: `self._style_loader._samples_dir(slug)` 调的是实例方法, 实为模块级函数 → 抛 `AttributeError` 被 `except` 吞成"读样本失败", **蒸馏此前从未真正跑通过**。S3 一并修掉 (`web_backend.py:1653`)。
4. **`count_reasoning_fields` 对 MagicMock 桩记 0**: 既有假 delta 测试用 `MagicMock()`, 其属性恒为真; 只看 `str` / 非空序列, 避免既有测试被误计数 (D7 可观测性不因此失真)。
5. **文档计数同步**: README 套件 18→19、回归 1463→1550、冒烟 91→96。

---

## 13. 审计记录 (2026-09-26)

- **方式**: 独立只读 verifier agent (subagent, 不继承主会话上下文), 报告:
  `.workbuddy/reviews/review-think-strip-v5.4-plan.md` (本地, 不入库)
- **裁决**: 方向成立, 但 v1 §2 D4 按原文实现会违背自身不变式 → **需修订后开工 (5 阻塞项 B1-B5)**;
  B1/B2 各需 1-2 句设计修补, 不必放弃安全前缀路线
- **事实抽查**: 证据清单 20 行中 17 处逐字一致; 3 处行号偏移 (web_backend content 读取实际在
  `:1075` / `:1303` / `:1693`, v1 引成了 delta 赋值行); 1 处引用过度 (`processor.py:812` 注释只证
  `max_tokens`, 不证 `reasoning_effort`/`thinking`) — 均已在 v2 修正

| 阻塞项 | 处置 (v2 位置) |
|---|---|
| B1 行内反引号豁免跨 delta 翻转 (已复现反例) | D3 砍豁免改行首规则; T16/T17 锁定; §3.3-5 地基 |
| B2 flush/尾部语义三处互斥 | D4: flush = strip 与已 emit 差额; 围栏豁免优先; T9/T12 锁定 |
| B3 DeAI 消费点漏列 | D8: "只保留剥后累积器"不变式 + 6 组消费点表 + 改动清单 #5/#7 |
| B4 D6 超出用户诉求 | §0.4 收窄为已知边界; D6 与实现项/用例移入 §9 Phase 2 |
| B5 测试锁不住 DoD 三处 | §6.1: smoke 改用真实模块预生成 partial (i); T13-T15 + T17 补边界 (ii); 纯正文全切点 property (iii) |

**已采纳的非阻塞项**: 行号修正 (1075/1303/1693); §0.1 口径改写 (代码目录零命中 + CHANGELOG 例外);
§0.2 表格按路径限定 (harness 不漏); §0.4 收窄 (BadRequestError 路径); 蒸馏照剥;
D9 定向失效; 性能断言放宽; §4 矩阵标签改 "DeAI 全步"; `<analysis>` 降级 Phase 2;
R-A~R-F 并入 §7; `\r\n` 用例 (T18); harness `new_text` 防御入 Phase 2。

### 第二轮复审 (v2 → v2.1, 2026-09-26)

- **方式**: 独立只读 verifier subagent (不继承主会话结论); 报告:
  `.workbuddy/reviews/review2-think-strip-v5.4-plan.md` (本地, 不入库)
- **裁决**: **需修订后开工** — B1-B5 五项销项逐条核对**全部真实并入**; 但 v2 新增核心规格暴露 2 个阻塞项:

| 阻塞项 | 内容 | 处置 (v2.1 位置) |
|---|---|---|
| V1 | "行首"坐标未定义: 文字 (原文行) 与 T4 期望互斥; 混用会把 B1 类前缀破例带回来 (已复现 deltas 反例) | D3-1/§3.1 钉死"可见文本口径"; D4 H3 同坐标; T4 拆 T4a/T4b; T28 锁反例; §11-9 |
| V2 | 围栏闭合继承 md_strip 的 CRLF 行为 → CRLF 文本围栏永不闭合, 围栏后整段漏剥 (T18 覆盖不到) | D3-4/§3.1: 围栏行判定前 `rstrip("\r")`; T18b; §11-10; R9 影响升为中 |

- **事实抽查**: 复审实读 35 处引用 (web_backend 12 / processor 10 / md_strip / app.js / tests), **全部一致**;
  2 处措辞偏差已修 (§0.1 "全仓唯一命中" 口径 → 代码目录零命中; D5 蒸馏是**新增**空判据而非"改")。
- **采纳的非阻塞建议**: `has_think_residue` 收敛为 `strip_thinking` 单点口径 + 原文自带残留不重跑 (D9);
  蒸馏空卡不落盘 (D5); T24/T25 (未闭合变体) / T26/T27 (围栏×块嵌套) fixture;
  惰性锁改结构性断言; §8 测试映射; README 套件计数 18→19 + AGENTS 测试清单补 `test_think_strip.py` (S4);
  §0.1 口径改写 (同上)。

---

## 附: 证据清单 (审计已复核; 行号按 v2 修正后)

| 引用 | 内容 |
|---|---|
| `app/processor.py:798` | 流式只取 `event.choices[0].delta.content` |
| `app/processor.py:803-810` | 节流 emit (5 token / 50ms), take 调用点 |
| `app/processor.py:809` / `:836` | 节流 emit 累计文本 / 块末 emit 全量 |
| `app/processor.py:825-827` | `corrected` 为空 → `raise ValueError` |
| `app/processor.py:909-910` | harness 把 `message` 交给 `parse_tool_calls` |
| `app/processor.py:917-918` / `:941-942` / `:950-951` | edits 空 → 原文 + 空 audit + "无需修改" 判成功 |
| `app/processor.py:283-291` | 断点缓存命中路径 (D9 插入点) |
| `app/processor.py:567-573` | 不可重试错误 → 立即 FAILED (§0.4) |
| `app/processor.py:812` | `max_tokens` 注释 (只证该参数) |
| `app/harness.py:107` | TOOL_DISCIPLINE: 无错时回复"无需修改" |
| `app/harness.py:291-304` | `audit_has_warnings()` 判定 |
| `app/web_backend.py:1052` | 块间衔接 prompt `partial[-400:]` |
| `app/web_backend.py:1075` / `:1303` / `:1693` | DeAI 三处只取 `delta.content` (v2 修正行号) |
| `app/web_backend.py:1086-1087` / `:1317-1318` | DeAI 空块判据 (D5 改剥后) |
| `app/web_backend.py:1099-1101` / `:1127-1131` / `:1150-1154` | 错误/取消/降级 payload + 落盘 |
| `app/web_backend.py:1200` / `:1243` | `ai_score_local` 输入 |
| `app/web_backend.py:1727-1729` | style-card 落盘 + 收尾帧 |
| `app/md_strip.py:27` | HTML 标签原样保留 (实测 `<think>` 不被剥) |
| `app/md_strip.py:139-151` | 行内反引号 run 等长配对 (v1 复用它才引入 B1) |
| `app/ai_score_local.py:318` | 本地评分入口 |
| `web/app.js:1777-1778` / `:1934-1935` | 前缀单调契约与回缩保护 |
| `web/app.js:2885-2886` | 取消时前端展示 `data.partial` |
| `CHANGELOG.md:72` | v5.1.0 烟测: MiniMax content 含 `<think>`, harness 不受影响 |
| `tests/test_chunk_lifecycle.py:479` | 既有假 delta 流测试范式 |
| `tests/test_harness.py:399-412` | "无需修改" 正常路径锁定 |
| `tests/test_web_backend_deai.py:1086-1097` | strip 后置与收尾帧断言 |
| `tools/smoke_ui.py:11` / `:107-111` | 静态托管 + 桩注入 (B5-i 依据) |
