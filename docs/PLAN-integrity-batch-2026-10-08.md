# 墨准 数据完整性批次（Group 1）修复计划

> 状态：**待评审（v2 — 经独立 verifier 复审后修订）**（2026-10-08）
> 基线：本机 HEAD `8861469`（v5.4.4；origin/master `0d29104` + 21 个未推送提交）
> 依据：外部复核报告第一组（完整性与数据保护）+ 本机独立复现 + 独立 verifier 复审（6 BLOCKER，处置见 §10）
> 性质：**只做数据完整性 / 防误删 / 防假成功；不加功能、不改 Prompt、不改正常路径输出形态**
> 关联：AGENTS.md §8/§9/§36/§42/§43；姊妹计划 `docs/PLAN-harness-review-receipt-2026-10-08.md`（第 2 组，写点与顺序见 §4.5）

---

## 0. 背景：本机独立复现的证据（全部在 8861469 实测）

| 编号 | 现象 | 复现结果 | 位置 |
|---|---|---|---|
| M06 | 缓存不校验输入身份 | 内容改后仍命中且 original_text 为旧文本；**删文件后仍报缓存命中、COMPLETED** | processor.py:324-337、utils.py:838-845 |
| M04 | 缺 new_text 删原文 | apply_edits('他表视很好。', [{'old_text':'表视'}]) → **'他很好。'**，status=OK | harness.py:269-270 |
| M05 | harness 不读 finish_reason | _harness_call 只取 usage/message；仅流式路径有 | processor.py:973-987 vs :881-901 |
| M08 | DeAI 落盘失败仍报完成 | 三处调用不检查返回值；前端回退预览但 UI 仍写"完整 N 字已存盘" | web_backend.py:1170/1217/1239/1445-1455、app.js:2968-3011 |
| M09 | 切分提交非事务 | 先删旧章再逐个 os.replace；索引/报告在 try 之外后写 | novel_splitter.py:1024-1034/1046/1049/1067 |
| M11 | slug 冲突互相覆盖 | 书:甲 ≡ 书?甲 ≡ 书_甲；《X》≡ X；100 字截断互撞；batch 零检测 | novel_splitter.py:148/1118-1127、web_backend.py:2226-2247 |
| M10 | 无编号特章误删 | **已修**（v5.4.3 F3）：本机 dedup=0；0d29104 上复现 dedup=1 | novel_splitter.py:670 |
| 新 | **空章节可达** | split_text(min_words=100000) → chapters=0（现状 :1006 跳过提交、索引写 []） | novel_splitter.py:800-810、:1006 |
| 新 | **Windows 目录交换语义** | dir→不存在 OK；dir→**已存在空/非空目录均 PermissionError 5**；src 缺失 FileNotFoundError | 本机 Py3.12.3 实测 |
| 新 | **D9 语义边界** | preserve_done 保护"另一条轨的好结果"（含截断但真实的结果） | utils.py:788、test_bugs.py:214-247 |

---

## 1. 范围

### 1.1 在范围内（6 项）

| 编号 | 主题 | 目标 |
|---|---|---|
| I-1 | 输入身份（M06） | 输入变了/没了，旧结果不得冒充新结果 |
| I-2 | 工具必填字段与协议错误（M04 + 未知工具名） | 缺字段不得删正文；协议错误不得静默成功 |
| I-3 | 截断语义（M05） | 截断结果不得算"可复用缓存"（**但不削弱 D9 保护**） |
| I-4 | DeAI 落盘失败（M08） | 保存失败不得宣布完成、不得只留预览（含取消路径可达性） |
| I-5 | 切分提交事务（M09） | 提交失败必须整体回滚；空结果不得抹掉旧结果 |
| I-6 | 输出目录身份（M11） | 不同书不得映射到同一目录互相覆盖 |

### 1.2 明确不做（含理由）

- **不把输入哈希塞进 prompt_hash**（配置指纹单点不动）；不新增 TaskStatus 枚举；不引入第三方依赖；不引入 size+mtime 快筛（双真值）。
- **M03（空/短/否定式"无需修改"被接受）归第 2 组**：本计划只处理"有 tool_calls 的协议错误"，**不碰无 tool_calls 的纯 content 路径**（姊妹计划 §0.4 裁定）。
- **截断不做跨步传播**：step3 `deai_load_source`、`ai_score_local` 消费截断文本的可见性问题、`chunks_results` 级标记，均列第 3/4 组（本批只保证**顶层 FileResult + DeAI payload** 侧不假成功；理由：跨步传播要改落盘元数据格式与三步 UI，超出"完整性"最小面）。
- 不做 undo 栈 / 不改 revise 编排 / 不降 AI 阈值 / 不强制每篇 edit / 不重写 DeAI 停流取消。
- **不为了消歧而修改 `_book_name_to_slug`**（v2 修订：该函数向后兼容性优先，见 §2.6）。

---

## 2. 逐项设计（v2）

### 2.1 I-1 输入身份（M06）

**根因**：prepare_tasks 先查缓存（processor.py:324-326）后读文件（:340）；load_checkpoint 只比配置指纹（utils.py:838-845）；命中时直接采用断点里的 original_text。

**修法（v2：改为"先读后比"，消灭双读与空串陷阱）**

1. app/utils.py 新增 `compute_source_hash(text) -> str`（**入参是已解码文本**，纯函数）：sha256(text.encode('utf-8')).hexdigest()[:16]。放在 utils 与其余哈希工具同层。
2. FileResult 增 `source_hash: str = ""`（10 → 11 字段），to_dict/from_dict 带上（旧断点缺键读作空串）。
3. prepare_tasks（processor.py:318-337）顺序调整为：
   - 顶部与 `self.cached_files = []`（:310）同处**重置** `self._source_hashes = {}`；
   - **先 read_file_text**（现有 :340）；失败 → 走现有 FAILED 占位分支（:341-357），**不做缓存查找**（修掉"删文件仍命中"）；
   - 成功 → `src_hash = compute_source_hash(text)`，存 `self._source_hashes[key]`；
   - 缓存查找：`load_checkpoint(fp, expected_hash=..., expected_source_hash=src_hash)`（force_rerun 时照旧跳过）；
   - 命中 → 采用断点任务；未命中 → 走现有预处理（md_strip/punct_fix，:366-373）与就绪日志。
   - 思考链残留定向失效（:329-331）保留在命中之后。
4. load_checkpoint 增 `expected_source_hash` 参数，**两档语义**：`None` = 跳过输入指纹校验（兼容既有直调）；非 None = 必须比对，且**空串一律判不可复用**（防御式；旧断点 source_hash 默认 "" 正是"删文件仍命中"的老形态）。比对失败写日志（旧值/新值各为完整 16 位指纹，旧断点显示 `(empty/legacy)`）。
5. 结果组装单点（processor.py:581-595）补 `source_hash=self._source_hashes.get(key, "")`。本地两模式（:1211/:1235 结果）与两条轨都汇入该出口，**无第二处改动**。

**为什么改顺序**：byte 哈希方案要在读文件前读一遍字节，缓存命中路径与 miss 路径都变成两次读；先解码再哈希则**任何路径都只读一次**（miss 路径新增 0 次 IO，命中路径新增 1 次读，与旧方案相同），且 `expected_source_hash=""` 的漏洞从设计上不存在。

**边界表**

| 场景 | 期望行为 |
|---|---|
| 文件未变 + 配置未变 | 命中缓存（行为同现在） |
| 文件内容变了 | 不命中 → 重跑，diff 基线是新原文 |
| 文件被删除 / 不可读 | 不命中 → FAILED 占位 +"读取失败"（不再伪装完成） |
| 旧断点（无 source_hash） | 一次性不命中并重跑，日志写明原因 |
| force_rerun=True | 不变（跳过缓存） |
| 仅配置变化 | 仍由 prompt_hash 拦下（不变） |
| **写入侧**：引擎跑完落盘 | FileResult.source_hash 必须等于**磁盘原文**指纹，且断点可被再次命中（B1 复核 BLOCKER-1 补的端到端断言） |
| **写入侧**：引擎被跨批次复用（指纹表缺键） | 落盘空串前先 `[警告] … 缺少输入指纹` 留痕（生产路径不可达；不再静默劣化） |
| 文件不可读（权限/被占用） | 与"被删除"同路径：读失败 → FAILED 占位（不查缓存） |
| 仅编码变化（加 BOM，文本相同） | 按解码文本身份 → 指纹不变 → **仍命中**（保守方向：文本变了才会重跑） |

**迁移成本**：旧断点一次性失效 —— 与姊妹计划 §0.4 的 `|hv=` 失效**合并成同一次**（两份计划都依赖这一点）。

**新增测试**（建议 tests/test_cache_identity.py）：同内容命中 / 改内容不命中且 original_text 为新文本 / 删文件不命中且 FAILED / 旧断点不命中 / force_rerun 不报错 / `_source_hashes` 每次 prepare 重置。

---

### 2.2 I-2 工具必填字段与协议错误（M04 + 未知工具名）

**根因**：apply_edits 用 `e.get("new_text", "")`（harness.py:270）→ 缺字段与显式空串不可区分 → 删原文且 audit 报 OK；parse_tool_calls 对未知工具名直接 continue（harness.py:417-418）；"全部未生效"判据在 **processor.py:1053-1065（条件 :1059）**，只在 edits 非空时生效。

**修法（v2：不动 parse_tool_calls 签名）**

1. apply_edits（harness.py:265-282）在类型检查**之前**加必填键检查：缺 `old_text` 或 `new_text` → SKIPPED_BAD_ARGS("缺必填字段 …")。
   - **保留**显式 `new_text=""` 的删除语义（schema 本就 required 两键 harness.py:86，删除语义见 :76 文档）；`old_text=""` 仍走 SKIPPED_NOOP。
2. parse_tool_calls（harness.py:405-437）：**签名保持 2 元组不变**（避免动 tests/test_harness.py:282/:289/:292 三处解包）；新增纯函数 `count_raw_tool_calls(message) -> int`；未知工具名 → 追加 audit 条目 SKIPPED_UNKNOWN_TOOL（reason 带工具名）。
   - ⚠ **接口变更须知**：姊妹计划 §0.4 写的是"消费 parse_tool_calls 的返回值（parse_audit 与 raw_count）"。本计划改由 `count_raw_tool_calls` 提供同一信息（纯函数、无状态），第 2 组消费点改一行调用即可，语义不变；该差异需同步回姊妹计划 §0.4。
3. _harness_call（processor.py:999-1044）：新增协议错误判据 `raw_count > 0 and not edits` → 并入 **F10 有界核查**（复用 `_harness_suspect` 与 max_retries 预算）：记一次可疑 → 重试一轮 → 仍如此则放行并落 `WARN_PROTOCOL_NOOP` audit。
   - **P-2 冻结为"有界核查 + WARN 放行"，禁止改为 raise**：姊妹计划不变量 **I2（任何新路径都不会把"零改动"变成 FAILED）** + F10 既有取向（CHANGELOG v5.4.3）双重约束。
   - 实现时**不得锁死预算语义**（第 2 组可能改用专用上限 `HARNESS_RECHECK_MAX`，届时单点替换）。
4. "无 tool_calls 的纯 content 回复"路径**完全不动**（归第 2 组）。

**边界表**

| 输入 | 现状 | 目标 |
|---|---|---|
| 缺 old_text | SKIPPED_NOOP | SKIPPED_BAD_ARGS + 计协议错误 |
| old_text=null / 非字符串 | SKIPPED_BAD_ARGS | 不变 |
| **缺 new_text** | **new="" → 删原文、audit OK** | **SKIPPED_BAD_ARGS，正文不变** |
| new_text 显式空串 | 删除该处 | **不变**（合法删除语义） |
| 未知工具名 | 静默忽略、零告警 | SKIPPED_UNKNOWN_TOOL + 计协议错误 |
| 参数非 JSON / 非对象 | SKIPPED_BAD_ARGS | 不变（整轮全是 → 协议错误判据） |
| 一条 OK + 一条缺字段 | 缺字段条删原文 | OK 生效 + BAD_ARGS + warnings=True |
| 全部 NOT_FOUND | FAILED（既有） | 不变（对照项） |
| raw>0 但零条可应用（含未知工具名） | 静默零改动完成 | 有界核查 → WARN_PROTOCOL_NOOP 放行（**不 FAILED**） |

**受影响既有用例（必须同步，不是掩盖回归）**：`tests/test_harness.py:284`（parse_audit 2 → 3 条，因 unknown tool 新增条目）；:282/:289/:292 **不受影响**（签名不变）。

**跨计划顺序**：本批 **B2 必须先落**，第 2 组 Session 1 不得与之并行（同改 harness.py / processor.py，姊妹计划 §0.4 已裁定）。

---

### 2.3 I-3 截断语义（M05）

**根因**：harness 非流式（processor.py:973-987）不读 finish_reason；DeAI 三条 `async for event in stream` 消费点不读（主改写 web_backend.py:1125-1139、revise :1394-1407、蒸馏 :1789-1808；**step1/3 共用主循环**）。校对流式路径已由 v5.3.0 覆盖（processor.py:897-901）。
**注意**：`onDeaiComplete.truncated` 语义是"推送预览被截断"（仅由 len(partial) > 50000 决定，web_backend.py:1238-1250），**不可复用**。

**修法（v2：只收紧"可复用"判据，不动 D9）**

1. FileResult 增 `truncated: bool = False`（11 → 12 字段）。
2. harness 侧：_harness_call 读 `completion.choices[0].finish_reason`，等于 `length` → `self.truncated_keys.add(task_key)` + [截断] 日志（口径同 processor.py:897-901）。
3. 结果组装（processor.py:581-595）：`truncated=(key in self.truncated_keys)`；`warnings` 计算不变（已含截断）。**只标顶层 result**，chunks_results 级不标（理由见 §1.2）。
4. 缓存语义：
   - **只改 load_checkpoint 的"可复用"判据**：见 `task.result.truncated` → return None（与 CANCELLED 同构，utils.py:832-837）；
   - **`_checkpoint_is_done`（utils.py:761-776）保持"有成功结果"语义不变** —— 它是 D9 的判据（utils.py:788），改掉会让"截断但真实"的结果被后续失败/取消的 preserve_done 收尾覆盖（test_bugs.py:214-247 保护的正是这种"另一条轨好结果"）；而"锁死"担心不成立：load_checkpoint 已判不可复用，下次成功写点仍会覆盖（preserve_done=False）。
5. DeAI 侧：新增单点 helper 取 finish_reason 并置局部 `output_truncated`：
   - 主循环：标记 + 日志，**不 raise**（保留已得文本）；
   - revise 轮：截断 → 丢弃本轮、保留上一轮（沿用 web_backend.py:1416-1417 兜底）；
   - 蒸馏：截断 → **不落盘风格卡**（P-4）；
   - step1/step3：payload 标记（报告不完整要可见）。
6. payload 新增 `output_truncated`（不动 `truncated`，向后兼容）；前端在 step 输出区加提示条（app.js:2968/2980/3009 附近）。
7. 蒸馏落盘判据：`app/style_profiles/loader.py:318-339` 只有"空卡 raise"，由调用侧（web_backend.py:1830-1836）把 `output_truncated` 纳入不落盘判据；是否加轴数校验见 P-4。

**新增测试**：harness length 端到端（COMPLETED + warnings + truncated=True + **再跑一次不命中缓存**）；**D9 回归**：截断结果在后续 CANCELLED preserve 收尾后仍在盘上（锁定"不改 _checkpoint_is_done"）；DeAI 三路 + step1 截断；蒸馏截断不落盘。

---

### 2.4 I-4 DeAI 落盘失败（M08）

**根因**：_save_deai_result 失败只 log 并返回空串（web_backend.py:1445-1455），三处调用点（:1170/1217/1239）不检查；前端 `truncated && result_file` 为假 → 回退预览（app.js:3104/3153），文案仍写"完整 N 字已存盘"（app.js:2970/2984/3011）→ 全文静默丢失。
**新发现（v2 增补）**：**取消路径**也落盘 partial（:1216-1217），但前端取消分支（app.js:3034-3050）只回填 `data.partial`、且 partial 以"…(内容过长"开头时直接跳过，**从不设置 `stepNFile`** → 已落盘的完整 partial 在 UI 上不可达。

**修法**

1. 三处调用点统一检查返回值：失败 → 推 `onDeaiError`（`save_failed: true` + partial 预览 + total_len），**不推** `onDeaiComplete`（P-5 备选：complete + save_failed 标记）。
2. **取消路径可达性**：取消 payload 带 `result_file` 时，前端取消分支设 `stepNFile` + 提示"完整部分结果已存盘"（app.js:3034-3050）。
3. 前端三处文案改由 `result_file` 真值决定：有值 → "完整 N 字已存盘"；空值 → "完整结果未落盘，仅预览可复制/导出"（app.js:2968-3011）。
4. 可选加强（P-5）：失败时回退临时目录 + `result_file_fallback`，并扩展 `_load_deai_result_text`。

**新增测试**：`_atomic_write_text` 抛 OSError（模拟满盘）→ 无 onDeaiComplete、有 onDeaiError + save_failed、`_load_deai_result_text` 为 None；取消超限路径 payload 带 result_file（回归 §2.4-2）；正常路径回归不变（tests/test_web_backend_deai.py:767-780 保留）。

---

### 2.5 I-5 切分提交事务（M09）

**根因**：提交阶段（novel_splitter.py:1024-1034）先删全部旧数字 txt（且吞 OSError）再逐个 os.replace；索引/报告在 try 之外后写（:1046/1049/1067）。危险窗口 :1030 → :1033。
**约束（v2 补充）**：① 现暂存目录 `_split_staging` 建在 output_dir **内部**（:1007）→ 必须改成**兄弟目录**，否则整目录交换会把它一起搬走；② Windows `os.replace` 对目录的语义（下表实测）。

| Windows 实测（Py3.12.3） | 结果 |
|---|---|
| dir → 目标不存在 | OK |
| dir → 目标已存在（空目录 / 非空目录） | **PermissionError 5** |
| src 不存在 | FileNotFoundError |
| 跨卷 / 目录内有打开句柄 | PermissionError 5（含首次让位） |

**修法（v2：分支化提交，空结果不交换）**

1. 暂存目录改兄弟级：`staging = output_dir.parent / (output_dir.name + "._split_staging")`；每次 run 先清理残留。
2. 暂存阶段扩展：3 个索引/报告文件也写进 staging，使暂存目录自成完整产物（现在落在 try 之外）。
3. **空结果（chapters == 0）不交换**：保留旧目录与旧索引（仅当目录不存在时创建并写空 chapters.json），返回值加 `empty: true` + 日志。理由：实测 `min_words` 过滤后可产生 0 章（novel_splitter.py:800-810），若照旧交换会把用户上一次的切分结果整体抹掉 —— 与"防误删"性质直接冲突。
4. 有结果时的提交：
   - **output_dir 不存在**（首次切分）→ 直接 `os.replace(staging, output_dir)`（实测 OK）；
   - **output_dir 已存在** → 先 rmtree 残留 backup（**rmtree 失败即显式报错**，不带着残留继续，否则下次首步必失败）→ `os.replace(output_dir, backup)` → `os.replace(staging, output_dir)` → `shutil.rmtree(backup, ignore_errors=True)`（失败只留目录 + 日志）。
   - **回滚只在 `backup.exists()` 时执行**；回滚失败 → 抛错并同时给出 backup 与 output_dir 的绝对路径与手工恢复指引（首步失败时 backup 不存在，不得谎报备份路径）。
5. **非托管文件的影响必须写明**：整目录交换会把 output_dir 里非本工具产生的文件一并移入 backup 并在清理时删除。当前 output_dir = `<slug>/blocks`（应用托管目录，README 已如此描述），故采此方案；若用户要求保留自建文件 → 走"托管文件集交换"变体（P-3）。此取舍写进 CHANGELOG/README。

**边界表**

| 失败点 | 现状 | 目标 |
|---|---|---|
| 暂存期写失败 | 旧结果保留（已有） | 不变 |
| 首次切分（目标不存在） | 逐个 replace | 整体 rename，原子 |
| 让位 replace 失败 | 旧结果保留 | 不变（直接抛，backup 不存在 → 不谎报路径） |
| 就位 replace 失败 | **旧章已删、索引陈旧** | 回滚（backup 存在时），旧结果逐字节完整 |
| 索引/报告写失败 | 章新索引旧 | 不可能（随暂存一起交换） |
| 空结果（0 章） | 旧章留着、索引写 [] | **不交换**，旧结果不动 + empty 标记 |
| 清理 backup 失败 | — | 留目录 + 日志；下次 run 若 rmtree 仍失败则显式报错 |

**新增测试**（tests/test_novel_splitter.py）：注入"就位 replace 失败"→ 旧章 + 旧索引完整（当前会红）；**首次切分**（目标不存在）不抛；空结果不交换；索引随交换；残留 staging/backup 清理；rmtree 失败路径报错；**并补实现有 :633"名为失败不留半截、实则只重跑幂等"的空断言**（:619 的断言同步）。
**测试注入点注意**：save_split 内部局部 `import os`（:1012/:1032）→ 必须 patch 全局 `os.replace`（或先提为模块级导入，作为实现第一步）。

---

### 2.6 I-6 输出目录身份（M11）

**根因**：`_book_name_to_slug`（novel_splitter.py:1118-1127）有三类丢信息行为，batch_splitter（web_backend.py:2226-2247）零冲突检测，后一本把前一本删净覆盖：

| 碰撞类型 | 实测例子 | 机制 |
|---|---|---|
| 非法字符替换 | 书:甲 ≡ 书?甲 → 书_甲；a/b ≡ a\b → a_b | `_SLUG_BAD_CHARS`（:148）统一换 _ |
| 书名号剥离 | 《斗破苍穹》≡ 斗破苍穹 → 斗破苍穹 | 正则含 《》（:148） |
| 100 字截断 | 前缀相同的长书名 → 同一 slug | :1125-1126 截断（测试 :462 断言 ≤100） |

**修法（v2：不改 slug 函数，改冲突检测点）**

1. **`_book_name_to_slug` 保持不变**（向前兼容：既有 5 条断言 tests/test_novel_splitter.py:453/454/456/467/468/710 不动、老用户目录不换名、≤100 不变量不破）。
2. 冲突消解移到 `batch_splitter`（web_backend.py:2226-2247）：
   - 批内维护 `slug -> book_name` 映射；同一 slug 第二次出现时**比对书名/源路径**：同书重跑 → 沿用现目录（覆盖，现状语义）；**不同书 → 目录名追加 `-2`/`-3`（序号确定性，且目录名仍 ≤100：让位时对 base 做截断）** + 日志 + 结果 payload 标 `dir_disambiguated: true`；
   - **目标目录已存在时的身份校验**：读该目录 `metadata.json` 的 title（save_split 已写 external_title，:1049/:508-509）与本次书名比对 → 不同则同样追加序号；相同则复用覆盖。
   - 结果 payload 增 `slug` / `dir_disambiguated`，供前端与用户核对。
3. 兼容：历史目录仍按原名命中；仅"真冲突"时才出现新目录，且**不会**静默覆盖另一本书。

**新增测试**：三类碰撞各 1 条（断言落到不同目录且两本内容都在）；同书重跑仍复用同一目录（不产生 -2）；批内同名两本；payload 字段；**既有 slug 断言零改动**（回归锁定）。

---

## 3. 数据与兼容性影响

| 项 | 变化 | 兼容处理 |
|---|---|---|
| FileResult | 10 → 12 字段（source_hash、truncated） | to_dict/from_dict 带默认；建议补字段数断言防回退（AST 实测：全仓无 to_dict 键集/字典相等/JSON 快照断言 → 安全） |
| ProjectConfig | **不变**（29） | 既有断言 tests/test_harness_split.py:51-55、test_components.py:63、test_web_backend_deai.py:1192 不受影响 |
| 断点 | 旧断点无 source_hash → 一次性重跑；truncated 结果不可复用（但**受 D9 保护**不被失败收尾覆盖） | 日志 + CHANGELOG；与第 2 组 `|hv=` 失效合并为同一次 |
| 前端 payload | 新增 output_truncated / save_failed / slug / dir_disambiguated；truncated 语义不变 | 老前端忽略新字段不报错 |
| 切分 | **slug 函数与老目录名不变**；仅在真冲突时新增 `-2` 目录；暂存/备份目录改兄弟级 | 历史结果可继续命中 |
| 空结果 | 不再覆盖旧结果（新增 empty 标记） | 与"防误删"一致 |

---

## 4. 批次划分与门禁

| 批次 | 内容 | 门禁 |
|---|---|---|
| B1 | I-1 输入身份（utils.py + processor.py） | 全量 + 新增 6 用例；**单独提交**（唯一一次性作废旧断点的一批） |
| B2 | I-2 必填字段/协议错误 + I-3 harness 截断（harness.py + processor.py） | 全量 + 新增用例；**必须先于第 2 组 Session 1** |
| B3 | I-4 落盘失败（web_backend.py + app.js） | 全量 + 前端静态断言 + smoke_ui（改文案） |
| B4 | I-5 切分事务 + I-6 目录身份 + M10 回归锁定（novel_splitter.py + web_backend.py） | 全量 + 新增用例，受影响既有用例逐条同步 |

统一门禁：`python run_all_tests.py` 零失败（本机 1886/2，2 项为缺 requests；CI 应为 1896/0）；每个修复做**变异自检**（撤掉修复 → 新用例变红 → 还原）。

### 4.5 受影响既有用例（必须逐条确认"同步修改，不是掩盖回归"）

| 文件:行 | 影响 | 处置 |
|---|---|---|
| tests/test_harness.py:284 | parse_audit 2 → 3（新增 UNKNOWN_TOOL 条目） | 同步断言并注明新增条目 |
| tests/test_harness.py:282/289/292 | 解包 2 元组 | **不受影响**（v2 不改签名） |
| tests/test_novel_splitter.py:453/454/456/467/468/710 | slug 断言 | **不受影响**（v2 不改 slug 函数） |
| tests/test_novel_splitter.py:462 | ≤100 不变量 | **不受影响**（不加后缀到 slug） |
| tests/test_novel_splitter.py:619/:633 | 空断言 / 未真正注入失败 | 补实为真失败注入用例 |
| tests/test_bugs.py:214-247、tests/test_chunk_lifecycle.py:630-677 | D9 语义 | **不得削弱**（v2 保留 _checkpoint_is_done） |
| **tests/test_bugs.py:50**（Bug#1 fixture） | 断点无 source_hash → 不再命中 | **已同步**：fixture 补 `source_hash=compute_source_hash('test')` |
| **tests/test_components.py:236**（prepare_tasks 加载缓存/缓存计数） | 同上 | **已同步**：补 source_hash（"cached content"） |
| **tests/test_web_backend_deai.py:894**（`_make_cache`，a/b/c 三处调用） | 同上 | **已同步**：helper 内补 source_hash |
| **tests/test_web_backend_proofread.py:875**（3 参数调用仍走缓存） | 同上 | **已同步**：补 source_hash（body） |
| **tests/test_web_backend_proofread.py:914**（残留定向失效） | 若不补，断言会因"输入不匹配"而非"残留"通过 → **用例变空** | **已同步**：补 source_hash（body），保住归因 |
| **tests/test_web_backend_proofread.py:926**（原文自带残留照常命中） | fixture 与磁盘内容本就不自洽（旧缓存不看内容，掩盖了） | **已同步**：`src.write_text(body2)` 使磁盘与断点一致 |

### 4.6 与第 2 组计划（PLAN-harness-review-receipt-2026-10-08）的接口

| 单点 | 归属 | 约定 |
|---|---|---|
| parse_tool_calls 未知工具名 | **本计划（B2）** | 记 SKIPPED_UNKNOWN_TOOL；raw 计数改由 `count_raw_tool_calls` 提供（需同步姊妹计划 §0.4 的措辞） |
| "有 tool_calls 但零条可应用" | **本计划（B2）** | 有界核查 + WARN 放行；第 2 组只消费，不重复实现 |
| F10 复核预算语义 | 共享 | 本批不得锁死；第 2 组若改专用上限 `HARNESS_RECHECK_MAX`，单点替换 |
| 无 tool_calls 的纯 content 路径 | **第 2 组** | 本计划不碰 |
| 前端 STATUS_LABEL | 第 2 组 | 同文件不同区块，串行（B3 文案改完后） |
| 顺序 | — | **B1 → B2 先落，第 2 组 Session 1 后开工；不并行** |

---

## 5. 测试清单汇总（新增约 34-40 条）

| 文件 | 新增 | 要点 |
|---|---|---|
| tests/test_cache_identity.py（新） | **10 用例 / 31 断言** | I-1 全边界 + _source_hashes 重置 + 写入侧端到端（BLOCKER-1） |
| tests/test_harness.py | 10 + 2 | I-2 边界表逐行（含 unknown tool）+ I-3 截断与重跑不命中 |
| tests/test_chunk_lifecycle.py | 1 | I-3 D9 回归（截断结果不被失败收尾覆盖） |
| tests/test_web_backend_deai.py | 7 | I-3 三路 + step1 截断、蒸馏不落盘、I-4 落盘失败 + 取消可达性 |
| tests/test_novel_splitter.py | 10-12 | I-5 提交事务（首次/失败/空结果/残留/注入点）+ I-6 冲突消解 + M10 回归 |
| 前端静态断言 | 2-3 | 新 payload 字段 + 文案真值分支 |

---

## 6. 风险与回滚

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R-1 | 旧断点一次性失效 | 中 | 逐文件日志；CHANGELOG；与第 2 组 `|hv=` 合并为一次；B1 单独提交便于 revert |
| R-2 | 缓存命中路径新增一次读+解码 | 低 | 如实标注；**不引入** size+mtime 快筛；miss 路径新增 0 次 IO（v2 设计） |
| R-3 | 截断结果反复重跑烧 token | 中 | 仅 finish_reason=length 触发；UI 提示"建议换更小分块" |
| R-4 | 协议错误判据误伤"全文无错" | 中 | 冻结为有界核查 + WARN 放行（不 FAILED），符合不变量 I2 |
| R-5 | 目录交换受句柄/跨卷影响 | 低中 | 兄弟目录天然同卷；失败回滚（仅 backup 存在时）；句柄占用 → 明确报错不破坏旧结果 |
| R-6 | **slug 换名导致老目录孤儿** | **已消除** | v2 不改 slug 函数；仅真冲突时新增 `-2` 目录 |
| R-7 | 空结果不交换 → 用户以为"没反应" | 低 | 返回 `empty: true` + 前端提示 + 日志 |
| R-8 | 整目录交换删除非托管文件 | 中 | P-3 决策 + README/CHANGELOG 写明 output_dir 为托管目录 |
| R-9 | 批次间同文件冲突（B3 前端 / B4 web_backend / 第 2 组） | 低 | 串行执行 + §4.6 归属表 |

**回滚锚点**：开工前打 tag `backup/pre-integrity-2026-10-08`；每批独立提交。

---

## 7. 完成定义（DoD）

- [ ] I-1 ~ I-6 每项都有新用例，且做过"撤掉修复 → 变红"的变异自检
- [ ] §4.5 受影响既有用例逐条同步并说明理由
- [ ] 全量门禁零失败（补齐本机 requests 后复跑）
- [ ] 正常路径输出**逐字节不变**（同输入跑旧/新实现对比）
- [ ] D9 不变量未被削弱（test_bugs.py:214-247 + 新增截断回归双绿）
- [ ] 断点迁移行为有日志/文档/用例
- [ ] 与第 2 组接口按 §4.6 对齐（含姊妹计划 §0.4 措辞同步）
- [ ] AGENTS.md 新增编号决策 + README + CHANGELOG + ROADMAP 同步
- [ ] 前端文案变更后 tools/smoke_ui.py 通过

---

## 8. 待拍板决策点

| 编号 | 问题 | 建议 | 状态 |
|---|---|---|---|
| P-1 | 截断结果终态 | COMPLETED + warnings + 不可复用（不改 _checkpoint_is_done） | 待拍板 |
| P-2 | "有 tool_calls 但零条可应用" | 有界核查 + WARN 放行 | **已冻结**（不变量 I2） |
| P-3 | 切分事务粒度 | 整目录交换（output_dir 视为托管目录）；备选托管文件集交换 | 待拍板 |
| P-4 | 蒸馏卡被截断 | 不落盘 + onDeaiError；是否加轴数校验待定 | 待拍板 |
| P-5 | DeAI 保存失败 | onDeaiError 终态；备选 complete + save_failed + 临时目录兜底 | 待拍板 |
| P-6 | 目录冲突策略 | **批内 + 已存在目录身份校验，冲突才追加 `-2`**（v2 改：不改 slug 函数） | 待拍板 |

---

## 9. 执行记录（待回填）

| 批次 | commit | 门禁结果 | 备注 |
|---|---|---|---|
| B1 | `835695e`（与 B2 合并提交） | 全量 **1913 → 1917 通过 / 2 失败**（2 项 = 本机系统解释器缺 requests；shim 定点复验 5/0）；新增套件 31 断言全绿 | 新增 tests/test_cache_identity.py；变异自检：撤掉 expected_source_hash → **4 条变红**；同步 6 处既有缓存 fixture（§4.5）；**步间独立复核：1 BLOCKER（缺指纹静默写空串 + 写入侧无断言）已修**（缺键留痕 + 写入侧端到端断言） |
| B2 | `835695e`（与 B1 合并提交） | 全量 **1962 通过 / 2 失败**（同为环境项） | I-2 必填字段/协议错误 + I-3 harness 截断；test_harness.py 162→202、test_chunk_lifecycle.py 74→79；变异自检三处分别变红 **10 / 3 / 3** 条；**步间独立复核待办** |
| B2 | — | — | 必须先于第 2 组 Session 1 |
| B3 | — | — | — |
| B4 | — | — | — |

---

## 10. 复审记录（v1 → v2）

独立 verifier 复审（只读，基线 8861469）判 **6 BLOCKER**；Lead 逐条复验后处置如下（全部**采纳**）：

| # | Blocker | Lead 复验证据 | v2 处置 |
|---|---|---|---|
| 1 | 空章节分支走交换 = 新增误删面 | 实测 `min_words=100000 → chapters=0` | §2.5-3：**空结果不交换** + `empty` 标记 |
| 2 | 回滚/首步在 Windows 不成立 | 实测 dir→已存在目录 PermissionError 5；src 缺失 FileNotFoundError | §2.5-4：分支化提交；**回滚仅在 backup.exists()**；rmtree 失败显式报错 |
| 3 | I-6 打破 5 条 slug 断言 + ≤100 | 读 tests/test_novel_splitter.py:453/454/456/462/467/468/710 | §2.6 改为**不改 slug 函数**，冲突消解移到 batch |
| 4 | "纯安全名向后兼容"不成立 | `infer_book_name` 优先取《…》(:1083-1112)，:703-710 实测 | 同上；R-6 由"低"改"已消除" |
| 5 | parse_tool_calls 改动打红既有用例 + 与 I2 冲突 | 读 tests/test_harness.py:282/284/289/292；读姊妹计划 §0.4 与不变量 I2（:239） | §2.2-2：**签名不变**，新增 `count_raw_tool_calls`；**P-2 冻结**；补 §4.5/§4.6 |
| 6 | 改 _checkpoint_is_done 打掉 D9 | 读 utils.py:788 + test_bugs.py:214-247 | §2.3-4：**只改 load_checkpoint 复用判据**，D9 判据不动 + 加回归用例 |

**其他采纳项**：行号勘误（全失败判据 → processor.py:1053-1065；loader 全路径；"四路流式" → 3 处 + step1/3 共用主循环）；遗漏边界 ③（取消路径 result_file 不可达 → 并入 I-4）、④（`expected_source_hash=""` 陷阱 → v2 改为先读后比，从设计上消除）、⑤（`_source_hashes` 重置 + 双读 → v2 设计解决）、⑥（非托管文件 → §2.5-5 + R-8）、⑦/⑧（测试注入点 → §2.5 注）。
**未采纳（转为显式不做）**：②"截断跨步传播/chunks_results 级" → §1.2 移出本批并写明理由；① M03 → §1.2 标明归第 2 组。
**复审未复核项**：未跑全量套件（环境缺 requests），1886/2 结论由 Lead 早前实测承担。
