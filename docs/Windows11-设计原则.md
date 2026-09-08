# Windows 11 设计原则（极尽详细版）

> 整理自 Microsoft Learn 官方文档：
> - 主入口：https://learn.microsoft.com/zh-cn/windows/apps/design/design-principles
> - 7 个签名体验子页：颜色 / 提升和分层 / 图标 / 材料 / 几何图形 / 字体设计 / 动态效果
> - 内容最后更新：2025-12-11（原则页） / 2024-09-19（颜色） / 2024-09-16（材料） / 2024-07-24（图标、运动） / 2021-06-24（分层、几何、字体）
> - 抓取时间：2026-09-05
> - 关联：Fluent Design System（fluent2.microsoft.design）

---

## 一、概述

Windows 11 标志着操作系统的视觉进化。微软与 **Fluent** 一起发展了他们的设计语言，以创建一个人类、通用和真正感觉与 Windows 一样的设计。

文档将分两层：

1. **设计原则**（5 条）—— 形而上的指导思想
2. **签名体验**（Signature Experiences，7 个）—— 视觉语言在所有 Fluent 体验中保持统一外观与感受的具体设计元素

---

## 二、Windows 11 设计原则（5 条）

> "以下设计原则在将 Windows 打造为 Fluent 的同类最佳实现的过程中，始终指引着我们。"

### 2.1 毫不费力（Effortless）

**原文定义**：
> Windows 11 更快、更直观。我可以轻松地做我想做的事，专注而精准。

**落地含义**：
- 性能与交互响应是第一优先级——用户不会感知到等待
- 交互链路最短、认知负担最低
- 默认行为覆盖 80% 场景，复杂操作隐藏在二级菜单

### 2.2 冷静（Calm）

**原文定义**：
> Windows 11 更柔和、更整洁；它呈现淡入背景的效果，可帮助用户保持冷静和专注。体验感觉温暖、空灵和平易近人。

**落地含义**：
- 视觉密度低，留白充足
- 颜色克制，强调色仅在必要时出现
- 动效短促、不抢戏，强化内容而非自身
- 背景层（Acrylic/Mica）柔和地融入桌面，让前景内容成为视觉主角

### 2.3 个人（Personal）

**原文定义**：
> Windows 11 可无缝适应用户操作设备的习惯。它会根据我的个人需求和偏好灵活调整，让我能够真正表达自我。

**落地含义**：
- 浅色/深色模式自动跟随系统设置
- 用户可自定义强调色，应用应能识别并融入
- 动效、布局、行为应响应不同的输入方式（鼠标/触摸/笔/键盘）
- 内容能根据上下文（设备能力、网络、用户习惯）调整

### 2.4 熟悉（Familiar）

**原文定义**：
> Windows 11 兼顾焕然一新的外观与体验，以及我早已熟悉的 Windows 的亲切感。用户无需学习如何操作，可以直接上手使用。

**落地含义**：
- 延续 Windows 既有交互范式（窗口、菜单、命令栏、文件资源管理器等）
- 关键 UI 元素（标题栏、最小化/最大化/关闭、右键菜单、拖拽）的行为和位置不变
- 新视觉风格（Fluent）建立在用户已建立的肌肉记忆之上

### 2.5 完整 + 连贯（Complete + Coherent）

**原文定义**：
> Windows 11 提供跨平台的视觉无缝体验。我可以在多个平台间工作，并且仍能获得一致的 Windows 体验。

**落地含义**：
- 同一应用在桌面、平板、Xbox、HoloLens 上保持一致的视觉语言
- 跨设备的状态同步符合直觉
- 设计令牌（颜色、字体、间距、圆角、阴影）全局复用，避免"两套系统"

---

## 三、Windows 11 签名体验（Signature Experiences）

> "标志性体验是 Windows 11 用于表达其视觉语言的设计元素，同时在所有 Fluent 体验中保持统一的外观与感受。"

7 个核心签名体验，每个都从概念、原则、具体数值、最佳实践几个层面展开。

---

### 3.1 颜色（Color）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/color

> "Windows 使用颜色来帮助用户通过指示用户界面元素之间的视觉层次结构和结构来专注于其任务。颜色取决于上下文，用于呈现一种平和的基调，巧妙地增强用户交互，仅在必要时突出重要项。"

#### 3.1.1 颜色模式和主题

- Windows 支持 **两种颜色模式**：浅色（Light）和深色（Dark）
- 每种模式由一组**中性颜色值**组成，自动调整以确保最佳对比度
- 应用主题影响：背景、文本、图标、命令控件的颜色
- **默认行为**：应用主题跟随 Windows 设置或设备的默认主题
- **可覆盖**：可在代码中专门为应用设置主题
- **重要规律**：在浅色和深色模式下，**较深的颜色指示背景图面不太重要**；重要图面突出显示，颜色较浅且较亮。详细见 [§3.2 提升和分层](#32-提升和分层layering)

#### 3.1.2 主题色（Accent Color）

- 强调色用于在 UI 中突出显示重要元素
- 指示交互对象或控件的状态（hover、pressed、focused、selected）
- 主题色值由系统**自动生成并优化**，以保证浅色/深色模式下的对比度
- **使用原则**：谨慎使用，仅在突出重要元素和传达交互状态时使用

#### 3.1.3 颜色使用原则

| 原则 | 解释 |
|---|---|
| **有效地使用颜色** | 谨慎地使用颜色突出显示重要元素时，颜色可帮助创建流畅直观的 UI |
| **使用颜色指示交互性** | 选一种颜色来指示应用程序中处于交互状态的元素（如蓝色文本表示超链接） |
| **可自定义颜色** | 用户选择的强调色 + 浅/深主题应贯穿其整个使用体验；按需融入而非覆盖 |
| **颜色具有文化性** | 不同文化对颜色解读不同——蓝色在一些文化中象征美德保护，在另一些文化中代表哀悼 |

#### 3.1.4 可用性（Accessibility）

| 维度 | 指南 |
|---|---|
| **对比度** | 确保元素和图像具有足够的对比度，在不考虑强调色或主题的情况下能清晰区分 |
| **照明** | 注意环境照明变化对应用可用性的影响——黑色背景的页面在户外可能因屏幕眩光难以看清；白色背景在黑暗房间可能刺眼 |
| **色盲** | 约 **8% 男性**和 **0.5% 女性**是红绿色盲，避免单独使用红绿对比来区分元素 |

#### 3.1.5 相关资源

- [Windows 应用中的主题（theming）](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/theming)
- [XAML 样式](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/platform/xaml/xaml-styles)
- [XAML 主题资源](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/platform/xaml/xaml-theme-resources)
- [WinUI 3 展示 - 颜色](winui3gallery://item/Colors)
- [Fluent 2 Color](https://fluent2.microsoft.design/color)

---

### 3.2 提升和分层（Layering & Elevation）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/layering

> "Windows 11 使用分层和提升作为应用层次结构的基础。层次结构传达了重要信息，这些信息涉及如何让用户在应用中导航时将注意力集中在最重要的内容上。分层和提升是强大的视觉提示，它们使体验现代化，让体验在 Windows 中给人一致化的感觉。"

#### 3.2.1 提升（Elevation）的概念

- 提升是一个图面相对于另一个图面产生的**空间关系（深度）**
- 当两个或多个对象占用屏幕上同一位置时，**只有提升程度最高的对象才会在该位置呈现**
- 阴影和轮廓在控件和图面上微妙地表示提升程度，引导用户关注焦点
- Windows 11 的标准提升值表（阴影高度 / 笔画宽度）：

| 元素 | 高度值 | 笔画宽度 |
|---|---|---|
| 窗口（Window） | 128 | 1 |
| 对话框（Dialog） | 128 | 1 |
| 浮出控件（Flyout） | 32 | 1 |
| 工具提示（Tooltip） | 16 | 1 |
| 卡片（Card） | 8 | 1 |
| 控件（Control） | 2 | 1 |
| 层（Layer） | 1 | 1 |

#### 3.2.2 控件状态下的提升变化

| 状态 | 高度值 | 笔画宽度 |
|---|---|---|
| 静止（Rest） | 2 | 1 |
| 悬停（Hover） | 2 | 1 |
| 按下（Pressed） | 1 | 1 |

> 注：阴影强度会因主题（浅色/深色）在相同数值条件下而变化。

#### 3.2.3 分层（Layering）的概念

- 分层是将一个表面与另一个表面**重叠**的概念，在同一应用中创建两个或多个视觉上可区分的区域
- **Windows 11 对应用程序使用双层系统**：

| 层级 | 作用 | 包含 |
|---|---|---|
| **基层** | 应用的基础，最底层 | 应用菜单、命令、导航相关控件 |
| **内容层** | 用户关注中心体验 | 叠加在连续元素上，或将内容分隔为多个卡片 |

#### 3.2.4 阴影（Shadow）

- 阴影是增强提升概念的关键视觉提示
- 当表面提升到另一个表面时，会在它下面的层上投射阴影
- **高程越高，阴影就越大又柔和**
- 在 Windows 11 中，阴影与**轮廓配合**以传达深度
- **设计准则**：
  - 标准控件（弹出窗口、对话框、工具提示）已根据其高度包含适当的阴影
  - **有目的地使用阴影**，而非仅为了装饰
  - 出现在基础层之上的对话框应投射出明显的阴影
  - 过度使用阴影会降低其影响并产生视觉噪音
- **实现**：见 [Windows 应用中的阴影](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/shadows)（ThemeShadow / DropShadow）

#### 3.2.5 相关资源

- [Fluent 2 Elevation](https://fluent2.microsoft.design/elevation)
- [Windows 应用中的阴影（ThemeShadow / DropShadow）](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/shadows)

---

### 3.3 图标（Iconography）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/iconography/

> "图标是一组视觉图像和符号，可帮助用户了解和移动你的应用。图标在整个用户界面中用作表示概念、操作或状态的视觉隐喻。"
> "Windows 11 使用三种类型的图标：应用程序、系统、文件类型。本文重点介绍了前两种类型。"

#### 3.3.1 三类图标

| 类型 | 用途 |
|---|---|
| **应用程序图标** | 表示 Windows shell 中的应用；主要用于打开应用；呈现应用 |
| **系统图标** | 应用 UI 中用于命令栏、导航、状态指示器 |
| **文件类型图标** | 表示特定文件格式（本文未展开） |

#### 3.3.2 应用程序图标（App Icons）

- 应用图标应该通过一个隐喻来体现应用的核心功能
- 详细设计指南见 [应用图标](https://learn.microsoft.com/zh-cn/windows/apps/design/iconography/app-icons)

#### 3.3.3 系统图标：Segoe Fluent Icons

- Windows 11 引入了新的系统图标字体 **Segoe Fluent Icons**
- 此字体与 Windows 11 的 [几何图形](#34-几何图形geometry) 设计相得益彰
- **所有字形都以单行样式绘制**——通过 **1 epx** 的单个笔划创建
- 遵循三项美学原则：

| 原则 | 含义 |
|---|---|
| **最小** | 字形仅包含传达概念所需的详细信息 |
| **和谐** | 标志符号基于简单的几何形式 |
| **翻新** | 字形使用现代隐喻，易于理解 |

#### 3.3.4 图标大小

- 字体指标与 SVG 和位图图标的习惯用法匹配
- 每个字体标志符号都经过设计，使占用的图标区域为方形 em
- **16-epx 字号的图标 = 16×16-epx 图标**——大小调整和定位更具可预测性

#### 3.3.5 修饰符（Modifier）

通过将**基图标**与**修饰符图标**组合，可以直观地构造系统图标标志符号。

| 角色 | 定义 | 位置 |
|---|---|---|
| **基图标** | 视觉标志的主元素 | 应填满整个图标的面积 |
| **修饰符图标** | 修改基图标的含义 | 放置在图标占用空间的**底部象限**之一 |

**示例**：
- 仅基图标：纸张图标 → 表达"文件"概念
- 基图标 + 修饰符：文件图标 + 向上箭头 → 表达"上传的文件"

#### 3.3.6 图标分层（Icon Layering）

- 图标分层是一种用于**重叠两个字形**的技术
- 建议用于创建**同一图标的不同状态**（例如活动或所选状态）
- 黑白文件夹图标 + 没有轮廓的米色文件夹图标 = 带有黑色轮廓的米色文件夹图标

#### 3.3.7 本地化

- 了解符号的文化内涵
- 尽管大多数情况下图标不需要本地化，但某些图标在一种区域性中可能可以接受，但不能在另一种区域性中接受
- **在实际使用的上下文中验证图标选择**

#### 3.3.8 相关资源

- [Windows 应用中的 Icons](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/controls/icons)
- [Fluent 2 Iconography](https://fluent2.microsoft.design/iconography)
- [Segoe Fluent Icons 字体](https://learn.microsoft.com/zh-cn/windows/apps/design/iconography/segoe-fluent-icons-font)
- [应用图标设计指南](https://learn.microsoft.com/zh-cn/windows/apps/design/iconography/app-icons)

---

### 3.4 材料（Materials）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/materials

> "材料是应用于 UX 图面（类似于真实的手工制品）的视觉效果。Windows 使用两种主要类型的材料：遮挡（Opaque）和透明（Transparent）。遮挡材料（如亚克力和云母）用作交互式 UI 控件下的基层。烟雾等透明材料用于突出显示沉浸式表面。"
> "Mica、Acrylic 和 Smoke 各自在 Windows 中使用方式具有特定用途。"

#### 3.4.1 三种核心材料总览

| 材料 | 类型 | 模式感知 | 用途 |
|---|---|---|---|
| **Acrylic（亚克力）** | 半透明（毛玻璃） | ✅ 支持浅色/深色 | 暂时性的轻型消除图面，如浮出控件、上下文菜单 |
| **Mica（云母）** | 不透明 | ✅ 支持浅色/深色 | 应用主背景层（基层）；内置活动/非活动窗口焦点指示 |
| **Smoke（烟雾）** | 半透明 | ❌ 始终为半透明黑色 | 模式对话框下，强调阻止交互 |

#### 3.4.2 Acrylic（亚克力）

- 复制毛玻璃效果的半透明材料
- **Windows 11 中已更新**：更亮、更半透明，加强与背后视觉对象的上下文关系
- **使用限制**：仅用于**暂时性的轻型消除图面**（如浮出控件、上下文菜单）
- **不能用于**：永久应用背景（应用主表面用 Mica）

#### 3.4.3 Mica（云母）

- **Windows 11 引入的新不透明材料**
- 云母图面使用**用户的桌面背景色进行淡染**——应用视觉上"扎根"于桌面
- **内置窗口焦点指示**：区分活动/非活动状态
- **适用场景**：应用主窗口的基层（Base Layer）

#### 3.4.4 Smoke（烟雾）

- 通过使下面的图面**变暗**来强调重要的 UI 图面
- 使下面的图面渐渐进入背景中
- 用于**模式 UI（Modal UI）**（如对话框）下，发出**阻止交互**的信号
- **不能感知模式**：在浅色和深色模式下，始终为半透明黑色

#### 3.4.5 选择材料的决策树

```
需要展示的图面是什么？
├── 应用主背景（Base Layer）
│   └── 使用 Mica（云母）—— 跟随桌面，淡染，模式感知
├── 浮出控件、上下文菜单、临时弹出
│   └── 使用 Acrylic（亚克力）—— 半透明毛玻璃，模式感知
└── 模式对话框（Modal Dialog）下
    └── 使用 Smoke（烟雾）—— 半透明黑色遮罩，阻止交互
```

#### 3.4.6 相关资源

- [Acrylic 详细指南](https://learn.microsoft.com/zh-cn/windows/apps/design/style/acrylic)
- [Mica 详细指南](https://learn.microsoft.com/zh-cn/windows/apps/design/style/mica)
- [Fluent 2 Material](https://fluent2.microsoft.design/material)

---

### 3.5 几何图形（Geometry）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/geometry

> "几何图形描绘了屏幕上 UI 元素的形状、大小和位置。这些基本设计元素有助于让整个设计系统的体验保持一致。"
> "Windows 几何图形已设计为支持新式应用体验。渐进式圆角、嵌套元素和一致的线槽组合在一起，产生了一种舒适、稳定和易使用的效果，强调了目的和易用性的统一。"

#### 3.5.1 圆角总览

- Windows 11 将圆角应用于**所有顶级应用窗口**以及最常见的控件（Button、ListView 等）
- 使用**三种级别的圆角**：

| 圆角半径 | 使用情况 |
|---|---|
| **8px** | 顶级容器（应用窗口、下拉菜单、对话框）的圆角 |
| **4px** | 页面内的元素（按钮、列表背板）的圆角 |
| **0px** | 与其他直边缘相交的直边缘不会被圆角化 |
| **0px** | 当窗口对齐或最大化时，窗口角不会变圆 |

#### 3.5.2 不同 UI 元素类型的圆角规则

| 元素类型 | 圆角半径 | 示例 |
|---|---|---|
| **矩形 UI 元素**（标准控件） | **4px** | Button、CheckBox、ComboBox、TextBox、ListView |
| **弹出/覆盖 UI 元素** | **8px** | ContentDialog、Flyout、MenuFlyout、TeachingTip；**例外：工具提示用 4px**（因为较小） |
| **条形/线条元素** | **4px** | ProgressBar、ScrollBar、Slider |
| **不进行圆角的情况** | **0px** | 容器内多 UI 元素相互接触时；浮出控件连接到某侧时 |

#### 3.5.3 不进行圆角处理的典型情况

- **当容器内的多个 UI 元素相互触摸**（如 SplitButton 的两部分）—— 接触时不应有空格
- **当浮出式 UI 元素连接到某个界面**——该侧不圆角（如自动建议弹出窗口贴在文本框下方）

#### 3.5.4 自定义角半径

默认角半径由两个全局资源控制：

| 全局资源 | 默认值 | 作用 |
|---|---|---|
| `ControlCornerRadius` | 4px | 页面内元素 |
| `OverlayCornerRadius` | 8px | 浮出/覆盖元素 |

可以在 `App.xaml` 中**重写这些数值**，以更改应用中所有控件的舍入。

**Win32 桌面应用**：可使用 **DWM API** 选择性启用应用窗口的圆角化。详见 [在桌面应用中应用圆角](https://learn.microsoft.com/zh-cn/windows/apps/design/desktop/modernize/ui/apply-rounded-corners)。

#### 3.5.5 间距与线槽

> （本文档基于的原则：渐进式圆角、嵌套元素、一致的线槽共同产生"舒适、稳定、易使用"的效果）

#### 3.5.6 相关资源

- [Fluent 2 Shapes](https://fluent2.microsoft.design/shapes)
- [在桌面应用中应用圆角](https://learn.microsoft.com/zh-cn/windows/apps/design/desktop/modernize/ui/apply-rounded-corners)

---

### 3.6 字体设计（Typography）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/typography

> "作为语言的视觉表示形式，版式的主要任务是传达信息。Windows 类型系统可帮助你在内容中创建结构和层次结构，以最大程度地提高 UI 中的可读性和可读性。"
> "**Segoe UI Variable** 是 Windows 的新系统字体。它是对经典 Segoe 字体的全新演绎，并使用**可变字体技术**在非常小的尺寸下动态提供出色的易读性，并在显示尺寸下改进轮廓。"

#### 3.6.1 Segoe UI Variable 的两个轴

| 轴 | 范围/作用 | 备注 |
|---|---|---|
| **权重（`wght`）** | 100（细）→ 700（粗） | 用于精细控制文本粗细 |
| **光学大小（`opsz`）** | 8pt（小）→ 36pt（大） | **自动默认开启**；控制字体的 counters 形状和大小；小字号优先可读性，大字号突出个性 |

> 使用 XAML 通用控件时，默认会为支持的语言选择 Segoe UI Variable 字体。使用此字体或其他带光轴的可变字体时，光学尺寸将自动匹配请求的字体大小。使用 HTML 时，也自动光学缩放，但需要在 CSS 中指定 Segoe UI Variable 字体。

#### 3.6.2 权重表

| 权重名称 | 权重轴值 |
|---|---|
| **浅色（Light）** | 300 |
| **半光（Semilight）** | 350 |
| **常规（Regular）** | 400 |
| **半粗体（Semibold）** | 600 |
| **加粗（Bold）** | 700 |

#### 3.6.3 Windows 11 排版最佳实践

| 特征 | 值 | 备注 |
|---|---|---|
| **重量** | 常规、半粗体 | 大多数文本用常规粗体，标题用半粗体 |
| **对齐** | 左、中 | 默认左对齐；仅极少数情况下居中对齐（如图标下方的文本） |
| **最小值** | 14px 半粗体、12px 正常 | 小于这些大小和重量的文本在某些语言中难以辨认 |
| **大小写** | 句子大小写 | 对所有 UI 文本使用句子大小写，包括标题 |
| **截断** | 省略号（默认）和剪切（极少） | 大多数情况下使用省略号；仅在极少数情况下使用剪裁 |

#### 3.6.4 字体选择最佳实践

- **整个应用的 UI 中使用一种字体**
- 推荐坚持使用 Windows 应用的默认字体 **Segoe UI Variable**
- 其设计旨在保持不同字体大小和像素密度下的最佳可读性
- 提供清晰、明亮、开放的美学风格，完美补充系统内容

#### 3.6.5 字体大小与缩放

- XAML 应用中的字体大小在**所有设备上自动缩放**
- 缩放算法确保大屏幕上 10 英尺外的 24px 字体与几英寸小屏幕上的 24px 字体一样清晰
- 因系统缩放工作原理，**设计时采用有效像素（epx）而非实际物理像素**，不必更改字体大小来适应不同尺寸屏幕的分辨率

#### 3.6.6 字体渐变（Type Ramp）

> "Windows 字体渐变可在页面上的字型之间建立关键关系，帮助用户轻松阅读内容。所有大小均采用有效像素（epx）。"

| 示例 | 角色 | 重量 | 大小/行高 |
|---|---|---|---|
| Caption（小型） | 小型 | 12/16 epx | — |
| Body（正文） | 文本 | 14/20 epx | — |
| Body Strong（正文加粗） | 文本半粗体 | 14/20 epx | — |
| Body Large（正文大） | 文本 | 18/24 epx | — |
| Body Large Strong（正文大加粗） | 文本半粗体 | 18/24 epx | — |
| Subtitle（副标题） | 显示半粗体 | 20/28 epx | — |
| Title（标题） | 显示半粗体 | 28/36 epx | — |
| Title Large（标题大） | 显示半粗体 | 40/52 epx | — |
| Display（显示） | 显示半粗体 | 68/92 epx | — |

这些类型样式可用作遵循 [XAML 类型渐变](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/platform/xaml/xaml-theme-resources#the-xaml-type-ramp) 约定的 XAML 静态资源。

#### 3.6.7 排版规则详解

**对齐**：
- 默认 `TextAlignment` 是**左对齐**
- 左边对齐但右边不对齐可提供一致的内容编排效果和统一的布局
- RTL 语言需特殊处理（见 [调整布局和字体以支持全球化](https://learn.microsoft.com/zh-cn/windows/apps/design/globalizing/adjust-layout-and-fonts--and-support-rtl)）
- XAML：
  ```xaml
  <TextBlock TextAlignment="Left">
  ```

**字符计数**：
- ✅ **每行保持 50-60 个字母**以便于阅读
- ❌ **每行不要少于 20 个字符或多于 60 个字符**，否则不便于阅读

**剪裁和省略号**：
- 文本超出可用空间时，**建议剪辑文本并插入省略号 `...`**
- 这是大多数 WinUI 文本控件的默认行为
- 多行时：✅ 剪裁文本并换行 ❌ 不要使用省略号来避免视觉混乱
- XAML：
  ```xaml
  <TextBlock TextWrapping="WrapWholeWords" TextTrimming="Clip"/>
  ```
- 省略号使用条件：容器未完善定义（不区分背景颜色）或有"查看更多"链接

**特别说明**：
> "粗体和斜体样式不属于 Windows 字体阶梯。**建议使用 Semibold 而不是 Bold** 来进行强调。**斜体被排除**因为它可以减少可读性和易读性，特别是对于患有阅读障碍的人。"

#### 3.6.8 全球化字体建议

**Segoe UI Variable** 用于英语、欧洲语言、希腊语和俄语。**其他语言**使用 `LanguageFont` 字体映射 API 以编程方式访问特定语言的建议字体系列、大小、粗细和样式。

**非拉丁语言的字体**：

| 字体系列 | 样式 | 备注 |
|---|---|---|
| **Ebrima** | 常规、粗体 | 非洲文字脚本 UI 字体（阿德拉姆文、埃塞俄比亚文、恩科文、奥斯曼亚文、提芬纳格文、瓦伊文） |
| **Gadugi** | 常规、粗体 | 北美语言脚本 UI 字体（加拿大音节文字、切罗基语、奥塞治文） |
| **Leelawadee UI** | 常规、半细、粗体 | 东南亚语言脚本 UI 字体（布吉斯语、高棉语、老挝语、泰语） |
| **Malgun Gothic** | 常规 | 朝鲜语 UI 字体 |
| **Microsoft JhengHei UI** | 常规、粗体、细体 | 繁体中文 UI 字体 |
| **Microsoft YaHei UI** | 常规、粗体、细体 | 简体中文 UI 字体 |
| **Myanmar Text** | 常规 | 缅甸脚本的回退字体 |
| **Nirmala UI** | 常规、半细、粗体 | 南亚语言脚本 UI 字体（孟加拉语、查克马文、梵文、古吉拉特语、锡克教文、埃纳德语、马拉雅拉姆语、曼尼普尔文、奥里亚语、欧甘语、僧伽罗语、索拉文、泰米尔语、泰卢固语） |
| **Segoe UI** | 多种 | 阿拉伯语、亚美尼亚语、格鲁吉亚语、希伯来语 UI 字体 |
| **SimSun** | 常规 | 旧版中文 UI 字体 |
| **Yu Gothic UI** | 细体、半细、常规、半粗、粗体 | 日语 UI 字体 |

#### 3.6.9 Sans-serif 字体

| 字体系列 | 样式 | 备注 |
|---|---|---|
| **Arial** | 常规、斜体、粗体、粗斜体、黑体 | 欧洲和中东语言脚本（拉丁、希腊、西里尔、阿拉伯、亚美尼亚、希伯来）；黑体仅支持欧洲 |
| **Calibri** | 常规、斜体、粗体、粗斜体、细体、细斜体 | 欧洲和中东（拉丁、希腊、西里尔、阿拉伯、希伯来）；仅提供竖排阿拉伯语 |
| **Consolas** | 常规、斜体、粗体、粗体斜体 | 欧洲（拉丁、希腊、西里尔）的等宽字体 |
| **Segoe UI** | 多种 | 欧洲和中东（阿拉伯、亚美尼亚、西里尔、格鲁吉亚、希腊、希伯来、拉丁）和 Lisu 脚本的 UI 字体 |
| **Selawik** | 常规、半细、细体、粗体、半粗 | 计量与 Segoe UI 兼容的开源字体；用于其他平台不希望包含 Segoe UI 的应用。 [GitHub](https://github.com/Microsoft/Selawik) |

#### 3.6.10 Serif 字体

| 字体系列 | 样式 | 备注 |
|---|---|---|
| **Cambria** | 常规 | 欧洲（拉丁、希腊、西里尔）的 Serif 字体 |
| **Courier New** | 常规、斜体、粗体、粗体斜体 | 欧洲和中东的 Serif 固定宽度字体 |
| **Georgia** | 常规、斜体、粗体、粗体斜体 | 欧洲（拉丁、希腊、西里尔） |
| **Times New Roman** | 常规、斜体、粗体、粗体斜体 | 欧洲和中东的旧字体 |

#### 3.6.11 可变字体

| 字体系列 | 轴 | 备注 |
|---|---|---|
| **Bahnschrift** | 重量、宽度 | 拉丁、希腊、西里尔的可变字体 |
| **Segoe UI Variable** | 粗细、光学尺寸 | 拉丁、希腊、西里尔的可变字体 |

#### 3.6.12 符号和图标字体

| 字体系列 | 备注 |
|---|---|
| **Segoe Fluent Icons** | 应用图标的 UI 字体 |
| **Segoe UI Emoji** | 表情符号的 UI 字体 |
| **Segoe UI Symbol** | 符号的后备字体 |

#### 3.6.13 相关资源

- [Fluent 2 字体设计](https://fluent2.microsoft.design/typography)
- [Segoe UI Variable 字体下载](https://learn.microsoft.com/zh-cn/windows/apps/design/downloads/#fonts)
- [Segoe Fluent Icons 字体](https://learn.microsoft.com/zh-cn/windows/apps/design/iconography/segoe-fluent-icons-font)
- [调整布局和字体以支持全球化](https://learn.microsoft.com/zh-cn/windows/apps/design/globalizing/adjust-layout-and-fonts--and-support-rtl)
- [LanguageFont 字体映射 API](/zh-cn/uwp/api/windows.globalization.fonts.languagefont)

---

### 3.7 动态效果（Motion）

**来源**：https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/motion

> "动态效果描述界面对用户交互进行动画处理和响应的方式。在 Windows 中，动画是具有反应性、直接且符合上下文的。它为用户输入提供反馈，并强化支持方法查找的空间范例。"

#### 3.7.1 运动原则（5 条）

##### 1) 已连接（Connected）：操作的元素无缝连接

- 更改位置和大小的元素应**直观地从一种状态连接到另一种状态**，即使它们未在后台连接
- 引导用户遵循从点到点的元素，降低静态状态更改的认知负载
- **示例**：当窗口在浮动、贴靠和最大化之间转换时，始终感觉是同一个窗口

##### 2) 一致（Consistent）：共享入口点时，元素行为应类似

- 共享同一 UI 入口点的界面应以**相同的方式**调用和关闭，保持交互一致性
- 每个转换都应尊重其他元素的**计时、缓动、方向**，确保界面感觉一致
- **示例**：所有任务栏浮出控件在调用时**向上滑动**，在关闭时**向下滑动**

##### 3) 响应式（Responsive）：系统响应并适应用户输入和选择

- 清晰的指示器显示系统能够正常识别并适应不同的输入、姿势和方向
- 应用应基于操作系统的行为进行开发，根据输入方法提供响应性、动态性
- **示例**：
  - 分离键盘时，任务栏图标会**分散**
  - 窗口边缘根据光标或触摸输入调用不同的视觉对象

##### 4) 令人愉快（Delightful）：有意义的意外喜悦时刻

- 运动为体验增加个性与活力，将简单操作转换为愉悦时刻
- 这些时刻**总是短暂易逝**，有助于强化用户操作
- **示例**：
  - 最小化窗口会导致**应用图标弹跳**
  - 还原会**向上弹出**应用图标

##### 5) 机智（Resourceful）：尽可能利用现有控件实现一致性

- 如果可能，**避免使用自定义动画**
- 使用 [WinUI 3](https://learn.microsoft.com/zh-cn/windows/apps/design/winui/) 控件等动画资源进行**页面切换、页面内焦点、微交互**
- 如无法使用 WinUI 控件，请根据应用入口点的运行位置**模拟现有 OS 行为**
- **示例**：[页面切换](https://learn.microsoft.com/zh-cn/windows/apps/design/motion/page-transitions)、[连接动画](https://learn.microsoft.com/zh-cn/windows/apps/design/motion/connected-animation)、[动画图标](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/controls/animated-icon) 是推荐的 WinUI 控件

#### 3.7.2 动画属性（Animation Properties）

> "Windows 的运动速度快、直接，并且符合上下文。计时和缓动曲线根据动画的用途进行调整，以创建一致的体验。"

| 用途 | 定义 | 缓动曲线 | 时序 | 用途 |
|---|---|---|---|---|
| **直接入口** | 快入 | 三次方贝塞尔 `(0,0,0,1)` | 167, 250, 333 ms | 位置、刻度、旋转 |
| **现有元素** | 点到点 | 三次方贝塞尔 `(0.55,0.55,0,1)` | 167、250、333 ms | 位置、刻度、旋转 |
| **直接退出** | 快出 | 三次方贝塞尔 `(0,0,0,1)` | 167 ms | 位置、缩放、旋转（始终结合淡出） |
| **平缓退出** | 软出 | `cubic-bezier(1,0,1,1)` | 167 ms | 位置、比例 |
| **最低限度** | 淡入 + 淡出 | 线性 | 83 ms | 不透明度 |
| **强大入口** | 弹性入（3 个关键帧） | 见下表 | 见下表 | 位置、比例 |

**"强大入口"的 3 个关键帧**：

| 关键帧 | 缓动曲线 | 时序 |
|---|---|---|
| 关键帧 1 | 三次方贝塞尔 `(0.85, 0, 0, 1)` | 167 ms |
| 关键帧 2 | 三次方贝塞尔 `(0.85, 0, 0.75, 1)` | 167 ms |
| 关键帧 3 | 三次方贝塞尔 `(0.85, 0, 0, 1)` | 333 ms |

#### 3.7.3 核心控件（推荐使用的动画类型）

##### 页面转换（Page Transitions）：同一表面内的页面间转换

- 使用 [页面转换](https://learn.microsoft.com/zh-cn/windows/apps/design/motion/page-transitions) 从页面顺利转换到页面
- **配置动画方向**以遵守应用流
- 页面转换可引导用户眼睛进入传入和传出内容，降低认知负载
- **示例**：Windows 设置中顶层页面从**底部向上滑动**；顶级页面和子页之间页面向**左和向右**滑动

##### 连接动画（Connected Animations）：同一页中进行层到层转换

- 使用 [连接动画](https://learn.microsoft.com/zh-cn/windows/apps/design/motion/connected-animation) 突出显示页面或界面中的特定信息片段，同时保留上下文
- 将焦点赋予所选元素，并无缝地在焦点和非焦点状态之间转换
- **示例**：Microsoft Store 应用中图像由正常视图切换到放大视图

##### 动画图标（Animated Icons）：通过微交互增加愉悦感并展示信息

- 使用 [动画图标](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/controls/animated-icon) 通过 [Lottie](https://learn.microsoft.com/zh-cn/windows/communitytoolkit/animations/lottie) 动画实现带有运动的轻量级、基于矢量的图标和插图
- 吸引对特定入口点的注意，提供从状态到状态的反馈，增加对交互的愉悦感

#### 3.7.4 相关资源

- [Fluent 2 Motion](https://fluent2.microsoft.design/motion)
- [页面转换](https://learn.microsoft.com/zh-cn/windows/apps/design/motion/page-transitions)
- [连接动画](https://learn.microsoft.com/zh-cn/windows/apps/design/motion/connected-animation)
- [动画图标](https://learn.microsoft.com/zh-cn/windows/apps/design/develop/ui/controls/animated-icon)
- [WinUI 3](https://learn.microsoft.com/zh-cn/windows/apps/design/winui/)
- [Lottie 动画](https://learn.microsoft.com/zh-cn/windows/communitytoolkit/animations/lottie)

---

## 四、辅助资源

### 4.1 实时示例

- **WinUI 3 示例库（WinUI Gallery）** —— 包含 WinUI 控件和功能的交互式示例
  - [Microsoft Store 下载](https://apps.microsoft.com/detail/9P3JFPWWDZRC)
  - [GitHub 源代码](https://github.com/microsoft/WinUI-Gallery)

### 4.2 关联设计系统

- **Fluent 2 设计系统**（[fluent2.microsoft.design](https://fluent2.microsoft.design/)）—— 每个签名体验都对应一个 Fluent 2 详细页：
  - [Fluent 2 Color](https://fluent2.microsoft.design/color)
  - [Fluent 2 Elevation](https://fluent2.microsoft.design/elevation)
  - [Fluent 2 Iconography](https://fluent2.microsoft.design/iconography)
  - [Fluent 2 Material](https://fluent2.microsoft.design/material)
  - [Fluent 2 Shapes（几何）](https://fluent2.microsoft.design/shapes)
  - [Fluent 2 Typography](https://fluent2.microsoft.design/typography)
  - [Fluent 2 Motion](https://fluent2.microsoft.design/motion)

### 4.3 贡献与反馈

- **GitHub 仓库**：[MicrosoftDocs/windows-dev-docs](https://github.com/MicrosoftDocs/windows-dev-docs)
- **文档问题反馈**：[提出文档问题](https://github.com/MicrosoftDocs/windows-dev-docs/issues/new?template=1-customer-feedback.yml)
- **产品反馈**：[Windows Insider Feedback Hub](https://www.microsoft.com/en-us/windowsinsider/feedbackhub/fb)

---

## 五、一页速查表

### 5.1 设计原则

| 原则 | 核心 |
|---|---|
| 毫不费力 | 快、直、专注 |
| 冷静 | 柔和、克制、留白 |
| 个人 | 适应、响应、表达 |
| 熟悉 | 延续、零学习 |
| 完整+连贯 | 跨平台一致 |

### 5.2 签名体验数值速查

| 类别 | 关键数值 |
|---|---|
| **圆角** | 浮出/顶级=8px；页面内=4px；条形=4px；接触处=0px |
| **角半径全局资源** | `ControlCornerRadius`=4px；`OverlayCornerRadius`=8px |
| **高度** | 窗口=128；对话框=128；Flyout=32；Tooltip=16；Card=8；Control=2；Layer=1 |
| **字体** | Segoe UI Variable（权重 100-700；光学大小 8-36pt） |
| **最小字号** | 12px 正常 / 14px 半粗体 |
| **每行字符** | 20-60 字符（推荐 50-60） |
| **强调** | 用 Semibold 不用 Bold；不用斜体 |
| **材料选择** | 主背景=Mica；浮出=Acrylic；模态=Smoke |
| **图标字体** | Segoe Fluent Icons（1 epx 单行笔划） |
| **动效时长** | 83 / 167 / 250 / 333 ms |

---

## 六、附：原文出处一览

| 章节 | 来源 URL | 最后更新 |
|---|---|---|
| 总原则 | https://learn.microsoft.com/zh-cn/windows/apps/design/design-principles | 2025-12-11 |
| 颜色 | https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/color | 2024-09-19 |
| 分层和提升 | https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/layering | 2021-06-24 |
| 图标 | https://learn.microsoft.com/zh-cn/windows/apps/design/iconography/ | 2024-07-24 |
| 材料 | https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/materials | 2024-09-16 |
| 几何图形 | https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/geometry | 2021-06-24 |
| 字体设计 | https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/typography | 2021-06-24 |
| 动态效果 | https://learn.microsoft.com/zh-cn/windows/apps/design/signature-experiences/motion | 2024-07-24 |

> 文档为中文翻译版，原文以英文为准（canonical URL 在每页 metadata 中）。Microsoft Learn 的 `?accept=text/markdown` 端点可获取所有页面的原始 Markdown 源。
