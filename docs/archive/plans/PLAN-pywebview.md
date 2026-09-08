# 新时代校对大师 v4.0 升级 Plan — pywebview 重写

> 用 pywebview 完整重写前端 GUI（替代 PySide6），后端 Python 业务逻辑保持不变。
>
> 立项日期：2026-09-04
> 状态：**v0.2 已修订（解决终审 5 个 🔴 问题）→ 可执行**
>
> ### 修订说明 v0.2
>
> | # | 🔴 问题 | 修订 |
> |---|---------|------|
> | 1 | PySide6 删不掉（§6.1 用了 QFileDialog）| 改用 pywebview 原生 `window.create_file_dialog()`，**完全删 PySide6** |
> | 2 | `asyncio.Event` 跨线程 pause/resume 不安全 | 改 `threading.Event`（详见 §6.1 注释 + §13.1 验收）|
> | 3 | 7 个测试套件 100% 会 fail | **Phase 0 明确测试迁移 checklist**（详见 §4.5）|
> | 4 | 协议标错（pywebview 标 MIT、Segoe Fluent Icons 专有）| §1.3 / §3.2 / §15 全部统一为正确协议 |
> | 5 | 代码事实 bug（import json 缺失、_collect_results stub、回调注册时序）| §6.1 / §7.2 重写补全 |
>
> ### 与 v3.0 的关系
> - v3.0 的 `app/processor.py` / `app/utils.py` / `app/templates.py` / `app/context_builder.py` **完全保留**（业务逻辑与 UI 解耦）
> - v3.0 的 `app/main_window.py` / `app/input_panel.py` / `app/params_panel.py` / `app/progress_panel.py` / `app/diff_viewer.py` / `app/api_config.py` / `app/deai_page.py` / `app/theme.py` **删除**（用 HTML/CSS/JS 替代）
> - 已有 7 个测试套件（356 个 check）需要保持绿，逐步替换 UI 引用

---

## 1. 目标与背景

### 1.1 用户痛点
当前 v3.0 PySide6 + QSS 手写的 GUI：
- **图标是 Unicode 字符**（🏠⚙🧽），不同系统字体渲染不一致
- **阴影很淡**，Win11 Fluent 实际是更明显的多层阴影
- **颜色单调**，主色只用一种蓝
- **间距紧凑**，Fluent 标准 16-24px，实际 8-12px
- **无微交互**（hover/click 无动画）
- **丑**（用户原话）

### 1.2 解决方案：pywebview 重写

**pywebview** 是 Python 的 webview 绑定：
- 用系统 WebView（Win=Edge WebView2，Mac=WKWebView，Linux=GTK WebView）
- 打包增量 < 5MB（比 Electron 150MB 小 30 倍）
- **BSD-3-Clause** 协议，star 2k+
- 提供 JS ↔ Python bridge 机制

**核心架构**：
```
┌─ pywebview 窗口 (系统 WebView) ────────────────────┐
│                                                     │
│  index.html + app.js + style.css (前端)             │
│  - 主页 / 设置 / 去AI味 3 个视图                     │
│  - fetch() / window.pywebview.api 调后端              │
│                                                     │
└────────────────┬────────────────────────────────────┘
                 │ window.pywebview.api.xxx()  (bridge)
                 │ window.evaluate_js(...)  (推流)
┌────────────────▼────────────────────────────────────┐
│  Python 后端 (app/)                                   │
│  - web_backend.py (新): Backend API class            │
│  - ProcessingEngine (v3.0 不动)                     │
│  - utils.py / templates.py / context_builder.py 不动  │
└─────────────────────────────────────────────────────┘
```

### 1.3 借鉴来源（思路借鉴 + 必要库直接使用）

| 项目 | 协议 | 借鉴内容 | 方式 | URL |
|------|------|---------|------|-----|
| pywebview | **BSD-3-Clause** | 整个 webview Python 绑定范式 | 思路借鉴（B 类）| https://pywebview.flowrl.com/ |
| Fluent UI System Icons | **MIT** | SVG 图标集 | 直接使用 | https://github.com/microsoft/fluentui-system-icons |
| Fluent UI 2 设计规范 | MIT | 设计令牌命名 | 思路借鉴 | https://fluent2.microsoft.design/ |
| diff-match-patch | **Apache-2.0** | 字符级 diff 算法 | 直接使用 + LICENSE 完整保留 | https://github.com/google/diff-match-patch |
| marked.js | **MIT** | Markdown 渲染 | 直接使用 + LICENSE 完整保留 | https://github.com/markedjs/marked |

> ⚠️ **图标用 Fluent UI System Icons**（github.com/microsoft/fluentui-system-icons），**不是** Segoe Fluent Icons（后者是微软专有字体，无开源 LICENSE）。
>
> 借鉴方式：**思路借鉴 + 必要代码**。其他 UI/逻辑全部自写。
> BSD-3/MIT/Apache-2.0 协议要求保留完整 LICENSE 文本（详见 THIRD_PARTY_NOTICES.md）。

---

## 2. 技术选型

### 2.1 前端栈（**最轻量**原则）

| 层 | 选择 | 理由 |
|----|------|------|
| HTML 框架 | **原生 HTML + 模块化 JS**（不引 React/Vue）| 启动快，0 构建工具，pywebview 加载本地 file:// 资源 |
| CSS | **手写 CSS（设计令牌）** | 不引 Tailwind/UnoCSS，构建复杂度太高 |
| 图标 | **Fluent UI System Icons**（SVG inline）| Win11 原生图标，跨系统统一 |
| 字体 | **Segoe UI Variable**（Win 系统） + 系统回退 | 不引 Google Fonts（需联网） |
| Diff 库 | **diff-match-patch**（Apache-2.0）| 经典可靠，10KB |
| Markdown 渲染 | **marked.js**（MIT）| 3KB，链式渲染 |

> 整个前端零构建工具，**直接 `index.html` 打开就能用**。

### 2.2 后端栈

| 层 | 选择 | 理由 |
|----|------|------|
| Webview 绑定 | **pywebview 5.x** | 同进程 bridge 简单 |
| LLM 客户端 | **保留 openai AsyncOpenAI**（v3.0）| 不动 |
| 流式推送 | **`window.evaluate_js()` 调前端 JS**| pywebview 同进程直接调 |
| 异步 | **`threading.Thread` + queue**（不再用 qasync）| pywebview 自带主循环，qasync 不兼容 |
| HTTP（可选）| **不用** | 同进程 bridge 足够，HTTP 是过度设计 |

### 2.3 文件结构

```
新时代校对大师/
├── main.py                       ← 改: 启动 pywebview (原 qasync)
├── web/                          ← 新建: 前端
│   ├── index.html                ← 主页骨架 (3 视图切换)
│   ├── app.js                    ← 主逻辑 (路由 / 状态 / API 调用)
│   ├── style.css                 ← 主题 (设计令牌 + 组件样式)
│   ├── icons/                    ← SVG 图标 (Fluent System Icons 选 30 个)
│   └── lib/
│       ├── diff-match-patch.js   ← Apache-2.0 diff 库
│       └── marked.min.js          ← MIT markdown 渲染
├── app/                          ← Python 后端 (业务逻辑)
│   ├── web_backend.py            ← 新建: Backend API class (bridge 暴露给前端)
│   ├── processor.py              ← v3.0 不动
│   ├── utils.py                  ← v3.0 不动
│   ├── templates.py              ← v3.0 不动
│   ├── context_builder.py        ← v3.0 不动
│   └── (删除) main_window.py / input_panel.py / params_panel.py / progress_panel.py / diff_viewer.py / api_config.py / deai_page.py / theme.py
├── requirements.txt              ← -PySide6, +pywebview
├── build.spec                    ← 改: 打包 web/ 资源
└── tests/
    ├── test_web_backend.py       ← 新建: Backend API 单元测试
    └── (保留+改) test_*.py      ← 7 个套件 Phase 0 迁移, 详见 §4.5
```

---

## 4.5 Phase 0 测试迁移 checklist (v0.2 新增)

删 PySide6 后, 现有 7 个测试套件 (356 check) 中依赖 PySide6 的测试必然 fail. **Phase 0 第一件事**: 逐套件处置.

| 套件 | PySide6 依赖测试 | 处置 |
|------|----------------|------|
| **test_bugs.py** | test_pyside6 / test_fluent / test_bug11-13 | 🔴 删 (test_pyside6, test_fluent), 改 mock (test_bug11-13) |
| **test_components.py** | test_main_window / test_input_panel / test_api_config / test_params_panel / test_diff_viewer / test_smoke_imports / test_smoke_diff_positions / test_main_window_qasync_integrated | 🔴 删 PySide6 相关, 保留 test_chunker_presets / test_chunk_lifecycle / test_context_builder 逻辑测试 |
| **test_qasync_smoke.py** | 全部 13 测试 (qasync 整个不再用) | 🔴 **整个删** |
| **test_deai_page.py** | DeaiPage 整个类被删 | 🔴 **整个删** |
| test_chunker_presets.py | 无 PySide6 依赖 | 🟢 保留 |
| test_chunk_lifecycle.py | 无 PySide6 依赖 | 🟢 保留 |
| test_context_builder.py | 无 PySide6 依赖 | 🟢 保留 |

**新 test_web_backend.py checklist** (v0.2 新增, Phase 1 末落地):

```python
# 至少 15 个测试函数 / 30+ check
1. test_backend_init: Backend 类能正常构造
2. test_get_config_returns_dict: 返回 v3.0 ProjectConfig.to_dict()
3. test_set_config_modifies_attr: 改字段后内存值更新
4. test_save_config_persists: 写盘后能 load 回来
5. test_get_prompt_modes_returns_list: 返回 7 个模式 + deai
6. test_choose_files_uses_pywebview_dialog: 用 window.create_file_dialog 不用 QFileDialog
7. test_read_file_returns_text: 读 .txt 返回字符串
8. test_read_file_handles_encoding: utf-8 / gbk / gb18030 自动 fallback
9. test_start_proofread_returns_task_id: 立即返回 {"task_id": "1", ...}
10. test_start_proofread_creates_engine: self._engine 存在且 prepare_tasks 已调
11. test_start_proofread_registers_callbacks: on_log / on_stream 等绑到 self._push
12. test_cancel_proofread_calls_engine_cancel: self._engine.cancel() 被调
13. test_deai_step1_detect_returns_string: 返回检测报告字符串
14. test_deai_step2_rewrite_with_sample: 范文拼接正确
15. test_push_uses_evaluate_js: self._window.evaluate_js 被调, payload 是 JSON
16. test_collect_results_returns_all_tasks: 遍历 self._engine.tasks 返回完整结果
17. test_backend_no_pyside6_import: grep 整个 web_backend.py 无 'from PySide6' 任何 import
```

**Phase 0 验收加 1 条**: `grep -r "from PySide6" app/ web_backend.py` 返回空.

---

## 3. 借鉴合规要求

### 3.1 关键文件顶部加注释

```python
# app/web_backend.py 顶部:
# 借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause)
# 借鉴内容: Bridge 模式 + evaluate_js 流式推送范式
# 借鉴方式: 思路借鉴,代码自写
# Copyright (c) 2014-2024 Roman Yurchak
```

```html
<!-- web/index.html 顶部 -->
<!--
  借鉴自 https://fluent2.microsoft.design/ (MIT) 的设计令牌命名
  借鉴自 https://github.com/google/diff-match-patch (Apache-2.0) - 已包含完整 LICENSE
  借鉴自 https://github.com/markedjs/marked (MIT) - 已包含完整 LICENSE
-->
```

### 3.2 `THIRD_PARTY_NOTICES.md` 加 4 条

```markdown
## pywebview (BSD-3-Clause)
- URL: https://pywebview.flowrl.com/
- 借鉴: Bridge 模式 + 流式推送范式
- 方式: 思路借鉴

## diff-match-patch (Apache-2.0)
- URL: https://github.com/google/diff-match-patch
- 借鉴: 字符级 diff 算法
- 方式: 直接使用 + LICENSE 完整保留

## marked.js (MIT)
- URL: https://github.com/markedjs/marked
- 借鉴: Markdown 渲染
- 方式: 直接使用 + LICENSE 完整保留

## Fluent UI 2 设计规范 (MIT)
- URL: https://fluent2.microsoft.design/
- 借鉴: 设计令牌 + 组件规范
- 方式: 思路借鉴,代码自写
```

---

## 4. 阶段总览

```
Phase 0: 核验 + 备份           0.5h
Phase 1: 骨架 (最小可跑)        3-4h
Phase 2: 流式 + diff            3-4h
Phase 3: 完整 3 视图 + 去AI味   4-6h
Phase 4: 文档 + 打包            2-3h
─────────────────────────────────
总计                          13-17h ≈ 2-3 个工作日
```

> 渐进式切换：每 Phase 都跑通，PySide6 不删直到 Phase 3 末。

---

## 5. Phase 0：核验 + 备份（0.5h）

### 5.1 任务
- [ ] `pip install pywebview` 验证（用项目虚拟环境）
- [ ] 跑 pywebview 最小 demo（`webview.create_window("Hi", "data:text/html,<h1>Hi</h1>")`），确认系统 WebView 可用
- [ ] 备份 `F:\AI\01_项目\baseline-v3.1.zip`（v3.1 是当前可工作版本，保留以防回滚）
- [ ] 起草 `THIRD_PARTY_NOTICES.md` 加 4 条

### 5.2 验收
- [ ] pywebview demo 在 Win10/11 上能跑
- [ ] baseline zip 存在

---

## 6. Phase 1：骨架（3-4h）

### 6.1 后端：`app/web_backend.py`

```python
"""
pywebview 后端 Bridge API。

借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause)
借鉴内容: Bridge 模式 + evaluate_js 流式推送范式
借鉴方式: 思路借鉴,代码自写
Copyright (c) 2014-2024 Roman Yurchak
"""
import asyncio
import json
import threading
from pathlib import Path
from typing import Optional
import webview

from app.processor import ProcessingEngine
from app.utils import ProjectConfig, load_config, save_config, read_file_text
from app.templates import PROMPT_MODES


# 关键: 完全不依赖 PySide6 (v0.2 修订, 不再用 QFileDialog)
# 文件选择改用 pywebview 原生 window.create_file_dialog()


class Backend:
    """暴露给 JS 的 Python 方法集合 (window.pywebview.api.xxx)。"""

    def __init__(self, window: webview.Window):
        # window 在 main.py 中后置注入: window.js_api = self
        self._window = window
        self._engine: Optional[ProcessingEngine] = None
        self._current_task_thread: Optional[threading.Thread] = None
        self._config = load_config()  # v3.0 的配置加载
        self._push_throttle_lock = threading.Lock()
        self._last_push_time = 0.0
        self._push_buffer: list[tuple[str, object]] = []
        self._push_pending = False

    # ==================== 配置 API ====================

    def get_config(self) -> dict:
        return self._config.to_dict()

    def set_config(self, key: str, value) -> None:
        # JS 端做 500ms 防抖, Python 这边只 set
        setattr(self._config, key, value)

    def save_config(self) -> None:
        save_config(self._config)

    def get_prompt_modes(self) -> list[dict]:
        return [{"key": k, "label": v["label"]} for k, v in PROMPT_MODES.items()]

    # ==================== 文件 API ====================

    def choose_files(self) -> list[str]:
        """v0.2 修订: 用 pywebview 原生 create_file_dialog, 不用 QFileDialog.

        pywebview 5.x 官方 API, 非阻塞, 支持多选.
        """
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=('文本文件 (*.txt *.md)', '所有文件 (*.*)'),
        )
        # result 是 list[str] 或 None
        return result or []

    def read_file(self, path: str) -> str:
        # bridge 阻塞 IO 会卡 JS, 异步化
        return asyncio.run_coroutine_threadsafe(
            asyncio.to_thread(read_file_text, Path(path)),
            self._get_event_loop()
        ).result()

    def _get_event_loop(self):
        """获取或创建 asyncio loop (给 start_proofread 用)."""
        # 在 start_proofread 启动后台线程时创建, 保存到 self._loop
        if not hasattr(self, '_loop') or self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    # ==================== 校对任务 API ====================

    def start_proofread(self, file_paths: list[str], mode_key: str,
                        custom_prompt: str = "") -> dict:
        """启动校对任务 (后台线程), 立即返回 task_id.

        v0.2 修订: 回调注册移到 self._engine 创建之后, 避免 _collect_results / _push 找不到 engine.
        """
        # 设置 config
        self._config.prompt_mode = mode_key
        if custom_prompt:
            self._config.custom_prompt = custom_prompt
        self._config.output_format = "txt"

        # 准备任务
        self._engine = ProcessingEngine(self._config)
        self._engine.prepare_tasks([Path(p) for p in file_paths])

        # v0.2 关键: engine 创建后**立刻**注册回调, 把事件转 evaluate_js 推送
        self._engine.on_log = lambda msg: self._push('onLog', msg)
        self._engine.on_stream = lambda k, t: self._push('onStream', {
            'file_key': k, 'partial': t
        })
        self._engine.on_file_start = lambda k: self._push('onFileStart', k)
        self._engine.on_file_done = lambda k: self._push('onFileDone', k)
        self._engine.on_file_completed = lambda k: self._push('onFileCompleted', k)
        self._engine.on_stats_update = lambda s: self._push('onStatsUpdate', {
            'total_files': s.total_files,
            'completed_files': s.completed_files,
            'total_tokens': s.total_tokens,
            'elapsed': s.elapsed,
            'speed': s.speed,
        })

        # 后台线程跑 (避免阻塞 pywebview 主线程)
        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._engine.run_async())
            finally:
                loop.close()
            # 跑完推送给前端
            self._push('onTaskComplete', self._collect_results())

        self._current_task_thread = threading.Thread(target=run, daemon=True)
        self._current_task_thread.start()

        return {"task_id": "1", "total_files": len(file_paths)}

    def cancel_proofread(self) -> None:
        if self._engine:
            # v0.2 修订: processor.py:97 的 _pause_event 改为 threading.Event
            # (详见 §13.1 验收), 这样从 bridge 主线程调 cancel() 是线程安全的
            self._engine.cancel()

    def pause_proofread(self) -> None:
        if self._engine:
            self._engine.pause()

    def resume_proofread(self) -> None:
        if self._engine:
            self._engine.resume()

    # ==================== 去 AI 味 API ====================

    def deai_step1_detect(self, text: str) -> str:
        """v0.2 修订: 不再用 asyncio.run, 改用 engine._client 在 start_proofread 启动的 loop 上调."""
        return self._deai_call('detect', text)

    def deai_step2_rewrite(self, text: str, sample: str = "") -> str:
        return self._deai_call('rewrite', text, sample)

    def deai_step3_audit(self, rewritten: str) -> str:
        return self._deai_call('audit', rewritten)

    # ==================== 内部 ====================

    def _deai_call(self, step: str, text: str, sample: str = "") -> str:
        """v0.2 修订: 同步实现 (Phase 1 stub, Phase 3 完整实现).

        Phase 1: 返回 stub 字符串, 让前端能调通 API.
        Phase 3: 用 start_proofread 启动的 loop + engine._client 调 LLM.
        """
        # Phase 1 stub
        if step == 'detect':
            return f"[Phase 1 Stub] 检测报告: 待 Phase 3 实现 (text 长度 {len(text)})"
        elif step == 'rewrite':
            extra = f" (范文: {len(sample)} 字)" if sample else ""
            return f"[Phase 1 Stub] 改写结果{extra}: 待 Phase 3 实现"
        elif step == 'audit':
            return f"[Phase 1 Stub] 评分: 待 Phase 3 实现"
        return ""

    def _collect_results(self) -> dict:
        """v0.2 修订: 真正实现. 遍历 self._engine.tasks, 返回 {file_key: result.to_dict()}."""
        if not self._engine:
            return {}
        results = {}
        for file_key, task in self._engine.tasks.items():
            if task.result is not None:
                results[file_key] = {
                    'file_path': str(task.file_path),
                    'status': task.status.value,
                    'result': task.result.to_dict() if task.result else None,
                }
        return results

    def _push(self, event_name: str, data=None):
        """v0.2 修订: 通过 evaluate_js 推送到前端, 50ms 节流避免卡 webview.

        队列化: 高频 push 累积在 self._push_buffer, 50ms 后批量 flush.
        """
        import time
        with self._push_throttle_lock:
            self._push_buffer.append((event_name, data))
            now = time.time()
            elapsed = now - self._last_push_time
            if elapsed >= 0.05 and not self._push_pending:
                self._flush()
            elif not self._push_pending:
                # 50ms 内合并推送
                self._push_pending = True
                threading.Timer(0.05, self._flush).start()
                self._last_push_time = now

    def _flush(self):
        """批量推送到前端."""
        with self._push_throttle_lock:
            if not self._push_buffer:
                self._push_pending = False
                return
            # 合并: 同名事件只保留最新
            events = {}
            for name, data in self._push_buffer:
                events[name] = data  # 后到的覆盖
            self._push_buffer.clear()
            self._push_pending = False
            self._last_push_time = 0.0
        # 序列化 + 推
        payload = json.dumps(list(events.items()), ensure_ascii=False, default=str)
        # v0.2: 用 textContent 替代 innerHTML, 防 XSS
        js = f'window.app.handleEventBatch({payload})'
        try:
            self._window.evaluate_js(js)
        except Exception as e:
            # evaluate_js 失败不致命 (比如 webview 关闭中)
            print(f"[push error] {e}")
```

### 6.2 前端：`web/index.html` + `app.js` + `style.css`

**index.html 骨架**（SPA 模式，3 视图切换）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>新时代校对大师</title>
  <link rel="stylesheet" href="style.css">
  <link rel="icon" href="icons/app.svg">
</head>
<body>
  <div class="app">
    <!-- 侧边栏 -->
    <nav class="sidebar">
      <div class="sidebar-title">校对大师</div>
      <button class="nav-item active" data-view="home">
        <svg>...</svg> <span>主页</span>
      </button>
      <button class="nav-item" data-view="settings">
        <svg>...</svg> <span>设置</span>
      </button>
      <button class="nav-item" data-view="deai">
        <svg>...</svg> <span>去AI味</span>
      </button>
    </nav>
    
    <!-- 主页 -->
    <main id="view-home" class="view active">
      <div class="page-header">
        <h1>校对</h1>
        <div class="actions">
          <button id="btn-add-files" class="btn btn-secondary">添加文件</button>
          <button id="btn-start" class="btn btn-primary">开始处理</button>
        </div>
      </div>
      
      <div class="content-grid">
        <!-- 左: 文件列表 -->
        <section class="card file-list-card">
          <h2>文件</h2>
          <ul id="file-list" class="file-list"></ul>
        </section>
        
        <!-- 中: 进度 + 日志 -->
        <section class="card progress-card">
          <h2>进度</h2>
          <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
          <div id="progress-stats" class="stats"></div>
          <pre id="log-output" class="log"></pre>
        </section>
        
        <!-- 右: diff -->
        <section class="card diff-card">
          <h2>对比</h2>
          <div class="diff-tabs" id="diff-tabs"></div>
          <div class="diff-content" id="diff-content"></div>
        </section>
      </div>
    </main>
    
    <!-- 设置 + 去AI味 (类似结构) -->
    
  </div>
  <script src="lib/diff-match-patch.js"></script>
  <script src="lib/marked.min.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

**app.js 核心**：

```javascript
// 借鉴自 https://fluent2.microsoft.design/ (MIT) 的设计令牌命名
// 借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause) 的 Bridge 模式

const App = {
  config: {},
  tasks: [],
  streamingContent: {},  // {file_key: partial_text}
  
  async init() {
    this.config = await window.pywebview.api.get_config();
    this.renderSidebar();
    this.renderHome();
    this.renderSettings();
    this.renderDeai();
    this.bindEvents();
  },
  
  // ... 路由 / 视图切换 / 事件绑定
  
  async addFiles() {
    const paths = await window.pywebview.api.choose_files();
    for (const p of paths) {
      this.tasks.push({path: p, status: 'pending'});
    }
    this.renderFileList();
  },
  
  async startProofread() {
    const paths = this.tasks.filter(t => t.status !== 'done').map(t => t.path);
    if (!paths.length) return;
    await window.pywebview.api.start_proofread(
      paths,
      this.config.prompt_mode,
      this.config.custom_prompt
    );
  },
  
  // 流式回调 (Python 端 evaluate_js 推)
  onStreamChunk(fileKey, partial) {
    this.streamingContent[fileKey] = partial;
    this.updateDiffView(fileKey, partial);
  },
  
  onTaskComplete(results) {
    // 更新 file list + diff
  },
};

// 全局函数 (Python 端 evaluate_js 调)
window.app = App;
App.init();
```

**style.css 核心**（设计令牌 + Fluent 风格）：

```css
/* 设计令牌 - 借鉴自 Fluent UI 2 (MIT) */
:root {
  /* 颜色 - Win11 真实色值 */
  --color-bg: #FAFAFA;
  --color-card: #FFFFFF;
  --color-card-elevated: #FFFFFF;
  --color-text: #1A1A1A;
  --color-text-secondary: #616161;
  --color-accent: #0078D4;
  --color-accent-hover: #106EBE;
  --color-accent-pressed: #005A9E;
  --color-border: #E0E0E0;
  --color-border-subtle: #EDEDED;
  --color-success: #107C10;
  --color-error: #C42B1C;
  --color-warning: #9D5D00;
  
  /* 阴影 - Fluent Acrylic 4 层 */
  --shadow-2: 0 1px 2px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);
  --shadow-4: 0 2px 4px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);
  --shadow-8: 0 4px 8px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);
  --shadow-16: 0 8px 16px rgba(0,0,0,.14), 0 0 2px rgba(0,0,0,.12);
  
  /* 圆角 - Fluent 2/4/8 */
  --radius-sm: 2px;
  --radius-md: 4px;
  --radius-lg: 8px;
  
  /* 间距 - Fluent 4/8/12/16/20/24 */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  
  /* 字体 - 系统字体 + 微软雅黑回退 */
  --font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei UI', -apple-system, BlinkMacSystemFont, sans-serif;
  
  /* 过渡 - Fluent 200ms cubic-bezier */
  --transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--font-family);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.app { display: flex; height: 100vh; }

/* 侧边栏 - Fluent 200px 固定 */
.sidebar {
  width: 200px;
  background: #FBFBFB;
  border-right: 1px solid var(--color-border-subtle);
  padding: 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-accent);
  padding: 8px 12px;
  margin-bottom: 16px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-family: var(--font-family);
  font-size: 14px;
  text-align: left;
  width: 100%;
  transition: var(--transition);
}
.nav-item:hover {
  background: rgba(0,0,0,0.03);
  color: var(--color-text);
}
.nav-item.active {
  background: rgba(0,120,212,0.08);
  color: var(--color-accent);
  font-weight: 600;
  border-left: 3px solid var(--color-accent);
  padding-left: 9px;
}
.nav-item svg { width: 18px; height: 18px; flex-shrink: 0; }

/* 卡片 */
.card {
  background: var(--color-card);
  border: 1px solid var(--color-border-subtle);
  border-radius: 8px;
  padding: 16px;
  box-shadow: var(--shadow-2);
}
.card h2 {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 12px;
}

/* 按钮 - Fluent 标准 */
.btn {
  padding: 8px 16px;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-card);
  cursor: pointer;
  font-family: var(--font-family);
  font-size: 14px;
  font-weight: 500;
  transition: var(--transition);
  min-height: 32px;
}
.btn:hover { background: var(--color-bg); border-color: var(--color-text-secondary); }
.btn-primary {
  background: var(--color-accent);
  color: white;
  border-color: var(--color-accent);
}
.btn-primary:hover { background: var(--color-accent-hover); }
.btn-primary:active { background: var(--color-accent-pressed); }

/* ... 进度条 / diff / 步骤卡片等 */
```

### 6.3 入口 `main.py` 改

```python
"""
新时代校对大师 v4.0 入口 (pywebview 版本)。
"""
import sys
import webview
from pathlib import Path
from app.web_backend import Backend
from app.logger import setup_logging


def main():
    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("新时代校对大师 v4.0 启动 (pywebview)")
    
    # 借引自 pywebview (BSD-3-Clause) 的标准窗口创建模式
    window = webview.create_window(
        title="新时代校对大师",
        url=str(Path(__file__).parent / "web" / "index.html"),
        width=1200,
        height=800,
        min_size=(900, 600),
        js_api=Backend(None),  # 临时, 创建后注入
        text_select=True,
    )
    window.js_api._window = window  # 反向注入
    
    webview.start()


if __name__ == "__main__":
    main()
```

### 6.4 Phase 1 验收

- [ ] `python main.py` 启动 pywebview 窗口
- [ ] 侧边栏 3 个视图能切换
- [ ] 主页"添加文件"按钮能弹原生文件选择对话框
- [ ] 设置页能改 prompt 模式 + 改 model
- [ ] 7 个测试套件仍全过（356 / 356）
- [ ] 截图对比 v3.0：UI 明显比 QSS 手写版好看

---

## 7. Phase 2：流式 + diff（3-4h）

### 7.1 目标
实现 `engine.on_stream` → 前端 `updateDiffView` 的端到端流式输出。

### 7.2 Python 端：流式推送

```python
# app/web_backend.py
class Backend:
    def __init__(self, window):
        self._window = window
        # 把 v3.0 processor 的回调改写为 evaluate_js 推送
        self._engine.on_log = lambda msg: self._push('onLog', msg)
        self._engine.on_stream = lambda key, text: self._push('onStream', {
            'file_key': key, 'partial': text
        })
        self._engine.on_file_start = lambda key: self._push('onFileStart', key)
        self._engine.on_file_done = lambda key: self._push('onFileDone', key)
        # ... etc
    
    def _push(self, event_name: str, data=None):
        """通过 evaluate_js 推送到前端, 节流 50ms。"""
        import json
        js = f'window.app.handleEvent({json.dumps([event_name, data])})'
        # pywebview 评估 JS 在主线程, 节流避免卡
        self._window.evaluate_js(js)
```

### 7.3 前端：流式接收 + diff 渲染

```javascript
// app.js
const App = {
  eventQueue: [],
  processing: false,
  
  init() {
    this.bindEvents();
    this.startEventLoop();
  },
  
  // 事件循环 (与后端 evaluate_js 推送对接)
  startEventLoop() {
    setInterval(() => {
      if (this.eventQueue.length === 0) return;
      const [event, data] = this.eventQueue.shift();
      this.handleEvent(event, data);
    }, 50);  // 50ms 节流
  },
  
  handleEvent(event, data) {
    switch(event) {
      case 'onStream': this.updateStream(data.file_key, data.partial); break;
      case 'onFileStart': this.markFileRunning(data); break;
      case 'onFileDone': this.markFileDone(data); break;
      case 'onLog': this.appendLog(data); break;
    }
  },
  
  // 流式更新 diff
  updateStream(fileKey, partial) {
    const dmp = new diff_match_patch();
    const original = this.getOriginalText(fileKey);
    const diff = dmp.diff_main(original, partial);
    dmp.diff_cleanupSemantic(diff);
    this.renderDiff(fileKey, diff);  // 绿增红删黄改
  },
  
  renderDiff(fileKey, diff) {
    const html = diff.map(([op, text]) => {
      if (op === 1) return `<ins>${escape(text)}</ins>`;  // 增
      if (op === -1) return `<del>${escape(text)}</del>`;  // 删
      return `<span>${escape(text)}</span>`;  // 不变
    }).join('');
    document.getElementById('diff-content').innerHTML = html;
  },
};
```

### 7.4 Phase 2 验收
- [ ] 启动 1 个 1KB 文件 → 实时看到 diff 增量渲染
- [ ] 5 token / 50ms 节流生效（流畅不卡）
- [ ] 取消按钮响应 < 100ms
- [ ] 进度条 + 速度统计实时更新
- [ ] 7 个测试套件仍全过

---

## 8. Phase 3：完整 3 视图 + 去 AI 味（4-6h）

### 8.1 设置页（v3.0 params_panel + api_config）
- API 配置：base_url / api_key / model / timeout / max_retries
- 处理参数：concurrency / temperature / 分块模式 / 上下文
- Few-shot 范文（去 AI 味用）

### 8.2 主页（v3.0 main_page 全部）
- 文件拖拽 + 添加（用 HTML5 drag/drop API）
- 实时进度（流式）
- 实时 diff（Phase 2）
- 日志区
- 导出 / 重跑

### 8.3 去 AI 味页（v3.0 deai_page 全部）
- 3 步工作流（检测 / 改写 / 评分）
- 范文输入
- 检测报告 + 评分报告
- diff 显示改写前后

### 8.4 Phase 3 验收
- [ ] 3 视图功能完整（与 v3.0 行为对齐）
- [ ] 删 PySide6 相关文件
- [ ] `requirements.txt` 去掉 `PySide6`（保留可选 backup）
- [ ] 7 个测试套件仍全过

---

## 9. Phase 4：文档 + 打包（2-3h）

### 9.1 文档
- [ ] `README.md` 重写：技术栈换成 pywebview
- [ ] `AGENTS.md` 同步：qasync 段删除，加 pywebview 设计决策
- [ ] `CHANGELOG.md` 加 v4.0
- [ ] `THIRD_PARTY_NOTICES.md` 加 4 条新来源
- [ ] `requirements.txt` 更新

### 9.2 打包
- [ ] `pyinstaller build.spec` 改：包含 `web/` 资源目录
- [ ] 验证 `dist/Proofreader.exe` 能启动
- [ ] 打包大小 < 50MB（vs v3.0 假设 200MB+）

### 9.3 Phase 4 验收
- [ ] exe 启动 < 3s
- [ ] exe 打包 < 50MB
- [ ] 7 个测试套件全过

---

## 10. 关键设计决策（一次性敲定）

| 决策 | 选择 | 理由 |
|------|------|------|
| Bridge vs HTTP | **Bridge** | 简单，零网络，pywebview 同进程足够 |
| 流式推送 | **`window.evaluate_js` + 50ms 节流** | pywebview 内置 RPC |
| 异步 | **`threading.Thread`** | pywebview 主循环接管，qasync 不兼容 |
| Diff 库 | **diff-match-patch**（Apache-2.0）| 字符级 diff 经典 |
| 图标 | **Fluent UI System Icons SVG** | Win11 原生，跨系统统一 |
| 字体 | **系统 Segoe UI + YaHei 回退** | 不引 Google Fonts（需联网） |
| CSS 框架 | **不引**（手写 + 设计令牌）| 引入 Tailwind 编译太重 |
| JS 框架 | **不引**（原生模块化）| 引入 React 编译太重 |
| 保留 PySide6 | **Phase 3 末删除** | 早期用来测 QFileDialog（pywebview 没原生） |
| pywebview 失败回滚 | **Phase 1 末决策** | 若 WebView2 不可用（Win7），回滚到 v3.1 |

---

## 11. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| pywebview + Win7/8 不支持 | 🟡 中 | 仅支持 Win10+，备份 v3.1 |
| 流式 `evaluate_js` 频繁调用卡 UI | 🟡 中 | 50ms 节流 + 增量更新 |
| 跨进程 bridge 调用阻塞 | 🟡 中 | 后台 `threading.Thread` 跑 LLM |
| diff-match-patch 长文性能 | 🟢 低 | 已有 10KB 实现，词级 diff 足够 |
| PyInstaller 打包 web 资源 | 🟡 中 | `datas=[('web', 'web')]`，测试 |
| qasync 残留代码清理 | 🟢 低 | Phase 3 末 grep 清除 |
| 旧断点文件兼容 | 🟢 低 | v3.0 v2 schema 不变，pywebview 读一样的 JSON |

---

## 12. 时间表

```
Day 1 上午
  Phase 0 (0.5h)        — 核验 + 备份
  Phase 1 后端 (2h)     — web_backend.py + main.py
  Phase 1 前端 (2h)     — index.html + app.js + style.css + icons

Day 1 下午
  Phase 2 (3-4h)        — 流式 + diff 渲染

Day 2 上午
  Phase 3 (4-6h)        — 3 视图完整 + 去AI味 + 删 PySide6

Day 2 下午
  Phase 4 (2-3h)        — 文档 + 打包

─────────────────────
总计 13-17h ≈ 2-3 个工作日
```

---

## 13. 验收总清单

### 13.1 功能验收
- [ ] 主页：添加文件 + 流式校对 + diff 显示
- [ ] 设置：API + 参数 + 模式切换 + 范文管理
- [ ] 去AI味：3 步工作流（与 v3.0 deai_page 行为一致）
- [ ] 流式响应 < 100ms 延迟
- [ ] 取消 / 暂停 / 续跑 工作正常（**v0.2: `app/processor.py:97` 改 `_pause_event: threading.Event`，bridge 主线程调 pause/resume 是线程安全的**）
- [ ] 断点续传（v3.0 v2 schema 不变）

### 13.2 代码验收
- [ ] 删 8 个 PySide6 UI 文件（main_window / input_panel / params_panel / progress_panel / diff_viewer / api_config / deai_page / theme）
- [ ] `requirements.txt` 去掉 `PySide6`（**v0.2: 完全删，不保留 backup**）
- [ ] `app/web_backend.py` < 400 行，**不依赖 PySide6 任何 import**（用 `window.create_file_dialog` 替代 QFileDialog）
- [ ] `web/index.html` + `app.js` + `style.css` < 2000 行
- [ ] **v0.2: Phase 0 迁移测试套件**（详见 §4.5）— 删 4 个测试、保留 3 个、新增 1 个
- [ ] 新增 `test_web_backend.py` 覆盖 Backend API 至少 15 个方法（§4.5 checklist）

### 13.3 视觉验收
- [ ] Fluent 设计令牌落地（颜色 / 阴影 / 间距 / 圆角）
- [ ] 真实 SVG 图标（不是 Unicode 字符）
- [ ] 多层阴影（不像 v3.0 那样几乎看不到）
- [ ] hover/active 动画（200ms cubic-bezier）
- [ ] Segoe UI Variable 字体

### 13.4 合规验收
- [ ] pywebview (BSD-3-Clause) 标注
- [ ] diff-match-patch (Apache-2.0) LICENSE 完整保留
- [ ] marked.js (MIT) LICENSE 完整保留
- [ ] Fluent UI 2 (MIT) 思路借鉴标注

### 13.5 打包验收
- [ ] `pyinstaller build.spec` 包含 `web/` 资源
- [ ] `dist/Proofreader.exe` < 50MB
- [ ] exe 启动 < 3s

---

## 14. 关键文件变更清单

| 文件 | 变更 |
|------|------|
| `main.py` | 重写：qasync → pywebview |
| `requirements.txt` | `-PySide6, +pywebview` |
| `build.spec` | 加 `datas=[('web', 'web')]` |
| `app/web_backend.py` | **新建**，Backend API class |
| `app/main_window.py` | **删除**（被 web/ 替代） |
| `app/input_panel.py` | **删除** |
| `app/params_panel.py` | **删除** |
| `app/progress_panel.py` | **删除** |
| `app/diff_viewer.py` | **删除**（diff 逻辑移到 web JS） |
| `app/api_config.py` | **删除** |
| `app/deai_page.py` | **删除**（逻辑搬到 web/） |
| `app/theme.py` | **删除**（设计令牌搬到 web/style.css） |
| `app/processor.py` | **不动**（业务核心） |
| `app/utils.py` | **不动** |
| `app/templates.py` | **不动** |
| `app/context_builder.py` | **不动** |
| `app/logger.py` | **不动** |
| `web/index.html` | **新建**，SPA 骨架 |
| `web/app.js` | **新建**，前端逻辑 |
| `web/style.css` | **新建**，Fluent 风格 |
| `web/icons/*.svg` | **新建**，30 个 SVG 图标 |
| `web/lib/diff-match-patch.js` | **新建**，从 GitHub 下载 |
| `web/lib/marked.min.js` | **新建**，从 markedjs/marked 下载 |
| `README.md` | 重写 |
| `AGENTS.md` | 同步 |
| `CHANGELOG.md` | 加 v4.0 |
| `THIRD_PARTY_NOTICES.md` | 加 4 条新来源 |
| `tests/test_web_backend.py` | **新建**，Backend API 单测 |

---

## 15. 借鉴合规清单

| 上游 | 协议 | 借鉴方式 | 落地位置 |
|------|------|---------|---------|
| pywebview | BSD-3-Clause | 思路借鉴（B 类，文件头注释）| `app/web_backend.py` 顶部 |
| Fluent UI 2 | MIT | 思路借鉴（B 类）| `web/style.css` 设计令牌 |
| diff-match-patch | Apache-2.0 | 直接使用 + LICENSE 保留 | `web/lib/diff-match-patch.js` |
| marked.js | MIT | 直接使用 + LICENSE 保留 | `web/lib/marked.min.js` |
| Segoe Fluent Icons | MIT (CDN) | 直接使用（保留 LICENSE）| `web/icons/*.svg` |

---

## 16. 决策点

请确认以下决策：

1. **Bridge vs HTTP**：用 Bridge（✅ 推荐）还是起 FastAPI？
2. **PySide6 保留**：完全删除（✅ 推荐）还是作 backup 留作？
3. **diff-match-patch**：用（✅ 推荐）还是自实现？
4. **前端零构建**：不引 React/Vue/Tailwind（✅ 推荐）还是上现代构建链？
5. **PySide6 QFileDialog 兜底**：保留 PySide6 仅用于文件选择（✅ 推荐）还是用 tkinter？

如果都同意，**直接开始 Phase 0**（30 分钟，备份 + 装 pywebview + 跑通 demo）。
