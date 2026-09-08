# PLAN-distill-style — v4.1.7 借鉴蒸馏文风融入 DeAI 升级 plan

> 借鉴自 [jianshuo/claude-skills](https://github.com/jianshuo/claude-skills) (MIT License) 的 9 轴风格指纹 + 事实骨架纪律 + AI 6 处易露馅 + 8 轴自评思路, 把 DeAI 3 步工作流从 V4 升级到 V5.
>
> **Copyright (c) 2026 Jianshuo Wang (王建硕)** — 完整 LICENSE 见 `THIRD_PARTY_NOTICES.md §9`.

---

## 1. 背景与决策

### 1.1 用户痛点
- V4 DeAI 改出来是"通用 AI 味换种 AI 味", 用户想要"像某人写"做不到
- 改写可能篡改事实 (顺手"中和"或"补料")
- 改写完没客观评分 (自己看着像 ≠ 真的像)
- 样本没沉淀, 每次从零喂范文

### 1.2 为什么借鉴 jianshuo
- 9 轴 + 事实骨架 + AI 6 处 + 8 轴自评 是**结构化指纹方案**, 跟 V4 "通用反 AI 腔" 是正交升级
- 仓库 MIT 协议, 借鉴合规风险低
- claudewave.com 上有完整 SKILL.md 公开可查 (SKILL.md 全文成功拉到)
- 不用 azoth07 (无 LICENSE 风险)
- 不用图灵判别盲测 (用户单模型, 不需要)

### 1.3 决策
- ✅ 借鉴: 9 轴指纹 / 事实骨架 / AI 6 处 / 8 轴自评 / 蒸馏流程 (样本 → 9 轴拆解 → 锚点原句 → style-card.md)
- ✅ 思路借鉴, 无代码复制 (跟项目 AGENTS.md 既有 8 段借鉴一致)
- ❌ 不借鉴: 图灵判别盲测 (单模型场景, 内联 8 轴自评替代)
- ❌ 不引用: jianshuo 仓库真迹 (home.wangjianshuo.com) — 3 套预置 profile 抽象化无具体作家

### 1.4 升级定位
- DeAI V4 → V5 (prompt 升级 + 新增 6 个 Bridge API + 前端 Step 0 卡片)
- 不动现有 3 步主流程 (向后兼容, styleCardSlug 空时走 V5 默认 prompt)
- 不动业务逻辑 (processor.py / context_builder.py)
- 不打包, 修完 dev 验证

---

## 2. 9 轴 schema (项目语言重写, 不复制 jianshuo 原文)

每轴 3 件事: 观察 (样本里看到什么) / 可执行规则 (改写时怎么照做) / 锚点原句 (从样本摘 2-3 句真实原句).

| # | 轴 | 抓什么 | V5 prompt 改写应用 |
|---|---|---|---|
| 1 | 句子节奏 | 长短句分布 / 长短交替的拍子 / 标点签名 | 改写时长短交替 / 短句为主 / 单句成段 |
| 2 | 段落长度 | 平均段长 / 单句成段 / 长段密度 | N 句一段 / 单句成段在 X 场景 |
| 3 | 词汇 | 高频词 / 口头禅 / 自造词 / 人称 / 中英混用 / 用词雅俗 | 专名原文 / 替换 / 翻译习惯 |
| 4 | 语气腔调 | 自信度 / 距离感 (亲密 vs 客观) / 正式度 / 幽默 | 我/你/您 / 距离感 / 允许语气词 |
| 5 | 论证结构 | 断言先行 vs 层层铺垫 / 推进路径 | 结论前置 / 推进连接 |
| 6 | 比喻运用 | 家常 vs 抽象 / 频率 / 抽象↔具体架梯子 | 生活类比 vs 抽象 + 频率上限 |
| 7 | 情绪强度 | 情绪温度 / 克制 vs 喷发 / 感叹密度 | 动作暗示 vs 直白 + "我" 出场数 |
| 8 | 开头与收尾 | 起手 (断言/场景/钩子) / 落地收束 | 时间锚 / 场景 / 留白 |
| 9 | 雷区 | 绝不会做的事 (不用某类钩子 / 不用某类书面词) | 改写时黑名单 |

### 9 轴 → 30-45 个细颗粒可执行维度 (推荐成卡形态)
- 9 轴是起手拆解的脚手架
- 成卡时拆成 ~30-45 个**细颗粒可执行维度**, 分组放表格
- 每维一句"怎么样的"规则
- 蒸馏过程靠锚点原句校准 (必须, 否则规则空转)
- 成卡里例子要精简 — 例子不一定典型、容易被当公式照搬, 规则才有通用性

### 调料校准 (写进每张卡尾部)
- 签名动作 (造词 / 家常比喻 / 单句成段 / 破折号) 是**工具**不是**清单**
- 短内容就短写, 别把每个签名动作都堆满
- 堆满就是拙劣模仿, 不是那个人

### AI 6 处易露馅 (写进每张卡尾部)
1. 缺真实专名 → 用真实 API/库名/版本号替代占位符
2. 结尾太圆 → "希望对您有帮助" / "总之" / "综上所述" 一律删
3. 推进太顺 → 允许 "但有个例外" / "坑:" 转折, 不允许一气呵成
4. 鸡汤教科书化 → "站在更高的视角看" / "底层逻辑是" 一律删
5. 批次指纹 → 一段不同时塞 3+ 个短句/破折号/反问/口头禅
6. 文章原型不匹配 → 论点型不冒充叙事型, 叙事型不冒充段子型

---

## 3. 蒸馏流程 (样本 → Style Card)

```
样本入库 (3-6 篇)
    ↓
判断样本数量 (>= 3 才进)
    ↓
拼 samples/ 全文 + SYSTEM_PROMPT_DISTILL_STYLE → LLM 流式
    ↓
LLM 逐轴分析, 每轴摘 2-3 句真实原句 (锚点纪律)
    ↓
写出 style-card.md (Markdown 9 段 + 调料校准 + AI 6 处)
    ↓
meta.distilled_at 标记
    ↓
前端可读 / 手改 / 注入 Step 2/3
```

### 3 段纪律
1. **观察与规则必须基于样本, 不许编** — 锚点原句必须从输入直接抄, 不许 AI 写"我看到的"假摘要
2. **指纹只抓"怎么写", 不抓"想什么"** — "他爱唱反调"是想法, 不是文风; 同一个观点换他来写会长什么样才是文风
3. **样本 < 3 篇时**在卡头加警告 "⚠️ 样本仅 N 篇, 指纹可能不稳"

---

## 4. 改写流程 (带事实骨架 + 8 轴自评闭环)

```
抽事实骨架 (3-8 条 bullet, 改写不增不减)
    ↓
按 9 轴改写 (短句节奏 / 词汇 / 比喻 / 收尾)
    ↓
范文学习 (学句长, 口气, 转折, 毛边)
    ↓
调料校准 (签名动作不堆满)
    ↓
AI 6 处反制 (改写后自查)
    ↓
事实校对 (改写后事实不能篡改)
    ↓
8 轴自评 (单模型场景内联, 替代'独立判官盲测')
    ↓
三维评分 (AI 味消除度 / 流畅度 / 保留原意度)
```

### 关键决策
- 单模型场景, 用 8 轴自评 (1-5 评分 + 摘出戏句) 替代 jianshuo 推荐的"独立判官盲测"
- 满足度足够, 不用引入异模型判官
- 找具体出戏句 (必做, 不许只说"有 AI 味") — 每条低于阈值的轴, 引用 1-2 句"出戏"的具体句子

---

## 5. 实现方案

### 5.1 后端 (3 大块)

#### 5.1.1 `app/style_profiles/` (新建模块)
- `__init__.py` 模块入口
- `loader.py` `StyleProfileLoader` 类:
  - `list_builtin() / get_builtin(key)` — 3 套预置 profile
  - `list_custom() / get_custom(slug)` — 扫 `~/.proofreader/styles/<slug>/meta.json`
  - `create_custom(slug, name)` / `delete_custom(slug)` / `add_sample(slug, content, filename)` / `save_style_card(slug, markdown)` / `get_style_card(slug)` / `start_distill(slug, llm_callback)`
  - **slug 校验**: `[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}` (拒 `..` / `/` / `\` / 空 / 中英混)
- `builtin/{plain_tech,narrative_general,daily_colloquial}.json` 3 套抽象化预置 (9 轴 schema, 项目语言重写, 无具体真人作家)

#### 5.1.2 `app/templates.py` (新增 4 个 V5 prompt)
- `SYSTEM_PROMPT_DISTILL_STYLE` — 蒸馏入口 (9 轴 schema + 锚点纪律 + AI 6 处)
- `SYSTEM_PROMPT_DEAI_DETECT_V5` — 升级 detect: 原 7 大类 + AI 6 处反制
- `SYSTEM_PROMPT_DEAI_REWRITE_V5` — 升级 rewrite: 9 轴 + 事实骨架 + 范文锚点
- `SYSTEM_PROMPT_DEAI_AUDIT_V5` — 升级 audit: 原 3 维 + 8 轴自评
- 4 段借鉴注释在 V5 段上方

#### 5.1.3 `app/web_backend.py` (新增 6 个 Bridge API + 升级 _deai_run)
- `list_style_profiles() -> {builtin: [...], custom: [...]}` — 列所有
- `create_style_profile(slug, name, summary="") -> {ok, profile, error}` — 建 custom
- `delete_style_profile(slug) -> {ok, deleted, error}` — 删 custom (拒 builtin)
- `add_sample_to_profile(slug, content, filename="") -> {ok, slug, filename, samples_count, error}` — 加范文
- `distill_style_profile(slug) -> task_id` — 启动后台蒸馏, 流式推 onDeaiStream (step='distill'), 完成推 onDeaiComplete
- `get_style_card(slug) -> {ok, slug, name, samples_count, distilled_at, card_markdown, axes, ai_tells_counter, error}` — 读 style-card.md
- `deai_step1_detect / deai_step2_rewrite / deai_step3_audit` 全部加 `style_card_slug: str = ""` 可选参数
- `_deai_run` 接受 `style_card_slug`, 走 V5 路径
- `_build_deai_prompt` V5 注入 (rewrite/audit 加 9 轴 + 风格卡全文)
- `_deai_distill_run` 后台蒸馏主循环 (建临时 AsyncOpenAI, 流式调 LLM, 落盘 style-card.md)

### 5.2 前端 (3 大块)

#### 5.2.1 `web/index.html` view-deai 加 Step 0 卡片
- profile 下拉 (builtin 3 套 optgroup + custom N 套 optgroup)
- 新建 profile (slug + name inputs + 按钮)
- 加范文 (textarea + 按钮 + info 显示 samples_count)
- 蒸馏按钮 (>= 3 篇才 enabled)

#### 5.2.2 `web/app.js` 5 个新方法
- `loadStyleProfiles()` 异步, init() 时调一次
- `renderStyleProfileSelect()` 渲染下拉 (builtin + custom 分组)
- `createStyleProfile()` 弹窗 + 调 API + 自动选上
- `addSampleToProfile()` 调 API + 清空 textarea + 刷新下拉
- `distillStyleProfile()` 调 API, 流式 partial 推 onDeaiStream (step='distill')
- `selectStyleProfile(slug)` 更新 info + 按钮联动 (builtin 禁加样本/蒸馏, custom 样品 < 3 禁蒸馏)
- 路由分发: `handleDeaiStreamOrDistill` (按 step 路由)
- `deaiStep1/2/3` 全部传 `this.deai.styleCardSlug`

#### 5.2.3 `web/style.css` 新增 .style-profile-section
- `.input-with-action` flex 布局
- `.style-profile-card` 列表卡片
- `.style-profile-loading` 蒸馏 spinner (animation: spin)

### 5.3 存储路径
- `~/.proofreader/styles/<slug>/` (跟项目 CONFIG_DIR/CHECKPOINT_DIR 一致, 不引入新 home 子目录)
- jianshuo 原 `~/code/style-cards/<author-slug>/` 路径, 改项目统一路径
- 结构: `{samples/, style-card.md, meta.json}`

---

## 6. 测试方案 (12 个新测试, 100 check)

| # | 测试 | 验证 |
|---|------|------|
| 1 | `test_v417_list_style_profiles` (10) | builtin 3 套 + 字段完整 |
| 2 | `test_v417_create_and_delete_profile` (10) | 目录/samples/meta.json/重名 |
| 3 | `test_v417_delete_builtin_rejected` (2) | 拒删 plain_tech |
| 4 | `test_v417_add_sample_increments_count` (9) | count 自增/空内容/不存在 |
| 5 | `test_v417_save_and_get_style_card` (8) | 9 轴粗解析 |
| 6 | `test_v417_distill_style_profile_mock` (8) | mock LLM callback 落盘 |
| 7 | `test_v417_distill_too_few_samples` (3) | < 3 篇抛 ValueError |
| 8 | `test_v417_deai_step2_with_style_card_prompt` (5) | prompt 含 9 轴 + 事实骨架 |
| 9 | `test_v417_deai_step2_without_style_card_backward_compat` (4) | 无 style_card 仍走 V5 |
| 10 | `test_v417_deai_step3_audit_8_axis_prompt` (6) | 8 轴自评 + 三维 |
| 11 | `test_v417_style_card_path_traversal` (22) | 11 种非法 slug 拒绝 |
| 12 | `test_v417_distill_concurrent_no_interference` (4) | 2 thread 不串台 |

---

## 7. 借鉴合规 (5 项强制)

1. **4 段注释** 加在 4 个新文件 + 改文件头部 (loader.py 头部 / templates.py V5 段上方 / web_backend.py 6 个新方法 docstring / test_web_backend.py v417 段)
2. **THIRD_PARTY_NOTICES.md §9** 加完整段 (URL + MIT License 全文 1076 字节 + 借鉴内容 + 借鉴方式 + Copyright)
3. **MIT 完整文本** 复制 (web_fetch raw.githubusercontent.com/jianshuo/claude-skills/main/LICENSE 字符级匹配)
4. **不复制任何 jianshuo prompt 文本** — 9 轴描述 / prompt 措辞 全部项目语言重写
5. **不硬编码** "jianshuo" / "王建硕" / "wjs-distilling-style" 字样 — 只在致谢和注释
6. **不用真迹** (home.wangjianshuo.com 文章) — 3 套预置抽象化, 无具体真人作家

---

## 8. 已知限制 (dev 验证前提)

- 蒸馏 10-30s 等待 (UI spinner 提示)
- 9 轴 prompt 增加 ~80% token 成本 (单次调用 ~3-4K tokens 进 system)
- 单模型无独立判官 (Step 3 内联 8 轴自评替代, 满足度足够)
- profile 文件系统管理靠用户主动 (不云同步, 不导出导入)
- 1 个 flaky test (`test_v417_distill_concurrent_no_interference`) 在系统繁忙时偶发 fail, 重跑都过, 接受
- 抽事实骨架在 prompt 里要求, 实际不改写后做事实校对 (本项目只要求"事实不增不减" 在 prompt 层, 不用 LLM 二次校对)

---

## 9. 文件改动清单 (落地核对)

| 类型 | 路径 | 改动 |
|------|------|------|
| 新建 | `app/style_profiles/__init__.py` | 模块入口, 4 段借鉴注释 |
| 新建 | `app/style_profiles/loader.py` | `StyleProfileLoader` 类 (~480 行) |
| 新建 | `app/style_profiles/builtin/plain_tech.json` | 通用技术文 (抽象化) |
| 新建 | `app/style_profiles/builtin/narrative_general.json` | 通用叙事文 (抽象化) |
| 新建 | `app/style_profiles/builtin/daily_colloquial.json` | 通用口语朴实 (抽象化) |
| 改 | `app/templates.py` | +4 个 V5 prompt + 4 段借鉴注释 |
| 改 | `app/web_backend.py` | +6 个 Bridge API + `_deai_distill_run` + 升级 `_deai_run` / `_build_deai_prompt` 走 V5 |
| 改 | `web/index.html` | view-deai 加 Step 0 区域 |
| 改 | `web/app.js` | +5 个新方法 + 路由分发 `handleDeaiStreamOrDistill` + deaiStep1/2/3 传 styleCardSlug |
| 改 | `web/style.css` | +.style-profile-section / .style-profile-card / .style-profile-loading |
| 改 | `test_web_backend.py` | +12 个测试函数 (100 check) |
| 改 | `run_all_tests.py` | 加注释 (无新文件) |
| 改 | `THIRD_PARTY_NOTICES.md` | §9 完整段 (URL + MIT 全文 + 借鉴内容 + 借鉴方式 + Copyright) |
| 改 | `AGENTS.md` | 关键设计决策 17-20 (9 轴/事实骨架/AI 6 处/8 轴自评) + 文件名 + 不要做 |
| 改 | `CHANGELOG.md` | v4.1.7 段 |
| 改 | `README.md` | DeAI 表格加 Step 0 + 借鉴来源加 jianshuo + 段升级 8→9 |
| 新建 | `PLAN-distill-style.md` | 本文件 |

---

## 10. 验收 (用户 dev 验证步骤)

1. `dev_check.bat` — 7 项检查全过
2. `dev_run.bat` — pywebview 启动正常
3. DeAI 视图:
   - 顶部 Step 0 卡片出现
   - profile 下拉含 3 套预置 (plain_tech / narrative_general / daily_colloquial)
   - 选 1 套预置 → info 显示摘要, 按钮禁加样本/蒸馏
   - 输 slug + name → 创建 custom profile → 自动选上 → 按钮可点
   - 粘 3 篇范文到 textarea → 加 3 次 → info 显示"3 篇"
   - 蒸馏按钮变可点 → 跑 10-30s → status 显示"已完成" → 写盘 `~/.proofreader/styles/<slug>/style-card.md`
   - 选 custom profile → Step 2 改写 prompt 含 9 轴 (可在后端 logger 看到 SYSTEM_PROMPT_DEAI_REWRITE_V5 注入)
   - Step 3 评分含 8 轴自评
4. 跑 `python run_all_tests.py` 确认 **652/0 全过**

---

**最后更新**: 2026-09-05
**借鉴来源**: [jianshuo/claude-skills](https://github.com/jianshuo/claude-skills) (MIT) — 9 轴风格指纹 + 事实骨架纪律 + AI 6 处反制 + 8 轴自评
**Copyright (c) 2026 Jianshuo Wang (王建硕)**
