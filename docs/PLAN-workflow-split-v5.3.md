# 墨准 v5.3 工作流双入口 — 实施计划

**版本**: v5.3.0 (拟)
**基线**: `master @ 3c41f8c` (校对与对比单页已合并)
**状态**: ⏳ 待评审 — **尚未开工**
**总工时**: 16-24h (2.5-3.5 人天, 6 个 session)
**最后更新**: 2026-09-26
**调研方式**: 3 个并行只读 agent (数据层 / 前端 IA / 引擎语义) + 主会话逐条复核

---

## 0. 三条前提修正 (先读, 否则方案会建在错的假设上)

### 0.1 「harness 单块上限 50000」不存在

| 说法 | 事实 | 依据 |
|---|---|---|
| harness 单块可达 50000 字 | **当前不存在该档位**。分块档只有 `fast 2000 / balanced 3000 / high_context 4000 / large 6000 / whole_file 0`, harness 默认 `large=6000`, `whole_file` 才表示整篇不切块 | `app/utils.py:532-538` |
| 50000 是什么 | 是 IPC 推送阈值 `_ORIGINAL_PUSH_LIMIT` / `_DEAI_PUSH_LIMIT`, 超过就不往前端推原文, 前端改走 `read_file` 兜底 | `app/web_backend.py:56-68` |
| 50000 档从哪来 | v5.2c plan 的**延期项**: "新增 `extra_large=50000` — 等真实烟测确认 50000 字符 harness 块可承受再单独加档", 风险表也标 "50000 字块未实测 🟡" | `.workbuddy/plans/plan-v5.2c-harness-split.md:29-31, 399, 475` |

**结论**: 拆入口的理由**不能**是"harness 能跑大块"。harness 当前的真实优势是输出形态 (逐条 `tool_calls`, 输出 token 少、可审计)。想拿 50K 大块作为卖点, 必须先补一次真实烟测, 那是**独立于本计划**的另一件事。

### 0.2 现在没有"模式"这个一等概念

引擎选择是**两个字段派生**出来的, 且派生逻辑只写在引擎里:

- `_harness_active()` = `harness_enabled` **且** `prompt_mode ∈ {strict, polish}` — `app/processor.py:805-816`
- 前端入口只传 `mode_key` + 旧 `chunking_preset` — `web/app.js:1225-1231`
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
4. 顺带修掉 0.3 的三处不一致, 以及三个渲染成实心方块的坏图标。

**非目标 (本版明确不做)**

- ❌ `extra_large=50000` 分块档 (需真实烟测, 独立立项)
- ❌ 同一文件两轨结果**并存** (双结果槽 + 双断点; 见 §2 D1 与 §9)
- ❌ 两轨**并行**运行 (现为单 engine / 单线程 / 单队列)
- ❌ harness 改流式 (AGENTS §36 已定"建议不做流式")
- ❌ 拆分 `view-home` 成两个视图 (会复制 DOM/ID, 且掩盖真正的共享状态问题)

---

## 2. 决策表 (本计划的选型, 逐条给理由)

| # | 决策 | 选择 | 理由 / 被否方案 |
|---|---|---|---|
| **D1** | 两轨结果是否并存 | **共享队列 + 单结果槽 + 强制来源标注**; 双槽留 Phase 2 | 用户诉求是"入口清晰", 不是"两轨对拍"。双断点方案实测代价 5-8 天 + 要迁移老 `cp_*.json` (迁移失败会**不可逆覆盖**用户已完成结果)。Phase 1 的 workflow 身份是 Phase 2 的严格前置, 分期不浪费 |
| **D2** | 导航层级 | **两层**: 组标题 (工作区/工具/设置) → 项; 只有「重写 → 去 AI 味」一层父子 | WinUI NavigationView 官方指引: 层级可做但"two levels is ideal"。用户原提案的"工作区 > 工具 > 项"是三视觉层级, 偏离指引 |
| **D3** | 入口命名 | **逐条校对 / 整篇校对**, 不在引擎入口上用"重写"二字 | 见 §3.2 命名分析: harness 是**机制**不是校对本身; `tech_doc/custom` 与本地模式都会溢出错父组 |
| **D4** | 模式是否升为一等字段 | **是**: `ProjectConfig.workflow_mode ∈ {harness, rewrite}`, 持久化 | 仅做 UI 预设 (不改 schema) 会让**每次切入口都失效断点** (因 `harness_enabled` 已在 hash 里), 且后端永远不知道是哪个入口启动的 |
| **D5** | 入口状态是否持久化 | **持久化**, 导航入口即"当前工作流" | 只做一次性运行参数会导致: 入口显示的和 `校对参数` 页存的不是一回事, 反而更难懂 |
| **D6** | 版本与排期 | 独立 **v5.3.0**, 排在 v6.0 清理 C2 (`app.js` 拆 ES module) **之前** | C2 要在 12 个模块里重新分布导航与 track 状态; 应在 IA 稳定后再拆 |

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

---

## 5. 改动清单

| # | 类型 | 文件 | 内容 | 估计行 | 风险 |
|---|---|---|---|---:|---|
| 1 | 改 | `app/utils.py` | `ProjectConfig.workflow_mode` 字段 + `to_dict`/`from_dict` 派生与镜像 | +45 | 🟡 |
| 2 | 改 | `app/utils.py` | `compute_prompt_hash` / `compute_prompt_hash_for_config` 加 `\|wm=` | +6 | 🟡 |
| 3 | 改 | `app/processor.py` | `_harness_active()` 改读 `workflow_mode` (保留 getattr 兜底) | +10 | 🟡 |
| 4 | 改 | `app/web_backend.py` | `start_proofread(..., workflow="")` 末位可选参数; 不再无条件改写旧 `chunking_preset` | +25 | 🟡 |
| 5 | 改 | `app/web_backend.py` | `set_config` 补: workflow↔harness 镜像 + 老字段→新字段镜像 + 两个 timeout 的 clamp (60-600) | +30 | 🟢 |
| 6 | 改 | `app/web_backend.py` | payload 带 `workflow` (`_file_done_payload` / `_collect_results`) + 导出默认名 | +15 | 🟢 |
| 7 | 改 | `app/web_backend.py` | DeAI 改读 `chunking_preset_rewrite or chunking_preset` / `rewrite_request_timeout or timeout` | +8 | 🟡 |
| 8 | 改 | `web/index.html` | 侧边栏三组 + 父/子项 DOM; 头部机制说明位 | +40/-15 | 🟢 |
| 9 | 改 | `web/style.css` | `.nav-children` / `.nav-item.is-child` / `.nav-expander` / 来源徽标 / 跨入口提示条 (全走 token) | +70 | 🟡 |
| 10 | 改 | `web/app.js` | `workspaceTrack` 状态 + 唯一 `data-nav-key` 激活 + 父项展开 + 入口切换写配置 | +80 | 🟡 |
| 11 | 改 | `web/app.js` | 来源徽标 / 跨入口提示 / pending 判定 / 覆盖确认 / 事件里落 `runWorkflow` | +70 | 🟡 |
| 12 | 改 | `web/app.js` | `_deaiChunkEstimate` 与 DeAI 折叠文案改读 rewrite 轨 | +10 | 🟢 |
| 13 | 新增 | `web/icons/check-list.svg` 等 3 个 | 补 `check-list` / `document-edit` / `document-multiple` 图标 + CSS mask 映射 | +40 | 🟢 |
| 14 | 改 | `tests/*` | 见 §6 测试计划 | +300 | 🟡 |
| 15 | 改 | `README.md` / `AGENTS.md` / `CHANGELOG.md` / `docs/ROADMAP.md` | 架构图 / 决策 §39 + 修正 §37 假声明 / v5.3.0 条目 / 进度 | +90 | 🟢 |

**合计**: 2 新增 + 13 改, 净增约 830 行。

---

## 6. 测试计划

### 6.1 必须新增

| 测试文件 | 断言 |
|---|---|
| `tests/test_harness_split.py` | `workflow_mode=harness` 强制走 harness; `workflow_mode=rewrite` 即使 `harness_enabled=True` 也不走 harness; 两条轨的 chunk/timeout 派生互不串 |
| `tests/test_harness_split.py` | hash 含 `\|wm=`: 同配置改 workflow → hash 变; 老配置 (无 `workflow_mode`) 派生结果 = 旧逻辑 `harness_enabled and prompt_mode in {strict,polish}` |
| `tests/test_components.py` | `ProjectConfig` 字段数 31 → 32; `to_dict`/`from_dict` 往返; 老断点 (无 `workflow_mode`) 加载不炸 |
| `tests/test_web_backend_proofread.py` | `start_proofread` 不传 workflow 时行为不变 (旧调用兼容); 传 `rewrite` 时 payload 带 `workflow=rewrite`; 导出默认名含轨名 |
| `tests/test_web_backend_config.py` | `set_config("workflow_mode", ...)` 镜像到 `harness_enabled`; 反向亦然; 非法值返回 `{ok:false}`; 两个新 timeout 被钳制到 60-600 |
| `tests/test_web_backend_deai.py` | 导航: 3 组标题 / 2 个 `data-view=home` 且 `data-workflow` 不同 / 「重写」子项 `data-view=deai` / 7 个视图 id 仍唯一存在 / 展开箭头是独立 button |
| `tests/test_web_backend_deai.py` | 静态: `setView` 激活态用唯一 key; 点击文件不跳页 (回归); 来源徽标与跨入口提示元素存在 |
| `tests/test_web_backend_deai.py` | 图标: 每个 `data-icon` 都有对应 `.svg` 文件 + CSS mask 映射 (**新增, 防止再出现实心方块**) |

### 6.2 必须回归

- 现有 `test_v420_nav_split` 全部改写到新结构 (视图数仍 7, 导航项变化)。
- 断点相关: `test_bugs.py` / `test_chunk_lifecycle.py` / `test_components.py` 的 cp 往返测试 (单槽语义不变, 应全绿)。
- `tests/test_harness.py` 的 `harness_enabled=False` 走 rewrite 的既有覆盖。
- 全量 `python run_all_tests.py` (基线 1343 通过)。

### 6.3 手工冒烟 (不可省)

1. **pywebview 真机** 打开, 截侧边栏图: 确认 200px 宽下「逐条校对 / 整篇校对 / 去 AI 味」不换行、不挤压。
2. Playwright 三视口 (1440×900 / 1280×720 / 1000×760) 布局无重叠 (沿用 v5.2 UI 收口的冒烟脚本)。
3. 端到端: 同一文件 → 逐条跑完 → 切整篇 → 确认出现"来自逐条"提示 → 重跑 → 确认覆盖确认弹窗 → 结果源变"整篇"。

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

---

## 8. Session 划分

| Session | 内容 | 工时 | 产出 |
|---|---|---:|---|
| S1 | 引擎与配置: `workflow_mode` 字段 + hash + `_harness_active` + `set_config` 镜像/钳制 + 单测 | 4-6h | 后端可显式选轨 |
| S2 | 桥接: `start_proofread(workflow)` + payload + 导出命名 + 测试 | 3-4h | 前端能拿到轨身份 |
| S3 | 导航 DOM/CSS/JS + 3 个图标补齐 + 静态测试 | 4-6h | 侧边栏成型 |
| S4 | 前端 provenance: 徽标 / 跨入口提示 / pending 判定 / 覆盖确认 | 3-4h | 不会误读结果 |
| S5 | DeAI 一致性 (`rewrite` 轨字段 + 估算 + 文案) | 2-3h | 父组语义自洽 |
| S6 | 文档四件套 + 全量回归 + 真机/Playwright 冒烟 | 2-3h | 可发布 |

每个 session 独立可回滚; S1/S2 完成后后端即可被测试覆盖, 不依赖前端。

---

## 9. Phase 2 候选 (本版**不做**, 需求成立再做)

1. **两轨结果并存** — `_checkpoint_file(path, workflow)` → `cp_{digest}_{workflow}.json` + 旧 cp 只读迁移 (只迁 hash 匹配的 completed) + 双内存槽 + 按轨路由 pause/cancel + 前端 `streamingContent`/`renderState` 键改 `workflow|path`。代价 5-8 天, 前置是 Phase 1 的 workflow 身份。
2. **本地模式独立入口** — `punct_local` / `md_local` 提升为 `工具` 组下的独立视图。
3. **`extra_large=50000` 分块档** — 先做真实烟测 (单块 50000 字符 + harness 的耗时/失败率), 通过再谈加档。
4. **两轨并行运行** — 需双 engine / 双线程 / 双锁与前端按轨控制。

---

## 10. 验收标准 (DoD)

- [ ] 侧边栏 3 组 + 「重写 → 去 AI 味」子项; 7 个视图 id 不变且唯一
- [ ] 两个入口分别以 `harness` / `rewrite` 启动, 日志、payload、导出名都带 workflow
- [ ] 结果来源徽标 + 跨入口提示 + 覆盖前确认三件套可用
- [ ] `punct_local` / `md_local` 在两个入口都可选且不触网
- [ ] `set_config` 老↔新字段镜像与两端钳制生效; `AGENTS.md` §37 假声明被修正
- [ ] `run_all_tests.py` 全绿 (基线 1343 + 新增)
- [ ] 真机侧边栏截图 + Playwright 三视口冒烟通过
- [ ] `config` 里无 `workflow_mode` 的老用户升级后行为可预测 (派生 = 旧逻辑)

---

## 11. 待用户拍板 (影响本计划是否需要改)

1. **命名**: 接受「逐条校对 / 整篇校对」(本计划推荐), 还是坚持字面「校对 / 重写」?
2. **结果并存**: 接受"共享单结果槽 + 强提示"(Phase 1), 还是要求同一文件两轨结果并存 (触发 Phase 2, 工时翻倍)?
3. **排期**: 接受 v5.3 排在 v6.0 C2 之前?

---

## 附: 调研依据

三份并行只读调研报告 (未修改任何文件) + 主会话逐条复核:

- **数据层**: 现状数据流 8 环节 / 三方案 (单槽+标记、双内存槽、双槽+双断点) 改动清单与迁移代价 / 11 条风险
- **前端 IA**: 导航与路由链路 / DOM-CSS-JS 落地清单 / WinUI NavigationView 层级指引 / 共享队列不失真的 5 条规则 / 测试与文档影响面
- **引擎语义**: 两条轨 12 维行为差异表 / `workflow_mode` 方案 A-B 对比 / DeAI 一致性缺口 6 条 / 风格库双重身份 / 命名评分

主会话独立复核过的事实: 分块档表 (`app/utils.py:532-538`)、`_ORIGINAL_PUSH_LIMIT` (`app/web_backend.py:60`)、v5.2c plan 延期项 (`plan-v5.2c-harness-split.md:29-31`)、`clamp_map` 缺新 timeout (`app/web_backend.py:157-176`)、`start_proofread` 改写旧字段 (`app/web_backend.py:511-516`)、`set_config` 无镜像分支、`_deaiChunkEstimate` 读旧字段 (`web/app.js:2442-2443`)、harness 在途无 `_await_resume` (`app/processor.py:842-1006` 内无调用)、本地模式不建 client (`app/processor.py:357-366`)、三个图标缺 SVG 与 mask 映射 (`web/icons/` + `web/style.css:489-500`)。
