# 墨准 v5.4 思维链剥离 (think block strip) — 实施计划

> 状态: **待独立审计** (用户 2026-09-26 拍板: 思维链"直接丢")
> 基线: `master @ cc2617c` (v5.3.1) — 回归 1463 通过 / 0 失败, 冒烟 91 项 / 0 失败
> 本计划只做一件事: **模型输出的思维链一律丢弃, 不进任何用户可见结果**

---

## 0. 四条前提 (先读, 否则方案会建在错假设上)

### 0.1 现状不是"处理得不好", 而是"完全没处理"

全仓 (`app/` + `web/`) 检索 `think|thinking|reasoning_content|reasoning`: **代码零命中**, 唯一命中是
`CHANGELOG.md:72` 的一句历史结论("模型 content 带 `<think>` 推理块 — harness 只解析 tool_calls, 不受影响")。

当前不出事, 靠的是两个巧合:

1. **harness 路径压根不读 `message.content`** — `app/processor.py:909-910` 只把 `message` 交给
   `app/harness.py:307-339` 的 `parse_tool_calls()`, 该函数只遍历 `message.tool_calls`。思维链写了也白写。
2. **主流厂商把思维链放独立字段** (`reasoning_content` / `reasoning`), 而三条流式链路都只取
   `delta.content` (`app/processor.py:798`; `app/web_backend.py:1074` / `:1302` / `:1692`), 等于天然丢弃。

这两个巧合都不覆盖"内联式思维链"(§0.2 第 3 类)。

### 0.2 会漏的是"内联式"思维链 —— 四形态矩阵

| # | 形态 | 代表 | 今天的结果 |
|---|---|---|---|
| 1 | 独立字段 `reasoning_content` | DeepSeek-R1 系 / Kimi / GLM thinking | 自动不进结果 (只读 `content`) |
| 2 | 独立字段 `reasoning` / `reasoning_details` | OpenRouter 归一化格式 (含 `redacted_reasoning`) | 同上 |
| 3 | **内联成对标签** `<think>…</think>` | MiniMax M2/M3 部分端点、部分自建 Qwen/GLM、把 reasoning 合并进 content 的中转网关 | **整段进入 `corrected`** |
| 4 | 内联无标签 | 少数端点直接拼接 | 无标记可切, 只能靠 prompt 约束 |

第 3 类的污染面 (全链路):
`corrected` → 字符级 diff 右栏 → 「复制」→ 「导出」→ 断点落盘 → 「→ 去AI味」送去改写 → `ai_score_local` 当正文打分
→ DeAI 蒸馏/评分把它们当风格样本。

**本计划覆盖第 3 类**; 第 1/2 类从"隐式不读"升级为"显式契约 + 测试锁死"(§2 D7); 第 4 类不做 (无判别依据, 属模型侧 prompt 问题)。

### 0.3 既有后处理链路不会替我们清 (已实测)

- `strip_markdown("前言\n<think>推理</think>\n\n# 标题\n正文 **加粗**")`
  → `"前言\n<think>推理</think>\n\n标题\n正文 加粗"` — 标签与内容**原样保留**
  (`app/md_strip.py:27` 的既定原则: HTML 标签不动)。
- `ai_score_local` (`app/ai_score_local.py:318`) 把思维链当正文打分。
- 前端只渲染 diff, 没有任何折叠/隐藏思维链的渲染分支。
- 全仓**没有** `max_tokens` / `reasoning_effort` / `thinking` 参数 (`app/processor.py:812` 注释确证),
  所以"靠请求参数关掉思维链"这条路本版不碰 (§1 N3)。

### 0.4 附带风险: harness 的静默 no-op (本计划新增项, 请审计裁定范围)

`app/processor.py:929-955`: `edits` 为空时 `corrected = 原文`, 记一条
`[harness] <file>: 模型未提交编辑 (无需修改)` 并**判成功** (无 warnings)。

而 `TOOL_DISCIPLINE` (`app/harness.py:107`) 明确要求: "全文没有错误时, 回复**无需修改**四个字"。
也就是说 **`0 tool_calls` + 有正文, 在正常场景下是合法的** —— 这决定了我们不能简单地把"没有 tool_calls"判为失败。

但代价是: 模型若不支持 tools / 把编辑写在 content (含 think 块内), 我们与"无需修改"**无法区分**, 于是一次真实的
校对请求会静默变成"已完成、无改动"。§2 D6 给出保守收口方案, 请审计判断是否属本版范围。

---

## 1. 目标与非目标

### 目标

- **G1** 内联思维链块一律丢弃; 三条链路全闭环: 逐条校对 (harness) / 整篇校对 (流式) / 去 AI 味 (分块 + revise + 蒸馏)
- **G2** 流式预览**不闪现**思维链, 且满足不变式: `预览累计 + flush == strip_thinking(原文输出)`
  (前端增量渲染依赖"累计文本前缀单调", 见 `web/app.js:1777-1778` 与回缩保护 `:1934-1935`)
- **G3** 独立字段形态 (`reasoning_content` / `reasoning`) 显式不读取, 并有测试锁死, 防止将来"顺手支持"时漏进结果
- **G4** 剥离可观测: 每次剥离记一条日志 (块数 + 字符数), 不做静默删除

### 非目标

- **N1** 不做思维链展示面板 / 不落档 (用户明确"直接丢")
- **N2** 不加"保留思维链"开关 (Phase 2 候选, §9)
- **N3** 不改 prompt、不改请求参数 (不引入 `max_tokens` / `reasoning_effort` / `thinking` 字段)
- **N4** 不碰断点 schema 与 `compute_prompt_hash` (理由见 §2 D9)
- **N5** 不改前端渲染逻辑 (UI 零新增元素; 只在 `tools/smoke_ui.py` 增加一条端到端断言)

---

## 2. 决策表 (逐条给理由 + 被否方案)

### D1 新建单点模块 `app/think_strip.py` (纯函数 + 增量过滤器, 无 IO 无 GUI)

与 `app/md_strip.py` / `app/punct_fix.py` 同层同纪律。对外只暴露两个 API:

```python
THINK_TAGS = (...)

def strip_thinking(text: str) -> str:
    """一次性剥离 (非流式路径 / 收口 / 测试基准)。"""

class ThinkFilter:
    """流式增量过滤器: feed(delta) -> 可安全显示的增量; flush() -> 收尾剩余。"""
```

- **理由**: 三条流式链路 (`processor` 1 处 + `web_backend` 3 处) 必须共用同一份语义, 否则必然漂移
  (v4.1.8.1 审计 C2 就是"两处派生不一致"的教训)。
- **否**: 在 `processor.py` / `web_backend.py` 各写一份正则 (4 份重复, 改标签集合必漏);
  **否**: 扩展 `md_strip` (它的契约是 Markdown 装饰, 且明确保留 HTML 标签 — 语义冲突)。

### D2 标签集合 (大小写不敏感, 允许属性)

`think` / `thinking` / `reasoning` / `thought` / `analysis` —— 单点常量 `THINK_TAGS`, 便于日后加变体。

- **理由**: 前四个是社区最常见的思维链包裹标签; `analysis` 有真实端点使用。**只剥白名单**, 其余 `<foo>` 一律不动。
- **否**: `scratchpad` / `<|think|>` / `<|begin_of_thought|>` 等变体 —— 无本仓库证据, 列入 Phase 2 (§9)。

### D3 剥离范围: 成对块 + 未闭合的**收尾块**; **代码区内不剥**

剥:

1. 完整成对块 `<tag …>…</tag>` (含多行、含属性、含嵌套同名标签的外层)
2. 流结束时**仍未闭合**的块 → 内容整体丢弃 (截断场景: 模型想完了但没来得及输出正文)
3. 剥完若开头只剩空白 → 去掉前导空行 (避免结果以空行开头)

不剥:

4. **fenced code (``` … ```) 与行内反引号内的标签** —— 保护"用户文档里本就存在 `<think>` 字样"的合法内容
   (本工具有 `tech_doc` 模式和 Markdown 清洗, 文章里合法出现这类标签不是假想)
5. 白名单外的标签 (如 `<div>` / `<b>`) —— 与 `md_strip` 的"HTML 标签原样保留"原则一致

- **理由**: 静默删掉用户正文, 比"偶尔漏掉一段思维链"严重得多 —— 前者不可见、后者肉眼可见且可重跑。
- **代价 (明写)**: 若某中转网关把思维链塞进代码围栏, 这一段不会被剥; 靠 D10 的日志让用户能发现。
- **备选 (请审计裁定)**: 不感知代码围栏, 全量剥白名单标签 —— 实现更简单, 但会吃掉文档里合法的 `<think>`。

### D4 流式实现: 单一"安全前缀"策略 (不做字符级状态机)

每次 `feed(delta)`:

1. `raw += delta` (累积原文)
2. 计算 `hold` = 从哪个下标起可能还在**半截标签**里 (尾部未闭合的 `<`/`<tag`/`<tag attrs` 一律回退到该 `<`)
3. 对 `raw[:hold]` 调 `strip_thinking(..., hold_unclosed=True)` → 得到 `(显示文本, 未闭合块起点)`
4. 只 emit 到 `min(hold, 未闭合块起点)`, 并保证新 emit 是上次 emit 的**前缀延长**
5. `flush()` 返回剩余部分 (未闭合块内容丢弃)

**不变式 (测试锁定)**: 对任意切分方式, `"".join(feed 序列) + flush() == strip_thinking(raw)`。

- **理由**: 全量重算 + 前缀截取, 天然处理"标签被 delta 切断"(`"<thi"` + `"nk>"`)、属性跨帧、多个块;
  不必维护"我在不在标签里"的隐式状态。重算成本按 emit 节流点算 (processor 已有 5 token / 50ms 节流,
  `app/processor.py:83-84` → `:804-805`; DeAI 每 50ms 一推), 50K 字符量级下可忽略。
- **否**: 字符级状态机 (状态多、跨帧 bug 面大、两处实现易漂移); **否**: 只在最终结果上剥
  (预览会闪现整段思维链, 违反 G2)。

### D5 剥后为空 → 沿用"空输出"语义抛错

`app/processor.py:825-827` 已有: `corrected` 为空 → `raise ValueError("API 返回空内容")` → 走既有重试链。
本版把判据改成**剥后**为空, 错误文案区分"仅含思维链, 无有效输出", 便于日志定位。

- **理由**: 复用一个已经验证过的失败/重试路径, 不新增语义。
- **注意**: 该块若同时 `finish_reason="length"` (v5.3.0 截断检测, `:829-834`), 截断标记先记录, 再走空输出 raise。
  若最终整文件 FAILED, `truncated_keys` 是会话内存态、不落断点 — 用户重跑一次即可, 属可接受 (审计可复核)。

### D6 harness 收口: `0 tool_calls` 但 content 像编辑载体 → 记 `WARN_EDIT_IN_CONTENT`

判据 (保守, 只抓高置信度情形): 去掉思维链后 content 同时含 `old_text` 与 `new_text` 字面量 → 视为
"模型把编辑写在正文里, 没有走工具链" → 往 `file_audits` 追加一条整轮级告警 (`index=-1`),
复用 `app/harness.py:196` / `:282-285` 的既有 `WARN_*` 机制。

好处 (零新增 UI):

- `app/harness.py:291-304` 的 `audit_has_warnings()` 已把 `WARN_*` 判为 warnings → `FileResult.warnings=True`
  → 文件行自动显示「完成（部分建议未采纳）」→ 用户**看得见**
- 同一条目会出现在右侧「改动清单」里 (`index=-1` 的整轮级条目已有渲染路径, 与 `WARN_RATIO` 同款)

- **否**: 一律把"没有 tool_calls"判 FAILED —— 会把 `TOOL_DISCIPLINE` 规定的正常"无需修改"路径误杀 (见 §0.4)。
- **否**: 解析 content 里的 JSON 当编辑用 —— 未经烟测的协议扩展, 本版不做 (Phase 2 候选)。

### D7 独立字段显式不读 + 测试锁死

`reasoning_content` / `reasoning` / `reasoning_details` 一律不读、不显示、不落盘。
新增测试: 造带这些字段的假 delta, 断言 `corrected` 不含其内容。

- **理由**: 把今天"因为没写代码所以没漏"变成"有测试证的显式行为", 防止将来有人为了"显示思维链"顺手读了字段又漏进结果。
- 参考事实: `openai` SDK 2.36 会把未知字段放进 `model_extra` (本机实测), 我们的代码只取 `delta.content`。

### D8 DeAI 三处接线 + 处理顺序

顺序固定为 **think_strip → md_strip → ai_score** (先剥思维链, 再剥 Markdown 装饰)。

接线点: `app/web_backend.py:1074` (分块流式) / `:1295-1303` (revise 轮) / `:1684-1695` (蒸馏)。
注意 `:1186-1194` 与 `:1238-1241` 的 md_strip 是**收尾**处理, 思维链必须在流式阶段就剥掉 (否则中间帧已经推给前端了)。

- **理由**: `md_strip` 不动 HTML 标签 (§0.3 实测), 顺序颠倒会导致思维链被当成正文留下。

### D9 不动断点 hash 与 schema

`compute_prompt_hash` 不加版本位, `schema_version` 保持 2。

- **代价 (明写)**: 磁盘上**已存在**的旧断点里若含思维链, 命中缓存时仍会把脏结果复用回来。
  出口: 右键「重新校对（忽略缓存）」/ 结果来源提示条的强制重跑 (v5.3.0 已就位), CHANGELOG 明示让用户重跑一次。
- **否**: 加 `|ts=1` 让全部历史断点一次性失效 —— 用户已校对过的每个文件都要重新烧一遍 token, 代价远大于收益
  (与 v5.3.0 引入 `|wm=` 那次不同: 那次是**轨道正确性**, 必须失效)。

### D10 可观测: 每次剥离记一条日志

格式: `[思维链] <文件名>: 丢弃 N 块 / M 字符` (0 块时不打, 避免噪音)。不改 UI 布局, 不加统计面板。

- **理由**: D3 的代码围栏豁免会漏, 日志是用户唯一能发现"漏了一段"的线索。

---

## 3. 目标行为规格 (边界逐条)

### 3.1 块的定义

- 开标签: `<` + 标签名 + 可选属性 + `>`; 标签名大小写不敏感; 允许标签前后空白
- 闭标签: `</` + 标签名 + 可选空白 + `>`
- 成对要求: **必须同名**才算一块 (`<think>…</thinking>` 不构成一对, 各自按"未闭合"处理)
- 容器内的换行、Markdown、代码围栏一律照原文, 整块丢弃

### 3.2 边界表 (测试逐条覆盖)

| # | 输入 | 期望输出 |
|---|---|---|
| B1 | `<think>a</think>正文` | `正文` |
| B2 | `<THINK>a</THINK>\n\n正文` | `正文` (大小写不敏感, 前导空行去掉) |
| B3 | `<think foo="1">a</think>正文` | `正文` (带属性) |
| B4 | `<think>a</think><think>b</think>正文` | `正文` (多块) |
| B5 | `前言<think>a</think>正文` | `前言<think>a</think>正文` — **中间块保留 or 剥?** → 见 §11 待拍板 (默认: **剥**) |
| B6 | `<think>a` (未闭合, 流结束) | `` (整体丢弃) |
| B7 | `<think>a</thinking>正文` | `<think>a</thinking>正文` (标签名不同, 不构成块) |
| B8 | ```` ```\n<think>样例</think>\n``` ```` | 原样保留 (代码区内不剥) |
| B9 | `` `<think>a</think>` `` (行内反引号) | 原样保留 |
| B10 | `<div>a</div>` | 原样保留 (白名单外) |
| B11 | `<thinking>a</thinking>` | `` (白名单命中) |
| B12 | 空字符串 / 纯空白 | 原样返回 (不抛异常) |
| B13 | `<think>` + 正文 + `</think>` 跨越 3 个 delta | 与一次性剥离结果一致 (流式一致性) |

### 3.3 流式契约 (写进模块 docstring, 测试锁定)

1. `feed()` 返回的每段都是"可显示文本"; 任意时刻 `累计 feed` 是上一次累计的**前缀延长** (不回溯)
2. `"".join(feed(d) for d in deltas) + flush() == strip_thinking("".join(deltas))`
3. `flush()` 幂等 (调用两次第二次返回空)
4. 标签被切开、属性跨帧、多块连续 —— 结果不得依赖切分方式

### 3.4 日志格式

`[思维链] <文件名>: 丢弃 N 块 / M 字符` (N=0 时不打)

---

## 4. 路径 × 形态 行为矩阵 (改造后)

| 路径 | 代码位置 | 独立字段 (1/2 类) | 内联标签 (3 类) |
|---|---|---|---|
| 逐条校对 (harness, 非流式) | `processor.py:868-956` | 不读, 不进结果 | content 整体不参与结果; 但 content 含编辑载体 → `WARN_EDIT_IN_CONTENT` |
| 整篇校对 (流式) | `processor.py:780-838` | 不读, 不进结果 | `ThinkFilter` 实时剥离 (预览 + 最终 + 断点) |
| 去 AI 味 · 分块改写 | `web_backend.py:1074` | 同上 | 同上 (逐块剥离, 拼接前) |
| 去 AI 味 · revise 轮 | `web_backend.py:1295-1303` | 同上 | 同上 |
| 去 AI 味 · 风格蒸馏 | `web_backend.py:1684-1695` | 同上 | 同上 |
| 本地模式 (`punct_local` / `md_local`) | 不调 LLM | 不适用 | 不适用 |

---

## 5. 改动清单

| # | 类型 | 文件 | 内容 | 估计行 | 风险 |
|---|---|---|---|---|---|
| 1 | 新增 | `app/think_strip.py` | `THINK_TAGS` + `strip_thinking()` + `ThinkFilter` (含代码围栏豁免 + 未闭合持有) | +150 | 🔴 |
| 2 | 新增 | `tests/test_think_strip.py` | §3.2 边界表逐条 + §3.3 切分一致性 (遍历切点) + 幂等 | +180 | 🟡 |
| 3 | 改 | `app/processor.py` | 流式路径接 `ThinkFilter` (`:798-838`): 节流 emit 与块末 emit 都走过滤后文本; 空结果判据 (`:825-827`) 改剥后 | +30/-8 | 🔴 |
| 4 | 改 | `app/processor.py` | harness 收口 (`:929-955`): content 去 think 后含 `old_text`+`new_text` → 追加 `WARN_EDIT_IN_CONTENT` (index=-1) | +25 | 🟡 |
| 5 | 改 | `app/processor.py` | 剥离日志 (D10) | +10 | 🟢 |
| 6 | 改 | `app/web_backend.py` | DeAI 三处流式接 `ThinkFilter` (`:1074` / `:1295-1303` / `:1684-1695`) + 日志 | +45/-10 | 🔴 |
| 7 | 改 | `tests/test_chunk_lifecycle.py` | 新增: 假 delta 流含 `<think>` 与 `reasoning_content` → `corrected` 无思维链; 剥后为空 → 走重试链 | +70 | 🟡 |
| 8 | 改 | `tests/test_web_backend_deai.py` | 新增: 三处 DeAI 流式剥离 + 蒸馏; 现有假流用例补 `reasoning_content` 字段的负向断言 | +60 | 🟡 |
| 9 | 改 | `tests/test_harness.py` | 新增: content 含 `old_text/new_text` → `WARN_EDIT_IN_CONTENT` + `warnings=True`; content 为"无需修改" → 保持正常完成 | +40 | 🟡 |
| 10 | 改 | `tools/smoke_ui.py` | 端到端: 桩推含 `<think>` 的 `onStream` → 预览与最终 diff 都不含思维链 | +30 | 🟢 |
| 11 | 改 | `README.md` / `AGENTS.md` / `CHANGELOG.md` / `docs/ROADMAP.md` | 特性说明 + 决策条目 + v5.4.0 条目 + 进度 | +60 | 🟢 |
| 12 | 改 | `tests/test_components.py` | 纯函数模块入库断言 (`THINK_TAGS` 非空 / 幂等 / 空输入不炸) | +15 | 🟢 |

**合计**: 2 新增 + 10 改, 净增约 715 行。

---

## 6. 测试计划

### 6.0 既有断言必须逐个复核 (实施时逐条过)

| 位置 | 为什么会被碰 | 要做什么 |
|---|---|---|
| `tests/test_chunk_lifecycle.py:479` (`test_m4_stream_monotonic_fulltext`) | 假 delta 流经过新增过滤器 | 断言链不变; 补一条含 think 的对照组 |
| `tests/test_harness.py` 空 content / 无 tool_calls 用例 | harness 收口会影响 warnings | 确认"无需修改"路径仍判成功; 补 `WARN_EDIT_IN_CONTENT` 用例 |
| `tests/test_web_backend_deai.py` 各处假 `onDeaiStream` 断言 | 推送文本经过滤器 | 纯正文必须逐字不变 (回归硬要求) |
| `tests/test_components.py` 模块清单/纯函数套件 | 新增模块 | 若存在"模块清单"断言需同步 |
| `tools/smoke_ui.py` 既有 91 项 | 前端无改动, 应全绿 | 作为回归基线 |

### 6.1 必须新增

- `strip_thinking`: §3.2 全 13 条边界
- `ThinkFilter`: 遍历**所有切点** (2 段 / 3 段) 断言 §3.3-2 不变式; `flush()` 幂等
- 大文本性能: 50K 字符含 5 个思维链块, 单次剥离 < 50ms (防止实现退化成 O(n²))
- 引擎级: `_stream_single` 假流 (含 `<think>` + `reasoning_content`) → `corrected` 干净、预览链单调
- 引擎级: 纯思维链输出 → 剥后为空 → 走既有重试链, 耗尽后 FAILED (不静默成功)
- DeAI 三处: 分块 / revise / 蒸馏 各一条剥离断言
- harness: `WARN_EDIT_IN_CONTENT` → `audit_has_warnings()` → `FileResult.warnings=True` 全链

### 6.2 必须回归

- `run_all_tests.py` 全绿 (基线 **1463 / 0**; 期望净增)
- `tools/smoke_ui.py` 91 项全绿 + 新增端到端项
- 纯正文输出**逐字节不变** (最重要的回归: 过滤器不能动正常结果)

### 6.3 手工冒烟 (不可省)

1. 真机接一个内联 `<think>` 的端点 (或临时把本地 mock 服务指向会输出 `<think>` 的脚本):
   逐条校对 → 结果与 diff 均无思维链, 日志有 `[思维链]` 一行
2. 同一文本走整篇校对 → 流式预览全程不闪思维链
3. 去 AI 味 3 步 → 三处输出均无思维链
4. 故意让输出在 think 块中途截断 → 结果为空 → 走重试/失败, 不产出半截思维链

---

## 7. 风险表

| # | 风险 | 概率 | 影响 | 处置 |
|---|---|---|---|---|
| R1 | 过滤器误删用户正文里合法的 `<think>` 字样 | 中 | 高 (静默丢内容) | D3 代码围栏豁免 + 只剥白名单 + D10 日志; 测试 B8/B9/B10 |
| R2 | 流式与最终结果不一致 (预览闪回/残留) | 中 | 中 | D4 不变式 + §3.3-2 切分遍历测试 |
| R3 | 剥后为空把正常"无需修改"整篇轨结果误判为空输出 | 低 | 中 | 只对**流式路径**应用空判据; harness 路径单独处理 (D6) |
| R4 | 性能: 每帧全量重算 | 低 | 中 | 只在既有节流点重算; 50K 基准测试兜底 |
| R5 | 旧断点复用脏结果 | 高 | 中 | D9 不失效 + CHANGELOG 指引强制重跑 |
| R6 | `WARN_EDIT_IN_CONTENT` 误报 (模型正常回复里恰好含 old_text/new_text) | 低 | 低 | 只是 warnings 不是失败; 文案写清"疑似" |
| R7 | DeAI 蒸馏输出本身含 `<think>` 教学示例 (风格卡里要举例) | 低 | 中 | 蒸馏产物不落 `corrected`, 但要复核 §8-4 的样本; 必要时蒸馏路径豁免剥离 (审计裁定) |

---

## 8. Session 划分

| Session | 内容 | 工时 | 产出 |
|---|---|---:|---|
| S1 | `app/think_strip.py` + `tests/test_think_strip.py` (纯函数与状态机, 不接线) | 3-4h | 可独立验证的剥离内核 |
| S2 | 引擎接线: `processor.py` 流式 + 空判据 + 日志; 引擎级测试 | 3-4h | 整篇校对干净 |
| S3 | DeAI 三处接线 + 相关测试 | 3-4h | 去 AI 味干净 |
| S4 | harness 收口 (`WARN_EDIT_IN_CONTENT`) + 测试 | 2h | no-op 可见 |
| S5 | 冒烟 + 文档四件套 + 全量回归 | 2-3h | 可发布 |

每个 session 独立可回滚; S1 不接线, 零行为变化。

---

## 9. Phase 2 候选 (本版不做)

1. **思维链留档**: 丢到独立面板 / 落盘 `think_log/`, 不污染结果 (需 UI)
2. **开关**: `think_strip: bool = True` 配置项 + 参数页复选框
3. **更多标签变体**: `<|think|>` / `<|begin_of_thought|>` / `<scratchpad>` (拿到真实样本再加)
4. **content 里的编辑 JSON 解析**: content 含可解析的编辑对象时直接当编辑用 (替代只记 WARN)
5. **无标签内联思维链**: 需要模型侧 prompt 约束或启发式切分, 风险高本版不做

---

## 10. 验收标准 (DoD)

- [ ] `strip_thinking` / `ThinkFilter` 边界表 + 切分不变式全绿
- [ ] 三条链路 (整篇校对 / DeAI 分块 / revise / 蒸馏) 输出不含内联思维链
- [ ] 流式预览全程无思维链闪现, 且预览累计 == 最终结果
- [ ] `reasoning_content` / `reasoning` 有负向测试锁死
- [ ] 纯正文输出逐字节不变 (回归硬要求)
- [ ] 纯思维链输出 → 判失败 (不静默成功), 日志明示原因
- [ ] harness `0 tool_calls` + content 含编辑载体 → `warnings=True` + 改动清单可见
- [ ] 每次剥离有日志; 代码区内的 `<think>` 不被剥
- [ ] `run_all_tests.py` 全绿 (≥ 基线 1463) + 冒烟 91 + 新增项全绿
- [ ] 文档四件套更新; CHANGELOG 明示"旧断点可能含思维链, 需强制重跑"

---

## 11. 待拍板 (给推荐值, 不阻塞; 审计可推翻)

1. **中间块 **(B5)**: 正文中间出现的 `<think>…</think>` 剥不剥?
   **推荐: 剥** — 模型常先说"我检查一下"再开块; 代价是文档里合法中间块会被吃 (已由代码围栏豁免 + 日志缓解)。
2. **代码围栏豁免** (§2 D3-4): 保留豁免 (推荐, 防静默丢内容) 还是全量剥 (实现简单, 但会吃掉文档样本)?
3. **旧断点**: 不失效 + 提示重跑 (推荐) 还是加 `|ts=1` 强制全量重跑?
4. **D6 harness 收口**是否纳入本版 (推荐纳入: 它是同一族"思维链/工具链"问题, 且零 UI 改动即可可见)?

---

## 12. 执行记录 (按 session 回填)

| Session | 状态 | commit | 备注 |
|---|---|---|---|
| S1 剥离内核 | ⏳ 待做 | — | — |
| S2 引擎接线 | ⏳ 待做 | — | — |
| S3 DeAI 接线 | ⏳ 待做 | — | — |
| S4 harness 收口 | ⏳ 待做 | — | — |
| S5 冒烟 + 文档 | ⏳ 待做 | — | — |

---

## 附: 证据清单 (审计可逐条复核)

| 引用 | 内容 |
|---|---|
| `app/processor.py:798` | 流式只取 `event.choices[0].delta.content` |
| `app/processor.py:809` / `:836` | 节流 emit 累计文本 / 块末 emit 全量 |
| `app/processor.py:825-827` | `corrected` 为空 → `raise ValueError` |
| `app/processor.py:909-910` | harness 把 `message` 交给 `parse_tool_calls` |
| `app/processor.py:929-939` | 有效编辑全未生效才 raise |
| `app/processor.py:950-951` | "模型未提交编辑 (无需修改)" 分支 (无 warnings, 判成功) |
| `app/processor.py:706` / `:868` | `_stream_single` / `_harness_call` 入口 |
| `app/harness.py:107` | TOOL_DISCIPLINE: 无错时回复"无需修改" |
| `app/harness.py:196` / `:282-285` | 整轮级 WARN 条目 (`index=-1`) 既有先例 |
| `app/harness.py:291-304` | `audit_has_warnings()` 把 `WARN_*` 判为 warnings |
| `app/web_backend.py:1074` | DeAI 分块流式只取 `delta.content` |
| `app/web_backend.py:1186-1194` | 收尾 md_strip (空结果兜底) |
| `app/web_backend.py:1238-1241` | revise 轮 md_strip |
| `app/web_backend.py:1295-1303` | revise 流式路径 |
| `app/web_backend.py:1684-1695` | 蒸馏流式路径 |
| `app/md_strip.py:27` | HTML 标签原样保留 (实测 `<think>` 不被剥) |
| `app/ai_score_local.py:318` | 本地评分入口 (把思维链当正文) |
| `web/app.js:1777-1778` / `:1934-1935` | 前端增量渲染的前缀单调契约与回缩保护 |
| `CHANGELOG.md:72` | v5.1.0 烟测: MiniMax content 含 `<think>`, 当时结论"harness 不受影响" |
| `tests/test_chunk_lifecycle.py:479` | 既有假 delta 流测试范式 (实现期直接复用) |
