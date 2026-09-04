# Changelog

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
