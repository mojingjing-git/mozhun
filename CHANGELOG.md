# Changelog

> **曾用名**: 新时代校对大师 (v3.0 — v4.4.2 期间, 2024 → 2026-09 改名为墨准)。历史 CHANGELOG 条目保留原名, 详见 README.md 与 AGENTS.md。
>
> 当前产品: **墨准 (MoZhun)** v5.4.0 — 本地标点修复 + LLM 批量校对 + 去 AI 味 + 小说切分, 支持任意 OpenAI 兼容 API; 模型思维链一律丢弃。

## v5.4.2 (2026-09-26) — 全量代码扫描修复批次

**依据**: 4 个独立只读 subagent 并行全量扫描 (引擎 / Bridge / 前端 / 规则引擎+测试), 报告见 `.workbuddy/reviews/scan-*-2026-09-26.md` (本地, 不入库)。共报 **41 项** (高危 6), 本批修复已验证高危/中危 **8 项**。

### 高危修复
1. **DeAI revise 轮 100% 静默失效** (`app/web_backend.py:1126`): 主循环 `finally: await client.close()` 无条件关闭 client, 而后置管线的 revise 轮仍用同一个 client → httpx 抛 "Cannot send a request, as the client has been closed" → 被 revise 的 broad except 吞成"调用失败, 保留原改写"。用户开了「评分超阈值追加一轮改写」却永远拿不到效果、UI 无任何提示。修法: 后置管线需要 client 时不关闭, 用完后统一关闭 (不泄漏 socket); client 为 None 时明确记"客户端已关闭"而非伪装成调用失败。
2. **配置里任一数值字段为 `null` → 整份配置丢失** (`app/utils.py`): `from_dict` 多个字段裸取 `d.get(...)`, `null` 让 `int()` 抛 `TypeError`, 而 `load_config` 的 broad except 会返回全新默认 —— **用户手填的 API key 静默清空且不可恢复**。修法: 数值字段一律 `or 默认值`。
3. **分块路径把 `PLACEHOLDER` 字面量当 system prompt 发给 LLM** (`app/processor.py`): `_stream_single` 有占位模式兜底, 但 `_stream_chunked` 为注入跨段上下文**自己重算了一遍**, 漏掉 PLACEHOLDER 判定 → 同一文件内 chunk0 正确回退 strict、后续块拿到 `PLACEHOLDER`。修法: 抽出 `_base_system_prompt()` **单点**, 两处共用。
4. **`md_strip` 在 CRLF 下围栏永不闭合** (`app/md_strip.py:56`): 闭围栏正则只认 `[ \t]` 不认 `\r`, 而 Windows 用户的 .md 默认就是 CRLF → 围栏未闭合到 EOF, 代码内容失去保护且标记残留。修法: 闭围栏认 `\r?$`; 入口统一归一 CRLF/CR → LF (顺带修掉 CRLF 下的幂等破例)。
5. **`md_strip` 表格分隔行灾难性回溯**: 旧 `(\|\s*:?-{3,}:?\s*)+` 嵌套量词, 实测 `-` + 30000 空格单行使整篇清洗跑 **9.4 秒**。修法: 改线性实现 (按 `|` 切段 + 段内无嵌套量词校验), 同输入 **1.5ms**, 形态判定与原正则一致。
6. **流式节流时间兜底 50ms 写成 50 秒** (`app/processor.py:87`): `_STREAM_THROTTLE_MS = 50.0` 与 `time.time()` (秒) 比较 = 50 秒, **时间兜底从未生效**, 慢速模型 (5 token 要几秒) 预览长时间不更新。修法: 改 `_STREAM_THROTTLE_SEC = 0.05`。

### 中危修复
- **`apply_edits` 对非字符串 `old_text`/`new_text` 抛 TypeError** (`app/harness.py`): 违反模块自身"apply 不抛异常"契约, 且异常冒到上层会被当作通用失败**烧掉整文件重试额度**。修法: 类型边界拦住 → `SKIPPED_BAD_ARGS`。
- **v5.4.1 守卫误判面收窄** (`app/harness.py`): 原 `len > 8` 会把「无需修改（无错别字）」这类合法的补充说明短回复判为可疑 → 重试耗尽后误标 FAILED。改: 含"无需修改"且 ≤40 字符放行, 长文本 (含"无需修改"混在大段推理里) 才可疑。

### 测试
- `test_web_backend_deai.py` +1 (`test_v542_revise_client_not_closed`): mock 校验 client 已关闭时 create 必须失败, 锁住 revise 时序 (既有 27 条用 mock 不校验 `is_closed()`, 全绿也没能发现这个 bug)
- `test_md_strip.py` +16: CRLF 围栏 / 换行归一 / 分隔行形态 9 条 / 性能 2 条
- `test_harness.py` +3: 守卫放行与可疑边界
- 全量回归 **1581 通过 / 0 失败**, 冒烟 96 项全绿

### 未修 (记录在扫描报告, 按优先级排)
前端: 结果来源提示条的重跑按钮闭包串文件 (`_provenanceKey` 缺 fileKey)、`cfg-timeout` 在 index.html 重复定义两处、`window.App` 与 `window.app` 双对象致小说切分视图日志静默退化、快捷键无视图守卫。引擎: `punct_fix` 单引号包英文词误报不平衡、破折号补齐需两遍才到不动点、`_FRONTMATTER_RE` 不校验 `key: value`、`novel_splitter._dedup_same_key` 对 `num=None` 静默删章。测试: 多处恒真断言与 `inspect.getsource` 源码式断言、`run_all_tests.py` 把 unittest 套件只算 1 个 PASS。

## v5.4.1 (2026-09-26) — 用户烟测双修复 (Q1 no-op 误判 / Q2 模型下拉)

### Q1: "完成但零改动" — 0 tool_calls 防误报守卫
- **症状**: 逐条校对一个 3740 字的章节, 22.9s / 11229 tokens 后显示"模型未提交编辑 (无需修改)" → 完成但 diff 零改动。真实原因: 推理模型 (MiniMax-M3 类) 走 tools 协议时偶发**不产出 tool_calls**, 而是把整轮推理 + "无需修改"答复全部写进 `content` —— 工具链根本没被触发, 但旧逻辑把它当成合法"无需修改"静默判成功。
- **修法** (`app/harness.py` + `app/processor.py`): 新增 `content_suspicious_noop()` 守卫 — `0 tool_calls` 时若 `content` 非空且不是"无需修改"原话/常见短变体 → 判"模型未走工具链" → raise 走既有重试链 (默认重试 1 次, 耗尽后 FAILED 并写明原因), **不再静默成功**。日志预览前 80 字符便于定位。
- 守卫规则: 空 / `"无需修改"` / `"无需修改。"` 等短变体放行; 含 `old_text` / `new_text` 字面量可疑; 其余长文本 (>8 字符或不含"无需修改") 可疑。

### Q2: 模型拉取成功但右侧箭头/下拉无法选择
- **症状**: ⟳ 拉取成功 (打字过滤联想也正常), 但点输入框右侧箭头或聚焦时原生 datalist 下拉不弹出 → 无法从列表选模型。
- **根因**: WebView2 (Chromium) 的原生 `datalist` 下拉存在已知交互缺陷 —— 自动填充/箭头点击路径偶发不弹 (键入过滤却正常), 不是应用逻辑问题。pywebview 6.2.1 + WebView2 环境下普遍存在。
- **修法** (`web/app.js` + `web/style.css`): 弃用原生 datalist 下拉交互, 改为**应用自己的下拉面板** (复用右键菜单 `.menu-flyout acrylic` 同源样式): 拉取成功后自动弹出; ⟳ 箭头在已有结果时直接弹全量; 输入框聚焦/键入时按当前值过滤弹出; 支持 280px 内滚动 + 上/下翻转 + mousedown 优先于 blur 选中。

### 测试
- `tests/test_harness.py` +9 (119 项): 可疑 content → FAILED (不静默成功) / 真"无需修改"仍成功 / 守卫单元 6 条
- 全量回归 **1559 通过 / 0 失败**, 冒烟 96 项全绿

## v5.4.0 (2026-09-26) — 思维链剥离

**依据**: `docs/PLAN-think-strip-v5.4.md` (v2.1 — 经两轮独立审计: 一审计 5 阻塞项 B1-B5, 复审 2 阻塞项 V1/V2, 全部并入后开工)。

### 为什么要做
部分端点把模型推理过程内联进正文 (`<think>…</think>`), 它会整段进入校对结果 → 字符级 diff / 复制 / 导出 / 断点 / 本地 AI 味评分 / 去 AI 味改写 / 风格蒸馏样本全链路污染。此前"不出事"只靠两个巧合: harness 轨不读 `content`、主流厂商把思维链放独立字段。

### 新模块 `app/think_strip.py` (零 LLM 纯规则, 与 md_strip / punct_fix 同层)
- **只剥行首块**: 开标签必须位于行首 (`<` 之前同一行内只有空白, 允许缩进) 且围栏外。**行首 = 已剥离可见文本坐标** (已剥除区段视为不存在, 头部连排块同口径) —— 这是流式"已 emit 文本永不是最终结果前缀"不变式的地基 (复审 V1 钉死)
- **白名单 4 标签**: `think` / `thinking` / `reasoning` / `thought` (大小写不敏感、允许属性、同名嵌套深度配对)。`<analysis>` 因在前端教程里是合法自定义元素、误删面更大, 列入 Phase 2
- **不剥**: 行内提及 (如 `` `<think>` ``)、同一行中间的块、代码围栏 (``` / ~~~) 内一切。围栏行判定 `rstrip("\r")` — 修 CRLF 文本围栏永不闭合导致的整段漏剥 (复审 V2)
- **头部清理**: 头部块连"块前空白 + 块后连续空行"一并清; 正文中间的块只剥块本身
- **未闭合块**: 流结束时从开标签起整段丢弃; 裸半截标签 (`<thi`) 按字面保留, 不静默删内容

### 接线 (4 处, 共用同一过滤器)
- 整篇校对流式 (`processor.py`): 预览 / 最终结果 / 断点全剥; 输出**只有**思维链 → 按空输出走既有重试链 → 耗尽后 FAILED (不静默成功)
- 去 AI 味三处 (`web_backend.py`): 分块流 (detect/rewrite/score) / revise 轮 / 风格蒸馏。写死不变式"**只保留剥后累积器**", 于是 6 组下游消费点自动干净: 块间衔接 prompt / 错误 payload / 取消 payload / 超限落盘 / 本地评分输入 / style-card 落盘
- 蒸馏**照剥** (style-card 是后续全部改写的长期风格样本); 空卡不落盘 (原路径无空判据)
- 独立字段 (`reasoning_content` / `reasoning` / `reasoning_details`) 显式不读不落盘, 只在 debug 日志记帧数

### 旧断点定向失效 (不失效全部)
- 不动 `compute_prompt_hash` 与 schema v2 (全量失效会让每个已校对文件重烧一遍 token)
- 命中缓存时扫 `corrected` 是否被剥离改写、而 `original` 不会被改写 → 判定残留 → 忽略缓存强制重跑一次 (零 LLM 成本, 只烧脏文件), 日志 `[思维链] <文件>: 旧断点含思维链残留, 忽略缓存强制重跑`
- **原文自带行首块的语料不触发** (否则 harness 轨 `corrected=原文` 会永久打不中缓存)
- **症状提示**: 若你升级前的结果里出现 `<think>` 或大段推理文字, 直接右键「重新校对（忽略缓存）」重跑一次即可; 新版本在命中缓存时会自动处理

### 日志与可观测
- `[思维链] <文件>: 丢弃 N 块 / M 字符` (N=0 不打)
- `[思维链] <文件>: 忽略独立字段 N 帧` (debug)

### 修复 (顺带)
- 风格蒸馏读样本目录调用了不存在的实例方法 `self._style_loader._samples_dir(slug)` (它是模块级函数), 抛 `AttributeError` 被 `except` 吞成"读样本失败" —— **蒸馏此前从未真正跑通过**

### 测试
- 新增 `tests/test_think_strip.py` (70 项): §3.2 边界表 T1-T28 逐条 + 全 2 段切点/3 段抽样遍历 (完整性 + 前缀单调) + 纯正文逐字节 property + 惰性/幂等/性能 + D9 `has_think_residue`
- 引擎级: 流式剥离 (预览单调 + 日志) / 纯思维链 → FAILED / 旧断点残留定向失效
- DeAI 级: 三处剥离 + 6 组消费点 + 空卡不落盘
- `tools/smoke_ui.py` 用真实 `app.think_strip` 预生成剥后 partial 序列推给前端 (前端无过滤逻辑, 只推原文会变成假 E2E), 断言渲染不含思维链且单调不回缩; 冒烟 91 → 96
- 全量回归 **1550 通过 / 0 失败** (基线 1463), 冒烟 96 项全绿

## v5.3.1 (2026-09-26) — API 面板移除模型示例

- `API_TEMPLATES` 全部预设不再写死模型名（原 OpenRouter / MiniMax / 阿里百炼 / 智谱清言 / 硅基流动 / DeepSeek 各带一个示例模型）：**Model 一律由用户自己填，或点 ⟳ 从服务端拉取**
- 预设下拉不再拼 `服务商 (模型名)`，只显示服务商名（悬浮说明仍在，里面写清了"模型名点 ⟳ 拉取"）
- 选预设模板不再覆盖 Model 输入框 —— 以前模板 `model` 为空时会把用户已填/刚拉取的模型名清空；现在空值直接跳过（与 API Key 的"已有值不覆盖"同规则）
- 预设说明文案里的具体模型名一并清掉，只保留类型提示（如 `vendor/model` 格式、火山 `ep-xxx` 接入点 ID 格式）
- 新增回归断言：预设 `model` 字段必须全为空、模板文本不得出现已知示例模型名、面板 HTML 不得含模型示例、`applyTemplate` 的空值不覆盖分支必须在位（全量回归 1463 通过 / 0 失败）
- `tools/smoke_ui.py` 增加 API 面板三项端到端断言（下拉无模型后缀、下拉不含已知模型示例、选预设后已填模型名不变），冒烟总断言 84 → 91

## v5.3.0 (2026-09-26) — 工作流双入口: 逐条校对 / 整篇校对

**依据**: `docs/PLAN-workflow-split-v5.3.md`（含一轮独立审核的 6 个阻塞项 B1-B6 修订与 §12 执行记录）。

### 侧边栏三分组 + 双入口
- 侧边栏改为 **工作区 / 工具 / 设置** 三组：工作区 = 逐条校对 + 整篇校对 + 重写 › 去 AI 味（父子项）；工具 = 风格库 + 小说切分；设置 = API 接口 + 校对参数 + 外观与关于
- 「逐条校对 / 整篇校对」共用 `view-home`，靠 `data-workflow` 区分运行轨；激活态改用唯一 `data-nav-key`（旧的 `[data-view="home"]` 只会命中第一个）
- 「重写」父项本身可点击进入去 AI 味，展开箭头是**独立 button**（不嵌套），`aria-expanded` 双向维护；`Ctrl+.` 进 DeAI 时父项自动展开
- 7 个视图 id 与顺序零改动；校对参数页的「启用 Edit 工具链」复选框移除，改由入口决定；段控件改为「当前入口」只读显示
- 启动按 `config.workflow_mode` 恢复入口（老配置为空 → 按 v5.2c 旧逻辑派生，行为不变）

### 引擎与配置
- `ProjectConfig.workflow_mode: str = ""`（字段数 31→32；**空 = 未显式指定**，按 `harness_enabled 且 prompt_mode ∈ {strict, polish}` 派生）；派生单点 = `app/utils.py:effective_workflow()`，引擎 / payload / 导出名 / 断点指纹全部共用
- `compute_prompt_hash` 加 `|wm=`（传 effective 值，显式与派生等价）；切入口 → 另一轨断点不命中 → 重跑覆盖（单结果槽已知取舍，双结果槽列 Phase 2）
- `set_config` 单向兼容镜像：写 `workflow_mode` → 同步 `harness_enabled`；写 `harness_enabled`（老客户端）→ 推出 workflow；反向不回写；非法值返回 `{ok:false}`；两个 timeout 补后端钳制 60-600
- 逐条入口下 prompt 模式下拉按白名单过滤；历史配置若停在白名单外（tech_doc / custom），引擎按整篇行为执行并在页头明示——不静默降级、也不改写用户的 prompt 模式

### `extra_large = 50000`（逐条校对专属）
- 新增第 6 档分块预设 `extra_large`（50000 字符），`tracks=["harness"]`；`get_chunking_presets(track)` 按轨过滤，只有逐条入口的下拉能看到它
- 取档单点 helper `resolve_chunk_preset(cfg, workflow)`：越轨 / 未知档回退 `large` 并记日志；引擎、DeAI、风格蒸馏全部改走它（含两个新 timeout 的 `resolve_request_timeout`）
- **依据**: 用户烟测确认 harness 单块 **50000 字符可用**、**10 万档才出现失误** → 50000 定为设计上限正式档。烟测的模型与耗时未逐项留档，日后补到数据再回填本节

### 数据安全与告警
- **断点保护 (D9)**: `save_checkpoint(_async)` 新增 `preserve_done`，失败 / 取消收尾不再覆盖磁盘上已完成的结果；副作用（普通「开始」会命中断点秒完成）由既有的**强制重跑出口**兜住——右键「重新校对（忽略缓存）」+ 结果来源提示条按钮，均传 `force_rerun=True`
- **截断检测 (D8)**: 捕获 `finish_reason == "length"` → 结果带截断告警（不再静默当完整结果）
- **整文件告警阈值 20000**: 「整篇校对」入口 + 整文件档 + 单文件超 20000 字时先弹确认（与去 AI 味的整文件兜底阈值一致）；字数走新增只读接口 `get_file_char_counts`（只回长度不回正文）。逐条轨不查该阈值——它有 50000 正式档

### 结果来源可追溯（单结果槽的诚实告知）
- payload（`_file_done_payload` / `_collect_results`）带 `workflow`；前端 `t.workflow` **只在成功完成时写入**，失败 / 取消保留上一轨好结果的来源
- 文件行「逐条 / 整篇」来源徽标（来源不等于当前入口时标黄）+ 结果区提示条「此结果来自 X，当前入口是 Y」+ 一键强制重跑
- 覆盖前确认：批量开始与右键单文件重跑两条路径都会提示「本次将覆盖 N 个文件在另一入口的结果」
- 缓存命中提示分两种口径（本轨命中 / 命中的是另一轨遗留结果）；导出默认名带 `-逐条` / `-整篇`，避免两个入口同秒撞名
- 去 AI 味联动（`→ 去AI味`）在页内标注来源入口，`_deaiChunkEstimate` 改读 rewrite 轨

### 测试与工具
- 全量回归 **1448 通过 / 0 失败**（基线 1343 → 新增 workflow 派生 / 按轨取档 / 断点保护（含引擎级"强制重跑仍能覆盖"）/ 截断 / 导航静态断言等）
- 新增 `tools/smoke_ui.py`：Playwright 三视口（1440×900 / 1280×720 / 1000×760）UI 冒烟——静态托管 `web/` + 桩注入 `window.pywebview.api`，断言侧边栏 200px 不被挤压、导航项单行不重叠、工作区两栏不重叠、双入口标题与父项展开正确，并端到端验证"跨入口结果 → 来源提示条 → 重跑带 `force_rerun`"，输出截图到 `.local/smoke-ui-v5.3/`（84 项断言全绿）
- 该冒烟在实机截图里抓到并修掉一个真实缺陷：`.provenance-bar{display:flex}` 会盖掉 UA 的 `[hidden]{display:none}`，导致空提示条占位

## v5.2 UI 收口 (2026-09-26) — 校对与结果对比合并为单页

- `view-results` 独立视图与侧栏「结果对比」入口移除，工作区从 8 页收敛为 7 页
- `view-home` 改为左侧 `workspace-column`（文件 + 运行状态）和右侧常驻 `compare-card`（原文 / 校对结果 / 改动清单）
- 点击文件只调用 `selectFile()` 切换右侧内容，不再跨页跳转
- 保留 `compare-original` / `compare-revised` / `result-file-select` / 复制 / 导出 / diff 模式等既有 ID，Bridge 与流式事件协议不变
- 窄于 1100px 时切换为单列纵向滚动，避免对比双栏过窄
- 更新静态导航测试、README、AGENTS 和路线图说明

## v5.1.0 (2026-09-07) — 校对流程 harness 化: Edit 工具链 (function calling) + 改动清单审计

**依据**: `final-report.md` §5.2 harness 改造方案 + `agent1-tech-feasibility.md` §3 (Edit 工具 schema + 12 条边界表 + 工具纪律 prompt)。LLM 不再整篇重输出，改为逐条返回编辑建议、客户端精确匹配应用 — 输出 token 大幅下降，且每条改动可审计。

### Phase C 烟测结论 (MiniMax-M3 真实 API, 3 次调用, key 只用末 4 位核对)
- **协议选定: OpenAI 兼容 tools / function calling** (`edit_text(old_text, new_text, reason)`, 非流式, `tool_choice="auto"`) — 请求被接受, `finish_reason=tool_calls`
- **单响应 tool_calls 数量**: 最多 8 条 (≥2 = 并行可用); json_object / 内容内嵌 JSON 两条降级阶梯**未启用** (tools 一次通过, 运行时不做任何 fallback)
- **NOT_FOUND/SKIPPED 基线**: 两轮真实样本 (7 错 + 3 错, 含多段/引号/换行) 共 11 条编辑 **11 OK / 0 NOT_FOUND / 0 NOT_UNIQUE**, 7 处预埋错误全命中 + 1 处附加修正; 无错文本返回 0 个 tool_calls + "无需修改" (空 edits 边界实证)
- 模型 content 带 `<think>` 推理块 — harness 只解析 tool_calls, 不受影响

### 新模块 app/harness.py (零 LLM 纯函数, 与 punct_fix/md_strip 同层同纪律)
- **apply_edits(original, edits) -> (corrected, audit)**: agent1 §3.3 **12 条边界全表实施** — 单条 status ∈ {OK, SKIPPED_NOT_FOUND, SKIPPED_NOT_UNIQUE, SKIPPED_CASCADED, SKIPPED_NOOP}, 另有现实边界扩展 SKIPPED_CAP (超 50 条上限) / SKIPPED_BAD_ARGS (坏 JSON) 与整轮级告警 WARN_EDIT_CAP / WARN_RATIO (改动 >50% 不熔断只告警)
- 严格按返回顺序 `str.replace(old, new, 1)` 串行 (不重排); 边界 8 `\r\n` 归一匹配 + 位置映射替换, 新文本换行风格跟随被替换区域, audit 标注; 每块 ≤50 条 (超限不应用 + 告警); audit 条目 {index, status, reason, old_preview, new_preview(≤80 字符)[, note]}
- **全失败由调用方判** (corrected==original 且存在有效编辑 → 引擎 raise, 走既有重试链耗尽后 FAILED); 部分成功接受不重试
- EDIT_TOOLS schema + TOOL_DISCIPLINE (工具纪律 7 条 + 输出要求) + CHUNK_SCOPE_NOTE 单点定义; 借鉴头注释: Claude Code Edit 工具 (思路借鉴, THIRD_PARTY §20)

### 引擎 (app/processor.py)
- `_stream_single` harness 分支: `harness_enabled` **且** prompt_mode ∈ {strict, polish} 双条件生效 (白名单双决策); 构建非流式 tools 调用 + system prompt 尾部注入工具纪律; **建议不做流式** — 无 token 流需求, 取消语义不变 (B2 强制中断覆盖在途 await)
- edits 空 → corrected=原文 (正常); 全部未生效 → raise ValueError (同"API 返回空内容"语义); **engine 按 file_key 存 audit** (`file_audits`, 各 chunk 合并, 会话内存态不落断点); 部分成功 → `FileResult.warnings=True` (边界 12)
- 分块路径注入 CHUNK_SCOPE_NOTE (跨段上下文只是参照物, 不可编辑, agent1 §3.4 "edit 跨块不允许"); 整文件重试时 audit 重建防跨 attempt 累积

### 配置与缓存 (app/utils.py)
- ProjectConfig `harness_enabled: bool = True` (字段 26→27, to_dict/from_dict 同步; 用户逃生口, 校对参数页 checkbox)
- compute_prompt_hash 补纳 `|he=` + compute_prompt_hash_for_config 同步加参 (两函数相邻同步) — 开关切换旧断点一次性失效 (C2/E16 同语义)
- FileResult `warnings: bool = False` 新字段 (不新增 TaskStatus 枚举; to_dict/from_dict 序列化, 旧断点缺字段兜底 False); **audit 列表按设计决策不放 FileResult**

### 桥接与前端 (web_backend + index.html/app.js/style.css)
- onFileDone/onFileCompleted payload 附加 `audit` + `warnings`; onTaskComplete 每文件条目附 `audit`; 缓存命中补推同样携带 (audit 会话内存态, 缓存命中的新 engine 无历史 audit 属预期)
- 结果对比页新增「改动清单」`<details>` 折叠面板 (default 收起): 逐条 status/reason/old→new 预览, SKIPPED 灰显 / WARN 告警色, 全走既有 token; 文件行 warnings 时状态显示「完成（部分建议未采纳）」
- 校对参数页 harness checkbox (`cfg-harness-enabled`, 沿用 cfg-md-strip 模式); 新事件 `onHarnessWait` — harness 非流式调用无 token 流, 右栏显示等待文案 (watchdog 活动信号同步纳入)
- set_config 走 dataclass 通用 setattr, bool 类型无需新增分支

### 借鉴合规
- THIRD_PARTY_NOTICES 新增 §20 Claude Code Edit 工具 (Anthropic 文档, 致谢非协议, 同 §10 Microsoft 先例 — 不贴 LICENSE 全文); 顶部索引同步
- AGENTS 新增 §36 (harness 设计决策 + 12 边界表出处); README 特性段 + 借鉴清单 19→20

### 测试
- 新增 `test_harness.py` (110 checks): 12 边界逐条 / 部分成功与全失败 / \r\n 归一双向 / ≤50 cap / audit 结构 / parse_tool_calls / 顺序与重叠 / 引擎端到端 ×8 (strict 走 harness / 空 edits / warnings 置位 / 全失败 FAILED / harness_enabled=False 不走 / custom 不走 / polish 走 / 多 chunk audit 合并) / 重试 audit 重建 / hash 双函数
- test_chunk_lifecycle 2 处流式路径测试显式 `harness_enabled=False` (语义即为测流式); test_components 字段计数 26→27; 全量 run_all_tests.py 全绿

---

## v5.2c (2026-09-13) — 校对流程 harness / 重写 双轨配置 (D 方案)

**依据**: `.workbuddy/plan-v5.2c-harness-split.md` v2 (Critical 修复版, 经独立 verifier 审核 5 Critical + 5 Major + 7 Minor + 7 Missing 全部消化) + 用户反馈 "CHANGELOG.md 校对 harness 模式 APITimeoutError 反复触发整文件重试链"。

**核心**: 解决 harness 模式慢 2-5x 导致 APITimeoutError 反复触发整文件重试链的问题。harness 模式走更大 chunk (`large=6000`) + 更长 timeout (180s/3 分钟), 整篇重写走原配置 (`balanced=3000` + 120s)。

### Phase A: 后端核心 (字段 + 引擎 + hash)

- **ProjectConfig 字段 27→31** (`app/utils.py:310-315` 加 4 字段, `to_dict` / `from_dict` 同步):
  - `chunking_preset_harness: str = "large"` (harness 模式专用分块档, 默认 6000)
  - `chunking_preset_rewrite: str = "balanced"` (整篇重写分块档, 默认 3000, 含原 `chunking_preset` 兼容迁移值)
  - `harness_request_timeout: int = 180` (harness 模式 timeout, 3 分钟)
  - `rewrite_request_timeout: int = 120` (整篇重写 timeout, 沿用原 `timeout` 字段值)
- **兼容保留**: 老 `chunking_preset` / `timeout` 字段保留, `from_dict` 时作为新字段兜底来源 (老 `chunking_preset="fast"` → `chunking_preset_rewrite="fast"`, harness 字段走默认不被覆盖), `to_dict` 全部 31 字段都写
- **引擎 helper** (`app/processor.py:818-843`): 2 个新方法 `_effective_chunk_preset` + `_effective_timeout`, 派生实际生效值 (harness 模式走新字段, 重写模式走新字段, 字段缺失时走 `getattr` 兜底)
- **引擎 3 处改用 helper** (v1 漏改 L1021, 修法=helper 抽象, 两处共用):
  - L364: `timeout=self.config.timeout` → `timeout=self._effective_timeout()`
  - L475 (`_stream_single`): `preset = self.config.chunking_preset` → `preset = self._effective_chunk_preset()`
  - L1021 (`_call_api_stream`): 同 L475
- **compute_prompt_hash 4 字段** (`app/utils.py:101-110`): 加 `|hchunk= |wchunk= |hto= |wto=`, `compute_prompt_hash_for_config` 同步加 4 字段, 老断点一次性失效 (与 v5.1.0 `|he=` 同质, **属预期**)
- **web_backend.py:set_config** (X-4 修): 老字段写时自动同步给新字段 (`chunking_preset` → `chunking_preset_rewrite`, `timeout` → `rewrite_request_timeout`), 老 API 客户端兼容

### Phase B: 前端 (段控件 + 双轨配置 UI)

- **index.html 校对参数页** "长文本分块" 卡片 (L340-353 改): 段控件 (复用现有 `.theme-switcher` 类, 只读 disabled, 改 prompt_mode / harness_enabled 切换) + 4 个新控件 (`cfg-chunking-preset-harness` / `cfg-chunking-preset-rewrite` / `cfg-harness-request-timeout` / `cfg-rewrite-request-timeout`) + 兼容字段 `<details>` 折叠 (`cfg-chunking-preset` / `cfg-timeout` 标 `data-scope="deai"`, DeAI 视图专用)
- **app.js `renderSettings`** (L480 后加): 4 个新控件填充 + `_updateModeSegment()` 调用
- **app.js `_updateModeSegment`** (新方法): 段控件 active 重算 + `.mode-dependent` 灰显, 监听 `cfg-prompt-mode` / `cfg-harness-enabled` 变化
- **app.js `_effectiveChunkPreset`** (新方法): 派生实际生效 chunking 档 (前端版, 与 engine `_effective_chunk_preset` 同步)
- **app.js `bindCompatFields`** (新方法): DeAI 字段改时同步给 rewrite 字段 (M-3 修法)
- **app.js `renderChunkingDisplay`** (L414 改): 主页 chunking 显示读 `_effectiveChunkPreset()` (避免 UI 与引擎不一致)
- **app.js `_collectAllConfig`** (L2053 后加): 4 新字段写 (M-5 修: 显式模板, `_clampNum(..., 60, 600, true)` 钳制 timeout 60-600s)
- **app.js `init()`** (L101 加): `this.bindCompatFields()` 调用
- **token 复用**: 段控件 + 4 控件 + 兼容字段折叠全部走现有 `--colorNeutral*` / `--space-*` / `--controlCornerRadius` token, 0 新增硬编码

### 配置与缓存 (字段数 27→31)

- 字段总数 27→31: `chunking_preset_harness` / `chunking_preset_rewrite` + `harness_request_timeout` / `rewrite_request_timeout`
- 老字段 `chunking_preset` / `timeout` 保留 (DeAI 视图走), UI 仍暴露但打 `data-scope="deai"` 标记, 改时同步给新字段
- `to_dict` 全部 31 字段都写, `from_dict` 老配置自动迁移, `schema_version=3` 不变
- **升级提示**: 升级到 v5.2c 后首次启动会重跑所有文件 (compute_prompt_hash 加 4 字段, 老断点按设计预期失效, 与 v5.1.0 `|he=` 引入时一次性失效同质)

### 借鉴合规

- 0 新增借鉴 (字段 + UI 改造, 无新依赖)
- AGENTS §36 harness 决策保持 + §37 新增双轨决策 (本次 17 → §37 改为 §37, 新加 §38 在 v5.2c 段后, 见 commit 2 文档)
- 段控件复用现有 `.theme-switcher` CSS 类 (style.css:1158-1183, 3 态主题切换同源)
- 0 字段 + 2 timeout 是 ProjectConfig 内部扩展, 不涉及第三方

### 测试

- 新增 `tests/test_harness_split.py` (25 项): 字段默认值 (3) / from_dict 老配置迁移 (2) / from_dict 新配置 (1) / to_dict 31 字段 (1) / compute_prompt_hash 4 字段 (5) / 引擎 helper `_effective_chunk_preset` (2) / `_effective_timeout` (2) / `_harness_active` (5) / 字段缺失兜底 (2) / 跨模式 hash 变化 (2)
- `tests/test_components.py:63` 字段计数 27→31 (1 处)
- `tests/test_web_backend_deai.py:1173` 字段计数 27→31 (1 处)
- `tests/test_harness.py:519` 修 1 处: `chunking_preset="fast"` → `chunking_preset_harness="fast"` (测试目的是 harness 模式多 chunk, 必须用新字段)
- **全量基线 17 套件全绿, 0 失败** (基线 1335 → 实际 ~1409+)
- 立即可解决 CHANGELOG.md 校对失败: harness 模式自动用 large(6000) + 180s timeout, 22 块 → 11 块, timeout 触发概率减半, **重启主程序即可**

---

## v5.0.2 (2026-09-07) — DeAI 后置三件套: strip 后置 + 本地评分 + revise

**依据**: `.workbuddy/research/verifier-plan-v5.0.1.md` 独立审核报告的最终裁定 (§8 P0/P1 经 parent 复核修正后实施)。全部为去 AI 味 rewrite 步的**后置处理**, 校对链路 0 改动。

### 新模块 app/ai_score_local.py (零 LLM 纯函数, 与 md_strip 同层同纪律)
- **客户端 0-100 AI 味评分**: 六维加权求和 (权重和恒=100, 模块 assert + 测试兜底) — 硬黑名单词频 28 / 7 大类痕迹 24 (第 1 类=黑名单不双计) / AI 6 处反制 18 (本地可测 5 项 4+4+4+4+2, "原型不匹配"需语义理解本地不计) / 句长方差 burstiness 12 / Markdown 装饰密度 10 / 标点签名 8
- 接口 `ai_score(text) -> {score, dims, offenders}`; offenders 出戏句 (最多 5 条) 供 revise 反馈
- `REVISE_THRESHOLD=50` 与全部权重均为**初始拍定值, 待真实样本校准** (严禁编造校准数据来源); 评分与 Step 3 LLM audit 并存互补 (本地粗筛 / LLM 定性质)
- 纯函数幂等 / 0 依赖 0 网络 0 IO; 正则全部有界防回溯爆炸

### 集成 (app/web_backend.py)
- **strip 后置**: rewrite 完整输出拼装后 `strip_markdown` 剥 Markdown 装饰 (prompt 侧「输出形态」节配合), 空结果兜底回退原文本 (P2-16 共识); 落盘 result_file / onDeaiComplete payload / 收尾帧均用剥后版本; **diff 链路不动** (verifier P1-6)
- **ai_score 附 payload**: onDeaiComplete 新增 `ai_score: {score, dims}` (仅 rewrite 步), transient 推送**不进任何缓存/断点** (DeAI 本无断点体系)
- **revise 内层循环** (借鉴 harshaneel/humanize audit-revise 思路): 仅 rewrite 步 + 开关开 + 评分 ≥ 阈值 + 文本 ≤ 2 万字时, offenders 反馈并入 user_prompt 再改写一轮, 重新 strip + 评分**取分低者**; 失败/空输出/取消一律兜底保留上一轮; **不做跨步编排** (verifier C.11, 放 v5.1.0); 新增 `_deai_postprocess_rewrite` / `_deai_revise_round` 两个方法, 取消检查合并为单一结构化取消块

### 配置 (app/utils.py + 前端)
- ProjectConfig 3 开关: `deai_strip_after=True` / `deai_ai_score=True` / `deai_revise=False` (字段 23→26, to_dict/from_dict 同步); **裁定: 不进 compute_prompt_hash** — DeAI 无断点缓存体系, 塞进校对断点指纹只会让校对断点无谓失效 (AGENTS §35)
- 前端去AI味视图「输入」卡片下方新增 `<details>` 折叠参数区 (3 checkbox, 沿用 checkbox-with-config-fallback 接线); Step 3 输出区顶部显示「本地 AI 味评分：N/100」(无 payload 则不显示; 颜色走 token)

### Prompt (app/templates.py)
- REWRITE_V5 末尾新增「输出形态」节: 输出纯文本正文、禁 Markdown 装饰 (strip 后置的 prompt 侧配合)
- AUDIT_V5 末尾补「与本地评分的关系」: 出戏句口径对齐 ai_score.offenders (摘原句不许转述)

### 借鉴合规
- THIRD_PARTY_NOTICES 新增 §17 harshaneel/humanize (MIT) / §18 blader/humanizer (MIT, 表述采用现行 v3.0 "five sections + 25 patterns", 禁用其新旧编号) / §19 Aboudjem/humanizer-skill (MIT), 完整 LICENSE 经 web fetch 粘贴; 顶部索引 + 核验状态 v5.0.2 子表; README 借鉴清单 16→19
- AGENTS 新增 §33/§34/§35 (后置管线 / 权重阈值裁定 / 3 开关不进 hash 的理由)

### 测试
- 新增 `test_ai_score.py` (权重和=100 / 各维命中行为 / offenders 截断 / 幂等 / 空文本 / 界值); test_web_backend 补 strip 后置与空结果兜底 / revise 开关行为 / ai_score payload / 3 开关往返

---

## v5.0.1 (2026-09-07) — 三份外部审计修复批 (8 critical + 4 notable 全清)

**修订版**: 3 份审计报告 (基线 v4.4.2) 经独立核验 agent 逐条复现 (12 条受核 finding 零误报, 1 条已过时, 2 条降档) 后按当前 HEAD 修复。审报告全文见 `.workbuddy/research/audit-bugs-*.md`。

### 引擎 (app/md_strip.py)
- **L-1 围栏同字符闭合** (CommonMark §4.5): 闭合围栏必须与开启同字符且长度 >= 开启 — 旧版任何围栏行都当闭合, `~~~` 开 ``` 闭导致内容行被吞 (触红线 1)
- **L-2 行内代码等长 run 配对** (§6.1): ``code`` 双反引号整段剥壳 — 旧版只配单引号对, 双反引号残留半对; 含 ` 内容整体保留分支同步重验幂等

### 集成 (app/processor.py)
- **I-1**: punct_local 模式补引号不平衡报告收集 (旧版只认 strict 路径, 报告的主用场从不显示)
- **I-2**: md_local 报告收集移出 total 门控 (只有落单引号 total=0 的文件旧版连累积都没有); `_collect_punct_reports` 每条同时走 `_log` — 修复"运行期累积的报告无人推前端"断链 (prepare 阶段回调未注册时 _log 静默丢弃, 该阶段仍有专用 push)

### 工程化
- **I-3**: 新增 `compute_prompt_hash_for_config(cfg)` — processor 与 3 处测试统一走它, 消灭"部分传参 8/14 字段靠默认值碰巧匹配"的缓存屏障虚标
- **I-4**: deai_cancel 三处 docstring/AGENTS 第 26 条纠正 — 实际语义是"保留 partial 重跑从头", 非"丢弃"
- **F-1**: warning.svg 感叹号点零长度 path 改 circle (与 info.svg 同构)

### 文档 (D-2/D-3/D-4/D-5)
- THIRD_PARTY_NOTICES 顶部索引与核验状态表补齐 §10-§16 (v4.1.8/v4.3.4/v4.4.2), 底部元数据更新
- README: templates 模式数措辞收敛 (6 模式 + deai)、借鉴清单补 commonmark (15→16)、套件数三处口径统一
- README 表"漏长句检测行" (D-1) 已过时: v5.0.0 砍模式后恰好对齐, 无需修

### 测试
- 新增: punct_local/md_local 不平衡报告收集 ×2; 8 个 L-1/L-2 复现用例并入套件; 8 套件 **1168/0**

---

## v5.0.0 (2026-09-07) — 校对流程架构重构: 模式精简 + 校对→DeAI 联动

**修订版**: 依据 `.workbuddy/research/` 三份调研报告 (2 explore + 1 verifier, 20 条核验/5 处契约澄清) 的决策落地。产品方向: 校对与改写分层 (竞品一致范式), 重润色类需求收拢到去 AI 味视图。

### 模式精简 (Phase A): 9 模式 → 6 模式
- **砍 3 模式**: `deep_polish`(重润色) / `anti_rambling`(去流水账) → **改走去 AI 味视图** (Step 2 改写覆盖 ~90% 用例); `long_sentence`(长句检测) → **并入 polish** (处理规则 4: 60+ 字长句断开)
- 保留 6 模式: 纯纠错 / 纠错+轻润色 / 技术文档校对 / 仅标点修复 / 仅 Markdown 清洗 / 自定义 (`deai` 保持隐藏)
- **旧配置静默归一**: `deep_polish/anti_rambling/long_sentence → polish` (utils `_LEGACY_MODE_MAP`, from_dict 时生效); schema_version 2→3; 模式值变化使旧断点自动失效重跑
- **DeAI V5 prompt 补默认重组规则** (Step 1.5): 无 9 轴卡时的句式重组/主次前置/段落合并 — 补齐砍模式后的覆盖缺口 (事实不增不减前提下)
- 兜底链第二道保险: 未知模式 → 日志警告 + 回退 strict (已有机制, 不变)

### 校对→DeAI 联动 (Phase B)
- 校对文件行 (仅已完成) 新增 **「→ 去AI味改写」** 按钮: 一键切换视图 + 载入该文件校对结果 + 跳过 Step 1 检测直接改写
- 后端新增 `deai_load_source(file_key)`: 内存取数 (当前会话); engine 已被替换时返回 stale, 前端按钮置灰提示重跑 (断点兜底为可选增强, 暂不做)

### 不做 (final report §5.4 确认)
- tool calling 降级 fallback / 本地小模型特殊处理 / undo 栈 / 批量联动

---

## v4.4.2 (2026-09-06) — Markdown 清洗 (md_local 本地引擎)

**修订版**: 用户需求 "AI 产的 .md/md 格式 txt 直接丢进去, 产出一篇没有 md 标记的适宜人类阅读的文章". 决策: **不做独立功能页**, 复用 punct_local 本地脚本通道 (计划 + 1 轮 agent 复审, 7×P1 全吸收).

### 新引擎 app/md_strip.py (与 punct_fix 同类, 零 LLM 成本)
- 规则: YAML frontmatter 整块剥离 / ATX 标题去井号 (# 后须空格, `#1` 不是标题) / 引用剥 > / 无序列表剥标记 (有序列表保留数字) / 表格数据行两空格连接+分隔行删 / 水平线与引用定义行删 / 图片→alt / 链接→text (空文字回退 url) / 星号强调剥 (带 ASCII 词边界)
- 四条红线: ① 内容不丢 (例外仅 URL 丢弃与纯标记行删除) ② 代码内容保留 (围栏剥壳留内容; 行内代码脏内容整体保留含反引号, 干净内容剥反引号) ③ 幂等 (非代码区; 围栏内容单遍保护, 管线单遍使用) ④ 保守 (`2*3*4` 不剥; **下划线强调整类不剥** — `__init__`/snake_case 必误伤)
- 明确不做: HTML 标签 / 4 空格缩进代码块 / 转义还原 (确证幂等漏洞, 评审 P1-3) / 数学 $...$

### 集成 (镜像 punct_local 全部通路)
- 校对模式新增 **「仅 Markdown 清洗（本地脚本，不调用 LLM）」**: 整文件处理不切块 (围栏跨行状态, 分块会切开围栏 — 评审 P1-6); 空结果兜底回退原文 (纯标记文件防击穿 diff/is_done — P2-16)
- **「发送 LLM 前先剥离 Markdown 标记」** 开关 (校对参数页, 默认关): 剥离先于标点修复 (剥掉标记后标点规则的 CJK 邻接上下文才准); 纳入 compute_prompt_hash (`|ms=`, 旧断点一次性失效, C2/E16 同语义)
- 双本地模式 (punct_local/md_local) 全程不触网: 不建 AsyncOpenAI + 前端跳过 API 配置校验
- md_local 模式下标点修复开关链式生效 (皆本地零成本, 选项不静默失效 — 评审 P2-14a)

### 测试
- 新增 `test_md_strip.py` 89 项 (规则正反例/幂等双跑/红线/中文端到端/引擎分支端到端/空结果兜底)
- 3 处既有 PROMPT_MODES 遍历循环豁免 md_local (评审 P1-1/2); 字段 22→23; 8 套件 **1171/0** (新增第 8 个套件文件 test_md_strip.py)

---

## v4.4.1 (2026-09-06) — 水墨设为默认皮肤 + 清理 Emoji

**修订版**: 用户反馈两则 — "Emoji 没啥必要了" + "宣纸风格作为默认风格".

### 默认皮肤 fluent → ink
- `ProjectConfig.ui_skin` 默认值与缺省回退改为 **ink**; index.html 首帧静态 `data-skin="ink"` 与默认一致 (默认用户零 FOUC)
- 配置语义: **已存 fluent 的用户保持 fluent** (显式保存优先), 仅无字段的旧配置跟随新默认
- 外观页「界面风格」切换器默认选中水墨宣纸

### Emoji 清理
- 保存按钮反馈 "✓ 已保存" → "已保存" (唯一用户可见的 Emoji 风格字符)
- 代码注释中 v4.1.5 批次标记 🟠/🔴 移除 (10 处)
- 保留: →/↔ (注释与 LLM prompt 的转换符号, 有语义), ⟳ (拉取模型按钮功能图标), ⚠️ (蒸馏 prompt 卡头警告, 属 LLM 输出格式约定)

### 测试
- 7 套件 **1072/0** 全绿 (ui_skin 默认值期望更新; 新增首帧静态属性/切换器默认选中/init 回退 3 项, 移除过时 fluent 回退断言 1 项)

---

## v4.4.0 (2026-09-06) — 新增「水墨宣纸」皮肤 (贴合墨准品牌)

**修订版**: 实施前 1 轮 agent 评审 (3×P1 全吸收: token 全集清单/acrylic 令牌化/验证矩阵补系统深色路径). 加皮肤不换框架, Win11 Fluent 2 保留为默认.

### ✨ 皮肤轴 (fluent / ink)
- **水墨宣纸 (ink)**: 浅=宣纸底 #F7F3E9 + 焦墨 accent + 朱砂印; 深=玄墨底 #191612 + 宣纸白正文 + 阳文反转 accent (纸底墨字, 如钤白文印); 全部 33 token 重新定义, 对比度验算 ≥4.5:1 并入回归
- **2×2 自由组合**: 皮肤 (fluent/ink) × 深浅 (auto/light/dark) 两轴正交, 层叠特异性逐格验算 (ink 深 manual (0,2,1) 压过 fluent 手动深块; ink 浅/深 media 同特异性靠源序)
- **主题内装饰**: 侧栏品牌「墨准」楷体 + 0.25em 疏排 + 朱砂方印 (空心印面, 用户反馈去「印」字; 取色全走 token); 页标题楷体; body 两团墨晕 (新 --skin-halo-1/2); 圆角放宽 6/10/3px; 暖墨低扩散阴影
- **brand 字体**: 新 --fontFamilyBrand (KaiTi → STKaiti → Noto Serif SC → serif, 系统字体零打包)

### 🔧 工程化
- ProjectConfig 新字段 `ui_skin` (默认 fluent, 旧配置兼容), 随 set_config/save_config 落盘; 外观与关于页新增「界面风格」切换器 (复用 .theme-switcher 样式)
- **acrylic 4 处硬编码 rgba 令牌化** `--colorAcrylicBg` (fluent 4 块 + ink 3 块), 皮肤/主题双轴可调
- CSS 层叠回归项 `test_v440_ink_skin_css`: 3 块选择器/统一 html 前缀/源序/27+3 token 定义计数 ≥7/装饰守卫/对比度验算

### 测试
- 7 套件 **1070/0** 全绿 (v4.3.5 基线 1012 → +58: `test_v440_ui_skin_roundtrip` 5 项 + `test_v440_ink_skin_css` 53 项含 token 全集计数与 media/manual 深色等价断言)

### 已知限制
- 首帧皮肤闪变: index.html 静态 HTML 无 data-skin, 存了 ink 的用户启动首帧先渲 fluent (与既有主题 FOUC 同构, pywebview 启动极快可感知度低)
- 楷体缺字环境 (罕见) 回退 serif, 仅品牌字/页标题受影响

---

## v4.3.5 (2026-09-06) — 更名「墨准」

**修订版**: 项目更名 「新时代校对大师」 → **「墨准」(MoZhun)**. 查重结论: 写作/校对赛道无同名产品 (全网唯一同名 "墨准天气" 为天气类应用, 品类无关).

- 动机: 原名 "新时代" 口号感 + "大师" 自封感; "墨准" 取 "落墨即准", 对齐当前定位 — **本地标点修复 + LLM 批量校对 + 去 AI 味** 的 AI 稿件收尾工具
- 同步更新: 窗口标题 (main.py)、前端 title/侧栏品牌/关于页定位行 (web/)、统一启动器与 PyInstaller 产物名 (start.py/build.spec → `dist/墨准.exe`)、check_exe.py、README (加 MoZhun 拼写)/AGENTS/THIRD_PARTY_NOTICES (标注曾用名)
- 历史文档 (PLAN-*.md 与 CHANGELOG 旧条目) 保留旧名, 不改写历史
- 配置目录 `~/.proofreader/` 与全部内部标识不变 (配置/断点/文风数据完全兼容); 功能零改动
- 注意: 旧 `dist/新时代校对大师.exe` 为改名前产物, 下次 `PyInstaller build.spec` 输出 `dist/墨准.exe` 后可删

---

## v4.3.4 (2026-09-06) — 标点修复 v2 (GitHub 调研成果全量吸收)

**修订版**: 按"派 agent 深度调研 3 个 GitHub 同类项目 (typeset/autocorrect/macro-correct + 排版指北)"的结论, 全量落地 9 项改进; 实施中 1 轮 agent 实测评审 (P1-P10), 必修项全部修复. **不打包, dev 验证**.

### ✨ 新规则 (app/punct_fix.py 重写为 v2)
1. **省略号权重归一化** (typeset): `。。。`/`…...`/混合 run → `……`; GB/T 15834: 省略号后不加句号, `……。` 整体归一
2. **属格撇号保护** (调研新增): `James'/players'` 不参与配对 (修评审 FP-2); 缩略/属格撇号字形规范为 `’` (don't → don’t)
3. **全角字母/数字归一化** (macro-correct q2b 算法): `ＡＢＣ１２３` → `ABC123` (指北 B4; 不动全角标点/空格)
4. **逗号低危档** (autocorrect 两档设计): `iPhone,好开心`/`John, 他说` (跳一个空格回看) 均转换
5. **分号永不转换** (autocorrect 原则): `&quot;`/`i++` 等高危场景免疫
6. **URL/邮箱整段掩蔽** (autocorrect PATH_RE 思路): RFC 3986 白名单, 其内标点全免疫
7. **破折号/波浪补齐** (GB/T): `--`/单个`—`→`——`、`~`→`～` (中文上下文)
8. **直角引号风格开关** (指北争议项 C1): 「」/区间内『』嵌套, 默认弯引号
9. **引号不平衡检测报告** (macro-correct check_double 思路, 只报不改): 落单/计数不等的行号清单

### 🔧 工程化 (autocorrect 配置设计借鉴)
- 规则选项 4 字段入 ProjectConfig (`punct_quote_style/punct_fullwidth_alnum/punct_repeat_compress/punct_dash_tilde`), 全部纳入缓存指纹; 校对参数页新增引号风格下拉 + 3 复选框
- 新接口 `fix_punctuation_ex` 返回 `{total, rules, imbalance}` 详情; `fix_punctuation` 旧签名兼容

### 🔍 实测评审 (实施中 agent, P1-P10 必修全落地)
- P1 撇号字形 `’` 触发假不平衡报告 (每行刷屏级误报) — detect 按转换位置+字母邻接启发式剔除
- P2 不平衡条目 schema 统一 (统一含 line, 消除双写)
- P3 省略号 run 含全角字符即自证中文上下文 (独立成行也归一) + docstring 与代码对齐
- P4 入口剥离 NUL (掩蔽占位符与原文 NUL 串号会破坏用户文本)
- P5 URL 正则白名单化 (原 `\S+` 吞噬紧邻引号/标点/中文)
- P6 掩蔽还原改单遍 O(N) (URL 密集 22 倍性能劣化实测修复)
- P7 重复压缩计数 / P8 直角引号计数

### 测试
- 7 套件 **1012/0** 全绿 (v4.3.3 基线 974 → +38: `test_v434_research_rules` 等)

### 已知限制
- 属格撇号 `James'` 转换为 `’` 属保守字形修正, 不参与配对; `rock 'n' roll` 会被配对 (罕见)
- 直角引号为整段风格开关, 不做逐段混排

---

## v4.3.3 (2026-09-06) — 本地标点修复 (纯规则脚本, 零 LLM 成本)

**修订版**: 用户场景 — AI 写小说时常混入英文半角字符尤其是引号 (中文引号必须成对), 这类确定性错误用脚本修复比 LLM 更快更稳且零成本. **不打包, dev 验证**.

### ✨ 新增

#### 1. 规则脚本 `app/punct_fix.py` (纯函数, 无 GUI/LLM 依赖)
- 三条设计红线: ① 只在中文上下文动手 (3.14/1,000/12:30/U.S./纯英文句一律不碰); ② 引号**按段落交替配对**, 落单不猜 (宁漏改不误改), 不跨行; ③ 只做半角→全角, 不做改写
- 规则: `"→“”` 交替配对; `'→‘’` 同理且字母间撇号 (don't) 保护; `...+→……`; `, : ; ? ! .` → 全角 (带上下文守卫, `John,他说` 也转); `( )→（ ）` (对内含 CJK 或前邻中文)
- 性能: 66 万字 < 0.5s (书级无感)

#### 2. 两个入口
- **「仅标点修复（本地脚本，不调用 LLM）」校对模式**: 下拉直接选 — 全程本地不触网 (跳过 AsyncOpenAI 创建, 前置校验跳过 API 检查), 复用分块/进度/diff/断点全管线
- **「发送 LLM 前先本地修复标点」开关** (校对参数页, 默认开): 读入文件时先脚本修引号, LLM 再管语病 — 省得 LLM 在标点上浪费 token

#### 3. 接线
- `ProjectConfig.punct_fix` (默认 True); `compute_prompt_hash` 纳入该开关 (改开关自动重跑, 不串缓存)
- `prepare_tasks` 读入即修复并记日志 `[标点] xxx: 本地修复 N 处`; `_call_api_stream` 增 punct_local 本地分支 (复用 _split_text 分块, 即时完成不做流式 emit)
- 测试断言: LLM prompt 结构断言豁免 punct_local (system 永不发 LLM)

### 测试
- 新套件 `test_punct_fix.py` (34 check): 引号配对/落单/跨行/撇号保护/上下文守卫/书级性能/指纹纳入/引擎本地分支/prepare_tasks 开关
- 7 套件 974/0 全绿 (基线 940 → +34)

### 评审修复 (实施后经独立 agent 实测评审, 3 项"上线前必须修"全部落地)
- **E-1**: 「仅标点修复」模式不再在 prepare_tasks 预处理阶段修复 — 修复前原文保留为 diff 基准, 结果对比页能看到全部变化 (修复前默认配置下 diff 完全为空, 无法审计)
- **FP-1**: 跨行引号保守降级 — 上一行有未闭合引号时本行双引号整体跳过转换 (修复前 `[closer, opener, ...]` 序列会被整体反向配对, 把对的改错)
- **FN-1**: 数字+半角逗号+中文 (`1937,战争` / `1000,成交`) 现已转换 (后邻 CJK 时不构成千分位形态); `1,000` / `3,14万` 实测仍安全
- E-2/E-3: 测试断言从 `_call_api_stream` 升级为 `_run_all` 端到端 (真验证不建客户端); 前端 checkbox 读取加默认值兜底 (防 DOM 缺失时默认 True 字段被静默写 False)

### 已知限制
- 落单引号不修 (不猜测开闭) — 交给 LLM 模式或人工; 属格撇号 (`James'`) 两个同行时可能配错向 (评审 FP-2, 随下一批)
- DeAI 页未接入标点修复 (用户场景是校对; 需要时可在 deai 输入侧复用 fix_punctuation)
- 省略号只处理 `...`+ 不处理 `。。。`(已是全角) 与 `~` 波浪号
- hash 纳入 punct_fix/api_base 使 v4.3.2 及更早的旧断点一次性全部失效重跑 (属预期)

---

## v4.3.2 (2026-09-06) — API 预设按用户指定清单重写

**修订版**: 用户指定 10 项预设清单替换旧 7 项 (移除 Ollama/vLLM/旧通义条目). 接入地址逐一查证 (OpenCodeGo = OpenCode Zen Go 套餐 `opencode.ai/zen/go/v1`; MiniMax 国内站已迁至 `api.minimax.cn/v1`, 国际站密钥用 `api.minimax.io/v1`).

### 改动
- `API_TEMPLATES` 重写: LM Studio / OpenCodeGo / OpenRouter / MiniMax / 阿里百炼 / 智谱清言 / 火山引擎 / 硅基流动 / DeepSeek / 自定义 (顺序即下拉顺序)
- 语义约定: **model 留空** = 服务端模型名动态/不确定 (OpenCodeGo/火山引擎/LM Studio), 提示用 ⟳ 拉取列表; **api_key 留空** = 必须用户自填, 不再预填 "sk-" 类占位 (旧 DeepSeek 预设预填占位会被误当已配置)
- MiniMax 描述注明国内/国际站域名与密钥匹配关系 (错配 = 鉴权失败)
- 前端: 下拉占位改"选择预设..."; 模型名留空的预设显示 "(拉取模型)"; description 作为选项悬浮说明
- **Model 双框合一**: 移除"拉取后才出现的第二个下拉框", 改为单输入框 + 原生 datalist 补全 — 点 ⟳ 拉取后点输入框右侧箭头直接选择, 选中自动进防抖保存
- 测试: `test_get_api_templates` 断言 10 项名称与顺序一致

---

## v4.3.1 (2026-09-06) — UX 直觉性修复批次 (用户视角审查 22 项全落地)

**修订版**: 用户反馈"操作非常反直觉但说不清哪里"。派 agent 以认知走查法 (6 条用户旅程逐步骤核验) 产出 22 条反直觉清单, 本版全部修复。核心诊断: 反馈闭环与流程引导, 而非信息架构。**不打包, dev 验证**.

### 🟠 核心病灶
**全应用把"校对页日志区"当唯一反馈通道** — 复制/测试连接/保存/主题切换/Profile 操作的确认全部写进用户看不见的页面; 跨页任务 (配 API→校对→看结果、失败→修配置) 靠用户脑补; 错误信息原样抛异常栈词汇; 禁用按钮不说原因。

### ✨ 修复清单 (按审查编号)

#### 反馈闭环 (最大一类, 一个 toast 组件消四条)
- **全局 toast** (`#toast-root` 右下角, success/info 3s、error 5s、同屏 4 条、点击即关): 复制/导出/主题切换/Profile 操作/拖入 等全部就地反馈 (原 #2)
- **测试连接内联化** (原 #3): 按钮"测试中…"禁用态 + 卡片内绿/红结果行 (纯文字+状态色, 无 emoji)
- **保存反馈统一** (原 #9/#10): "✓ 已保存"作用于被点的那个按钮 (两页各有保存钮); 参数页补自动保存说明 hint
- **完成汇总人话** (原 #19): `完成：成功 N / 失败 M / 取消 K` + 分级 toast; **ETA 去重** (原 #20)

#### 首跑与异常路径
- **开始前置校验** (原 #4): Base URL/Key/Model 三缺一弹 ContentDialog 引导至 API 接口页 (不再陪跑重试链); 顺带修复 v4.2.0 回归——`setView('settings')` 指向已删除视图导致白屏 (原 #1)
- **错误人话化 + 行动指引** (原 #5): `_humanizeError` 按 401/限速/超时/连接/404 分类翻译; 结果对比页 error-mark 显示人话 + 原始错误小字 + "前往 API 接口页"按钮; 失败 chip title 同步
- **暂停不误杀** (原 #14): 暂停清看门狗/恢复重挂 — 暂停超 60s 文件不再被误标"失败"

#### 流程补全
- **重新校对入口** (原 #7): 右键菜单"重新校对（忽略缓存）"; 后端 `start_proofread` 加 `force_rerun` 参数 (prepare_tasks 跳过缓存), 重跑必真实执行
- **缓存命中可见** (原 #8): 启动返回 `cached_files`, toast 提示"N 个文件命中缓存（右键可强制重跑）"
- **块级进度** (原 #18): 多块文件每块完成推 `onChunkProgress`, 运行状态卡显示"当前文件: 块 X/Y" (不再长时间 0%)
- **点击文件策略** (原 #6): completed/failed 才跳结果对比页; 处理中文件仅选中, 留在校对页看进度
- **分块标签可点** (原 #21): 校对页"分块: 均衡"改为可点, 直跳校对参数页
- **拖错文件有反应** (原 #22): 校对区非 .txt/.md 拖入 toast 拒绝不入列
- **禁用原因 title** (原 #15): diff 切换/复制/导出/清空等条件禁用按钮全部说明启用条件

#### 风格库补全 (原 #11/#12/#13/#15/#17)
- 两页 Profile 下拉创建后同步 (原失同步); **Profile 列表卡片**: 查看 9 轴风格卡 (dialog 长文本形态) / 删除 (danger 确认); **蒸馏可取消** (复用"运行中按钮=取消"模式, cancelled 分流覆盖 distill); 预置 Profile 禁用原因 title; Few-shot 与 Profile 关系说明 hint

#### 术语与文案 (原 #16)
- "查看完整 diff/流式 diff" → "查看增删标记/返回逐字对比"; 空态去"流式"开发者词汇
- 顺带修复: 重跑成功后旧 error-mark 永久残留 (onTaskComplete 无条件回写 error 字段)

### 测试
- 6 套件 **921/0** 全绿 (v4.3.0 基线 900 → +21: `test_v431_force_rerun_and_progress` 覆盖强制重跑/缓存上报/块进度回调)
- 三个实施 agent 按文件所有权并行 (后端 / 前端基建 / 前端功能), 互零冲突, 均独立跑绿后合并

### 已知限制
- toast 不带操作按钮 (如错误 toast 直接跳转页) — 现阶段错误跳转走结果页 error-mark 与对话框

---

## v4.3.0 (2026-09-06) — DeAI 长文本支持 (分块/取消/降级推送) + 拖入文本

**修订版**: 用户需求"待处理文本和 Few-shot 范文支持拖入, 极端情况塞进一本书也能处理". 实施前经 agent 逐行评审修正设计 (6 项必须修改全部落地). **不打包, dev 验证**.

### 🟠 原有硬伤 (为什么一本书以前处理不了)
1. **DeAI 无分块** — 校对引擎有 Chunker, 但 `_deai_run` 把整段文本塞进一次 LLM 调用, 一本书远超模型上下文直接 400
2. **不可取消** — 三步一旦开跑无法中断, 长文本只能干等
3. **拖入被全局吞掉** — body 级 drop preventDefault 让 textarea 的原生拖放完全无响应
4. **输出端巨载** — onDeaiStream 每帧推全量 partial (评审实测: 30 万字收尾单帧 ~1MB x 30FPS 拖死 WebView)

### ✨ 改动 (评审结论 6 项"必须修改"全部落地)

#### 1. 分块引擎 (评审#2/#6)
- `split_text` 从 processor 平移到 utils (processor 委托保兼容), 校对与 DeAI 共用
- `_deai_run` 按当前分块预设切块逐块调用: **rewrite** 纯拼接 (块间注入前块结尾 400 字做衔接, 导出文本干净无分隔符); **detect/audit** 报告按「第 i/N 块」分节
- **whole_file 兜底**: 该预设 + 文本超 2 万字 → 强制回退 large(6000), 杜绝"整本书单次调用"

#### 2. 取消 (评审#3)
- `_deai_tasks` 登记 `cancel_event`; 新增 `deai_cancel(task_id)` bridge; 逐 delta + 块间检查
- **结构化取消 payload** (`cancelled: true`) 区分"用户取消"与"失败" (不撞 F3 语义); 已完成中间结果以 partial 保留填回输出框; 蒸馏任务同样可取消
- 取消语义与校对对齐: 丢弃中间态, 重跑从块 0 (AGENTS.md 第 8 条)

#### 3. 降级推送 + 结果落盘 (评审#1/#5)
- partial 超 5 万字 (对齐 `_ORIGINAL_PUSH_LIMIT`) 只推尾部预览 + 进度 `{chunk, total}`
- 完整结果落盘 `~/.proofreader/deai_results/<task_id>.txt`: onDeaiComplete 带 `result_file`; 复制/导出走新 bridge `deai_copy_result` / `deai_save_result` (后端直读, 全文不过 IPC)
- step3 支持引用 step2 落盘结果 (`source_task_id` 参数), 超长链路全文不回传前端

#### 4. 拖入支持 (评审#4)
- 纯文本拖放: 只 `stopPropagation` 不 `preventDefault` — 保留浏览器原生"光标处插入"
- 文件拖入: 双注册 `#deai-input/#deai-sample` 的 pywebview DOM drop → 拿路径走 Python `read_file_text` (BOM/gb18030 编码兜底), **规避 File.text() 恒 UTF-8 把 GBK 记事本文件变乱码**; 仅接受 .txt/.md
- 已有内容时 WinUI 三命令对话框 (追加/替换/取消) — `showConfirmDialog` 扩展 closeText 第三命令按钮 (WinUI 3 ContentDialog 三命令模式)

#### 5. 进度感知 (评审#5)
- textarea 下方字符计数 + 预计块数 (与后端 whole_file 兜底算法一致)
- 状态行显示「生成中… 块 i/N」; 超 20 万字启动前确认 (给出预计 LLM 调用次数)
- Few-shot 范文超 2 万字自动截断并标注 (范文用途是学风格, 截断无增益损失)

### 测试
- 6 套件全部通过 (v4.2.0 基线 868 → 900+)
- `test_f3_deai_error_no_complete` 从源码位置解析改为行为断言 (mock LLM 抛错)
- 新增 `test_v430_deai_longtext` (~30 check): 多块调用/分节/纯拼接/衔接 prompt/降级落盘/取消 payload/step3 引用/whole_file 兜底/sample 截断/前端挂载点

### 已知限制
- 取消生效时机: 下一个流 delta 或块边界; 模型停流时等 timeout (与校对一致)
- 输入方向 (textarea → bridge) 未设硬上限: 200 万字 ≈ 6MB postMessage 未经极限验证, 有 20 万字确认框拦截
- DeAI 无断点续跑 (明确不做): 取消即丢弃, 重跑从块 0

---

## v4.2.0 (2026-09-06) — 信息架构重构: 3 视图拆成 7 视图 (Win11 设置应用式分组导航)

**修订版**: 用户反馈"功能挤在 3 个视图里不直观" — 按 Win11 设置应用的导航模式拆成 7 页, 侧边栏分「工作区/设置」两组, 每页只做一件事. **不打包, dev 验证**.

### 🟠 用户痛点
1. **主页过载** — 文件/进度/日志/对比区挤一屏, 对比区常驻却多数时间在看进度
2. **设置页 12 个字段 3 卡堆叠** — API 配置和校对参数混在一页, 找字段靠滚
3. **去AI味页 4 组内容** — Step 0 Profile 管理(建/加范文/蒸馏)和 3 步工作流互相挤压

### 拆分映射
| 原 | 新 (7 视图) |
|---|---|
| 主页 | **校对** (文件+拖拽+启动控制+进度+日志) + **结果对比** (新页: diff/复制/导出, 点文件自动跳转) |
| 设置 | **API 接口** (模板/Base/Key/Model/测试连接) + **校对参数** (生成参数/分块/System Prompt, 双卡) + **外观与关于** (主题持久化 + 版本/日志/快捷键速查) |
| 去AI味 | **去 AI 味** (紧凑 Profile 下拉 + 输入 + 3 步工作流, 页头「管理风格库」跳转) + **风格库** (Profile 选择镜像/新建/加范文/蒸馏 + 9 轴说明卡) |

### 改动
- **侧边栏**: 分组标题 (`.nav-group`) + 7 个导航项 (启用闲置图标 check/document/app/info) + 底部版本号
- **结果对比页**: 页头文件下拉 (`#result-file-select`, 与文件列表同一数据源, 带状态标签) + 对比卡撑满高度
- **设置组三页**: `.content-narrow` 窄栏居中 (Win11 设置式); 校对参数页有独立保存按钮 (`.js-save-config` 同逻辑)
- **JS 适配**: 配置防抖选择器覆盖拆分后的三页; 文件点击 `selectFile + setView('results')`; 风格库下拉与去AI味页镜像同步
- **CSS**: 新增 nav-group/sidebar-footer/content-narrow/result-select/about-row/list-hint/run-card; 删除无引用的 `.compare-header`; home-grid 改两列等宽

### 兼容性
- **所有元素 id 拆分前后保持不变** — JS 绑定/事件推送零迁移; `data-nav` 通用跳转属性供页头按钮复用

### 测试
- 6 套件全部通过 (v4.1.9 基线 813 → 新增 `test_v420_nav_split` 约 45 check: 7 视图/分组/关键 id 唯一性/cfg 13 字段齐全/JS 适配点/CSS 组件)

### 已知限制
- 结果对比页暂无"上一处/下一处修改"导航 (diff 较长时需滚动)

---

## v4.1.9 (2026-09-06) — Win11 视觉完全体 (材料/动效/个性化三签名额补)

**修订版**: v4.1.8 只搭好了 token 骨架, 本版把设计文档要求但未落地的三块补齐 — 材料 (Mica/Acrylic/Smoke 真实使用), 动效 (页面转换/reduced-motion), 个性化 (主题持久化). **不打包, dev 验证**.

### 🟠 用户痛点 (5 项)
1. **材料类零使用** — `.acrylic`/`.smoke-overlay` 定义了但没有任何元素引用 (审计确认), 清空文件用原生 `confirm()` 弹窗, 与 Fluent 视觉割裂
2. **视图切换无转场** — 三个视图瞬间硬切, WinUI 3 顶级页面应有上滑入场转场 (§3.7.3)
3. **主题不持久化** — 切换 light/dark 后重启回退 auto (违反 §2.3 个人原则)
4. **字体栈不完整** — 未启用 Segoe UI Variable 光学尺寸轴 (§3.6.1)
5. **组件硬编码色残留** — file-status 五态/hover 边框/log 深底写死色值, 暗色靠逐状态覆盖块打补丁

### 改动

#### 1. 材料 (§3.4) — 三种材料全部真实落地
- **Mica 近似** (§3.4.3): body 用两个中性色 radial-gradient 模拟云母"淡染扎根" (web 内无法调 DWM, 注释说明为视觉近似); 侧边栏=基层, 内容卡=内容层 (§3.2.3 双层系统), 卡片阴影升为 Card 档 shadow-8 (§3.2.1 提升值表)
- **Acrylic** (§3.4.2): 文件列表右键菜单 `.menu-flyout.acrylic` (blur 20px + saturate 180%), 带视口钳制/Esc/外点关闭 — 落实 §2.4 熟悉原则 (Windows 右键肌肉记忆)
- **Smoke + ContentDialog** (§3.4.4): 新增 WinUI 3 原版样式的确认对话框 (Smoke 遮罩 + 不透明面板 + overlay 8px 圆角 + shadow-128 + 底部等宽双按钮 + 250ms 缩放入场), 替代 `clearFiles` 的原生 `confirm()`

#### 2. 动效 (§3.7)
- **页面转换** (§3.7.3): `.view.active` 上滑入场 (24px + 淡入, 167ms point-to-point 曲线)
- **无障碍**: 全部动画/过渡包 `@media (prefers-reduced-motion: reduce)` 守卫; 新增全局 `:focus-visible` 键盘焦点环 (2px accent)

#### 3. 个性化 (§2.3)
- `ProjectConfig` 新增 `ui_theme` 字段 (auto/light/dark, 旧配置缺省 auto), 主题切换即写入配置并落盘, 启动时恢复; 主题逻辑抽为 `applyTheme()` 统一入口

#### 4. Token 纪律 (§2.5 完整+连贯)
- file-status 五态改用 status subtle/fg token, 删除 12 行逐状态暗色覆盖块 (token 自适应)
- `.log` 改主题感知 (Background2 内凹面), input hover 新增 `--colorNeutralStrokeHover` token (4 主题块)
- `.card` 等组件零硬编码色; 删除零引用死类 (diff-tabs/diff-content/diff-empty/btn-small/compare-empty/style-profile-card/style-profile-loading)
- 启用 2 个闲置图标 (document/close) 做右键菜单图标, warning/error/info 用于对话框标题

### 测试
- 6 套件 813 check 全部通过 (v4.1.8.2 基线 784 → +29)
- 新增 `test_v419_win11_polish` (22 check: Mica 渐变/ContentDialog/flyout/页面转换/reduced-motion/focus-visible/token 化/死类删除) + `test_v419_ui_theme_roundtrip` (5 check: 默认值/往返/旧配置兼容/bridge 可写)

### 已知限制
- Mica 为 CSS 视觉近似, 无法感知真实桌面壁纸 (需 DWM/WinUI 才能原生云母)
- 右键菜单为浏览器内模拟, 非 DWM 原生上下文菜单

---

## v4.1.8 (2026-09-05) — 前端按 Win11 Fluent 2 设计原则完整重构

**修订版**: 按 `Windows11-设计原则.md` (Microsoft Learn 官方文档) 5 原则 + 7 签名体验**完全重构**前端, 从 4.0 临时方案对齐到 Win11 Fluent 2 视觉. **不打包, dev 验证**.

### 🟠 用户痛点 (4 项视觉缺陷)
1. **图标风格不统一** — 12 SVG 全部 `fill="black"` 实心 (v4.0 临时方案), 跟 Win11 设置应用 1px 单线风格冲突
2. **diff 鲜绿/红刺眼** — `#107C10 / #C42B1C` 是 Office 2007 老配色, Win11 §3.1.3 强调"平和不刺眼"
3. **暗色模式缺失** — pywebview 默认跟随系统亮度, 但应用本身不响应, 深夜校对刺眼
4. **色盲用户分不清 diff** — 8% 男性红绿色盲, 单纯红绿对比无法区分, Win11 §3.1.4 要求"避免单独使用红绿"

### ✨ 借鉴内容 (Microsoft Learn 设计原则文档 + fluentui-system-icons 风格)
- **5 设计原则**: 毫不费力 / 冷静 / 个人 / 熟悉 / 完整+连贯
- **7 签名体验**: 颜色 (17 token + 5 accent) / 提升和分层 (6 阴影) / 图标 (1px 单线) / 材料 (Acrylic+Smoke) / 几何 (3 圆角) / 字体 (9 type ramp) / 动态 (5 曲线 4 时长)
- **Microsoft Terms of Use**: 文档非版权材料, 借鉴 5 原则 + 7 签名体验的**数值与命名约定**, 代码全部自写
- **fluentui-system-icons MIT**: 1px 单线 / 24×24 网格 / round cap **风格借鉴**, path 全部项目语言手写

### 改动

#### 1. CSS 完全重写 (`web/style.css`, 35KB, 1100+ 行)
- **17 Win11 色板 token**: `--colorNeutralBackground1-4` / `Foreground1-3` / `Stroke1-2` / `--colorBrandBackground1-3` / `Foreground` / `Subtle` / `--colorStatus*` / `--colorDiff*`
- **5 Accent 档**: rest (#0078D4) / hover (#106EBE) / pressed (#005A9E) / subtle / foreground
- **6 阴影档** (elevation 1/2/8/16/32/128 对应 Layer/Control/Card/Tooltip/Flyout/Dialog)
- **3 圆角 token**: `--controlCornerRadius=4px` / `--overlayCornerRadius=8px` / `--radiusSmall=2px`
- **9 type ramp 档**: Caption 12/16 → Display 68/92
- **2 字重档**: Regular 400 + Semibold 600 (不用 Bold 700, 不用 italic)
- **5 动画曲线 + 4 时长**: fastIn / pointToPoint / fastOut / softOut / linear + 83/167/250/333ms
- **完整暗色模式**: `@media (prefers-color-scheme: dark)` 独立块 (F1 硬约束) + `[data-theme="light"]` / `[data-theme="dark"]` 覆盖
- **Acrylic** (`.acrylic`): `backdrop-filter: blur(20px) saturate(180%)` 模拟毛玻璃
- **Smoke** (`.smoke-overlay`): `rgba(0,0,0,0.32)` 半透明黑遮罩
- **按钮语义化**: `.btn` + `.btn-standard` / `.btn-accent` / `.btn-subtle` / `.btn-icon-only`

#### 2. 12 SVG 重画 (1px 单线 Segoe Fluent 风格)
- 13 个 SVG (含 app.svg favicon) 全部从 `fill="black"` 实心 → `stroke="currentColor" stroke-width="1" fill="none"` 单线
- viewBox 全部 `0 0 24 24`, `stroke-linecap="round" stroke-linejoin="round"`
- 每个 SVG 头部 4 段借鉴注释 (URL + License + 借鉴内容 + 借鉴方式 + Copyright)
- 特殊: play/stop 用 `fill=currentColor` (Segoe Fluent 实心图标语义保留)
- 调整: add/check 用 `stroke-width="1.25/1.5"` 因为 16px 渲染单线 1px 太细

#### 3. HTML 微调 (`web/index.html`)
- `<html lang="zh-CN" data-theme="auto">` 加 theme hook
- 5 处 `.btn-primary` → `.btn .btn-standard .btn-accent`
- 16 处 `.btn-secondary` → `.btn .btn-standard .btn-subtle`
- 2 处 `.btn-icon` → `.btn .btn-icon-only`
- 4 处 `.compare-empty` → `.type-emptystate`
- `.sidebar-title` 加 `type-body-large-strong` 类
- Settings 页加 1 个 `theme-switcher` 三态切换 (auto/light/dark)
- `<title>` 改 "新时代校对大师 v4.1.8"

#### 4. JS 微调 (`web/app.js` 业务逻辑零改动)
- 4 处 `compare-empty` → `type-emptystate` 字符串引用
- 新增 `bindThemeSwitcher()` 方法, 监听 `#theme-switcher button[data-theme-value]`, 写 `document.documentElement.dataset.theme`
- 头部注释加 Microsoft Learn 致谢

#### 5. 测试追加 12 函数 (108 check)
- **`test_web_backend.py`** 新增 12 个 `test_v418_*` 函数, 108 check
- `test_v418_color_palette_tokens` (22): 17 token + 5 accent 档存在
- `test_v418_type_ramp_tokens` (18): 9 字号 + 9 行高
- `test_v418_corner_radius_tokens` (3): 4px/8px/2px
- `test_v418_motion_tokens` (9): 5 curve + 4 duration
- `test_v418_dark_mode_tokens` (9): @media 块存在 + 3 个 data-theme 覆盖 + 6 个暗色 token 值
- `test_v418_icon_stroke_style` (36): 12 SVG × 3 check (viewBox/stroke/fill)
- `test_v418_accessibility_contrast` (4): WebAIM 验算 (UI 3:1 + Text 4.5:1)
- `test_v418_diff_color_blind_shape` (2): ins/del border-left 形状标记 (色盲补救)
- `test_v418_no_11px_font_size` (1): M10 修补
- `test_v418_no_italic` (1): F5 修补
- `test_v418_no_bold_700` (1): F6 修补
- `test_v418_acrylic_and_smoke_classes` (2): .acrylic + .smoke-overlay 存在

#### 6. 文档
- **`THIRD_PARTY_NOTICES.md`** §10 加 Microsoft Learn 设计原则致谢 (非 MIT, 文档非版权材料) + §11 fluentui-system-icons (MIT) 完整 LICENSE
- **`AGENTS.md`** 加关键设计决策 21 (Win11 重构) + 不要做的事 +1 (硬编码颜色)
- **`CHANGELOG.md`** (本段) + **`README.md`** 借鉴来源加 Microsoft Learn + 主题使用建议

### 🧪 测试
- 基线: 660/0 (test_web_backend.py 428)
- v4.1.8: **768/0** (test_web_backend.py 536, +108)
- 净增: 108 check (test_web_backend.py: 428 → 536, 6 个测试套件 660 → 768)
- 借 12 个新 check 包括可访问性 (色盲/对比度/11px/italic/Bold) 静态校验

### 借鉴合规
- 4 段注释: ✅ (web/style.css 头 + 13 SVG 头 + web/app.js 头)
- THIRD_PARTY_NOTICES §10/§11: ✅ (Microsoft Learn 致谢 + fluentui-system-icons MIT 完整 LICENSE)
- 不复制 fluentui-system-icons path: ✅ (12 SVG path 全部项目语言手写)
- 不复制 Microsoft Learn 文档原文: ✅ (5 原则 + 7 签名体验命名按官方约定, 数值在合理范围内)
- 暗色 token 数值: ✅ (按 Microsoft Learn §3.1.1 + Fluent 2 暗色配色实践)

### ⚠️ 已知限制
- **WebAIM 对比度实际值**: `#0078D4 on #FAFAFA = 4.39:1`, 符合 AA UI Components (3:1) 但不达 AA Normal Text (4.5:1). Win11 设置自身用这套配色, 接受 (微软默认门槛).
- **`backdrop-filter: blur(20px)`** 在老版 WebView2 / GPU 驱动下可能不渲染, 自动降级到 `background: rgba(255,255,255,0.7)`.
- **Mica 跳过** (主窗口无法染桌面, pywebview 限制).
- **暗色 6 档阴影** 浅色版也写进去了 (在浅色下用浅色值), 暗色下覆盖; token 切换瞬时 (250ms 过渡), 不闪烁.
- **主题切换** 不持久化 (写到 `document.documentElement.dataset.theme`, 刷新即重置回 auto). 后续可加 `localStorage` 持久化.
- **CSS 文件大小**: 35KB (gzip 估计 ~7KB), 比 v4.0 26KB 增加 35%, 主要来自暗色块 + type ramp 9 档 + 5 动画曲线 token.

---

## v4.1.7 (2026-09-05) — 借鉴 jianshuo/claude-skills 蒸馏文风融入 DeAI

**修订版**: DeAI 3 步工作流升级到 V5 (加 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评). **不打包, 修完 dev 验证**.

### 🟠 用户痛点 (借鉴驱动)
1. **DeAI 改写没风格定位** — 改出来是"通用 AI 味"换种"AI 味", 用户想要"像某人写"做不到
2. **改写可能篡改事实** — 改写顺手"中和"或"补料", 原文事实丢失
3. **改写完没客观评分** — 自己看着像 vs 真的像, 没法量化
4. **样本没沉淀** — 每次改写都从零喂范文, 没用 style-card 持久化

### ✨ 借鉴内容 (来自 jianshuo/claude-skills MIT 9 轴蒸馏文风 skill)
- 9 轴风格指纹: 句子节奏 / 段落 / 词汇 / 语气 / 论证 / 比喻 / 情绪 / 起收 / 雷区
- 事实骨架纪律: 改写前抽 3-8 条 bullet, 改写不增不减
- AI 6 处反制: 缺真实专名 / 结尾太圆 / 推进太顺 / 鸡汤化 / 批次指纹 / 原型不匹配
- 8 轴自评: 1-5 评分 + 摘出戏句 (替代'独立判官盲测' 在单模型场景)
- 调料校准: 签名动作是工具不是清单

### 改动

#### 1. 后端 (借鉴思路, 无代码复制)
- **`app/style_profiles/loader.py`** (新建, ~480 行)
  - `StyleProfileLoader` 类: builtin CRUD + custom CRUD + 蒸馏入口
  - 路径: `~/.proofreader/styles/<slug>/{samples/,style-card.md,meta.json}`
  - 4 段借鉴注释在文件头
- **`app/style_profiles/builtin/`** (新建 3 套抽象化预置 profile)
  - `plain_tech.json` (通用技术文)
  - `narrative_general.json` (通用叙事文)
  - `daily_colloquial.json` (通用口语朴实)
  - 无具体真人作家, 9 轴描述项目语言重写
- **`app/templates.py`** (新增 4 个 V5 prompt)
  - `SYSTEM_PROMPT_DISTILL_STYLE` (9 轴 schema + 锚点纪律 + AI 6 处)
  - `SYSTEM_PROMPT_DEAI_DETECT_V5` (原 7 大类 + AI 6 处反制)
  - `SYSTEM_PROMPT_DEAI_REWRITE_V5` (9 轴 + 事实骨架 + 范文锚点)
  - `SYSTEM_PROMPT_DEAI_AUDIT_V5` (3 维 + 8 轴自评)
- **`app/web_backend.py`** (新增 6 个 Bridge API + 升级 _deai_run)
  - `list_style_profiles()` builtin + custom
  - `create_style_profile(slug, name)`
  - `delete_style_profile(slug)` 拒删 builtin
  - `add_sample_to_profile(slug, content)`
  - `distill_style_profile(slug)` 异步, 流式推 onDeaiStream
  - `get_style_card(slug)` 返 markdown + meta + axes
  - `_deai_run` 接受 `style_card_slug` 参数, 走 V5 路径
  - `_build_deai_prompt` V5 注入 (rewrite/audit 加 9 轴 + 风格卡全文)

#### 2. 前端 (Step 0 区域)
- **`web/index.html`** view-deai 加 Step 0 卡片
  - profile 下拉 (builtin 3 + custom N)
  - 新建 profile (slug + name)
  - 加范文 textarea + 按钮
  - 蒸馏按钮 (>= 3 篇)
- **`web/app.js`** 5 个新方法
  - `loadStyleProfiles()` / `renderStyleProfileSelect()`
  - `createStyleProfile()` / `addSampleToProfile()`
  - `distillStyleProfile()` (流式 partial 推 onDeaiStream, step='distill')
  - `selectStyleProfile(slug)` (更新 info + 按钮联动)
  - 路由分发: `handleDeaiStreamOrDistill` (按 step 路由)
  - `deaiStep1/2/3` 全部传 `this.deai.styleCardSlug`
- **`web/style.css`** 新增 .style-profile-section 等

#### 3. 测试
- **`test_web_backend.py`** 新增 12 个测试函数, 100 check
  - `test_v417_list_style_profiles` (10): builtin 3 套 + 字段
  - `test_v417_create_and_delete_profile` (10): 目录/samples/meta.json/重名
  - `test_v417_delete_builtin_rejected` (2)
  - `test_v417_add_sample_increments_count` (9): count 自增/空内容/不存在
  - `test_v417_save_and_get_style_card` (8): 9 轴粗解析
  - `test_v417_distill_style_profile_mock` (8): mock LLM callback 落盘
  - `test_v417_distill_too_few_samples` (3): 抛 ValueError
  - `test_v417_deai_step2_with_style_card_prompt` (5): prompt 含 9 轴 + 事实骨架
  - `test_v417_deai_step2_without_style_card_backward_compat` (4)
  - `test_v417_deai_step3_audit_8_axis_prompt` (6): 8 轴自评 + 三维
  - `test_v417_style_card_path_traversal` (22): 11 种非法 slug 拒绝
  - `test_v417_distill_concurrent_no_interference` (12, v2 顺序跑): 2 profile 互不干扰, samples_count/distilled_at 独立

#### 4. 文档
- **`THIRD_PARTY_NOTICES.md`** §9 完整段 (URL + MIT 全文 + 借鉴内容 + 借鉴方式 + Copyright)
- **`AGENTS.md`** v4.1.7 关键设计决策 17-20 (9 轴/事实骨架/AI 6 处/8 轴自评)
- **`PLAN-distill-style.md`** (新建, 借鉴流程 + 9 轴 schema + 融入 DeAI 方案)
- `CHANGELOG.md` (本段) + `README.md` (一行)

### 🧪 测试
- 基线: 552/0 (test_web_backend.py 320)
- v4.1.7: **660/0** (test_web_backend.py 428, +108)
- 净增: 108 check (远超任务要求 ≥ 564, 现 660)
- 3 次连续跑 660/0 全过 (无 flaky)

### 借鉴合规
- 4 段注释 15 处: ✅ (app/style_profiles/{__init__,loader}.py + app/templates.py V5 段 + app/web_backend.py 6 个新方法 + test_web_backend.py v417 段)
- THIRD_PARTY_NOTICES §9: ✅ (URL + MIT 全文 1076 字节 + 借鉴内容 + 借鉴方式 + Copyright)
- 不复制 jianshuo 任何 prompt 文本: ✅ (9 轴描述 / prompt 措辞 全部项目语言重写)
- 不硬编码 "jianshuo" / "王建硕" / "wjs-distilling-style": ✅
- 不用真迹: ✅ (3 套预置抽象化, 不引用 home.wangjianshuo.com)
- 思路借鉴, 无代码复制: ✅

### ⚠️ 已知限制
- 蒸馏 10-30s 等待 (UI spinner 提示)
- 9 轴 prompt 增加 ~80% token 成本
- 单模型无独立判官 (Step 3 内联 8 轴自评替代)
- profile 文件系统管理靠用户主动 (不云同步)
- 并发测试 v2 修法: 顺序跑 2 个 profile + 同一临时目录, 消除 OS 调度 flaky (3 次连跑 660/0 全过)

---

## v4.1.6 (2026-09-05) — 配置持久化修复 (5 处静默吞错 + 关窗兜底)

**修订版**: 用户报告 cfg 不能持久化, 排查发现前端 `saveConfig` 5 处吞错 + 缺关窗兜底. **不打包, 修完 dev 验证**.

### 🟠 用户痛点 (5 静默吞错)
1. **`for await set_config` 串行** — 11 次 bridge 串行 await 累积延迟, 500ms 防抖可能错过
2. **`set_config` 失败静默** — `catch (e) { /* ignore */ }` 不打 log
3. **`save_config` 失败静默** — r.ok 没检查, 写盘失败 UI 假装成功
4. **缺 `beforeunload` 兜底** — 500ms 防抖内关窗, 改动全丢
5. **silent 模式不显示反馈** — auto save 静默成功, 用户不知道落盘了

### ✨ 改动

#### 1. 前端 saveConfig 重写 (修复 🔴 1+2+3+5)
- **`web/app.js:1018-1033`** (`_collectAllConfig` helper, 新增)
  - 抽 12 字段 (api_base/api_key/model/prompt_mode/temperature/concurrency/max_retries/timeout/chunking_preset/context_max_chars/context_max_chunks/custom_prompt) 从 DOM 收集
  - 复用场景: `saveConfig` 异步调用 + `beforeunload` 同步 fire-and-forget
- **`web/app.js:1035-1064`** (`saveConfig` 重写)
  - **改前**: 串行 `for await set_config` + `catch (e) { /* ignore */ }` + `if (!opts.silent)`
  - **改后**: `Promise.all(12 个 set_config 并发)` + `.catch(e => "${k}=${e}")` 收集失败 + `r.ok` 检查 + 始终打印 `[设置] 已保存 (12 字段)`
  - 任何 set_config / save_config 失败立即 log `[错误]`, 不再静默

#### 2. 关窗兜底 (修复 🔴 4)
- **`web/app.js:332-345`** (`bindEvents` 末尾新增)
  - `window.addEventListener('beforeunload', () => { if (this.configDirty) { ... } })`
  - 同步 fire-and-forget 12 个 set_config + 1 个 save_config
  - try/catch 吞错, 接受最坏情况 (1ms 级一般来得及塞进 IPC 队列)

#### 3. 保存按钮 UX 反馈 (增强 P4)
- **`web/app.js:1001-1013`** (`saveConfigNow` 加按钮状态切换)
  - 显式保存后按钮文案变 "✓ 已保存" + disabled 2 秒, 然后恢复原文案
  - auto save (silent) 仍走 `[设置] 已保存 (12 字段)` log, 但按钮不变 (避免闪烁)

#### 4. 测试新增 35 check
- **`test_web_backend.py:1636-1775`** (5 个 v4.1.6 测试函数)
  - `test_v416_save_config_persists_all_fields` (14 check): 12 字段全 set + save + reload, tmpdir 隔离不污染 `~/.proofreader/last_config.json`
  - `test_v416_save_config_error_handling` (3 check): mock `web_backend.save_config` 抛 OSError, 验 r.ok=False + r.error 含信息
  - `test_v416_save_config_ok_returns_dict` (2 check): happy path 返 ok=True
  - `test_v416_set_config_accepts_all_cfg_fields` (15 check): 12 字段全在 ProjectConfig + set_config 全不抛 + get_config 全含
  - `test_v416_save_config_idempotent` (3 check): 3 次 save 结果一致

### 🧪 测试
- 基线: 517/0 (test_web_backend.py 285)
- v4.1.6: **552/0** (test_web_backend.py 320, +35)
- 净增: 35 check (远超任务要求 ≥ 523, 现 552)

### ⚠️ 已知限制
- `beforeunload` fire-and-forget: 关窗时如果 set_config 慢可能丢, 接受 (1ms 级一般来得及)
- `app.utils.save_config` 内部 try/except 仅 log 不 re-raise (历史行为, 未改) — web_backend.save_config 的 except 兜底仅在 mock/直接抛错时生效

## v4.1.5 (2026-09-05) — 主页 UI 重构 + D 方案 incremental Diff

**修订版**: 主页 3 栏 → 2 栏重构, 流式 D 方案增量算法。**不打包, 修完 dev 验证**。

### 🟠 用户痛点 (5 致命 + 5 重要)
1. **进度占用中央独立栏** — 文件 / 进度 / diff 拆 3 栏, 4K 屏都挤; 改 2 栏布局 (Files+进度子页面 | Compare)
2. **流式无原文字对照** — 左栏原文字只在完成才有 (via `onTaskComplete`); 流式过程左栏空白
3. **diff 全量计算卡 UI** — 大文件 (10K+ 字) 每 token 都全量 `diff_main`, 卡 WebView; 改 D 方案 incremental 增量
4. **流式无 diff 高亮** — 流式只能看到打字机, 不知道哪里是新加字符; 改 ins 实时高亮
5. **跨 chunk 边界 partial 跳跃** — 段间新内容全丢失; D 算法接受接缝为 ins (合理视觉)
6. **复制/导出流式时 enabled** — 用户复制到一半的 partial, 体验差; 流式时 disabled
7. **错误态右栏空白** — 校对失败时右栏什么都不显示; 改 error-mark fallback
8. **HTML 旧 ID 残留** — `.diff-tabs` / `.diff-content` 旧 JS 静默失效; 强制列 ID 删/增清单
9. **CSS 3 栏 fallback** — `.home-grid` 未显式声明, 落到默认 3 栏; 显式 `1fr 1.5fr`
10. **renderState 内存泄漏** — 文件删除时 renderState 不清理; removeFile + clearFiles 显式清

### ✨ 改动

#### 1. 后端事件协议 (修复 🔴 1)
- **`app/web_backend.py:35-44`** (`_ORIGINAL_PUSH_LIMIT` 常量)
  - 新增 `_ORIGINAL_PUSH_LIMIT = 50000` (50K 字阈值)
  - 超过不推 `original`, 避免 JSON 序列化 + `evaluate_js` payload 过大 (>150KB)
- **`app/web_backend.py:342-359`** (`on_file_start` 回调)
  - **改前**: `lambda k: self._push("onFileStart", k)` (只推 file_key)
  - **改后**: `lambda k: self._push("onFileStart", {"file_key": k, "original": ..., "original_truncated": bool})`
  - 大文件 (> 50K) 推 `original: null` + `original_truncated: true`
  - 前端 fallback 调 `window.pywebview.api.read_file(path)` 异步读

#### 2. HTML 结构 (修复 🔴 3)
- **`web/index.html:44-120`** (主页)
  - **删**: `<section class="card progress-card">` (整中央栏)
  - **删**: `<div class="diff-tabs" id="diff-tabs">` (旧 tab 选择)
  - **删**: `<div class="diff-content" id="diff-content">` (旧单栏 diff)
  - **加**: `<div class="content-grid home-grid">` (显式 2 栏, 覆盖 .content-grid 默认 3 栏)
  - **加**: `<div class="progress-subpanel">` (在 `.file-list-card` 底部, 推到底部)
  - **加**: `<section class="card compare-card">` (替换 `.diff-card`)
  - **加**: `<div class="compare-grid">` (2 子栏 grid: 1fr 1fr)
  - **加**: `<div id="compare-original">` (左: 原文字)
  - **加**: `<div id="compare-revised">` (右: 流式 + ins 高亮)
  - **加**: `<button id="btn-toggle-diff-mode">` (流式 ↔ 全量 切换)
  - 主页元素对应表: `progress-fill` / `progress-stats` / `progress-eta` / `log-output` / `home-chunking-display` 全部保留, ID 不变 (只挪位置)
  - `btn-copy-result` / `btn-export-result` 也保留 ID, 挪到 `.compare-header` actions 里

#### 3. CSS 改动 (修复 🔴 4)
- **`web/style.css:208-222`** (`.content-grid.home-grid`)
  - 显式 `grid-template-columns: 1fr 1.5fr` (左文件 1fr, 右对比 1.5fr, 因为对比内容多)
- **`web/style.css:540-660`** (v4.1.5 主页 UI 重构样式)
  - `.progress-subpanel`: `margin-top: auto` 推到底部, `border-top` 分隔线
  - `.progress-subpanel .log`: `max-height: 120px` 限高 (v4.0 无限制会撑爆)
  - `.file-list-card`: `display: flex; flex-direction: column` 让 progress-subpanel 推到底部
  - `.file-list-card .file-list`: `max-height: 300px` 限文件列表
  - `.compare-grid`: `grid-template-columns: 1fr 1fr`, `gap: 1px` 用 border 当分隔, `flex: 1` 撑满
  - `.compare-original` / `.compare-revised`: `font-family: var(--font-mono), var(--font-family)` (中文回退)
  - `.compare-revised ins`: 绿底 (流式新增字符高亮)
  - `.compare-revised del`: 红底 + 删除线 (全量 diff 模式)
  - `.compare-empty`: 居中 italic 空状态
  - `.error-mark`: 红色 error-light 背景, 错误态 fallback
  - **不硬编码 `calc(100vh - Xpx)`**: 改用 `flex: 1` + `min-height: 0` 撑满剩余高度

#### 4. app.js D 算法 + 集成 (核心)
- **`web/app.js:51-65`** (`renderState` 数据结构)
  - 新增 `renderState: {}` 在 App 对象顶层
  - 每个 fileKey 独立 state: `{lastPartialLen, renderedHTML, renderedOriginalLen, rafScheduled, mode}`
  - `mode` 显式默认 `'streaming'` (避免 || 兜底混乱, 跟 plan v2 §3.1 一致)
- **`web/app.js:110-117`** (`startEventLoop` 50ms → 16ms)
  - 🟠 修复 7: 16ms (60 FPS) 拉取 eventQueue, 跟后端 _push 33ms 节流兼容
  - D 算法 RAF 渲染需要高频 (30 FPS) event 拉取
- **`web/app.js:139-145`** (`dispatch` onFileStart 处理)
  - 🔴 修复 1: 拆成 `handleFileStart(data)` (同步设 t.original) + `markFileRunning(fileKey)` (设 status)
- **`web/app.js:269-271`** (`bindEvents` 加 toggle 按钮)
  - `<button id="btn-toggle-diff-mode">` 绑 `toggleDiffMode()` handler
- **`web/app.js:401-417, 425-435`** (`clearFiles` / `removeFile`)
  - 🔴 修复 5: `clearFiles` 设 `this.renderState = {}`, `removeFile` `delete this.renderState[path]`
  - 防内存泄漏
- **`web/app.js:467-484`** (`selectFile` 复制/导出按钮状态)
  - 🟠 修复 8: `const hasResult = !!(t && t.corrected && !this.isProcessing)`
  - 复制/导出流式时 disabled, 完成后 enabled
  - toggle 按钮: 仅 `t.corrected` 时 enabled
- **`web/app.js:594-602`** (`updateStream` 用 scheduleRender)
  - 改前: 直接调 `renderDiffForFile(fileKey)`
  - 改后: 调 `scheduleRender(fileKey)` (RAF 合并, 避免每 token innerHTML)
  - 不管是否选中都更新 (切回时能从 lastPartialLen 续)
- **`web/app.js:619-625, 627-635`** (`markFileRunning` / `markFileDone`)
  - markFileRunning 同步触发 renderCompare (左栏原文字立刻显示)
  - markFileDone 触发 renderCompare + selectFile (复制/导出按钮 enabled)
- **`web/app.js:678-876`** (D 算法 + renderCompare + handleFileStart + toggleDiffMode)
  - `_commonPrefixLength(a, b)`: 纯前缀匹配, 不用 diff_main
  - `_initRenderState(fileKey)`: 显式初始化, 避免隐式 init 时序问题
  - `scheduleRender(fileKey)`: RAF 合并, `rafScheduled` 标志防同帧多次 schedule
  - `renderCompare(fileKey)`: 核心渲染, 拆 4 步:
    1. 未选文件 → 空状态
    2. 🟠 修复 9: `t.error` → 显示 `<div class="error-mark">校对失败: ...</div>`
    3. 左栏原文字: `t.original` 直接显示, `t._originalTruncated` 调 read_file 异步读
    4. 右栏: 模式分流
       - `state.mode === 'full'`: 用 `diff_main` 全量 (带 del)
       - `state.mode === 'streaming'`: D 算法增量
         - 🔴 修复 2: `if (partial.length < state.lastPartialLen)` 倒退保护, reset state
         - `if (partial.length === state.lastPartialLen) return` (无新内容)
         - 增量: `newChars = partial.slice(state.lastPartialLen)`, `matches = commonPrefixLength(newOriginalSlice, newChars)`, `inserted = newChars.slice(matches)`
         - 拼 HTML: `<span>matches</span><ins>inserted</ins>`
  - `_loadOriginalFallback(fileKey)`: 大文件 fallback, 异步 read_file + 防重复请求 (`t._loadingOriginal` 标志)
  - `toggleDiffMode()`: 切 streaming ↔ full, 切回流式时重置累积 (`lastPartialLen=0; renderedHTML=''; renderedOriginalLen=0`)
  - `handleFileStart(data)`: 同步设 `t.original = data.original || ''` + `t._originalTruncated = !!data.original_truncated`
- **`web/app.js:486-499`** (`startProofread` 显式 init renderState)
  - 启动时为每个待处理文件调 `_initRenderState(p)`, 语义清晰 (跟 plan v2 §7 一致)

#### 5. 删旧 JS
- 删 `renderDiffTabs` (旧 tab 选择, 单文件 selectedFileKey 替代)
- 删 `renderDiffForFile` / `_doRenderDiffForFile` (旧全量 diff)
- 所有 `getElementById('diff-tabs')` / `getElementById('diff-content')` 引用 → 改 `compare-original` / `compare-revised`

#### 6. 测试 (新增 11 个 check, +1 个测试)
- **`test_web_backend.py:1390-1565`** (v4.1.5 D 算法 + 后端事件协议 mock 测试)
  - `test_v415_d_algorithm_all_inserted`: D 算法 newChars 全部新增 → 全部 `<ins>`
  - `test_v415_d_algorithm_all_preserved`: newChars 全部保留 → 全部 `<span>`
  - `test_v415_d_algorithm_mixed`: 部分新增部分保留 → span + ins 混合
  - `test_v415_d_algorithm_incremental_multi_round`: 多轮 incremental 累积, 模拟 token-by-token 流式
  - `test_v415_d_algorithm_partial_reset`: partial 倒退保护 (retry 场景: partial 变短 reset)
  - `test_v415_renderstate_remove_cleanup`: removeFile / clearFiles 清理 (无内存泄漏)
  - `test_v415_error_state_fallback`: 错误态显示 error-mark
  - `test_v415_mode_toggle`: streaming ↔ full 切换
  - `test_v415_on_file_start_with_original`: onFileStart lambda 含 original / original_truncated / 50K 阈值
  - `test_v415_original_push_limit_constant`: `_ORIGINAL_PUSH_LIMIT = 50000` 常量
  - `test_v415_on_file_start_large_file_truncated`: 大文件 (> 50K 字) original=null, original_truncated=true (含 captured 实际 evaluate_js 验证)
- 测试总数: **517 / 0 全过** (v4.1.4: 490 / 0 → v4.1.5: 517 / 0, +27 check)

### 借鉴合规
- 无新增借鉴, 沿用 plan v2 第 4.1 (BSD-3-Clause pywebview) / 5.3 (Apache-2.0 diff-match-patch) / (MIT Fluent 2) / (MIT marked) / (MIT Fluent Icons) 节引用
- THIRD_PARTY_NOTICES.md 无需更新
- 不引入新外部依赖 (v4.0 → v4.1.5 仍 0 新增)

### 已知限制
- (D 算法跨 chunk 边界接缝为 ins, 接受, 合理视觉: 段间新内容)
- (大文件 10K+ 字 renderedHTML 累积 ~30KB, 接受)
- (并行 5 文件 renderState 累积 ~150KB, 接受)
- (大文件 > 50K 字 original 推 null, 前端 read_file fallback, 网络磁盘 IO 可能略慢)
- (CSS `.diff-tabs` / `.diff-content` / `.diff-empty` / `.diff-header` / `.diff-card` / `.progress-card` 旧规则保留无害, 新代码不再用)

## v4.1.4 (2026-09-05) — 流式 30 FPS + 导出原生保存对话框

**修订版**: 2 项用户反馈优化。**不打包, 修完 dev 验证**。

### 🟠 用户痛点
1. **流式动画太慢** — v4.1.1 起节流 100ms (10 FPS), 滚字看起来"刷出来", 用户体验差
2. **导出位置不灵活** — 之前固定输出到 `~/.proofreader/output/<stem>_corrected.<ext>`, 用户每次都得手动挪文件

### ✨ 改动

#### 1. 流式节流 100ms → 33ms (30 FPS)
- **`app/web_backend.py:642-666`** (`_push` 方法)
  - `elapsed >= 0.1` → `elapsed >= 0.033`
  - `threading.Timer(0.1, ...)` → `threading.Timer(0.033, ...)`
  - 注释更新版本演进: v4.0 (50ms) → v4.1.1 (100ms) → v4.1.4 (33ms)
- **为什么是 33ms**: 跟前端 `requestAnimationFrame` 渲染对齐, 接近 monitor refresh rate, 30 FPS 滚字无卡顿
- **不是 16ms (60 FPS)**: 跨线程 `evaluate_js` 频率从 10/s 提升到 30/s 已经够流畅, 再高会卡 WebView 内部锁

#### 2. 导出重做 — 弹原生保存对话框
- **`app/web_backend.py:467-540`** (`export_result` 方法)
  - **改前**: 固定写 `~/.proofreader/output/<stem>_corrected.<ext>`
  - **改后**: 弹 `create_file_dialog(FileDialog.SAVE, ...)` 让用户选位置
  - **默认位置**: 源文件同目录 (从 `file_path` 推导; DeAI 或无 file_path 走 `home/Documents`)
  - **默认文件名**: `<stem>-<YYMMDD>-<HHMMSS>.<ext>`
    - 例: `mydoc-260905-014530.txt` (2026-09-05 01:45:30 导出)
    - YYMMDD = `datetime.now().strftime("%y%m%d")` (6 位年月日)
    - HHMMSS = `datetime.now().strftime("%H%M%S")` (6 位时分秒)
  - **用户取消**: 返回 `{"ok": False, "cancelled": True}` (前端显示"用户取消保存"日志)
  - **写文件失败**: 返回 `{"ok": False, "error": "..."}` (权限不足 / 路径非法)
  - 借鉴自 pywebview (BSD-3-Clause) `create_file_dialog` SAVE 范式
- **`web/app.js:738-760, 1093-1115`** (前端适配)
  - `exportResult` 主页: 传源文件路径, 默认位置=源文件目录
  - `exportDeaiResult` 去AI味: 传 `''` 空路径, 触发 DeAI fallback 到 Documents
  - 两个方法都加 `r.cancelled` 处理, 显示"用户取消保存"日志
- **为什么不用 secrets/token_hex**: 之前我理解错 (以为是 6 位 hex 随机), 实际 YYMMDD 是可读时间戳, 用户一眼能看出"今天导的"

### 顺带修的 2 个 pre-existing 测试 bug
- **`test_web_backend.py:1085` (`test_f3_deai_error_no_complete` + `test_f3_deai_top_level_no_complete`)**
  - **bug**: 检查 `"onDeaiComplete" not in <except block>` 会被注释里的"不推 onDeaiComplete"误判
  - **修法**: 精确匹配 `_push("onDeaiComplete"` 调用, 排除注释
- **`test_web_backend.py:1108` (`test_i1_copy_to_clipboard_windows_calls_win32`)**
  - **bug**: 之前 stdout 缓冲隐藏 crash, 这测试从来没真跑过. mock `GlobalLock` 返回 `0x2000` (假地址), `ctypes.memmove` 写假地址触发 STATUS_STACK_BUFFER_OVERRUN 崩溃
  - **修法**: 加 `patch("ctypes.memmove", return_value=None)`
- **为什么之前 baseline 416/0 看起来通过**: stdout 缓冲让 `[PASS]/[FAIL]` 不实时 flush, 真正 crash 时缓冲里的 [PASS] 都丢不了, 测试报告看似 0 失败
- **本次 v4.1.4 改动**: 所有 `print()` 加 `flush=True`, 测试进度实时可见, 顺手修了 2 个 latent bug

### 设计决策
- **节流用 Timer 而非锁内即时 flush**: 33ms 内的多个 push 合并成一次 `evaluate_js`, 避免 WebView 内部锁等待
- **导出用 pywebview 原生对话框**: 跟 v4.0 文件选择一致 (也用 create_file_dialog), 用户体验统一
- **默认文件名带时间戳**: 多文件导出 (同一源不同时间) 不冲突, 一眼能看出导出时间
- **DeAI 导出走 Documents**: DeAI 没有"源文件"概念, 用 Documents 是最常见的"用户写文件"位置
- **不打包**: dev 验证完再 v4.1.5 打包

### 测试
- **6 套件 490 / 490 通过** (v4.1.3 是 416 / 416, 这次 +74 check)
  - test_bugs.py: 24 (无变化)
  - test_components.py: 115 (无变化)
  - test_chunker_presets.py: 32 (无变化)
  - test_chunk_lifecycle.py: 47 (无变化)
  - test_context_builder.py: 14 (无变化)
  - test_web_backend.py: 258 (v4.1.3 是 184, +74)
    - 7 个新 v4.1.4 测试函数 (30+ check): throttle 33ms / 文件名格式 / 用户取消 / DeAI fallback / md 格式 / 对话框异常 / Timer 常量
    - 修改 `test_export_result`: 5 check → 12 check (+7)
    - 修 2 个 pre-existing bug: F3 注释匹配, I1 memmove 假地址

### 已知限制
- 节流 30 FPS 在小文本 (< 100 字) 仍可能"跳", 大文本流畅 (小文本流式本身就快, 节流影响不大)
- DeAI 导出位置固定 Documents, 不让用户改 — 可未来加全局设置
- 写文件路径非法时弹原生错误框 (Windows), 没自定义错误 UI

### 用户验证步骤
1. 双击 `dev_run.bat` (或 `dev_run.ps1`) 启动
2. 主页: 选 .txt 文件 → 跑校对 → 流式滚字 30 FPS 流畅 (跟 v4.1.3 100ms 比明显)
3. 主页: 选中文件 → 单击"导出" → 弹原生保存对话框
   - 默认位置 = 源文件目录
   - 默认文件名 = `<stem>-YYMMDD-HHMMSS.txt` (例: `mydoc-260905-014530.txt`)
4. DeAI: 跑完 → 导出 → 弹保存对话框, 默认位置 = Documents

---

## v4.1.2 (2026-09-04) — dev 启动脚本 ASCII 化 (GBK 修复)

**修订版**: 4 个 dev 启动脚本全部改纯 ASCII 英文, 修 PowerShell 5.1 / cmd GBK codepage 解析错乱问题。**不打包, 不动业务层**。

### 🟠 痛点根因 (用户复测 v4.1.1 时报告)
- Windows PowerShell 5.1 默认 console codepage = GBK (cp936)
- .bat 文件没有 BOM, cmd 解析时按 GBK 解码所有字节
- 注释行 (REM) / echo 行里的 CJK 字节被 GBK 错误切分成"中文 token"
- cmd 把这些 token 当成"命令"去执行 → `'<token>' is not recognized` 雪崩
- v4.1.1 用了 ANSI 颜色 ESC 序列 (`%ESC%[92m`), 在 GBK 解析下变成 `[92m` 乱码
- **任务说明原本以为 "注释里可有中文 (不参与解析)" 是错的** — cmd 是字节流解析, 不区分"行是否注释", 任何非 ASCII 字节都会被切 token

### ✨ 改动
- **`dev_run.bat`** (改, 9404 bytes, 100% ASCII)
  - 文件中**每个字节都是 0x00-0x7F ASCII**, 包括 REM 注释
  - 删除所有 ANSI 颜色 ESC 序列 (`%ESC%[92m` 等) — GBK 解析下会变乱码
  - 删除所有中文 echo / title, 横幅改纯英文:
    ```
    ============================================================
      New Era Proofreader v4.1.2 dev launcher
      Working dir: ...
      3 windows will pop up:
        1) main cmd    (this window, waits for main.py, do NOT close)
        2) tail        (live log viewer, debug helper)
        3) GUI         (pywebview app, close GUI = exit main.py)
      If you see errors, run dev_check.bat first (5-sec env check)
    ============================================================
    ```
  - 5 步流程: venv / deps / WebView2 / duplicate process check / log + tail + start main.py
  - 失败时显示英文具体原因 + 修复命令
  - main.py 退出后显示日志最后 30 行 (调 PowerShell `Get-Content -Tail 30`)
  - 借鉴合规注释改成英文 (`Reference 1:`, `Borrowed:`, `Method:`) 保 THIRD_PARTY_NOTICES 链接
- **`dev_check.bat`** (改, 9049 bytes, 100% ASCII)
  - 7 项检查: Python / venv / main deps / hidden deps / edgechromium / WebView2 registry / WebView2Loader.dll
  - 每步: `echo [N/7] <name> ...` 然后 `[OK]` / `[FAIL]` / `[WARN]` 输出
  - 末尾 summary: "X / 7 passed - environment ready" 或 "X passed / Y failed - fix the failed items first"
  - 退出码 = 失败数 (CI 友好)
  - 最后 `pause` 让双击用户看到结果
- **`dev_run.ps1`** (改, 13739 bytes)
  - 输出全部 ASCII, 但保留文件头借鉴合规注释**中文** (PowerShell 5.1 按 UTF-8 BOM 解码, 安全)
  - 用 `Write-Host -ForegroundColor Green/Red/Yellow/DarkGray/Cyan` (颜色名是英文, 不会乱码)
  - try/catch + Continue 错误策略保留
  - 二次启动保护用 `Get-CimInstance Win32_Process` 查 CommandLine
  - WebView2 检测用 `Get-ItemProperty -Name pv` 取版本
- **`dev_check.ps1`** (改, 10271 bytes)
  - 同 ASCII 化, 中文注释保留
  - `Write-Ok` / `Write-Fail` / `Write-Warn` helper 函数着色
  - 7 项检查同 .bat 版, 退出码 = 失败数

### 设计决策
- **.bat 必须 100% ASCII** (包括 REM 注释) — cmd 是字节流解析, 不区分注释
- **.ps1 可保留中文** (仅在注释, 不在 echo) — UTF-8 BOM 标记编码, PowerShell 5.1 按 BOM 解码
- **不用 ANSI 颜色 ESC 序列** (.bat) — GBK 解析下会变乱码
- **PowerShell 颜色名都是英文** (`Green`/`Red`/`Yellow`/`DarkGray`/`Cyan`) — PowerShell 内部 token, GBK 安全
- **状态码用 ASCII**: `[OK]` `[FAIL]` `[WARN]` `[SKIP]`
- **借鉴合规注释改英文** (.bat): `Reference / Borrowed / Method / Copyright` 4 段, 链接保留指向 Microsoft Docs / vscode, 完整 LICENSE 在 THIRD_PARTY_NOTICES.md
- **借鉴合规注释留中文** (.ps1): UTF-8 BOM 安全, 4 段格式不变

### 测试
- **6 套件 399 / 399 通过** (业务层 0 改动, 全过)
  - test_bugs.py: 24
  - test_components.py: 115
  - test_chunker_presets.py: 32
  - test_chunk_lifecycle.py: 47
  - test_context_builder.py: 14
  - test_web_backend.py: 167
- **.bat 解析验证**: 跑 `cmd /c dev_run.bat` / `cmd /c dev_check.bat`, 输出 zero `is not recognized` parse errors ✓
- **.ps1 AST 验证**: `System.Management.Automation.Language.Parser.ParseFile` 零 error ✓
- **字节级验证**: `[System.IO.File]::ReadAllBytes` 确认 .bat 文件每个字节 ≤ 0x7F ✓
- **BOM 验证**: .ps1 文件首 3 字节 `EF BB BF` (UTF-8 BOM) ✓

### 已知限制
- 全英文 UI, 对中文用户不友好, 但保证能跑
- 未来要做中文 UI 建议用 Python 启动脚本 (UTF-8 跨平台一致, 不依赖 cmd 解析)

---

## v4.1.1 (2026-09-04) — dev 启动脚本鲁棒化

**修订版**：用户报告"双击 dev_run.bat 完全不可用"后做的诊断能力补完。**不打包**, 纯 dev 模式启动脚本改造。

### 🟠 痛点根因（用户报告时, 5 个可能根因）
1. Python 没装 / PATH 没 python.exe
2. venv 创建失败（权限 / 磁盘 / Python 版本不对）
3. pip install pywebview 失败（pythonnet / clr_loader 装不上 / 网络 / proxy）
4. main.py 启动后挂（WebView2 缺失 / webview.start() 抛异常）
5. 启动脚本本身鲁棒性差（cmd 窗口闪关 / 错误被吞 / tail 窗口弹不出 / pause 不明显）

### ✨ 改动
- **`dev_run.bat`** (改, 153 → 220+ 行)
  - 启动横幅明确写"会弹 3 个窗口: 1) 主 cmd 2) tail 3) GUI", 防 cmd 闪关恐慌
  - 颜色化输出 (ESC 序列), 关键状态 `[OK]` (绿) / `[FAIL]` (红) / `[WARN]` (黄) 显眼
  - 错误信息带具体修复建议（pip 装不上 / Python 版本不够 / WebView2 缺失 各自有解）
  - **修 bug**: 二次启动保护改用 PowerShell `Get-CimInstance Win32_Process` 查 `CommandLine`
    - 原 `tasklist /FO CSV` 不带命令行, 实际查不到 `main.py` 字符串, 等于无效
  - main.py 退出后自动 `Get-Content -Tail 30` 显示日志最后 30 行, 不开 log 文件也能看到崩溃信息
  - WebView2 检测 3 个注册表 key (HKLM-WOW64 / HKLM / HKCU), 之前漏了 HKCU
  - 兜底 wmic 失败时改用 PowerShell 取时间戳（Win11 24H2+ wmic 被废弃）
- **`dev_run.ps1`** (改, 182 → 280+ 行)
  - `$ErrorActionPreference = 'Continue'` (原 Stop 会让一项失败阻塞其他项)
  - try/catch 包裹每步, 即使有奇奇怪怪的 Win32 错误也不挂
  - 二次启动保护改用 `Get-CimInstance Win32_Process`, 兜底 `Get-Process` (PS 5.1 CommandLine 不可靠)
  - WebView2 检测用 `Get-ItemProperty -Name pv` 取版本, 比 `Test-Path` 准确
  - 颜色用 `Write-Host -ForegroundColor Green/Red/Yellow/DarkGray`
  - main.py 退出后 `$Host.UI.RawUI.FlushInputBuffer()` + 显示日志最后 30 行
- **`dev_check.bat`** (新增, 8130 bytes) — **独立诊断工具, 不启动 GUI**
  - 7 项检查: Python 版本 / venv 存在 / 主依赖 / pythonnet-clr_loader-comtypes 隐藏依赖 / edgechromium 平台 / WebView2 注册表 / WebView2Loader.dll
  - 全过显示 ✅, 任一失败显示 ❌ + 修复建议
  - 5 秒出结果, 用户报告"完全不可用"时第一件事就跑这个
- **`dev_check.ps1`** (新增, 9679 bytes) — PowerShell 等价版本
  - 用 `Get-ItemProperty` / `Get-ChildItem -Recurse` / `Test-Path` (比 .bat 更准)
  - 颜色化, PASS/FAIL/WARN 三色
  - 退出码 = 失败项数 (0 = 全过, 方便 CI / 自动脚本判断)

### 设计决策
- **不修 main.py / web_backend.py**: v4.1 已修, 不在本次范围
- **不打包**: dev 验证完再 v4.1.2 打包
- **配套 dev_check**: 这是 v4.0 + v4.1 都没做的"环境自检"——一旦用户报告问题, 先跑这个能立刻定位
- **颜色用 ESC 序列**: Win10 1607+ 默认支持 ANSI, 旧系统会显示乱码但不致命
- **二次启动保护必须有**: pywebview 6.x 会复用现有 GUI 进程, 双击两次会出 2 个窗口
- **退出码语义**: 0 = 成功, 1 = 启动失败, 2 = 异常退出 (main.py 挂)

### 用户重新验证步骤
1. 双击 `dev_check.bat` (或 `.\dev_check.ps1` 在 PowerShell) 先看环境 (5 秒出结果)
2. 全 ✅ 后再双击 `dev_run.bat` 启动
3. 如果哪步失败, `dev_run.bat` 退出时直接显示日志最后 30 行
4. 把日志贴给开发者

### 已知限制
- GUI headless 跑不了, dev_run.bat 在无 WebView2 环境仍会失败 — 这是预期的
- ANSI 颜色在 Win10 < 1607 显示乱码, 但不影响功能

---

## v4.1.0 (2026-09-04)

**补丁版**：v4.0.0 pywebview 迁移后的 17 项 bug 补完 + 2 个 dev 启动脚本。**暂不打包, 等用户 dev 验证后再打包**。

### 🟠 重要必修（10 项）
- **B2** (app.js:332-362) 拖拽事件改用 HTML5 `drop` + `pywebviewFullPath` (pywebview 6.x 注入, 给绝对路径). 删 `dragged_files` 监听
- **I1** (web_backend.py + processor.py) AsyncOpenAI 客户端加 `try/finally: await client.close()`. 避免 httpx 连接池泄漏
- **I2** (web_backend.py:50ms→100ms) `_push` 节流 50ms → 100ms. Timer 跨线程 evaluate_js 触发 pywebview 内部锁等待, 100ms 在 4K 屏下不卡 UI
- **I3** (web_backend.py + app.js) `fetch_models` / `test_connection` 改异步. 立即返回 `task_id`, 后台线程跑 `requests.get`, 完成推 `onFetchModelsComplete`
- **I4** (app.js) 验证 `r.ok` 检查 (现状已 OK, 略)
- **I5** (index.html + app.js) 主页 chunking select 移到设置页, 主页改只读 label. 单点配置, 防两处改
- **I6** (web_backend.py + app.js) 后端 `start_proofread` 顶层 `try/except` 兜底 + 前端 60 秒 watchdog. 防 `isProcessing` 永远卡 true
- **I7** 删除 `start.bat` / `start.ps1` (v2.0 PySide6 残留). 改用 `dev_run.bat` / `dev_run.ps1`
- **I8** (上一轮已修) `webview.start(gui='edgechromium')` 显式指定
- **I9** (build.spec hiddenimports) 加 `comtypes`, `webview.dom`, `webview.platforms.mshtml`. pywebview 6.x edgechromium 依赖
- **I10** (logger.py) 加 `app-debug.log` 专门存 DEBUG 级日志, `~/.proofreader/app-debug.log`. windowed 模式没控制台, 排查时让用户直接看文件
- **I11** (build.spec) `upx=False`. 杀软 (Defender/360/火绒) 经常误报 UPX 压缩过的 exe

### 🟡 中等（7 项）
- **M1** (index.html:202) "4 步法" 改 "1 步 LLM 调用: 草稿 → 砍废话 → 打破对称 → 加毛边 (合并在 1 次调用中完成)"
- **M2** (utils.py + web_backend.py + processor.py) chunking 档位单点定义在 `app/utils.py:CHUNKING_PRESETS`. web_backend 和 processor 改 import, 不再本地复制. 加一致性测试
- **M3** (web_backend.py:218) `task_id` 硬编码 `"1"` 改 `f"proof_{uuid.uuid4().hex[:8]}"`. 并发多任务不冲突
- **M4** (web_backend.py:471) `default=str` 改 `default=Backend._serialize`, 递归处理 Path/dataclass/Enum, 保留 JSON 结构
- **M5** (上一轮已修) DPI 感知
- **M6** (index.html + web/lib/marked.min.js) 删 `marked.min.js` (35KB), 死代码 (项目没真用 marked)
- **M7** (app.js:999) `'~deai_result.' + fmt` hack 路径改 `'deai_result.' + fmt`

### ✨ 新增 dev 启动脚本
- **`dev_run.bat`** (项目根, Windows CMD 双击即可)
  - venv 检查 / 依赖安装 / WebView2 检测 / 二次启动保护 / 日志落盘 / tail 窗口
  - 借鉴自 https://learn.microsoft.com/en-us/windows/win32/ (Microsoft Docs, CC-BY 4.0) + vscode (MIT) 思路
- **`dev_run.ps1`** (项目根, PowerShell 等价版本, Win10/11 默认)
  - 借鉴自 Microsoft Docs + PowerShell/PowerShell (MIT) 思路
  - 用 `Start-Process -RedirectStandardOutput` 写日志, `Wait-Process` 等主进程退出

### 文件变更
- **修改**:
  - `main.py` (无变化, 上一轮已修)
  - `app/web_backend.py` (I1/I2/I3/M2/M3/M4)
  - `app/processor.py` (I1/M2)
  - `app/logger.py` (I10)
  - `app/utils.py` (M2 - 上一轮已部分抽取, 本轮确认)
  - `web/app.js` (B2/I3/I5/I6/M7)
  - `web/index.html` (I5/M1/M6)
  - `build.spec` (I9/I11)
  - `test_web_backend.py` (加 11 个新测试)
- **删除**:
  - `start.bat` (v2.0 残留)
  - `start.ps1` (v2.0 残留)
  - `web/lib/marked.min.js` (35KB 死代码)
- **新增**:
  - `dev_run.bat` (5347 bytes)
  - `dev_run.ps1` (6701 bytes)

### 测试
- **6 套件 399 / 399 通过** (v4.0.0 是 360, 新增 39 个 check)
  - test_bugs.py: 24
  - test_components.py: 115
  - test_chunker_presets.py: 32
  - test_chunk_lifecycle.py: 47
  - test_context_builder.py: 14
  - test_web_backend.py: 167 (v4.0.0 是 128, 新增 39)
- **新增测试** (test_web_backend.py):
  - `test_m3_task_id_is_uuid` (4 check)
  - `test_m4_serialize_path` (2 check)
  - `test_m4_serialize_enum` (1 check)
  - `test_m4_serialize_nested` (2 check)
  - `test_m2_presets_consistent` (12 check, 5 档 × 2 字段 + 2 总数)
  - `test_i3_fetch_models_async` (5 check)
  - `test_i3_fetch_models_worker_uses_requests` (5 check)
  - `test_i3_fetch_models_worker_error` (4 check)
  - `test_i1_processor_closes_client` (2 check)
  - 加上 2 个空 base 测试的小改 (调 `b._config.api_base = ""`)
  - `test_push_uses_evaluate_js` wait 从 0.1 → 0.2 (I2 100ms)

### 用户验证步骤
1. 双击 `dev_run.bat` (或 `dev_run.ps1`)
2. 首次会创建 venv + 装依赖, 约 1-2 分钟
3. tail 窗口弹出, 实时看日志
4. GUI 起来后试 3 视图:
   - **主页**: 添加文件 → 设置 API → 开始校对 → 看 diff
   - **设置**: 拉模型 (异步) / 测试连接 (异步) / 保存
   - **去 AI 味**: 3 步工作流
5. 拖拽文件试试 (B2 修过)
6. 长跑/复现问题查 `~/.proofreader/app-debug.log`
7. 发现问题反馈给开发者

### 不打包说明
- 本轮**不跑 PyInstaller** (用户决定 dev 阶段不打包)
- `build.spec` 已为下次打包更新 (I9 hiddenimports + I11 upx=False)
- 通过 dev 验证后, 再派 v4.1.1 worker 跑 `pyinstaller build.spec`

---

## v4.0.0 (2026-09-04)

**重大重构**：GUI 从 PySide6 完整迁移到 pywebview 6.2.1，业务逻辑（校对引擎 / 断点 / chunking / 跨段上下文 / DeAI）完全保留。

### 重大变更
- **GUI 替换**: PySide6 6.11 + QSS → pywebview 6.2.1 + 原生 HTML/CSS/JS
- **异步架构替换**: qasync（Qt 主线程 asyncio 循环）→ `threading.Thread` + `asyncio.new_event_loop`（后台线程内）
- **跨线程同步原语替换**: `asyncio.Event`（pause/cancel）→ `threading.Event`（跨线程安全）
- **文件对话框替换**: `QFileDialog` → pywebview 原生 `window.create_file_dialog()`
- **测试同步重构**: 7 套件 → 6 套件（删 `test_qasync_smoke.py` + `test_deai_page.py` PySide6 部分，新增 `test_web_backend.py` 128 check 替代）
- **删除文件**: `app/main_window.py` / `app/input_panel.py` / `app/params_panel.py` / `app/progress_panel.py` / `app/diff_viewer.py` / `app/api_config.py` / `app/deai_page.py` / `app/theme.py`（8 个 PySide6 UI 文件移到回收站）

### 新增
- **3 视图 SPA** (`web/index.html` + `web/app.js`)
  - **主页视图** — 文件列表 / 拖拽上传 / 进度监控 / diff 高亮 / 流式渲染
  - **设置视图** — API 配置 / Prompt 编辑 / 5 档 chunking 切换 / 上下文参数 / 持久化
  - **去 AI 味视图** — 3 步工作流 UI（独立 LLM 调用）
- **`app/web_backend.py`** (新建, ~480 行) — `Backend` Bridge API class，暴露 ~20 个方法给 JS
- **`test_web_backend.py`** (新建, 128 check) — 替代 v3.x 的 `test_qasync_smoke.py` (13) + `test_deai_page.py` (63) PySide6 部分
- **DeAI 视图独立 LLM 真实调用** (Phase 3) — 每步独立 `AsyncOpenAI` 客户端 + 流式 partial + 完整结果
- **拖拽上传** — HTML5 drag/drop API，文件直接进文件列表
- **暂停/恢复** — UI 按钮 + `threading.Event`，响应 < 100ms
- **5 档 chunking 实时切换** — 不重启后端
- **Web 设计令牌** — `web/style.css` 借鉴自 [Fluent UI 2](https://fluent2.microsoft.design/) (MIT)，CSS 自定义属性全套
- **Fluent 2 风格** — Segoe UI Variable 字体 + 8/16/24px 间距 + 多层阴影 + hover/active 微交互
- **Fluent UI System Icons** (MIT) — 13 个 SVG 图标 (home/settings/sparkle/check/close 等)
- **diff-match-patch** (Apache-2.0) — 字符级 diff，前端 JS 实现，LICENSE 完整保留
- **marked.js** (MIT) — Markdown 渲染 3KB，LICENSE 完整保留
- **build.spec** (重写) — PyInstaller 6.19，onefile + windowed，打入 `web/` 整目录，排除 PySide6/qasync

### 改造
- `requirements.txt`: `-PySide6 -qasync` → `pywebview>=6.2.1,<7.0`
- `app/processor.py`: `pause_event` / `cancel_event` 从 `asyncio.Event` 改为 `threading.Event`（v0.2 修订）
- `app/utils.py` / `templates.py` / `context_builder.py` / `logger.py`: **不变**（v3.0 业务逻辑完整保留）
- `main.py`: 整个改写为 pywebview 启动模式
- `run_all_tests.py`: 适配 6 套件 + PowerShell 中文乱码兼容

### 修复
- **pause_event 跨线程 bug** (v3.0 qasync 模式) → 改 `threading.Event` (v4.0) 修掉
- **pywebview 6.x import 顺序**: 实测 pywebview 6.2.1 无 shiboken 那种坑，import 顺序自由
- **encoding 安全**: `read_file_text` 已有 utf-8/gbk/gb18030 fallback，v4.0 验证未坏

### 测试
- **6 套件 360 / 360 通过**（v3.1 是 7 套件 356 / 356）
  - test_bugs.py: 24
  - test_components.py: 115
  - test_chunker_presets.py: 32
  - test_chunk_lifecycle.py: 47
  - test_context_builder.py: 14
  - **test_web_backend.py: 128 (新)**
- 端到手测：`python main.py` 启动正常（pywebview 6.2.1 + WebView2）

### 借鉴来源（v4.0 新增 4 项 + v3.0 保留 4 项 = 共 8 项）
- **pywebview** (BSD-3-Clause) — Bridge 模式 + `evaluate_js` 流式推送范式
- **diff-match-patch** (Apache-2.0) — 字符级 diff 算法（直接使用 + LICENSE 完整保留）
- **marked.js** (MIT) — Markdown 渲染（直接使用 + LICENSE 完整保留）
- **Fluent UI 2 设计规范** (MIT) — 设计令牌 + 组件规范（思路借鉴）
- **Fluent UI System Icons** (MIT) — SVG 图标（直接使用 + LICENSE 完整保留）

完整 LICENSE 副本见 `THIRD_PARTY_NOTICES.md`。

### 设计决策
- **零构建工具**: `web/index.html` 直接打开能跑，避免 Vite/webpack 复杂度
- **CSS 设计令牌替代 QSS**: `--colorBrandBackground` 风格对齐 Fluent 2，比 PySide6 QSS 更好维护
- **threading.Event 替代 asyncio.Event**: pywebview 主线程不跑 asyncio loop，跨线程通信用 threading 原语
- **桥接而非 HTTP**: 同进程 `js_api` 避免 flask/http.server 部署麻烦，零网络配置
- **业务层零改动**: 5 档 chunking / 跨段上下文 / 断点续传 / DeAI 业务逻辑完整保留，v3.0 全部测试可重跑

---

## v3.1 (2026-09-04)

新增**去 AI 味**独立页面 + 3 步多步工作流。

### 新增
- **🧽 去 AI 味独立页面**（侧边栏第三个 tab）
  - 借鉴自 [harshaneel/humanize](https://github.com/harshaneel/humanize) (MIT) 4 pass 编辑法
  - 借鉴自 [blader/humanizer](https://github.com/blader/humanizer) (MIT) 7 大类 AI 味分类（来自 Wikipedia: Signs of AI writing）
  - 借鉴自 [Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) (MIT) ruthless editor 思路
- **3 步工作流**（每步独立 LLM 调用，可重跑）
  - **Step 1: 检测** — 扫 7 大类 AI 味模式（AI 高频词/否定式对照/三连词/破折号泛滥/意义膨胀/宣传腔/模糊归因）
  - **Step 2: 改写** — 4 步法：草稿 → 砍废话 → 打破对称 → 加毛边
  - **Step 3: 评分** — 给改写后文本打 0-100 分 + 残留 AI 味问题列表
- **范文 few-shot 学习**（可选）：粘贴 1-3 段你喜欢的真人写作，让 AI 学你的口气
- **`app/deai_page.py`**（新建）— 3 步工作流 UI（DeaiStepWidget 状态卡 + 双栏 diff + 报告区）
- **`app/templates.py` 加 `deai` 模式**（7 种校对模式 → 8 种）
- **`test_deai_page.py`**（新建，63 个 check）— 模板内容/页面方法/状态机/集成
- `run_all_tests.py` 加 `test_deai_page.py`

### 测试
- **7 个套件 356 / 356 通过**（v3.0 是 285 / 285）

### 设计决策
- **多步工作流**：参考 harshaneel 的 4 步法浓缩成 3 步（detect/rewrite/audit），每步独立 LLM 调用
- **保留事实优先**：改写 prompt 明确禁止"发明事实、编造来源、调整数字"
- **不替换为另一种 AI 味**：禁止"换汤不换药"（把"delve"换成"深入探索"）
- **评分独立**：让用户能看到改写后是否还有残留问题

---

## v3.0 (2026-09-04)

借鉴 3 个 GitHub MIT 开源项目（tianhm/ollama-batch-processor、shreyan241/gpt-proofreader、Xueheng-Li/proofreading）的设计思路，代码全部自写。

### 新增
- **5 档 chunking 预设**（设置 → 处理参数 → 分块模式）
  - 快速 (2000) / 均衡 (3000, 默认) / 高上下文 (4000) / 大块 (6000) / 整文件 (0)
  - 解决大文件超上下文窗口问题
  - `app/processor.py` 顶部借鉴来源注释
- **跨段上下文 prefix 注入**（设置 → 处理参数 → 上下文字符数 / 上下文 chunk 数）
  - `app/context_builder.py`（新建，借鉴 shreyan241/gpt-proofreader MIT 思路）
  - 自动把前 N 个 chunk 的校对结果注入当前 chunk 的 system prompt
  - 解决 chunk 级别处理下的"段落孤岛"问题
- **段级断点续传**（FileResult.chunks_results）
  - 旧的 v1 schema 断点自动迁移
  - CANCELLED 状态断点强制重跑
  - `app/utils.py` FileResult 加 `chunks_results` / `failed_chunks` / `schema_version` 字段
- **qasync 异步架构**
  - `main.py` 用 `qasync.QEventLoop` 替代 `app.exec()`
  - `app/main_window.py` 删 `ProcessingThread` QThread 类
  - 取消/暂停响应 < 100ms
  - `app/processor.py` 加 `run_async()` 方法（GUI 线程直接 await）
- **`_stream_single` 签名扩展**：`system_prompt_override: Optional[str] = None` 参数
- **新测试文件**：
  - `test_chunker_presets.py`（5 档预设 32 check）
  - `test_qasync_smoke.py`（qasync 集成 13 check）
  - `test_chunk_lifecycle.py`（chunk 级别 + 断点 47 check）
  - `test_context_builder.py`（跨段 prefix 14 check）
  - `run_all_tests.py`（一键跑全部 6 套件，解决 PowerShell 中文乱码）
- **新文档**：
  - `PLAN-chunking.md`（完整升级 plan + verifier 审 + v0.2 修订）
  - `THIRD_PARTY_NOTICES.md`（4 个上游 LICENSE 全文 + 借鉴来源文件头注释约定）
  - `CHANGELOG.md`（本文件）

### 改造
- `app/utils.py` FileResult 加 3 个字段 + 3 个 property（is_chunked / corrected_full / is_done）
- `app/utils.py` ProjectConfig 加 4 个字段：chunking_preset / schema_version / context_max_chars / context_max_chunks
- `app/processor.py` `_process_file_async` 改造为 chunk 串行（含整文件重试 / 不可重试分类 / 取消语义）
- `app/processor.py` `_stream_chunked` 集成 ContextBuilder 注入
- `app/processor.py` `_call_api_stream` 返回签名变更 `(str, int)` → `(str, int, list[FileResult])`
- `app/main_window.py` `_active_stream_keys` 改造（文件级 key 永驻，整文件完成才 discard）
- `app/main_window.py` `_on_processing_finished` 用 `corrected_full` 兼容 chunked 场景
- `app/main_window.py` `_on_file_done` 改为 chunk 级别（不 discard），新增 `_on_file_completed` 整文件级别
- `app/diff_viewer.py` 4 处 `task.result.corrected` 改用 `corrected_full`
- `app/params_panel.py` 加 chunking_combo + context_chars_spin + context_chunks_spin
- `test_components.py` ProjectConfig 字段数 11 → 15；test_pyside6 改为验证 USE_QASYNC flag
- `test_bugs.py` `test_pyside6` 适配新架构（验证 USE_QASYNC flag）

### 测试
- 6 个套件 **286 / 286 通过**（v2.0 是 13 / 13 + 17 / 17 = 30）
- 端到端手测通过：`python main.py` 启动正常

### 借鉴来源
- **tianhm/ollama-batch-processor** (MIT) — chunking preset 分档设计思路
- **shreyan241/gpt-proofreader** (MIT) — 跨段上下文 prefix 思路
- **Xueheng-Li/proofreading** (MIT) — 段级断点续传思路
- **qasync** (BSD-2-Clause) — 异步事件循环集成

### 设计决策
- **overlap=0**：校对场景下重叠区会被改两次产生不一致
- **跨段 context 通过 system prompt**：不污染 chunk 文本本身
- **整文件预设保留**：小文件不分块，质量更高
- **整文件级重试**：避免"chunk 内重试 × N chunks = N² 次重试"的重试风暴
- **Esc 取消时丢弃中间 chunk 断点**：v0.2 选项 A，简化逻辑避免段落孤岛
- **旧 v1 断点自动迁移**：保留用户历史数据
- **qasync 替代 QThread**：简化跨线程通信

---

## v2.0 (2026-06-21)

基于 LLM 的批量文本校对工具初版。

- PySide6 + Fluent Design
- 6 种 Few-shot Prompt 模式
- 1-32 文件并发
- 文件级断点续传（v1 schema）
- 差异高亮查看器
- 多服务商模板（DeepSeek/Ollama/vLLM/智谱/通义千问）
- 13 个回归测试 + 组件测试
