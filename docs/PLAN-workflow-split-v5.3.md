# 墨准 v5.3 工作流双入口 — 实施计划

**版本**: v5.3.0 (拟)
**基线**: `master @ 3c41f8c` (校对与对比单页已合并)
**状态**: 🚧 **执行中** (2026-09-26 用户批准: "排期设定为现在直接执行")
**审核**: ✅ 已过一轮独立审核 (2026-09-26, 只读 verifier)。裁决"需修订后开工", 6 个阻塞项 (B1-B6) 已全部并入本版: 见 §2 D4/D9/D10、§3.4、§3.5、§4-7、§5 #4/#7/#15/#19/#20、§6.0。审核报告原件: `.workbuddy/reviews/review-v5.3-workflow-split-plan.md`
**用户决策**: ✅ `extra_large=50000` 为**逐条校对专属的正式档** (50K 实测通过, 失败出现在 100K) (D7); ✅ 断点保护副作用接受 + 保留强制重跑出口 (D9 / §4-10); ✅ 整文件告警阈值 = 20000 (D8); ✅ **排期 = 立即执行**
**总工时**: 23-33h (3-4 人天, 8 个 session)
**最后更新**: 2026-09-26
**调研方式**: 3 个并行只读 agent (数据层 / 前端 IA / 引擎语义) + 主会话逐条复核

---

## 0. 三条前提修正 (先读, 否则方案会建在错的假设上)

### 0.1 「harness 单块 50000」: 档位尚未落地, 烟测已通过 → 本版纳入

| 问题 | 结论 | 依据 |
|---|---|---|
| 代码里有 50000 档吗 | **没有**。分块档只有 `fast 2000 / balanced 3000 / high_context 4000 / large 6000 / whole_file 0`; harness 默认 `large=6000`, `whole_file` 才是整篇不切块 | `app/utils.py:532-538` |
| 那 50000 是什么 | 是 IPC 推送阈值 `_ORIGINAL_PUSH_LIMIT` / `_DEAI_PUSH_LIMIT` (超阈值不往前端推原文, 走 `read_file` 兜底)。与新档位**同名不同义**, 别混 | `app/web_backend.py:56-68` |
| 50000 档从哪来 | v5.2c plan 的延期项: "新增 `extra_large=50000` — 等真实烟测确认 50000 字符 harness 块可承受再单独加档" | `.workbuddy/plans/plan-v5.2c-harness-split.md:29-31, 399` |
| 烟测做了吗 | **已通过**: 用户 2026-09-26 确认 "新模型绝对能支持 50000", **失误出现在 10 万档**, 即 50K 在上限内、100K 才越界。仓库内无报告文件 | 口述; 仓库检索无记录 |
| 于是怎么办 | **按正式档纳入 v5.3**, 只对逐条校对轨开放 (见 §2 D7); 50K 即**设计上限** (不再往上加档), 100K 的失败记录写进 CHANGELOG 作为边界依据 | §2 D7/D8 |

**待补的烟测参数** (实施时必须落到 CHANGELOG): 模型/端点、输入字符数、单请求耗时、是否触顶、失败率。
在拿到这几个数之前, plan 不编具体默认 timeout, 也不把 "50000 字符" 写进任何用户可见的"已支持"文案。

**另注**: 拆入口的核心理由仍然是**机制清晰**(逐条 vs 整篇), 不是"harness 更强"; 新档位只是让逐条轨多一档可选粒度。

### 0.2 现在没有"模式"这个一等概念

引擎选择是**两个字段派生**出来的, 且派生逻辑只写在引擎里:

- `_harness_active()` = `harness_enabled` **且** `prompt_mode ∈ {strict, polish}` — `app/processor.py:805-816`
- 前端入口按位置传 5 个参数 (`paths` / `prompt_mode` / `custom_prompt` / `chunking_preset` / `force_rerun`) — `web/app.js:1225-1231`
- `start_proofread` 直接改**全局单例** `self._config.prompt_mode` / `chunking_preset` — `app/web_backend.py:511-516` (即: 跑一次校对会顺带改掉 DeAI 之后用的分块配置)

所以"两个入口"要真的成立, 必须先有一个**显式 workflow 身份**, 否则导航只是两个长得一样的按钮。

### 0.3 三处文档与代码不一致 (本计划顺带修)

| 位置 | 文档声称 | 实际 |
|---|---|---|
| `AGENTS.md:105` / `CHANGELOG.md:78` | `web_backend.py:set_config` 写老字段时自动同步给新字段 (X-4 修) | **代码里没有这个分支**, 只有前端 `bindCompatFields` 在做 (`web/app.js:408-417`)。老 API 客户端兼容目前是假话 |
| 后端钳制 | 老 `timeout` 有 clamp (10-300) | `harness_request_timeout` / `rewrite_request_timeout` **不在 clamp_map 里** (`app/web_backend.py:157-176`), 只有前端 JS 钳制 |
| `web/index.html:350` | "改 prompt_mode (**API 接口页**) 或 harness_enabled 切换模式" | `cfg-prompt-mode` 就在校对参数页自己 (`web/index.html:279`) |

---

## 1. 目标与非目标

**目标**

1. 侧边栏把两条校对轨拆成两个**语义明确、行为可区分**的入口, 不再是"一个下拉 + 一个 checkbox"。
2. workflow 成为一等身份: 引擎、桥接、日志、结果、断点指纹共用同一个显式值, 不再靠白名单派生。
3. 结果**来源可辨**: 任何时刻用户都能看出"这份 diff 是哪条轨跑出来的", 且不会被静默覆盖。
4. 新增 `extra_large=50000` 分块档 (依据 §0.1 烟测), **仅对逐条校对轨开放**; 换掉逐条轨"要么 6000 要么整篇"的粗粒度。
5. 顺带修掉 0.3 的三处不一致, 以及四个渲染成实心方块的坏图标 (`check-list` / `document-edit` / `document-multiple` / `app`)。

**非目标 (本版明确不做)**

- ❌ 同一文件两轨结果**并存** (双结果槽 + 双断点; 见 §2 D1 与 §9)
- ❌ 两轨**并行**运行 (现为单 engine / 单线程 / 单队列)
- ❌ harness 改流式 (AGENTS §36 已定"建议不做流式")
- ❌ 拆分 `view-home` 成两个视图 (会复制 DOM/ID, 且掩盖真正的共享状态问题)
- ❌ 整篇校对轨的整文件模式**强制降级** (本版只加告警, 见 §2 D8)

---

## 2. 决策表 (本计划的选型, 逐条给理由)

| # | 决策 | 选择 | 理由 / 被否方案 |
|---|---|---|---|
| **D1** | 两轨结果是否并存 | **共享队列 + 单结果槽 + 强制来源标注**; 双槽留 Phase 2 | 用户诉求是"入口清晰", 不是"两轨对拍"。双断点方案实测代价 5-8 天 + 要迁移老 `cp_*.json` (迁移失败会**不可逆覆盖**用户已完成结果)。Phase 1 的 workflow 身份是 Phase 2 的严格前置, 分期不浪费 |
| **D2** | 导航层级 | **两层**: 组标题 (工作区/工具/设置) → 项; 只有「重写 → 去 AI 味」一层父子 | WinUI NavigationView 官方指引: 层级可做但"two levels is ideal"。用户原提案的"工作区 > 工具 > 项"是三视觉层级, 偏离指引 |
| **D3** | 入口命名 | **逐条校对 / 整篇校对**, 不在引擎入口上用"重写"二字 | 见 §3.2 命名分析: harness 是**机制**不是校对本身; `tech_doc/custom` 与本地模式都会溢出错父组 |
| **D4** | 模式是否升为一等字段 | **是**, 但用 `workflow_mode: str = ""` (**空 = 自动派生**) + 单一 `effective_workflow` 派生函数; 显式值域 `{harness, rewrite}` | 直接给硬默认值会与 `ProjectConfig(prompt_mode="custom")` 这类**直接构造**冲突 (测试大量这么写)。空值派生同时满足: 老配置无字段 → 按旧逻辑 `harness_enabled and prompt_mode ∈ {strict,polish}` 推出结果; 显式值 → 以它为准。**引擎侧白名单仍是权威** (`custom`/`tech_doc` 永远不走工具链, 守 AGENTS §36), 冲突由 UI 层过滤消除, 见 §3.4 |
| **D5** | 入口状态是否持久化 | **持久化**, 导航入口即"当前工作流" | 只做一次性运行参数会导致: 入口显示的和 `校对参数` 页存的不是一回事, 反而更难懂 |
| **D6** | 版本与排期 | 独立 **v5.3.0**, 排在 v6.0 清理 C2 (`app.js` 拆 ES module) **之前** | C2 要在 12 个模块里重新分布导航与 track 状态; 应在 IA 稳定后再拆 |
| **D7** | `extra_large=50000` 给哪条轨 | **逐条校对 (harness) 专属的正式档** (用户 2026-09-26 确认): 整篇校对 / DeAI / 蒸馏 / 兼容下拉一律不出现; **50K 即设计上限** (10 万档实测失误 → 不再往上加档) | 整篇校对是流式**整篇重输出**: 50K 字符输入 = 模型要重吐 ~50K 字。全仓无 `max_tokens`, 也无长度校验 (`app/processor.py:795-800` 只判空) → 端点默认输出上限会**静默截断**。同源先例: DeAI 的 `_DEAI_WHOLE_FILE_LIMIT = 20000` (`app/web_backend.py:66-68`)。另: 50000 档是**单响应**协议 (`_harness_call` 只调一次) 且单块编辑上限 50 条 (`app/harness.py:27-31`) |
| **D8** | 整篇轨 `whole_file` 现无尺寸兜底, 管不管 | 本版**加告警 + 加事后检测, 但不强制降级**。**告警的确切含义**: 在「整篇校对」入口选了 `whole_file`(整文件不分块) 档、且文件字数超过阈值 N 时, 开始前弹一次确认 ——「整篇会作为单次请求发出, 长文可能超模型上下文或被截断。继续?」, 点确认照跑 (不是限制线, 是提醒线) | proofread 的 `whole_file` 无条件返回 `[text]` (`app/utils.py:600-601`), 与 DeAI 的 20000 兜底待遇不一致。强制降级会悄悄改掉用户的显式选择 (留 Phase 2)。**告警必须放 `_runProofread`** (共享入口), 否则右键「强制重跑」(`web/app.js:1262-1273`) 会绕过; 同时捕获 `finish_reason == "length"` + 输出/输入长度比, 走既有 `warnings` 通道标记"疑似截断"。阈值 **N = 20000** (用户 2026-09-26 确认), 对齐 DeAI 的 `_DEAI_WHOLE_FILE_LIMIT` |
| **D9** | 单结果槽下, 失败/取消会不会冲掉另一轨的好结果 | **必须修**: 失败/取消收尾时, 若磁盘已有 `is_done` 断点则**不覆盖** | 现状 `_finalize_cancelled` (`app/processor.py:637`) 与 `_finalize_failed` (`app/processor.py:671`) 都无条件 `save_checkpoint_async`, 而断点文件只按路径命名 (`app/utils.py:572-582`)。后果: 逐条轨跑完 → 整篇轨启动后立刻取消 → 逐条成果被空 corrected 的 CANCELLED 断点覆盖。**不修这条, §1-3 的"不会被静默覆盖"就是假的**。**副作用已获用户接受 (2026-09-26), 并要求保留"忽略旧结果强制重跑"出口 —— 该出口已存在**(右键「重新校对（忽略缓存）」→ `force_rerun` → `prepare_tasks` 整体跳过 `load_checkpoint`, `web/app.js:297`/`1260-1273` + `app/processor.py:274`)。本版只需把它**接到来源提示条**并写进文案, 不新建机制 |
| **D10** | 参数页的 `harness_enabled` 复选框怎么处理 | **移除**, 降级为只读兼容字段; 只读段控件改成"当前入口"状态显示 | 前端任何参数改动都会 500ms 后**全量** `saveConfig`, payload 里含 `harness_enabled` (`web/app.js:2119-2121` → `2154-2174`)。若保留复选框而入口切到 rewrite, 下一次任意保存就会把 `harness_enabled=True` 发回后端, 把轨道**翻转回去** (且结果取决于键顺序, 属隐蔽的顺序依赖)。唯一真值必须是 `workflow_mode`, 入口即开关 |

---

## 3. 目标形态

### 3.1 侧边栏 (2 层, 7 视图 id 全部不变)

```text
工作区
  ├─ 逐条校对            data-view=home   data-workflow=harness     图标 check-list
  ├─ 整篇校对            data-view=home   data-workflow=rewrite     图标 document-edit
  └─ 重写                data-nav-parent (可点击进入 去 AI 味)
       └─ 去 AI 味       data-view=deai                             图标 sparkle
工具
  ├─ 风格库              data-view=styles    图标 document
  └─ 小说切分            data-view=splitter  图标 document-multiple
设置
  ├─ API 接口            data-view=api       图标 settings
  ├─ 校对参数            data-view=params    图标 check
  └─ 外观与关于          data-view=appearance 图标 info
```

要点:

- **视图 id 与顺序零改动** (`home/deai/styles/splitter/api/params/appearance`), 只改导航归属与分组标题。
- 两个入口共用 `view-home`, 靠 `data-workflow` 区分; 激活态**必须**用唯一 `data-nav-key`, 不能用 `[data-view="home"]` (现有 `setView` 只激活第一个匹配项, `web/app.js:114-121`)。
- 「重写」父项本身是可点击入口 (进 去 AI 味), 展开箭头必须是**独立 button** (不能 button 嵌套 button)。
- `工具` 与 `工作区` **并列**, 不放进工作区里做第三层。

### 3.2 命名分析 (为什么不用「校对 / 重写」)

评分维度 5 分最好; "不误导" 列 5 = 误解风险最低。

| 候选 | 一眼分辨 | 与引擎语义一致 | 不误导 harness=校对 | 结论 |
|---|---|---|---|---|
| **逐条校对 / 整篇校对** | 5 | 5 | 4 | ✅ **采用** |
| 逐条修改 / 整篇重写 | 5 | 4 | 5 | 备选, 但"重写"留给 DeAI 家族更自洽 |
| 精确编辑 / 整篇输出 | 4 | 4 | 5 | "输出"是工程词 |
| 校对 / 重写 (原提案) | 3 | 2 | 2 | ❌ 见下 |

原提案的两个具体失真:

1. `strict` 关掉 harness 后走的**还是校对**, 却挂在"重写"入口下 → 同一件事被叫两个名字。
2. `tech_doc` / `custom` / `punct_local` / `md_local` 在"校对 vs 重写"二分里没有正确归属。

缓解: 侧边栏保持短名 (200px 宽), 页面头部常驻机制说明 —— 「逐条校对 · 模型只提交改动条目, 输出 token 少, 可逐条审计」/「整篇校对 · 模型重写全文, 兼容不支持 function calling 的服务端」。

### 3.3 本地模式 (`punct_local` / `md_local`) 的归属

这两个模式**完全不建 `AsyncOpenAI`、不触网** (`app/processor.py:357-366`), 与两条 LLM 轨是平行的第三类。

**本版做法**: 保持在校对页的 Prompt 模式下拉里, 单独分组标注「本地处理 (不调用 API, 与入口无关)」, 选它时引擎忽略 workflow (`_harness_active` 的白名单天然不命中)。**明确记入 §9 的 Phase 2 候选**: 若用户觉得别扭, 再提升为 `工具` 组下的独立入口 (需新视图, 本版不做)。

### 3.4 入口 × Prompt 模式 行为矩阵 (修 B1)

优先级: **引擎侧白名单永远优先**, UI 层用"下拉过滤"消除冲突, 不制造静默降级。

| 入口 | UI 提供的 prompt_mode | 持久化配置是非法组合时 |
|---|---|---|
| 逐条校对 (harness) | `strict` / `polish` + 本地组 | 引擎按白名单退回整篇行为, **页头与日志明示**"当前模式不支持工具链, 本次按整篇输出执行"; 首次进入时提示一次 |
| 整篇校对 (rewrite) | `strict` / `polish` / `tech_doc` / `custom` + 本地组 | 无 (本身即兜底轨) |

- 本地模式 (`punct_local` / `md_local`): 两个入口的下拉都提供, 单独分组「本地处理 (不调用 API)」; 选中时引擎短路到本地规则, workflow 不参与引擎选择 (`app/processor.py:357-366`)。
- **已知取舍**: hash 含 `|wm=` 会让**本地模式的结果在两个入口互不命中**, 切入口重跑一次。本地引擎零成本, 本版选择"接受 + 在 §4 披露", 不为它做 hash 例外。
- 派生规则写成**一个函数** (`effective_workflow(config)`), `from_dict` 与直接构造 (`ProjectConfig(prompt_mode="custom")`) 走同一条路径, 避免两套真值。

### 3.5 启动与状态恢复 (修 B4)

| 项 | 现状 | 本版要求 |
|---|---|---|
| 首个 nav 硬编码 active | `web/index.html:35` 写死 `class="nav-item active"` | 去掉硬编码; 启动时按 `config.workflow_mode` 决定激活哪个入口 |
| 激活项查找 | `setView` 用 `querySelector('[data-view=...]')` 取首个匹配 (`web/app.js:114-121`) | 改用唯一 `data-nav-key` (两个 home 入口才能各自高亮) |
| 导航绑定 | `renderSidebar` 读 `dataset.view` (`web/app.js:403-405`) | 改读 `data-nav-key` |
| 全部跳转点 | `setView` 调用点: `app.js:103 / 404 / 644 / 671 / 776 / 778 / 1158 / 1628 / 2401` | 逐个确认: 命中 home 时带上 workflow; `Ctrl+.` (778) 与 `deaiHandoff` (2401) 进入 `deai` 时**自动展开「重写」父项** |
| 父项展开态 | 无 | 展开 button 独立 (不嵌套 button) + `aria-expanded` 双向维护; 子项激活时父项保持展开 |

---

## 4. 行为规格 (入口 × 结果来源)

**核心原则: 导航决定"现在要跑什么", 结果自带"当初用什么跑的"。两者不一致时必须说出来, 不允许静默展示。**

| 当前入口 | 选中文件的结果来源 | 界面行为 |
|---|---|---|
| 逐条校对 | 无结果 | 正常可跑 |
| 逐条校对 | 逐条校对 | 正常展示 diff + 改动清单 |
| 逐条校对 | **整篇校对** | 结果区顶部黄条: 「此结果来自 **整篇校对**, 当前入口是逐条校对」+ 按钮「用逐条校对重跑」 |
| 整篇校对 | 无结果 / 整篇校对 | 正常 (另一入口为镜像提示) |

补充规则:

1. **文件行徽标**: 每个已完成文件在状态旁显示来源 (`逐条` / `整篇`), 取 `task.runWorkflow`, **不取当前导航状态**。
2. **待处理判定**: `开始` 只挑"在当前 workflow 下没有可用结果"的文件 (现为只看 status, `web/app.js:1171-1179`)。否则在另一入口已完成的文件会被错误跳过。
3. **覆盖前确认**: 开始前若队列中存在"另一入口已有完成结果"的文件, 复用 `showConfirmDialog` 提示一次「本次将覆盖 N 个文件在另一入口的结果」(单结果槽的诚实告知, 不是可选项)。
4. **断点复用**: 同一入口重跑命中缓存秒完成 (不变); 切换入口后 hash 不匹配 → 重跑并覆盖 (预期, 见 §7 R1)。
5. **导出默认名**带 workflow (`<stem>-逐条-YYMMDD-HHMMSS.txt` / `-整篇-`), 避免两轨同秒同名 (`app/web_backend.py:770-771`)。
6. **去 AI 味联动**: `deaiHandoff()` 送去改写的是**当前选中的那份结果**, 并在 DeAI 页标明来源 workflow (`web/app.js:2379-2404`)。
7. **来源状态机** (修 B4): `resultWorkflow` **只在成功完成时写入**; 失败/取消保留旧来源。理由: `onTaskComplete` 的失败分支会清掉 `t.corrected` (`web/app.js:1508-1509`), 若那时改写来源字段, 就会把"上一轨的好结果"标成"当前轨的坏结果"。
8. **覆盖确认要覆盖两条路径** (修 B3 配套): 批量开始 (`web/app.js:1171-1179`) **与** 右键「重新校对」的单文件重跑 (`web/app.js:1262-1273`) 都要挂确认, 否则后者绕过。
9. **本地模式披露** (见 §3.4): 本地模式结果在两个入口互不命中, 换入口会重跑一次 —— 零成本, 但要在文案里说清, 不能让用户以为是 bug。
10. **「用当前入口重跑」必须走强制重跑** (用户 2026-09-26 要求): 来源提示条上的按钮要传 `force_rerun=True` (`_runProofread([path], { forceRerun: true })`, 现成通道在 `web/app.js:297`/`1260-1273`)。理由: D9 之后磁盘上仍留着上一轨的成功断点, 普通「开始」会被 `prepare_tasks` 判为缓存命中 (`app/processor.py:274-282`) **秒标完成**, 用户会觉得"点了没反应"。
11. **缓存命中提示分两种口径**: ①本轨刚跑完又重跑 → 沿用现有 `已跳过 N 个文件（命中上次校对缓存，右键可强制重新校对）` (`web/app.js:1243`); ②命中的是**另一轨遗留**的结果 (D9 后的新状态) → 走"来源不一致"提示 + 强制重跑入口, 不能报成普通缓存命中。

---

## 5. 改动清单

| # | 类型 | 文件 | 内容 | 估计行 | 风险 |
|---|---|---|---|---:|---|
| 1 | 改 | `app/utils.py` | `ProjectConfig.workflow_mode: str = ""` (空=自动派生) + `to_dict`/`from_dict` + **单一** `effective_workflow(config)` 函数 | +50 | 🟡 |
| 2 | 改 | `app/utils.py` | `compute_prompt_hash` / `compute_prompt_hash_for_config` 加 `\|wm=` (用 effective 值); **不动 `schema_version`** | +8 | 🟡 |
| 3 | 改 | `app/utils.py` | `CHUNKING_PRESETS` 加 `extra_large=50000` + `tracks` 元数据 (仍单点定义, 避免 label/max_chars 漂移) | +8 | 🟢 |
| 4 | 改 | `app/utils.py` | **断点保护 (D9)**: `save_checkpoint(_async)` 增加"已有 `is_done` 时是否允许覆盖"参数 | +25 | 🔴 |
| 5 | 改 | `app/processor.py` | `_harness_active()` 改读 `effective_workflow()`; 白名单仍是权威 (非法组合退回整篇 + 日志) | +14 | 🟡 |
| 6 | 改 | `app/processor.py` | `resolve_chunk_preset(cfg, track)` **单点 helper**: 按轨取档 + `extra_large` 仅 harness + 非法回退 `large`; 供 `_process_file_async` / `_call_api_stream` / `_deai_run` 共用 | +20 | 🟡 |
| 7 | 改 | `app/processor.py` | 失败收尾 (`:671`) 与取消收尾 (`:637`) 改成"不覆盖已完成断点"; 成功写点 (`:535`) 保持可覆盖 | +10 | 🔴 |
| 8 | 改 | `app/processor.py` | `_stream_single` 捕获 `finish_reason == "length"` + 输出/输入长度比 → 写入 `warnings` (D8 的事后检测) | +15 | 🟡 |
| 9 | 改 | `app/web_backend.py` | `start_proofread(..., workflow="")` **追加在第 6 位** (不能插在 `force_rerun` 前); 第 4 个 `chunking_preset` 参数标废弃并停止写旧字段 | +25 | 🟡 |
| 10 | 改 | `app/web_backend.py` | `get_chunking_presets(track="")` 按轨过滤 (空参 = 全量, 旧调用行为不变) | +10 | 🟢 |
| 11 | 改 | `app/web_backend.py` | `set_config` **单向**兼容 (`harness_enabled` → `workflow_mode`, 反向不写) + 两 timeout clamp 60-600 + 非法 workflow 值返回 `{ok:false}` | +30 | 🟡 |
| 12 | 改 | `app/web_backend.py` | payload 带 `workflow` (`_file_done_payload` / `_collect_results` / 缓存命中补发) + 导出默认名 | +18 | 🟢 |
| 13 | 改 | `app/web_backend.py` | DeAI (`:937`/`:955`) 与蒸馏 timeout (`:1581`) 改读 rewrite 轨并走 #6 的 helper | +15 | 🟡 |
| 14 | 改 | `web/index.html` | 侧边栏三组 + 父/子项; 头部机制说明; **去掉首个 nav 硬编码 `active`**; 移除 `cfg-harness-enabled` 复选框; 只读段控件改"当前入口"显示; 超大块提示文案 | +55/-25 | 🟡 |
| 15 | 改 | `web/style.css` | `.nav-children` / `.nav-item.is-child` / `.nav-expander` / 来源徽标 / 跨入口提示条 (全走 token) | +70 | 🟡 |
| 16 | 改 | `web/app.js` | 唯一 `data-nav-key` 激活 + `renderSidebar` 改读 nav-key + 父项展开/`aria-expanded` + **启动按 `workflow_mode` 恢复** + 入口切换写配置 | +95 | 🟡 |
| 17 | 改 | `web/app.js` | 来源徽标 / 跨入口提示 / pending 判定 / **两条路径的覆盖确认** / `resultWorkflow` 只在成功时写 / **重跑按钮走 `force_rerun=True`** / 缓存命中提示分两种口径 | +95 | 🟡 |
| 18 | 改 | `web/app.js` | chunking **与 prompt_mode 两个**下拉按轨过滤 + 整文件告警 (阈值 20000, 放 `_runProofread`) + `_deaiChunkEstimate` 改读 rewrite 轨 + `_collectAllConfig` 去掉 `harness_enabled` | +50 | 🟡 |
| 19 | 新增 | `web/icons/` 4 处 | 补 `check-list` / `document-edit` / `document-multiple` 的 SVG + mask 映射; `app` 补 mask 映射 (已有 SVG) | +45 | 🟢 |
| 20 | 改 | `tests/*` | 见 §6 (含既有断言更新 + 新档位 + 轨过滤 + 断点保护) | +420 | 🟡 |
| 21 | 改 | `README.md` / `AGENTS.md` / `CHANGELOG.md` / `docs/ROADMAP.md` | 架构图 / 决策 §39 + 修正 §37 假声明 / v5.3.0 条目 (含烟测参数) / 进度 | +110 | 🟢 |

**合计**: 4 新增 + 17 改, 净增约 1170 行。

---

## 6. 测试计划

### 6.0 既有断言必须同步更新 (审核 B6; 前两条主会话已复核, 其余实施时逐个复核)

| 位置 | 现状 | 要改成 |
|---|---|---|
| `tests/test_web_backend_proofread.py:344-345` | `len(CHUNKING_PRESETS) == 5` / `len(CHUNKING_PRESETS_MAP) == 5` | 6 档 |
| `tests/test_web_backend_config.py:180-182` | "恰好 5 档" `len(presets) == 5` + `expected` 集合 | 6 档 + `extra_large` |
| `tests/test_harness_split.py:208-236` | 断言旧双决策 (`harness_enabled` + `prompt_mode`) 语义 | 改断言 `effective_workflow` 语义 |
| `tests/test_harness.py:583-598` | 手工全字段 `compute_prompt_hash` 与 `for_config` 等值 | 补 `\|wm=` 参数 |
| `tests/test_components.py:63`、`tests/test_web_backend_deai.py:1189`、`tests/test_harness_split.py:45,115` | `ProjectConfig` 字段数 31 | 32 |
| `tests/test_web_backend_deai.py` 的 cfg id 唯一性列表 | 含 `cfg-harness-enabled` | 复选框移除后同步删项 |
| `app/web_backend.py:208`、`tests/test_chunker_presets.py:1,31,104` 的"5 档"字样 | 文案 | 6 档 |

### 6.1 必须新增

| 测试文件 | 断言 |
|---|---|
| `tests/test_harness_split.py` | `effective_workflow`: 老配置 (无字段) 按旧逻辑派生; `ProjectConfig(prompt_mode="custom")` **直接构造** → `rewrite`; 显式值优先; 非法值回退 |
| `tests/test_harness_split.py` | 入口 × 模式矩阵: 逐条入口 + `custom`/`tech_doc` → 引擎退回整篇且**不改写** `prompt_mode`; 本地模式在两条轨都短路到本地规则 |
| `tests/test_web_backend_config.py` | `set_config` **单向**兼容: 写 `harness_enabled` → `workflow_mode` 跟随; 写 `workflow_mode` → `harness_enabled` 镜像; 非法 workflow 值 `{ok:false}` |
| `tests/test_web_backend_config.py` | **B2 集成**: 按 `_collectAllConfig` 的真实键顺序整包保存一遍, 轨道**不翻转** |
| `tests/test_web_backend_proofread.py` | 5 参数老调用仍绑定 `force_rerun` (第 6 位新参数不破坏既有绑定) |
| `tests/test_web_backend_deai.py` | 静态: 来源提示条的重跑按钮传 `force_rerun=True` (不是普通开始); 缓存命中提示按"本轨/另一轨遗留"分两种文案 |
| `tests/test_chunk_lifecycle.py` | D9 保护生效后, `force_rerun=True` 仍能覆盖被保护的成功断点 (强制重跑出口没被堵死) |
| `tests/test_chunk_lifecycle.py` | **B3 断点保护**: 逐条轨成功 → 整篇轨失败/取消 → 磁盘断点仍是逐条的 `is_done`, 再次加载可命中 |
| `tests/test_chunk_lifecycle.py` | `finish_reason="length"` 的流式响应 → 结果带 `warnings` 标记 (不静默通过) |
| `tests/test_harness_split.py` | `workflow_mode=harness` 强制走 harness; `workflow_mode=rewrite` 即使 `harness_enabled=True` 也不走 harness; 两条轨的 chunk/timeout 派生互不串 |
| `tests/test_harness_split.py` | hash 含 `\|wm=`: 同配置改 workflow → hash 变; 老配置 (无 `workflow_mode`) 派生结果 = 旧逻辑 `harness_enabled and prompt_mode in {strict,polish}` |
| `tests/test_components.py` | `ProjectConfig` 字段数 31 → 32; `to_dict`/`from_dict` 往返; 老断点 (无 `workflow_mode`) 加载不炸 |
| `tests/test_web_backend_proofread.py` | `start_proofread` 不传 workflow 时行为不变 (旧调用兼容); 传 `rewrite` 时 payload 带 `workflow=rewrite`; 导出默认名含轨名 |
| `tests/test_web_backend_config.py` | `set_config("workflow_mode", ...)` → `harness_enabled` 跟随 (显示用); 写 `harness_enabled` → `workflow_mode` 跟随 (旧客户端兼容); **不反向覆盖**; 非法值返回 `{ok:false}`; 两个新 timeout 被钳制到 60-600 |
| `tests/test_web_backend_deai.py` | 导航: 3 组标题 / 2 个 `data-view=home` 且 `data-workflow` 不同 / 「重写」子项 `data-view=deai` / 7 个视图 id 仍唯一存在 / 展开箭头是独立 button |
| `tests/test_web_backend_deai.py` | 静态: `setView` 激活态用唯一 key; 点击文件不跳页 (回归); 来源徽标与跨入口提示元素存在 |
| `tests/test_web_backend_deai.py` | **B4**: 首个 nav 不再硬编码 `active`; 启动按 `workflow_mode` 选中唯一 nav-key; `Ctrl+.`/`deaiHandoff` 进 DeAI 时父项展开 |
| `tests/test_web_backend_deai.py` | 图标: **遍历全部 `data-icon`** 断言 `.svg` 存在 + 有 mask 映射 (现存 4 个不合格: `check-list` / `document-edit` / `document-multiple` / `app`) |
| `tests/test_web_backend_deai.py` | 静态: prompt_mode 下拉按轨过滤 (逐条轨不含 `tech_doc`/`custom`) |
| `tests/test_chunker_presets.py` | 新档 `extra_large.max_chars == 50000`; `tracks` 元数据标为 harness-only; 既有 5 档 max_chars **不变** (回归); 60000 字符文本按新档切成 2 块 |
| `tests/test_chunker_presets.py` | 边界: 50001 字符**无分隔符**单段文本的切分行为 (会切出 50000+1, 需固定为断言或显式接受) |
| `tests/test_harness_split.py` | 档位兜底: 逐条轨取到 `extra_large`; 整篇轨即便配置写成 `extra_large` 也回退 `large` 且不抛异常 |
| `tests/test_web_backend_config.py` | `get_chunking_presets("harness")` **含** extra_large; `("rewrite")` **不含**; 不传参 = 全量 (旧调用兼容) |
| `tests/test_web_backend_deai.py` | 静态: 前端三个 chunking 下拉按轨填充 (harness 下拉走 `get_chunking_presets('harness')`, 整篇/兼容下拉不出现 extra_large) |
| `tests/test_web_backend_deai.py` | DeAI: `_deai_run` 拿到 `extra_large` 时回退 `large`; 蒸馏 timeout 走 rewrite 轨 |

### 6.2 必须回归

- 现有 `test_v420_nav_split` 全部改写到新结构 (视图数仍 7, 导航项变化)。
- 断点相关: `test_bugs.py` / `test_chunk_lifecycle.py` / `test_components.py` 的 cp 往返测试 (单槽语义不变, 应全绿)。
- `tests/test_harness.py` 的 `harness_enabled=False` 走 rewrite 的既有覆盖。
- 全量 `python run_all_tests.py`: **以退出码为准**。2026-09-26 本会话实测 **1343 通过 / 0 失败**; 仓库文档记的 1336 (`README.md:251`) 已过期, 实施时顺带更新。

### 6.3 手工冒烟 (不可省)

1. **pywebview 真机** 打开, 截侧边栏图: 确认 200px 宽下「逐条校对 / 整篇校对 / 去 AI 味」不换行、不挤压。
2. Playwright 三视口 (1440×900 / 1280×720 / 1000×760) 布局无重叠。**注意**: 仓库内目前**没有** Playwright 脚本 (v5.2 那次跑在会话临时目录, 未入库), 本版需**新建**并入库 (建议 `tools/smoke_ui.py`) 或明确写"一次性、不入库"。
3. 端到端: 同一文件 → 逐条跑完 → 切整篇 → 确认出现"来自逐条"提示 → 重跑 → 确认覆盖确认弹窗 → 结果源变"整篇"。
4. 端到端 (修 B3): 同一文件 → 逐条跑完 → 切整篇 → **启动后立刻取消** → 回逐条轨确认结果仍在且命中断点 (不被空 CANCELLED 断点冲掉)。

---

## 7. 风险表

| # | 风险 | 等级 | 处置 |
|---|---|---|---|
| R1 | hash 加 `\|wm=` → 全部老断点一次性失效, 用户下次要重跑 | 🟡 | 与 v5.1 `\|he=`、v5.2c 4 字段同质, **属预期**; CHANGELOG 明示 |
| R2 | 单结果槽: 切入口重跑会**覆盖**另一轨结果 | 🔴 | §4 的来源徽标 + 覆盖前确认 + 文档明示; 若要并存必须上 Phase 2 |
| R3 | 老配置 `from_dict` 派生错误 → 用户一启动就跑错引擎 | 🟡 | 派生规则表单测 + 无 `workflow_mode` 时严格按旧逻辑; 非法值回退 |
| R4 | 导航重构破坏静态测试与既有联动 (`deaiHandoff` / 错误态跳 API / 快捷键) | 🟢 | 视图 id 不变 + 保留 `data-view` 语义; 测试同步改写 |
| R5 | 200px 侧边栏装不下子项与展开箭头 | 🟡 | 子项缩进 12-16px、不加图标放大; 真机冒烟 (§6.3-1) |
| R6 | DeAI 改读 rewrite 轨 → 老用户 DeAI 分块/超时行为变一次 | 🟡 | 保留老字段兜底 + CHANGELOG 明示; DeAI 无断点, 无迁移 |
| R7 | 与 v6.0 C2 (`app.js` 拆 ES module) 撞车 | 🟡 | D6: 本计划先做, C2 在稳定 IA 上拆 |
| R8 | `set_config` 补镜像后, 老 API 客户端写老字段会连带改新字段 | 🟢 | 正是 X-4 的本意; 补测试 |
| R9 | 新增图标影响已在用 `check-list` / `document-edit` 的校对参数页 | 🟢 | 属修复 (当前是实心方块), 冒烟覆盖 |
| R10 | 整篇轨误用 50000 → 输出被端点**静默截断**且代码无检测 (全仓无 `max_tokens`, `app/processor.py:795-800` 只判空) | 🔴 | D7 只对逐条轨开放 + 引擎侧回退 + 测试覆盖。**本版不给整篇轨加长度校验** (属 Phase 2), 因此这条靠"不可选"来堵, 不留口子 |
| R11 | 50K 块超模型上下文 → 400 / context_length 错误 | 🟡 | UI 明示"需长上下文模型"; 错误走既有重试链; CHANGELOG 写清适用档位 |
| R12 | 烟测报告未入库, 耗时/是否触顶等参数缺失 | 🟡 | 实施时补记 (§0.1); 在此之前**不写死**新默认 timeout, 沿用 `harness_request_timeout` (默认 180s) |
| R13 | 新档位导致展示位 label 漂移 (`home-chunking-display` / 下拉 / 日志) | 🟢 | 仍走 `CHUNKING_PRESETS` 单点定义, 前端只读 bridge 返回值 |
| R14 | 入口与白名单冲突 (选 `custom`/`tech_doc` 却在逐条入口) 导致静默换行为 | 🟡 | §3.4: UI 下拉按轨过滤 (第一道) + 引擎白名单退回整篇并明示 (第二道) + 老配置/老 API 走同一条派生函数 |
| R15 | **前端全量保存翻转轨道** (B2): 参数页任意改动都会 500ms 后整包 `saveConfig`, payload 含 `harness_enabled` | 🔴 | D10: 移除复选框 + `set_config` 只做单向兼容 + `_collectAllConfig` 去掉该键 + "整包保存后轨道不翻转"集成测试 |
| R16 | **失败/取消覆盖另一轨已完成结果** (B3) | 🔴 | D9: 收尾时若磁盘已有 `is_done` 则跳过写入 + `test_chunk_lifecycle` 回归 + §6.3-4 端到端冒烟 |
| R17 | 启动后导航高亮与实际 `workflow_mode` 不一致 (B4) | 🟡 | §3.5: 去掉硬编码 `active` + 按配置恢复 + 静态断言 |
| R18 | `extra_large` 在 DeAI / 蒸馏路径漏堵 (它们各读各的字段) | 🟡 | D7 + §5-6/§5-13: 单点 `resolve_chunk_preset(cfg, track)` helper, 三处调用点共用 + DeAI 专项测试 |
| R19 | 50000 档是**单响应 + 50 条编辑上限**协议, 错误密集文本可能触顶 | 🟡 | 标为实验档 + CHANGELOG 明示 + 触顶时沿用既有 `WARN_EDIT_CAP` 告警; 烟测若只验了"能返回", 不作为常规默认档 |

---

## 8. Session 划分

| Session | 内容 | 工时 | 产出 |
|---|---|---:|---|
| S1 | 引擎与配置: `workflow_mode` + `effective_workflow` + hash + `_harness_active` + `set_config` 单向兼容/钳制 + 单测 | 4-6h | 后端可显式选轨 |
| S1b | **数据安全**: 断点保护 (D9) + `finish_reason=length` 截断检测 (D8) + 单测 | 2-3h | 单槽不再丢好结果, 截断可检测 |
| S2 | 桥接: `start_proofread(workflow)` + payload + 导出命名 + 测试 | 3-4h | 前端能拿到轨身份 |
| S2b | `extra_large=50000` 档位: 预设 + `tracks` 元数据 + `get_chunking_presets(track)` + `resolve_chunk_preset` 单点 helper (含 DeAI/蒸馏) + 测试 | 3-4h | 逐条轨可选 50K 块, 其余路径全堵 |
| S3 | 导航 DOM/CSS/JS + 4 个图标补齐 + 静态测试 | 4-6h | 侧边栏成型 |
| S4 | 前端 provenance + 状态恢复: 徽标 / 跨入口提示 / pending / 两条路径覆盖确认 / 启动恢复 (B4) / 下拉按轨过滤 / 整文件告警 | 3-4h | 不会误读结果, 不会选错档 |
| S5 | DeAI 一致性 (`rewrite` 轨字段 + 估算 + 文案) | 2-3h | 父组语义自洽 |
| S6 | 文档四件套 + 全量回归 + 真机/Playwright 冒烟 | 2-3h | 可发布 |

每个 session 独立可回滚; S1/S2 完成后后端即可被测试覆盖, 不依赖前端。

---

## 9. Phase 2 候选 (本版**不做**, 需求成立再做)

1. **两轨结果并存** — `_checkpoint_file(path, workflow)` → `cp_{digest}_{workflow}.json` + 旧 cp 只读迁移 (只迁 hash 匹配的 completed) + 双内存槽 + 按轨路由 pause/cancel + 前端 `streamingContent`/`renderState` 键改 `workflow|path`。代价 5-8 天, 前置是本版的 workflow 身份。**用户已确认本版不做**。
2. **整篇轨的输出长度校验** — R10 留下的口子: 给 rewrite 结果加"显著短于原文"检测 (截断告警/标 FAILED), 以及给整篇轨的 `whole_file` 加真降级 (对齐 DeAI 的 `_DEAI_WHOLE_FILE_LIMIT`)。
3. **本地模式独立入口** — `punct_local` / `md_local` 提升为 `工具` 组下的独立视图。
4. **两轨并行运行** — 需双 engine / 双线程 / 双锁与前端按轨控制。

---

## 10. 验收标准 (DoD)

- [x] 侧边栏 3 组 + 「重写 → 去 AI 味」子项; 7 个视图 id 不变且唯一
- [x] 两个入口分别以 `harness` / `rewrite` 启动, 日志、payload、导出名都带 workflow
- [x] 结果来源徽标 + 跨入口提示 + 覆盖前确认三件套可用
- [x] 来源提示条的「重跑」走 `force_rerun=True`, 能覆盖 D9 保护住的旧断点; 缓存命中提示区分"本轨命中 / 另一轨遗留"
- [x] 整篇入口选「整文件」且超阈值时弹确认; `finish_reason=length` 会在结果上打截断警告
- [x] `extra_large=50000` 在**逐条轨**可选、**整篇轨不可见**; 引擎侧对误配回退 `large` 并记日志
- [x] 50000 档依据已写进 CHANGELOG —— **用户确认可用 / 10 万档才失误**, 模型与耗时未逐项留档 (CHANGELOG 明文标注, 不假装有报告)
- [x] `punct_local` / `md_local` 在两个入口都可选且不触网
- [x] `set_config` **单向**兼容 (`harness_enabled` → `workflow_mode`) 与两端钳制生效; `AGENTS.md` §37 假声明被修正
- [x] `run_all_tests.py` 全绿: **1448 通过 / 0 失败** (基线 1343 + 新增)
- [x] Playwright 三视口冒烟通过 (84 项断言, 含跨入口来源 + `force_rerun` + 整文件 20000 弹窗端到端, `tools/smoke_ui.py` 入库); ⏳ 真机 pywebview 截图未做 (需人工开窗, 见下方残留项)
- [x] `config` 里无 `workflow_mode` 的老用户升级后行为可预测 (派生 = 旧逻辑)

**残留项 (交付时向用户说明)**:
1. **真机 pywebview 侧边栏截图**未做 —— 需要人工启动 `python main.py` 开窗; Chromium (Playwright) 与 WebView2 同源内核, 布局断言已覆盖, 但"WebView2 下字体度量略有差异"这一层没实测。
2. 50K 档的模型 / 耗时参数仍未留档 (用户口头确认可用), 若日后补到数据回填 CHANGELOG。
3. 双结果槽仍是 Phase 2 候选 (§9)。

---

## 11. 待用户拍板 (影响本计划是否需要改)

**全部已定 (2026-09-26), 无待拍板项**:

1. ~~命名~~ → ✅ 采用「逐条校对 / 整篇校对」, 「重写」作为去 AI 味父项。
2. ~~结果并存~~ → ✅ 双结果槽延后到 Phase 2。
3. ~~排期~~ → ✅ **立即执行** (本 plan 即执行依据)。
4. ~~整文件告警阈值~~ → ✅ **20000**。
5. ~~断点保护副作用~~ → ✅ 接受 + 保留强制重跑出口 (`force_rerun` 已存在, 接到来源提示条)。
6. ~~50000 档标签~~ → ✅ **正式档** (用户确认 50K 通过、10 万档才失误; 50K 即设计上限)。
7. ~~烟测参数~~ → 🟡 仍无仓库报告: 实施时在 CHANGELOG 记为"用户确认, 参数未逐项记录"; 若日后补到模型/耗时数据再回填。

---

## 12. 执行记录 (按 session 回填)

| Session | 状态 | commit | 备注 |
|---|---|---|---|
| S1 引擎与配置 | ✅ 完成 | `933cd0f` | `workflow_mode`(空=自动派生) + `effective_workflow` 单点入口 + hash 用 effective 值 + `set_config` 值域校验/钳制 |
| S1b 数据安全 | ✅ 完成 | `933cd0f` | D9 `preserve_done` 保护完成态断点 + D8 `finish_reason=length` 截断标记 → `FileResult.warnings` |
| S2 桥接 | ✅ 完成 | `933cd0f` | `start_proofread(..., workflow="")` 第 6 位追加; 停止写旧 `chunking_preset`; payload/导出名带轨 |
| S2b `extra_large` 档位 | ✅ 完成 | `933cd0f` | 50000 仅 `tracks=["harness"]`, 越轨经 `resolve_chunk_preset` 回退 `large`; 回归 1371/1371 通过 |
| S3 导航 | ✅ 完成 | `2628575` | 三组侧边栏 + 双入口共用 `view-home` + 重写父子项 (独立箭头 button) + 4 图标补齐 + `data-nav-key` 唯一激活 + 启动恢复 + 参数页去复选框/段控件改入口 |
| S4 provenance + 状态恢复 | ✅ 完成 | `2628575` | 来源徽标/提示条/覆盖确认 (批量+右键两条路径)/`resultWorkflow` 只在成功写/强制重跑/缓存两口径/整文件 20000 告警 (新增只读 `get_file_char_counts`)/两个下拉按轨过滤 |
| S5 DeAI 一致性 | ✅ 完成 | `2628575` | `_deaiChunkEstimate` 读 rewrite 轨 + 联动来源标注 (`deai-source-hint`) + 导出名带来源轨 + 兼容字段文案改「DeAI / 整篇共用」 |
| S6 文档 + 回归 + 冒烟 | ✅ 完成 | 见下条 | README/AGENTS(§39-46 + §37 更正)/CHANGELOG/ROADMAP 四件套 + 回归 1446 + `tools/smoke_ui.py` |

**S6 备注**: 文档提交与 S3-S5 的代码提交分开记录 (文档为本表最后一批改动); 冒烟脚本在实机截图中抓到 `.provenance-bar` 被 `[hidden]` 覆盖的真实缺陷并已修复; §6.1 里"引擎级强制重跑仍能覆盖被保护断点"一条补落在 `tests/test_chunk_lifecycle.py::test_v530_preserve_done_and_force_rerun`。

**追加 (v5.3.1, 同日晚)**: 用户要求移除 API 面板里的模型示例 —— `API_TEMPLATES` 全部预设 `model` 置空、说明文案去掉具体模型名、下拉只显示服务商名、选预设不再覆盖 Model 框; 详见 `CHANGELOG.md` v5.3.1 节。回归 1448 → **1463**, 冒烟 84 → **91** (本计划 §10 的 1448/84 为 v5.3.0 交付时的数字, 保留不改)。

---

## 附: 调研依据

三份并行只读调研报告 (未修改任何文件) + 主会话逐条复核:

- **数据层**: 现状数据流 8 环节 / 三方案 (单槽+标记、双内存槽、双槽+双断点) 改动清单与迁移代价 / 11 条风险
- **前端 IA**: 导航与路由链路 / DOM-CSS-JS 落地清单 / WinUI NavigationView 层级指引 / 共享队列不失真的 5 条规则 / 测试与文档影响面
- **引擎语义**: 两条轨 12 维行为差异表 / `workflow_mode` 方案 A-B 对比 / DeAI 一致性缺口 6 条 / 风格库双重身份 / 命名评分

主会话独立复核过的事实: 分块档表 (`app/utils.py:532-538`)、`_ORIGINAL_PUSH_LIMIT` (`app/web_backend.py:60`)、v5.2c plan 延期项 (`plan-v5.2c-harness-split.md:29-31`)、`clamp_map` 缺新 timeout (`app/web_backend.py:157-176`)、`start_proofread` 改写旧字段 (`app/web_backend.py:511-516`)、`set_config` 无镜像分支、`_deaiChunkEstimate` 读旧字段 (`web/app.js:2442-2443`)、harness 在途无 `_await_resume` (`app/processor.py:842-1006` 内无调用)、本地模式不建 client (`app/processor.py:357-366`)、三个图标缺 SVG 与 mask 映射 (`web/icons/` + `web/style.css:489-500`)。

追加复核 (2026-09-26, 合并 50000 档位时): `_DEAI_WHOLE_FILE_LIMIT = 20000` 兜底先例 (`app/web_backend.py:66-68`)、全仓无 `max_tokens`、rewrite 无长度校验 (`app/processor.py:795-800`)、`get_chunking_presets` 单一列表喂三个下拉 (`app/web_backend.py:207-212`、`web/app.js:522-525`)、`test_chunker_presets.py:103-114` 的档位表为迭代式断言 (加档不会自动失败, 但需扩展覆盖)。

**审核阶段修正 (2026-09-26, 独立 verifier)**: ①图标缺口是 **4 个**不是 3 个 —— `app.svg` 存在但 `data-icon="app"` (`web/index.html:54`) 同样没有 mask 映射; ②`_DEAI_WHOLE_FILE_LIMIT` 在 `:66-68` 而非 `:70-72`; ③§0.2 原写"只传 mode_key + chunking_preset"不准, 实际 5 个位置参数; ④仓库内**不存在** Playwright 脚本 (v5.2 那次在会话临时目录); ⑤基线以本会话实测 1343 为准, `README.md:251` 的 1336 已过期; ⑥`tests/test_web_backend_proofread.py:344-345` 与 `tests/test_web_backend_config.py:180-182` 的 `len == 5` 断言必须同步。

**证据缺口**: §0.1 的 "50000 字符 harness 块烟测已通过" 来自用户口述, 仓库内无报告文件。本计划据此把档位纳入范围, 但把参数补记列为实施任务 (§11-4)。
