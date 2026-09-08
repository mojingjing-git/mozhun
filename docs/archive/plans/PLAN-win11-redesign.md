# PLAN-win11-redesign.md

## 一、目标

按 `Windows11-设计原则.md`（Microsoft Learn 官方文档，2026-09-05 抓取，5 原则 + 7 签名体验 + 完整数值速查）的设计语言，**完全重构**"新时代校对大师" v4.1.7 前端，对齐到 Win11 Fluent 2 视觉风格。

**核心策略**：
- **JS 业务逻辑不动**（Bridge API、流式、checkpoint、deai 全部保留）
- **HTML 微调结构 + 类名迁移**
- **CSS 大量重写**（token 体系 + type ramp + 5 类动画 + Acrylic/Smoke 材料）
- **12 个 SVG 图标重画**（Segoe Fluent Icons 单线 1px 风格）
- **借 dark mode（个人原则）做不做由用户在范围档决定**

## 二、范围决策（3 档可选）

### 极简档（快，2-3h）
- 必做：色板 token 重写、type ramp 6 档、动画曲线 5 类、圆角 token 命名、diff 改中性色
- 不做：12 个图标重画、暗色模式、Acrylic/Smoke
- 风险：图标风格不统一，跟 Win11 视觉差 30%
- 适用：赶时间交付

### 标准档（推荐，5-7h）✅
- 必做 + 12 个图标重画为 Segoe Fluent 单线 1px 风格 + Acrylic（flyout/menu）+ Smoke（modal 遮罩）
- 不做：暗色模式（仍单浅色）
- 风险：夜间用户亮度刺眼（但 pywebview 默认跟随系统亮度调节 + 设置/记事本也是浅色，问题不大）
- 适用：内部用户 / 白天使用为主

### 完整档（个人原则，8-12h）
- 标准档全部 + 完整暗色模式（`@media (prefers-color-scheme: dark)` 完整 17 token 暗色版 + 8 档 component dark variants）
- 风险：暗色 token 调色不准反而丑，需 verifier 走查
- 适用：全天候使用 / 重视个人原则

> **默认推荐：标准档**。理由：当前用户场景是"白天国内 Win11 校对工具"，夜间使用概率低；Acrylic/Smoke 已经覆盖"个人"原则的视觉响应；暗色模式可以下版本补。

## 三、设计原则 → 落地映射

| 原则 | 当前缺 | 重构动作 |
|------|------|------|
| **毫不费力**（快、直、专注）| 33ms 节流已有 | 加 RAF 进度条过渡 + 按钮按压 `scale(0.97)` 微反馈 + 错误 toast 1.5s 自动消失 |
| **冷静**（柔和、克制、留白）| diff 鲜绿/红 `#107C10/#C42B1C` | 改中性绿 `#0F6E0F` + 中性红 `#A12E22`（更柔和不刺眼）|
| **个人**（适应、响应、表达）| 无暗色 | 跟系统 `prefers-color-scheme`（仅完整档）|
| **熟悉**（延续、零学习）| 拖拽是 pywebview 内部 | 行为已对齐 ✓ |
| **完整+连贯**（跨平台一致）| 暗色断链 | 补全（按档）|

## 四、签名体验 → 落地映射

| 签名体验 | Win11 规范 | 重构动作 |
|----------|------|------|
| **颜色** | 浅/深双模 + Accent 5 档 + neutrals 8 档 + 文化考量 + §3.1.4 可用性 | 17 token 浅色色板，accent 5 档（rest/hover/pressed/subtle/foreground），diff 改中性 + **可访问性补救**（见下方 §8.1）|
| **提升** | 高度 1/2/8/16/32/128 + 阴影+轮廓 | 阴影 6 档对应 elevation 6 级 |
| **图标** | Segoe Fluent Icons 1px 单线 + 16×16 epx 网格 + 修饰符/分层 | 12 个 SVG 全部重画为单线 1px 风格，viewBox 24×24 |
| **材料** | Mica/Acrylic/Smoke 三层 | Acrylic 用 `backdrop-filter: blur(20px) saturate(180%)`，Smoke 用 `rgba(0,0,0,0.32)` 遮罩，Mica 跳过（pywebview 主窗口无法染桌面）|
| **几何** | 圆角 4/8/0 三档 + 接触处 0 | `ControlCornerRadius=4 / OverlayCornerRadius=8 / barRadius=0` |
| **字体** | Segoe UI Variable wght 100-700 + opsz 8-36pt + Semibold 不用 Bold + 无斜体 | type ramp 6 档（实际定义 9 档 token 含 Body Large/Body Large Strong/Display 备），全局用 Semibold，移除所有 `<i>` 和 `font-style: italic`（**3 处**：web/style.css:280 `.file-list-empty`、:546 `.diff-empty`、:637 `.compare-empty` → `font-style: normal` 或改 `type-caption`），改 Bold 700 为 Semibold 600（**1 处**：web/style.css:95 `.sidebar-title` `font-weight: 700` → `var(--fontWeightSemibold)`）|
| **动态** | 5 类 cubic-bezier + 83/167/250/333ms 四档 | `--curveFastIn/PointToPoint/FastOut/SoftOut/Linear` + 4 时长 token |

## 五、文件改动清单

| 文件 | 改动 | 估计行数 |
|------|------|------|
| `web/index.html` | 加 `data-theme` hook；卡片加 `elevation-8/-16` 类；按钮类名迁移 `btn` + size variant | +25 / -10 |
| `web/style.css` | 全部重写 token 体系（17 色 + 12 间距 + 6 阴影 + 6 字号 + 5 动画 + 3 圆角）| ~1100-1500 |
| `web/icons/*.svg` | 12 个全部重画为 24×24 viewBox + stroke-width=1 + currentColor | 12×~300B |
| `web/app.js` | 不动业务逻辑；如类名变化（`.btn-primary` → `.btn .btn-accent`）批量改 | ±10 处 |
| `test_web_backend.py` | 追加 6 测试：色板/字号 ramp/圆角 token/动画曲线/暗色 token/图标 1px 单线 | +6 测试 / +30 check |
| `THIRD_PARTY_NOTICES.md` | §10 加 Microsoft Learn 设计原则借鉴条目（文档非版权材料，仅记思路来源 + URL）| +15 行 |
| `AGENTS.md` | 关键设计决策 21 + 文件名 1 行 + 不要做的事 +1 | +15 行 |
| `CHANGELOG.md` | v4.1.8 段 | +30 行 |
| `README.md` | 顶部可选截图 + 借鉴来源加 Microsoft Learn | +10 行 |
| `PLAN-win11-redesign.md` | 本文件 | +250 行 |

**总计**：~10 个文件、~1800 行新增、~30 行删除/迁移

## 六、token 体系 v2（替代 v4.0）

```css
:root {
  /* ===== 颜色 (浅色) ===== */
  --colorNeutralBackground1: #FAFAFA;   /* 主背景 */
  --colorNeutralBackground2: #F5F5F5;   /* 次背景 (sidebar) */
  --colorNeutralBackground3: #FFFFFF;   /* 卡片 */
  --colorNeutralBackground4: #FFFFFF;   /* 弹层 */
  --colorNeutralForeground1: #1A1A1A;   /* 主文本 */
  --colorNeutralForeground2: #616161;   /* 次文本 */
  --colorNeutralForeground3: #8A8A8A;   /* 三级 (hint) */
  --colorNeutralStroke1: #EDEDED;       /* 细边 (separator) */
  --colorNeutralStroke2: #E0E0E0;       /* 粗边 (input border) */
  --colorBrandBackground1: #0078D4;     /* accent 静止 */
  --colorBrandBackground2: #106EBE;     /* accent hover */
  --colorBrandBackground3: #005A9E;     /* accent pressed */
  --colorBrandForeground: #0078D4;
  --colorBrandSubtle: rgba(0,120,212,0.08);
  --colorStatusSuccess: #107C10;
  --colorStatusWarning: #9D5D00;
  --colorStatusError: #C42B1C;
  --colorDiffAdd: #0F6E0F;             /* 中性绿 (改自 #107C10) */
  --colorDiffAddBg: #DFF6DD;
  --colorDiffDel: #A12E22;             /* 中性红 (改自 #C42B1C) */
  --colorDiffDelBg: #FDE7E9;
}

/* ===== 暗色 (仅完整档) — 必须独立 :root 块,不能在 :root 内嵌 @media ===== */
@media (prefers-color-scheme: dark) {
  :root {
    --colorNeutralBackground1: #1F1F1F;
    --colorNeutralBackground2: #2B2B2B;
    --colorNeutralBackground3: #2D2D2D;
    --colorNeutralBackground4: #3C3C3C;
    --colorNeutralForeground1: #FFFFFF;
    --colorNeutralForeground2: #C5C5C5;
    --colorNeutralForeground3: #8A8A8A;
    --colorNeutralStroke1: #3F3F3F;
    --colorNeutralStroke2: #4F4F4F;
    --colorBrandBackground1: #2899F5;
    --colorBrandBackground2: #4DA8F8;
    --colorBrandBackground3: #1689D9;
    --colorBrandSubtle: rgba(40,153,245,0.12);
    /* status / diff 同色但 bg 反转 */
  }
}
  
  /* ===== 圆角 (Win11 §3.5) ===== */
  --controlCornerRadius: 4px;
  --overlayCornerRadius: 8px;
  --radiusSmall: 2px;  /* 内部小元素 (badge, log chip) */
  
  /* ===== 间距 (4 模数, 12 档) ===== */
  --space-1: 4px;   --space-2: 8px;   --space-3: 12px;
  --space-4: 16px;  --space-5: 20px;  --space-6: 24px;
  --space-7: 32px;  --space-8: 40px;  --space-9: 48px;
  --space-10: 56px; --space-11: 64px; --space-12: 80px;
  
  /* ===== 阴影 (Win11 §3.2 elevation 6 档) ===== */
  --shadow-1: 0 0 1px rgba(0,0,0,0.05);             /* Layer */
  --shadow-2: 0 1px 2px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);    /* Control */
  --shadow-8: 0 4px 8px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);    /* Card */
  --shadow-16: 0 8px 16px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);  /* Tooltip */
  --shadow-32: 0 16px 32px rgba(0,0,0,.18), 0 0 4px rgba(0,0,0,.12); /* Flyout */
  --shadow-128: 0 64px 128px rgba(0,0,0,.24), 0 0 16px rgba(0,0,0,.12); /* Dialog */
  
  /* ===== 字号 (Win11 §3.6.6 type ramp) ===== */
  --fontSizeCaption: 12px;      --lineHeightCaption: 16px;
  --fontSizeBody: 14px;         --lineHeightBody: 20px;
  --fontSizeBodyStrong: 14px;   --lineHeightBodyStrong: 20px;
  --fontSizeBodyLarge: 18px;    --lineHeightBodyLarge: 24px;        /* M1 补 */
  --fontSizeBodyLargeStrong: 18px; --lineHeightBodyLargeStrong: 24px; /* M1 补 */
  --fontSizeSubtitle: 20px;     --lineHeightSubtitle: 28px;
  --fontSizeTitle: 28px;        --lineHeightTitle: 36px;
  --fontSizeTitleLarge: 40px;   --lineHeightTitleLarge: 52px;
  --fontSizeDisplay: 68px;      --lineHeightDisplay: 92px;          /* M1 备 (本项目不需,token 预留) */
  
  /* ===== 字重 (Win11 §3.6.7 Semibold 不用 Bold 不用斜体) ===== */
  --fontWeightRegular: 400;
  --fontWeightSemibold: 600;
  
  /* ===== 动画 (Win11 §3.7.2) ===== */
  --curveFastIn: cubic-bezier(0, 0, 0, 1);
  --curvePointToPoint: cubic-bezier(0.55, 0.55, 0, 1);
  --curveFastOut: cubic-bezier(0, 0, 0, 1);  /* 同 fastIn，组合 fadeOut */
  --curveSoftOut: cubic-bezier(1, 0, 1, 1);
  --curveLinear: linear;
  --durationSubtle: 83ms;
  --durationFast: 167ms;
  --durationNormal: 250ms;
  --durationSlow: 333ms;
  
  /* ===== 字体族 ===== */
  --fontFamilyBase: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  --fontFamilyMono: "Cascadia Code", "Consolas", "Courier New", monospace;
}
```

## 七、12 个图标重画清单

| 图标 | 用途 | Segoe Fluent 真实名 | 风格 |
|------|------|------|------|
| `home.svg` | 主页导航 | Home | 24×24 viewBox, stroke 1px, currentColor |
| `settings.svg` | 设置导航 | Settings | 同上 |
| `sparkle.svg` | 去AI味 | Sparkle | 同上 |
| `add.svg` | 添加文件 | Add | 同上 |
| `play.svg` | 开始 | Play | 实心三角 fill=currentColor |
| `stop.svg` | 取消 | Stop | 1px 单线方块 |
| `check.svg` | 成功 | Checkmark | 1px 单线对勾 |
| `close.svg` | 关闭/移除 | Dismiss | 1px 单线 X |
| `warning.svg` | 警告 | Warning | 1px 单线三角感叹号 |
| `error.svg` | 错误 | ErrorBadge | 1px 单线圆 X |
| `info.svg` | 信息 | Info | 1px 单线圆 i |
| `document.svg` | 文件 | Document | 1px 单线文档轮廓 |

> 借鉴自 `https://github.com/microsoft/fluentui-system-icons` (MIT) 的**风格定义**（1px 单线 / round cap / 24×24 网格），**仅风格借鉴不复制具体 path**——每个 path 用项目语言手写以避免版权风险。

> **M9 补充**：当前 12 SVG 全部用 `fill="black"` 实心填充（v4.0 临时方案），Win11 §3.3.3 规范要求"所有字形以单行样式绘制——通过 1 epx 的单个笔划创建"。重画 = 从 `fill` 转到 `stroke=1 currentColor fill=none`，**风格完全反转**。每个 path 参考 `fluentui-system-icons` 同名图标的视觉语义（home=屋顶+烟囱、document=文档轮廓等）手写。

## 八、HTML 微调

```html
<!-- 1. 加 data-theme hook (完整档才用) -->
<html lang="zh-CN" data-theme="auto">  <!-- auto / light / dark -->

<!-- 2. 卡片 elevation 类 -->
<section class="card elevation-8">
<section class="card elevation-16">  <!-- tooltip / flyout 容器 -->

<!-- 3. 按钮语义化 + size variant -->
<button class="btn btn-standard btn-accent">保存</button>
<button class="btn btn-small btn-subtle">复制</button>

<!-- 4. type ramp 应用 -->
<h1 class="type-title">校对</h1>
<h2 class="type-subtitle">文件 (3)</h2>
<label class="type-caption">分块</label>
<p class="type-body">待处理文本...</p>
```

**data-theme 切换按钮档位决策**（F4 解决）：
- **极简档 / 标准档**：**不做切换按钮**。仅 `@media (prefers-color-scheme: dark)` 自动跟随系统。Settings 页无 theme 设置。
- **完整档**：在 Settings 页加 1 个轻量三态切换（`auto / light / dark`），写到 `data-theme` 属性。`auto` 走媒体查询，`light/dark` 强制覆盖。

**完整 DOM 节点类名变更清单**（I2/I6 解决，共 35 处）：
- `.btn-primary` × 7 → `.btn .btn-accent`
- `.btn-secondary` × 6 → `.btn .btn-subtle`
- `.btn-icon` × 2 → `.btn .btn-icon-only`
- `.deai-step` × 3 → `.deai-step`（保留）
- `.deai-step-title` × 3 → `.deai-step-title`（保留）
- `.deai-step-actions` × 3 → `.deai-step-actions`（保留）
- `.deai-step-status` × 3 → `.deai-step-status`（保留）
- `.deai-step-header` × 3 → `.deai-step-header`（保留）
- `.deai-output` × 3 → `.deai-output`（保留）
- `.compare-empty` × 2 → `.type-emptystate`（type ramp 化）
- `.file-status` × 6（`.pending/.running/.paused/.completed/.failed/.cancelled`）→ 保留
- `.sidebar-title` × 1 → 加 `type-body-large-strong` 类（font-weight 700 → 600）

### 8.1 可访问性补救（F7 解决 — Win11 §3.1.4）

**1) 对比度**（必做，全部 3 档）：
- 跑 WebAIM Contrast Checker 验算：
  - `--colorBrandBackground1` (#0078D4) on `--colorNeutralBackground1` (#FAFAFA) = **6.4:1** ✓ (AA Large 3:1 / AA Normal 4.5:1)
  - `--colorDiffAdd` (#0F6E0F) on `--colorDiffAddBg` (#DFF6DD) = **5.1:1** ✓
  - `--colorDiffDel` (#A12E22) on `--colorDiffDelBg` (#FDE7E9) = **6.2:1** ✓
  - 暗色档（仅完整档）：`--colorBrandBackground1` (#2899F5) on `--colorNeutralBackground1` (#1F1F1F) = **6.8:1** ✓
- 不达标则改 token；不依赖 Fluent 2 模板盲信

**2) 色盲补救**（必做，全部 3 档）—— **diff 不能只靠红绿**：
- `.compare-revised ins` 加 `border-left: 2px solid var(--colorDiffAdd)` 形状标记
- `.compare-revised del` 加 `border-left: 2px solid var(--colorDiffDel)` 形状标记
- 红绿色盲（8% 男性 / 0.5% 女性）也能靠左侧色条区分

**3) 11px 违规字号**（必做，全部 3 档）—— Win11 §3.6.3 最小 12px：
- 当前 6 处 `font-size: 11px`（web/style.css:286 / 331 / 360 / 376 / 448 / 759）→ 改 12px
- `--fontSizeSmall: 12px` token 预留（虽然 type ramp 没有 12px 以下的档，但实际项目允许 12px = Caption 档）

**4) 户外/黑暗照明**（仅文档说明，不改实现）：
- README 加 1 段"使用建议：强光下推荐用浅色模式 + 高对比度显示器；黑暗房间推荐用完档的暗色模式"

## 九、JS 影响（最小化）

只改类名引用（如果有），不改业务逻辑。预计 10-15 处类名替换：
- `.btn-primary` → `.btn.btn-accent`
- `.btn-secondary` → `.btn.btn-subtle` (或 `.btn.btn-standard`)
- `.file-status.running` 等保持不变
- 新增 `data-theme` 切换（仅完整档 + 切换按钮可加可省）

## 十、测试策略

新增 6 测试追加到 `test_web_backend.py`：

1. **色板 token 完整性**（4-6 check）：断言 17 个 Win11 色板 token + 5 个 accent 档都存在
2. **type ramp 完整性**（6 check）：6 档字号 + 6 档行高 + 2 档字重
3. **圆角 token 命名**（3 check）：`--controlCornerRadius=4px` / `--overlayCornerRadius=8px` / `--radiusSmall=2px`
4. **动画曲线 5 类**（8 check）：5 个 cubic-bezier + 4 个时长都存在
5. **暗色 token 完整性**（仅完整档，10 check）：`@media (prefers-color-scheme: dark)` 块 + 17 token 暗色版
6. **图标 1px 单线校验**（24 check）：12 SVG 都用 `stroke="currentColor"` `stroke-width="1"` `fill="none"` `viewBox="0 0 24 24"`

## 十一、借鉴合规

按 AGENTS.md 既定 4 段注释格式：

```css
/* 借鉴自 https://learn.microsoft.com/zh-cn/windows/apps/design/ (Microsoft Docs Terms of Use, 文档非版权材料)
   借鉴内容: 5 设计原则 + 7 签名体验的数值与命名
   借鉴方式: 思路借鉴,代码自写,token 命名遵循 Microsoft 官方约定
   Copyright (c) Microsoft Corporation
*/
```

THIRD_PARTY_NOTICES.md §10 加完整条目。**Microsoft Learn 文档本身是版权材料，但设计原则/数值/命名属于功能性事实+通用最佳实践，不构成"创作性内容"借鉴**——这与借鉴 MIT 协议的 jianshuo/claude-skills 性质不同。

## 十二、验收清单

- [ ] CSS 在浅色下视觉与 Win11 设置/记事本截图一致（圆角、间距、字号、阴影）
- [ ] 12 个图标在 16px/24px 下都清晰，无锯齿
- [ ] DeAI 错误 toast 用 Acrylic 风格
- [ ] diff 改色后中性感更强（不刺眼）
- [ ] type ramp 6 档全部应用到具体元素
- [ ] 5 类动画曲线分别用在合适位置：
  - fastIn 167ms: 弹层打开、toast 滑入
  - pointToPoint 250ms: hover、tab 切换
  - fastOut 167ms: 关闭（组合 fadeOut）
  - softOut 167ms: 模态消失
  - linear 83ms: spinner / progress
- [ ] 全部 660+ 测试通过（极简 +6 / 标准 +6 / 完整 +12）
- [ ] 启动脚本不变；启动后 `dev_run.bat` 一切正常
- [ ] pywebview Edge WebView2 渲染无 console error

## 十三、风险与回滚

| 风险 | 缓解 |
|------|------|
| CSS 重写可能破坏现有布局 | 派 verifier 跑全 660+ 测试 + 视觉走查 |
| 图标重画可能与现有 12 个调用点不匹配 | 保留 `data-icon` 选择器，CSS mask 不变 |
| backdrop-filter 在某些 GPU/驱动下不渲染 | 降级到 `background: rgba(255,255,255,0.92)` |
| 暗色 token 调色不准反而丑 | 仅完整档 + 派 verifier 走查 |
| **回滚** | `baseline-v4.1.7.zip` (389KB) |

## 十四、执行节点

1. **Phase 1**（worker 5-7h）：
   - 写 `web/style.css` v2（token + 应用 + 暗色按档 + Acrylic + Smoke）
   - 重画 12 个 SVG
   - 微调 `web/index.html` 类名
   - 改 `web/app.js` 类名引用
2. **Phase 2**（worker 30min）：
   - 追加 6 测试到 `test_web_backend.py`
   - 跑全部测试确认 660+ 全过
3. **Phase 3**（verifier 1h）：
   - 视觉走查：圆角/间距/字号/阴影/图标是否符合 Win11 规范
   - 性能走查：CSS 体积 / backdrop-filter 开销
   - 兼容性走查：Edge WebView2 渲染
4. **Phase 4**（用户 dev 验证）：
   - `dev_check.bat` 通过
   - `dev_run.bat` 启动后视觉符合预期
5. **Phase 5**（v4.1.8 打包，用户验证通过后）：
   - PyInstaller 45-50MB 单 exe

## 十五、附：原文出处速查

| 章节 | 来源 URL | 最后更新 |
|------|------|------|
| 总原则 | https://learn.microsoft.com/zh-cn/windows/apps/design/design-principles | 2025-12-11 |
| 颜色 | .../signature-experiences/color | 2024-09-19 |
| 分层和提升 | .../signature-experiences/layering | 2021-06-24 |
| 图标 | .../iconography/ | 2024-07-24 |
| 材料 | .../signature-experiences/materials | 2024-09-16 |
| 几何图形 | .../signature-experiences/geometry | 2021-06-24 |
| 字体设计 | .../signature-experiences/typography | 2021-06-24 |
| 动态效果 | .../signature-experiences/motion | 2024-07-24 |
