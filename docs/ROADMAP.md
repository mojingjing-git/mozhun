# 墨准 (MoZhun) — 路线图与待办

> 当前版本: v5.3.1 (2026-09-26) — 工作流双入口 (逐条校对 / 整篇校对) + 50K 档位 + 断点保护; API 面板移除模型示例
> 下一阶段: 完成 v6.0 清理收尾，再重排 Word / docx 友好计划

跨会话持久化的工作清单。下次开新会话时, 先看本文件再决定从哪里续。

---

## ✅ 已完成: v5.3.0 工作流双入口 (2026-09-26 批准并当日完成)

计划文件: [`PLAN-workflow-split-v5.3.md`](PLAN-workflow-split-v5.3.md)（§12 执行记录表已回填）
审核报告: `.workbuddy/reviews/review-v5.3-workflow-split-plan.md` (本地, 不入库)

- 侧边栏拆出「逐条校对 / 整篇校对」两个入口，「重写 → 去 AI 味」父子项，新增「工具」组；7 个视图 id 不变
- `extra_large=50000` 并入为逐条轨专属正式档（用户烟测: 50K 通过、10 万档才失误）；整篇轨误配自动回退 `large`
- `workflow_mode` 成一等身份（空 = 旧逻辑派生）+ `|wm=` 进断点指纹 + `set_config` 单向兼容镜像
- 断点保护 D9（失败/取消不覆盖已完成结果）+ 强制重跑出口保留；截断检测 D8；整文件告警阈值 20000
- 结果来源徽标 / 跨入口提示条 / 覆盖前确认 / 导出命名带轨；参数页 harness 复选框移除，改由入口决定
- 回归 1463 / 0 失败（v5.3.1 移除 API 面板模型示例后）；新增 `tools/smoke_ui.py` 三视口 + 跨入口 + 阈值弹窗 + API 面板冒烟（91 项断言全绿）
- 提交: `933cd0f`（引擎+桥接）、`2628575`（前端+冒烟）

**Phase 2 候选（本版明确不做）**: 两轨结果并存（双断点 + 双内存槽 + 按轨路由 pause/cancel，5-8 天）；整篇轨输出长度校验；本地模式独立入口；两轨并行运行。

---

## ✅ 已完成 (历史)

- v5.1.0 (2026-09-07) — 校对流程 harness 化: Edit 工具链 (function calling) + 改动清单审计
- v5.2b — 小说切分: 独立视图 + 章节/卷识别 + 广告清理 + 去重
- v5.2c — harness / 重写双轨配置: chunking 与 timeout 分轨
- v5.0.2 (2026-09-07) — DeAI 后置三件套: strip 后置 + 本地评分 + revise
- v5.0.1 (2026-09-07) — 三份外部审计修复批 (8 critical + 4 notable 全清)
- v5.0.0 (2026-09-07) — 校对流程架构重构: 模式精简 + 校对→DeAI 联动
- v4.4.2 (2026-09-06) — Markdown 清洗 (md_local 本地引擎)
- v4.4.1 / v4.4.0 — 水墨宣纸皮肤 (默认)
- v4.3.x — 本地标点修复 v1/v2 + 10 API 预设
- v4.2.0 — 7 视图分组导航
- v4.1.8/9 — Win11 Fluent 2 视觉完全体
- v4.1.7 — 9 轴风格指纹 + 事实骨架 + AI 6 处反制
- v4.0 — pywebview 重写 (Bridge + 50ms 节流 + threading/asyncio)
- v3.0 — 业务层定型 (流式 / 客户端复用 / 5 档 chunking / 跨段上下文)

详见 `CHANGELOG.md`。

---

## 🚧 待重排: Word / docx 友好一揽子小幅修

> 原 v5.2 编号已与线上 v5.2b/c 冲突。本计划保留在本地 `.workbuddy/plans/`，
> 尚未纳入版本控制，启动前需要重新编号并核对当前 v5.2c 基线。
> v1 → v2 修复: C-1 虚拟落断点 / C-2 python-docx>=1.1 / C-3 跨段选(c) / C-4 XML escape / C-5 audit 默认 None / C-6 uuid 唯一化
> 工时: 3-4 → 4.5-4.75 人天
> 测试: 23 → 35+ 项

### P1: 粘贴即校对 (8 项测试)
- [ ] 前端: 校对页文件列表下 `<details>` 折叠粘贴面板 (镜像 DeAI `#deai-input`)
- [ ] 前端: 50K 字硬上限 + 超限 toast 引导 (不截断) (R-2)
- [ ] 前端: 任务列表行加「📋 粘贴于 HH:MM」角标
- [ ] 后端: `paste_proofread(text, source_label)` Bridge 方法
- [ ] 后端: 多次粘贴 `paste_path = Path(f"paste://{uuid.uuid4().hex[:8]}")` 唯一化 (C-6)
- [ ] 后端: `FileTask.is_virtual: bool = False` 字段, **不进 to_dict/from_dict** (A-2, 与 skip 同形)
- [ ] 后端: 落断点守卫 3 处 `if not task.is_virtual` (C-1, processor.py:535/637/671)
- [ ] 前端: 应用关闭时 `toWebviewConfirm` (有虚拟任务在跑) (R-4)
- [ ] 测试: `tests/test_paste_proofread.py` 8 项
  - [ ] 空文本拒绝 / 超 50K toast (不截断) / 正常粘走通 / 字符计数同步
  - [ ] 多次粘贴 file_key 唯一 (C-6 关键回归)
  - [ ] 虚拟任务不写 checkpoints/ (C-1 关键回归)
  - [ ] 关闭 confirm 触发
  - [ ] FileTask 序列化 is_virtual 默认 False (老断点兼容)
- [ ] AGENTS §38 虚拟 FileTask 内存态语义 / CHANGELOG v5.2

### P2: docx 平文本读入/导出 (12 项测试)
- [ ] `requirements.txt` 增 **`python-docx>=1.1.0`** (C-2 修订, 1.0 无 add_comment)
- [ ] `THIRD_PARTY_NOTICES.md` §21 完整 BSD-2-Clause LICENSE 副本 (L-1)
- [ ] `app/docx_io.py` 首部借鉴头注释 4 段 (A-4, Steve Canny)
- [ ] 新模块 `app/docx_io.py` (**非纯函数**, A-1)
  - [ ] `read_docx_text(path) -> str` (懒探测, 失败抛 `DocxReadError`)
  - [ ] `write_docx_text(path, text) -> None` (按段切分, 无格式)
  - [ ] `is_docx_available() -> bool` (探测 `import docx`)
  - [ ] `DocxReadError(Exception)` 自定义异常
  - [ ] docstring 显式标"非纯函数, IO 边界在 module 内"
  - [ ] 所有写出 `doc.core_properties.last_modified_by = "墨准"` (S-4)
- [ ] `choose_files` `file_types` 增 "Word 文档 (*.docx)"
- [ ] **拖入 docx 走 `prepare_tasks` 检测 `.docx` 后缀 → `read_docx_text`** (R-3, 不走 read_file 避免乱码)
- [ ] Bridge `is_docx_available()`, 前端据返回值灰掉 docx 入口
- [ ] `export_result(fmt='docx')` 路径, 源丢失回退 txt
- [ ] **导出对话框明示"无格式新 docx (原样式/页眉不保留)"** (S-5)
- [ ] 未装 python-docx 时后端拒收 fmt='docx'
- [ ] 测试: `tests/test_docx_io.py` 12 项
  - [ ] 读入: 普通 / 表格 / 空段 / 列表 / **加密** / **损坏** / **截断** / 抛 `DocxReadError` / 中文
  - [ ] 导出: 普通 / 多段 / 源丢失回退 / 中文 / `core_properties.last_modified_by == "墨准"`
  - [ ] 桥接: `is_docx_available()` True/False

### P3: docx Comments 注释导出 (15 项测试 + 真实 Word 验证)
- [ ] `app/docx_io.py` 增 `_xml_escape(text)` 工具函数 (C-4, 复用 `xml.sax.saxutils.escape`)
- [ ] `app/docx_io.py` 增 `write_docx_with_audit(path, text, audit)`
  - [ ] 每条 audit = 一条 comment, `author="墨准 harness"`
  - [ ] **initials 序号化 `"MZ-001"/"MZ-002"`** (S-3, 避免同 author 范围冲突)
  - [ ] 跨段定位: 累加 paragraphs 长度 → 段 index, 跨段挂首段
  - [ ] **跨段 comment 标 "[跨 N 段, 详见墨准改动清单第 X 条]"** (C-3 选策略 c)
  - [ ] 找不到 (str.find<0) 挂文末 + ⚠️
  - [ ] 全部 reason/old/new 走 `_xml_escape`
  - [ ] 长串截断 80 字符
  - [ ] `doc.core_properties.last_modified_by = "墨准"`
- [ ] `export_result` 签名 `audit: Optional[list[dict]] = None` 默认 (C-5, DeAI 路径不变)
- [ ] 前端: harness 模式从 `t.audit` 传, DeAI 模式不传
- [ ] 前端: **缓存命中 audit 空时标"📦 缓存命中, 改动清单不可恢复", 禁用「带审阅注释」** (R-1)
- [ ] 前端: harness 模式未跑 (prompt_mode 不是 strict/polish 或 harness_enabled=False) 不显示「带审阅注释」选项
- [ ] 测试: `tests/test_docx_audit_export.py` 15 项
  - [ ] `_xml_escape` 边界: 空串 / `<>&"'` / 中文 / 混合 / `&amp;` 实体
  - [ ] comment 写入: 空 audit / 全 OK / 全 SKIPPED / 混合 / 单段 edit
  - [ ] **跨段 audit** (C-3 关键回归): 跨 2 段 / 跨 3+ 段 / 跨段边界在段首/段中/段尾
  - [ ] 找不到定位挂文末 ⚠️
  - [ ] **多次同段落 comment initials 序号无冲突** (S-3 关键回归)
  - [ ] 长串截断 80 字符
  - [ ] round-trip: python-docx 写完再读, comment 文本一致
  - [ ] `audit=None` 走无注释 docx (C-5 关键回归)
  - [ ] 缓存命中 audit 空时不报错
- [ ] **真实 Word 兼容性测试 (T-2)**: Windows Word 2019/365 跑 3 个用例, 人工验证注释可见可"解决/答复"
- [ ] AGENTS §39 Comments 跨段策略选 (c) 的理由

### P4: 通用收尾
- [ ] `AGENTS.md` 新增 §37 docx_io 设计纪律 / §38 虚拟 FileTask / §39 Comments 跨段策略
- [ ] `README.md` 增特性段 + 借鉴清单 20→21
- [ ] `CHANGELOG.md` v5.2 条目
- [ ] `run_all_tests.py` 全绿 (35+ 新增)
- [ ] `start.py check` 增 `python-docx` 装/未装 + **版本 < 1.1 拒绝** 检测 (C-2 修订后)

---

## 📋 未来待办 (v5.3 / v5.4 / v6.0)

### v5.3 — docx 深度 + harness 覆盖扩展
- [ ] **docx 样式/表格/列表保留** (平文本→结构化, 真"无损"读入导出)
  - 段落 run 顺序保持
  - 表格 (行列 / 合并单元格 / 表头)
  - 有序/无序列表 (Markdown list → Word list)
  - 标题层级 (Heading 1-6)
  - 引用块
- [ ] **harness 覆盖扩展到 `tech` (技术文档) / `custom` 模式**
  - tech: 术语统一、Markdown 格式、中英文间距
  - custom: 自定义 prompt + 工具纪律双注入
  - 评估要不要给 `punct_local` / `md_local` 也加 audit (实质意义不大, 待评估)
- [ ] docx 写入样式保持 (跑 v5.2 读入→v5.3 写入, 视觉零漂移)

### v5.4 — 校对→DeAI 联动扩展
- [ ] 批量联动 (一次选多文件, 全部走「校对→DeAI 改写」流水)
- [ ] 校对结果做 DeAI Few-shot 范文 (闭环)
- [ ] DeAI 改写结果回写校对源文件 (原地替换, 留 diff 备份)
- [ ] Undo 栈 (v5.0.0 没做的"延后"项, 看 v5.3 用户反馈决定)

### v6.0 — Word 完整修订模式 (w:ins / w:del) — 立项单独评审
- [ ] **预研 1 轮**: OOXML w:ins/w:del 跨段编辑的真实复杂度
- [ ] **目标**: harness audit 直接生成 Word 修订, 用户在 Word 里逐条"接受/拒绝"
- [ ] **前置条件**:
  - v5.2/v5.3 harness 覆盖到所有模式 (否则 70% 模式导不出修订 = 负向信号)
  - audit 形态稳定 ≥ 2 个小版本
  - Python OOXML 库选型 (python-docx 不支持 w:ins/w:del 写入, 需 docx2python / 手工 XML)
- [ ] **范围**:
  - 跨段编辑: 切 paragraph + w:r 重组
  - 命名空间: w:ins/w:del/w:author/w:date 完整元数据
  - run properties 继承: 保留被替换区域的字体/字号/颜色
  - 段落级删除: 整段删除走 w:del + w:pPr
  - 兼容性测试: Word 2016/2019/365/Mac Word/WPS

### 长期 (v6.0+ 探索)
- [ ] undo 栈 (跨任务)
- [ ] 校对/DeAI 历史对比 (同一文本多次跑的版本管理)
- [ ] 多人协作 (共享 profile / 共享断点)
- [ ] 移动端 (Termux / iSH / Web 端)

---

## 🚫 明确不做 (跨版本共识)

- PyQt / PySide 重新引入 (v4.0 统一 pywebview)
- qasync (Python 3.13 不兼容, v4.0 已用 threading 替代)
- 第三方 UI 库 (qfluentwidgets 等, 破坏零构建原则)
- React / Vue / Tailwind (v4.0 零构建, 破坏 `python main.py` 直开)
- chunk overlap > 0 (校对场景重叠区被改两次)
- 借鉴项目代码复制 (全部思路借鉴, 代码自写)
- 放宽 `punct_fix.py` 四红线 (本地标点的安全优势)
- LLM tool calling 降级 fallback (v5.1.0 烟测证实一次通过, 运行时不做 fallback)
- 跨步 DeAI 编排 (step2→step3→回 step2, 放 v5.4 评估)

---

## 📊 进度跟踪

| 版本 | 状态 | 计划 | 实际 | 备注 |
|---|---|---|---|---|
| v5.1.0 | ✅ | 2026-09-07 | 2026-09-07 | harness 化 |
| v5.2b | ✅ | 2026-09-13 | 2026-09-13 | 小说切分 |
| v5.2c | ✅ | 2026-09-13 | 2026-09-13 | harness / 重写双轨 |
| v6.0 cleanup | 🚧 | TBD | — | C0/C1 完成，C2/C3/C4 待执行 |
| Word 友好 | 📋 | TBD | — | 需重新编号 |
| v5.3 | 📋 | — | — | docx 深度 + harness 扩展 |
| v5.4 | 📋 | — | — | DeAI 联动扩展 |
| v6.0 | 📋 | — | — | Word 完整修订模式 |

> 状态: ✅ 完成 / 🚧 进行中 / 📋 待办 / ⛔ 阻塞
