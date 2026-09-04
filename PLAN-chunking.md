# 新时代校对大师 v3.0 升级 Plan

> 借鉴 GitHub 开源项目（tianhm/shreyan241/Xueheng-Li），升级分块处理 + 跨段上下文 + 异步架构。
>
> 立项日期：2026-09-04
> 状态：**v0.2 已修订（解决终审 3 个 🔴 问题）→ 可执行**
>
> ### 修订说明 v0.2
>
> Verifier 终审发现的 🔴 必须改问题及修订：
>
> | 问题 | 修订 |
> |------|------|
> | §8.2.5 取消语义自相矛盾（保留断点 vs 整文件重跑） | 改为**选项 A：取消时不保留中间 chunk 断点**（详见 §8.2.5） |
> | §6.2 USE_QASYNC 切换无具体代码 | 补全 if-else 示例（详见 §6.2.3） |
> | `_stream_single` 签名修改未明文归属 | 明确归属 Phase 2.6（详见 §6.6） |
>
> 同时修正 3 处现状表行号错误（§2.1）、补充 Phase 2/3 测试文件约定（§6.4/§8.3）、加 THIRD_PARTY_NOTICES 全文占位（§4.2）。

---

## 1. 目标与背景

### 1.1 用户痛点
当前 `app/processor.py` 实现是"单次 LLM 调用 + 整文件发 + 文件级断点"，存在 3 个根本问题：

1. **大文件崩溃**：超过模型上下文窗口（如 8K/16K）的文件直接失败或被截断
2. **段落孤岛**：分块处理后相邻 chunk 失去上下文（当前虽然有 `_split_text` 但无跨段引用）
3. **跨线程繁琐**：`QThread` + `asyncio.run` + `Signal` 三层跨线程通信，取消/暂停响应差

### 1.2 借鉴来源（均为 MIT 协议，思路借鉴）

| 项目 | URL | 借鉴内容 |
|------|-----|---------|
| tianhm/ollama-batch-processor | https://github.com/tianhm/ollama-batch-processor | qasync 集成 + chunking preset 分档设计 |
| shreyan241/gpt-proofreader | https://github.com/shreyan241/gpt-proofreader | 跨段上下文 prefix 思路 |
| Xueheng-Li/proofreading | https://github.com/Xueheng-Li/proofreading | 段落级断点续传思路 |

### 1.3 v3.0 升级目标

- ✅ 5 档 chunking 预设 + 整文件兜底（用户可按文件大小自选）
- ✅ 跨段上下文自动注入（消除段落孤岛）
- ✅ qasync 事件循环（取消/暂停 < 100ms 响应）
- ✅ 段级断点续传（v1→v2 自动迁移，不丢旧数据）
- ✅ 文档化借鉴来源（`THIRD_PARTY_NOTICES.md`）

---

## 2. 现状事实（grep 确认 2026-09-04）

### 2.1 已存在的功能

| 文件 | 行 | 已有功能 |
|------|-----|---------|
| `app/processor.py` | 358 | `_split_text(text, max_chars)` 静态方法（按段落/句号切分，无 overlap） |
| `app/processor.py` | 455 | `_stream_chunked(task_key, chunks)` chunk 串行流式 |
| `app/processor.py` | 483 | `_call_api_stream` 内调用 `_split_text(6000)` 硬编码 |
| `app/main_window.py` | 30-47 | `ProcessingThread` 类（QThread 包 asyncio.run） |
| `app/main_window.py` | 92 | `self._active_stream_keys: set[str]` |
| `app/main_window.py` | 431 | `_poll_engine` 200ms 轮询 |
| `app/main_window.py` | 477-494 | `_active_stream_keys` add/discard/检查逻辑 |
| `app/main_window.py` | 517-521 | `total_errors = sum(len(corrected) - len(original))` |
| `app/utils.py` | 288-320 | 旧断点 `save_checkpoint` / `load_checkpoint`（文件级 JSON） |
| `app/utils.py` | 66-93 | `FileResult` dataclass（`original`/`corrected`/`error`/`token_count`/`elapsed`） |
| `app/utils.py` | 95-126 | `FileTask` dataclass（含 `result: Optional[FileResult]`） |
| `app/AGENTS.md` | 56 | "不要在 async 代码中直接操作 Qt 控件（通过 signal）" |

### 2.2 缺口

- ❌ chunking 没有分档（硬编码 6000 字符）
- ❌ 没有 overlap（这是优点，**不要加**）
- ❌ 没有跨段上下文
- ❌ 没有 qasync 集成
- ❌ 断点没有 chunk 粒度
- ❌ 旧断点无 v1→v2 迁移
- ❌ 借鉴来源未文档化
- ❌ 没有分块相关的 UI 控件

---

## 3. 阶段总览

```
Phase 0  核验 + 备份          0.5h     — 许可证核验、git tag 备份
Phase 1  5 档预设            2h       — 改造 _split_text 加分档
Phase 2  qasync 集成        4-5h     — 删 ProcessingThread
Phase 2.5 回归验证          1h       — 16 测试必须全绿
Phase 3  chunk lifecycle    3-4h     — FileResult 改造 + 断点 v2
Phase 4  ContextBuilder     2h       — 跨段 prefix 注入
Phase 5  文档 + e2e         1.5h     — THIRD_PARTY_NOTICES、README、AGENTS.md
─────────────────────────────────
总计                       14-16h   ≈ 2 个工作日
```

---

## 4. Phase 0：核验 + 备份（0.5h）

### 4.1 任务

| 任务 | 验证方式 | 负责人 |
|------|---------|--------|
| 核验 shreyan241/gpt-proofreader LICENSE | 浏览器打开 https://github.com/shreyan241/gpt-proofreader/blob/main/LICENSE | 用户 |
| 核验 qasync 许可证 | `pip show qasync` 或 https://pypi.org/project/qasync/ | 执行者 |
| 备份当前可工作版本 | `git tag v2.0-baseline` | 执行者 |
| 起草 `THIRD_PARTY_NOTICES.md` | 写入项目根 | 执行者 |

### 4.2 `THIRD_PARTY_NOTICES.md` 草稿

**必须包含每个上游的 LICENSE 全文**（MIT 协议明确要求），不能只列 URL 和协议名。

```markdown
# Third-Party Notices

本项目 (新时代校对大师) v3.0 升级过程中借鉴了以下开源项目的设计思路。
根据 MIT 和 BSD-3-Clause 协议要求,保留以下版权声明和 LICENSE 副本。

---

## 1. tianhm/ollama-batch-processor

- **URL**: https://github.com/tianhm/ollama-batch-processor
- **License**: MIT License
- **Copyright**: (c) 2025 tianhm
- **借鉴内容**: chunking preset 分档设计思路、qasync 集成模式
- **借鉴方式**: 思路借鉴（A 类），无代码复制

### MIT License 全文

> MIT License
>
> Copyright (c) 2025 tianhm
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

---

## 2. shreyan241/gpt-proofreader

- **URL**: https://github.com/shreyan241/gpt-proofreader
- **License**: MIT License（Phase 0 手动核验 LICENSE 文件确认）
- **Copyright**: (c) 2024 shreyan241
- **借鉴内容**: 跨段上下文 prefix 思路
- **借鉴方式**: 思路借鉴（A 类），无代码复制

### MIT License 全文

> (Phase 0 阶段从 https://raw.githubusercontent.com/shreyan241/gpt-proofreader/main/LICENSE 拉取并粘贴)

---

## 3. Xueheng-Li/proofreading

- **URL**: https://github.com/Xueheng-Li/proofreading
- **License**: MIT License
- **Copyright**: (c) 2025 Xueheng-Li
- **借鉴内容**: 段级断点续传思路
- **借鉴方式**: 思路借鉴（A 类），无代码复制

### MIT License 全文

> MIT License
>
> Copyright (c) 2025 Xueheng-Li
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

---

## 4. qasync

- **URL**: https://pypi.org/project/qasync/
- **License**: BSD 3-Clause License
- **Copyright**: (c) 2019, Gerard Marull Paretas
- **引用方式**: requirements.txt 依赖项 (仅 import,无代码复制)

### BSD 3-Clause License 全文

> (Phase 0 阶段从 `pip show qasync` 输出的 `License` 字段和 PyPI 项目页拉取并粘贴)

---

## 借鉴来源文件头注释约定

为满足 MIT 协议"在修改文件标注"要求,所有借鉴思路的源文件首部加注释:

```python
# 借鉴自 <URL> (<License>)
# 借鉴内容: <一句话>
# 借鉴方式: 思路借鉴,无代码复制
# Copyright (c) <year> <author>
```

**示例**（`app/context_builder.py`）:

```python
# 借鉴自 https://github.com/shreyan241/gpt-proofreader (MIT License)
# 借鉴内容: 跨段上下文 prefix 思路
# 借鉴方式: 思路借鉴,无代码复制
# Copyright (c) 2024 shreyan241
```

### 4.3 验收

- [ ] 用户已确认 shreyan241 是 MIT — **⏳ 待用户核验**
- [ ] `pip show qasync` 输出 BSD-3-Clause — **⏳ 待 Phase 2 装 qasync**
- [ ] `git tag v2.0-baseline` 成功 — **⏳ git 未安装,用 zip 替代**（已完成 `F:\AI\01_项目\baseline-v2.0.zip` 429KB）
- [x] `THIRD_PARTY_NOTICES.md` 已创建 — **✅ 已落地（含 4 个上游的协议和借鉴内容占位）**

### 4.4 Phase 0 实际落地状态（2026-09-04）

| 任务 | 状态 | 备注 |
|------|------|------|
| 备份可工作版本 | ✅ | `F:\AI\01_项目\baseline-v2.0.zip` (429KB),包含除 `nul` 外的所有文件 |
| 写 THIRD_PARTY_NOTICES.md | ✅ | 4 个上游条目 + LICENSE 全文（tianhm/Xueheng-Li 已贴全文,shreyan241/qasync 待补）|
| 核验 shreyan241 LICENSE | ⏳ | 需用户浏览器打开 https://github.com/shreyan241/gpt-proofreader/blob/main/LICENSE 确认 |
| 核验 qasync 许可证 | ⏳ | Phase 2 装 qasync 时核验 |
| `git tag` 备份 | ❌ | git 未安装,用 zip 替代。后续如安装 git,可补 tag |

---

## 5. Phase 1：5 档 chunking 预设（2h）

### 5.1 目标

把现有硬编码 6000 字符改造成 5 档可选预设，UI 暴露给用户。

### 5.2 改造点

#### 5.2.1 `app/processor.py`

```python
# 在文件顶部常量区（约 line 39 后）
_CHUNK_PRESETS = {
    "fast":         {"max_chars": 2000, "overlap": 0, "label": "快速 (2000 字)"},
    "balanced":     {"max_chars": 3000, "overlap": 0, "label": "均衡 (3000 字)"},
    "high_context": {"max_chars": 4000, "overlap": 0, "label": "高上下文 (4000)"},
    "large":        {"max_chars": 6000, "overlap": 0, "label": "大块 (6000)"},
    "whole_file":   {"max_chars": 0,    "overlap": 0, "label": "整文件 (不分块)"},
}
DEFAULT_CHUNK_PRESET = "balanced"

# 关键设计决策: overlap=0
# 理由: 校对是改错别字,重叠区会被改两次产生不一致。
# 跨段上下文通过 Phase 4 ContextBuilder 在 system prompt 注入,不通过 chunk 重叠。
```

#### 5.2.2 改造 `_split_text`（line 357-383）

```python
@staticmethod
def _split_text(text: str, max_chars: int, preset: str = "balanced") -> list[str]:
    """按段落/句号边界切分文本。
    
    切分点保留在段尾（即不丢标点），保证拼接时语义完整。
    overlap=0（Phase 1 决策）：校对场景下重叠区会被改两次，结果冲突。
    """
    # 整文件预设
    if preset == "whole_file" or max_chars == 0:
        return [text]
    
    if len(text) <= max_chars:
        return [text]
    
    # 现有切分逻辑（保持不变）
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = -1
        for sep in ("\n\n", "\n", "。", "！", "？", ".", "!", "?"):
            idx = window.rfind(sep)
            if idx > max_chars // 2:
                cut = idx + len(sep)
                break
        if cut <= 0:
            cut = max_chars
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks
```

#### 5.2.3 改造 `_call_api_stream`（line 483）

```python
# 旧: chunks = self._split_text(text, _MAX_CHUNK_CHARS)
# 新:
preset = self.config.chunking_preset or DEFAULT_CHUNK_PRESET
max_chars = _CHUNK_PRESETS[preset]["max_chars"]
chunks = self._split_text(text, max_chars, preset=preset)
```

#### 5.2.4 `app/utils.py` `ProjectConfig` 加字段

```python
@dataclass
class ProjectConfig:
    # ... 现有字段
    chunking_preset: str = "balanced"  # NEW
    # ... 其他字段
    schema_version: int = 2  # NEW（标记配置 schema 版本）
```

#### 5.2.5 `app/params_panel.py` 加下拉框

在 `temperature_spin` 后面加：
```python
self.chunking_combo = QComboBox()
for key, info in _CHUNK_PRESETS.items():
    self.chunking_combo.addItem(info["label"], key)
self.chunking_combo.setCurrentText(
    _CHUNK_PRESETS.get(self.config.chunking_preset, _CHUNK_PRESETS["balanced"])["label"]
)
```

加 `get_chunking_preset()` / `set_chunking_preset()` 方法。

#### 5.2.6 `app/main_window.py` 串通

`_collect_config()` 加 `api_cfg.chunking_preset = self.params_panel.get_chunking_preset()`。

`_apply_config_to_ui()` 加 `self.params_panel.set_chunking_preset(self.config.chunking_preset)`。

### 5.3 测试

新建 `test_chunker_presets.py`：

| 用例 | 期望 |
|------|------|
| 整文件预设（whole_file） | 返回 `[text]` |
| 小于 max_chars 的文本 | 返回 `[text]` |
| 5 段文本，balanced 预设 | 按段落切分，无 overlap |
| 1 段超长文本 | 强制切分 |
| 中文/英文混排 | 按段落边界切分 |
| preset 不存在 | 回退到 balanced |
| 5 档都跑一遍 | 每档结果合理 |

### 5.4 验收

- [ ] `python test_chunker_presets.py` 全过
- [ ] `python test_bugs.py` 13 个回归全过
- [ ] `python test_components.py` 全过
- [ ] UI 上能看到 5 档下拉框，选不同档行为不同
- [ ] 整文件预设下行为与升级前完全一致
- [ ] `last_config.json` 加 `chunking_preset` 字段后能正确加载

### 5.5 借鉴合规

仅借鉴"分档思路"（算法层面），代码全部自己写。**0 合规风险**。

---

## 6. Phase 2：qasync 集成（4-5h）

### 6.1 目标

删除 `ProcessingThread` QThread 类，让 asyncio 跑在 GUI 线程（qasync 模式），简化跨线程通信。

### 6.2 改造点

#### 6.2.1 `requirements.txt`

```
openai>=1.0.0
PySide6>=6.5.0
requests>=2.28.0
qasync>=0.27.0  # NEW
```

#### 6.2.2 `main.py`

```python
import sys
import asyncio
import qasync
from PySide6.QtWidgets import QApplication

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("新时代校对大师")
    app.setOrganizationName("Proofreader")
    
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("Proofreader.App.1")
        except Exception:
            pass
    
    # qasync 事件循环
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    from app.main_window import MainWindow
    window = MainWindow()
    window.show()
    
    with loop:
        loop.run_forever()  # 替代 sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

#### 6.2.3 `app/main_window.py` 删 `ProcessingThread`（line 30-47）

```python
# 旧: class ProcessingThread(QThread): ...
# 新: 删除整个类

# _start_processing 改造（line ~405）
def _start_processing(self, file_paths):
    self.engine = ProcessingEngine(self.config)
    self.engine.prepare_tasks(file_paths)
    if self.engine.stats.total_files == 0:
        QMessageBox.warning(self, "提示", "没有可处理的文件")
        return
    
    # 设置回调（替代原 signal）
    self.engine.on_log = lambda m: self.progress_panel.append_log(m)
    self.engine.on_stream = lambda k, t: self._on_stream(k, t)
    self.engine.on_file_start = lambda k: self._on_file_start(k)
    self.engine.on_file_done = lambda k: self._on_file_done(k)
    self.engine.on_stats_update = lambda s: self.progress_panel.update_stats(s)
    
    self._poll_timer = QTimer(self)
    self._poll_timer.timeout.connect(self._poll_engine)
    self._poll_timer.start(200)
    
    self._last_completed = 0
    self.progress_panel.set_running(True)
    self.progress_panel.set_has_failures(False)
    self.progress_panel.log_output.clear()
    self.progress_panel.update_stats(self.engine.stats)
    self.progress_panel.append_log("开始处理...")
    self.status_label.setText("处理中...")
    
    # qasync 模式: 在 GUI 线程直接跑 asyncio 协程
    import asyncio
    asyncio.ensure_future(self.engine._run_all())

def _on_processing_finished(self):
    # qasync: 通过监听 engine.is_running 或所有 task 完成来触发
    # 简化: 用 on_stats_update 检测 completed_files == total_files
    if not self.engine:
        return
    if self.engine.stats.completed_files >= self.engine.stats.total_files:
        # ... 原 _on_processing_finished 逻辑
```

#### 6.2.3.1 USE_QASYNC 切换代码（Phase 2 阶段性保留，Phase 5 删除）

**Phase 2 实施时**: 在 `app/main_window.py` 顶部加:

```python
# Phase 5 删除此行
USE_QASYNC = True
```

`_start_processing` 末尾改成:

```python
# qasync 模式切换
if USE_QASYNC:
    import asyncio
    asyncio.ensure_future(self.engine._run_all())
else:
    # Fallback 路径: QThread 包 asyncio.run
    from PySide6.QtCore import QThread, Signal

    class _FallbackThread(QThread):
        """Phase 2 兜底用,Phase 5 删除整个类。"""
        log_signal = Signal(str)
        stream_signal = Signal(str, str)
        file_start_signal = Signal(str)
        file_done_signal = Signal(str)
        finished = Signal()

        def __init__(self, engine, parent=None):
            super().__init__(parent)
            self.engine = engine

        def run(self):
            import asyncio
            self.engine.on_log = lambda m: self.log_signal.emit(m)
            self.engine.on_stream = lambda k, t: self.stream_signal.emit(k, t)
            self.engine.on_file_start = lambda k: self.file_start_signal.emit(k)
            self.engine.on_file_done = lambda k: self.file_done_signal.emit(k)
            self.engine.start()  # 旧版 entry: asyncio.run(self._run_all())
            self.finished.emit()

    self.thread = _FallbackThread(self.engine)
    self.thread.log_signal.connect(lambda m: self.progress_panel.append_log(m))
    self.thread.stream_signal.connect(self._on_stream)
    self.thread.file_start_signal.connect(self._on_file_start)
    self.thread.file_done_signal.connect(self._on_file_done)
    self.thread.finished.connect(self._on_processing_finished)
    self.thread.start()
```

**回滚方案**: Phase 2 失败时只需把 `USE_QASYNC = False`,代码自动走 QThread 路径,不需 git revert。

#### 6.2.4 `_poll_engine` 决策

**保留** `_poll_engine`（line 431-448）但**只更新 elapsed**：

```python
def _poll_engine(self):
    """qasync 模式下: 回调已在 GUI 线程,不需要轮询状态变化。
    但 elapsed 需要定时刷新,所以保留 200ms 定时器。
    """
    if not self.engine:
        return
    with self.engine._stats_lock:
        self.engine.stats.elapsed = time.time() - self.engine.stats.start_time
    self.progress_panel.update_stats(self.engine.stats)
    # 删掉: stats.completed_files 变化的轮询逻辑（已由 on_file_done 触发）
```

#### 6.2.5 `app/AGENTS.md` 同步改

```markdown
# 旧:
## 关键设计决策
...
4. **输入验证**: `api_config.py` 的 `validate()` 方法 + URL 正则校验 + 实时红框

## 不要做的事
- 不要在 async 代码中直接操作 Qt 控件（通过 signal）

# 新:
## 关键设计决策
...
4. **输入验证**: ...
5. **qasync 异步架构** (v3.0+): asyncio 事件循环跑在 Qt 主线程（`qasync.QEventLoop`），
   回调直接在 GUI 线程执行，无需 `Signal` 跨线程通信。
6. **流式节流** (v3.0+): 5 token 或 50ms 双重条件 OR 触发 emit
7. **5 档 chunking 预设** (v3.0+): fast/balanced/high_context/large/whole_file

## 不要做的事
- 不要引入 PyQt6（已迁移到 PySide6）
- 不要引入 qfluentwidgets（不支持 Python 3.13）
- 不要在 processor.py 中引入任何 GUI 依赖
- qasync 模式下: async 回调可直接调 slot（已在 Qt 线程）；
  非 qasync 模式: 仍走 `Signal` 跨线程（fallback）
```

#### 6.6 Phase 2 阶段：`_stream_single` 签名扩展（v0.2 修订）

**归属**: Phase 2 末尾（Phase 2.5 回归验证之前）。

**改动**（`app/processor.py:385`）:

```python
# 旧:
async def _stream_single(self, task_key: str, text: str) -> tuple[str, int]:

# 新:
async def _stream_single(
    self,
    task_key: str,
    text: str,
    system_prompt_override: Optional[str] = None,  # NEW: Phase 4 ContextBuilder 用
) -> tuple[str, int]:
    """单块文本的流式调用。

    system_prompt_override: 外部传入的 system prompt（Phase 4 跨段上下文用）。
    为 None 时按 self.config 选 base system prompt。
    """
    if system_prompt_override is not None:
        system_prompt = system_prompt_override
    elif self.config.custom_prompt:
        system_prompt = self.config.custom_prompt
    else:
        mode_info = PROMPT_MODES.get(self.config.prompt_mode)
        if not mode_info:
            self._log(f"[警告] 未知校对模式 '{self.config.prompt_mode}'，回退到纯纠错模式")
            mode_info = PROMPT_MODES["strict"]
        system_prompt = mode_info["system"]
    # ... 现有 stream 调用逻辑不变
```

**理由**: Phase 4 集成 ContextBuilder 时需要给每个 chunk 注入不同的 system prompt（带跨段 prefix），签名扩展现在做避免 Phase 4 触碰 Phase 2 完成的代码。

### 6.3 风险缓解

- `USE_QASYNC` flag 切换（保留 QThread 路径做兜底，Phase 2.5 验证稳定后删除）
- 关闭程序时若 `_run_all` 还在跑，`closeEvent` 加超时等待

### 6.4 验收

- [ ] 单文件流程跑通（结果与升级前一致）
- [ ] 取消响应 < 100ms
- [ ] 暂停恢复响应 < 100ms
- [ ] 关闭程序不卡死
- [ ] 16 个现有测试全过
- [ ] **新增** `test_qasync_smoke.py`:
  - `engine._run_all()` 启动后 `is_running` 立即为 True
  - `engine.cancel()` 调用后 100ms 内 `is_cancelled` 为 True
  - mock `AsyncOpenAI` 后整个 `prepare_tasks` + `_run_all` 在 qasync loop 内完成
  - `closeEvent` 时 `cancel()` + `wait(3000)` 不卡死

---

## 7. Phase 2.5：回归验证（1h）

### 7.1 目的

在 qasync 跑通但还没动 chunk 处理前，跑一遍所有现有测试。**这是必加的安全网**，避免 Phase 3 出问题时无法定位是 qasync 引入的还是 chunk 引入的。

### 7.2 跑测试

```bash
python test_bugs.py           # 13 个回归
python test_components.py     # 组件测试
python test_chunker_presets.py # Phase 1 新增
```

### 7.3 手动冒烟

- 启动应用，加 1 个 1KB 文件
- 跑完，看结果与升级前是否一致
- 跑一个 50KB 文件，看是否分块
- 跑一个 200KB 文件，看是否正常完成

### 7.4 验收

- [ ] 16+ 个测试全过
- [ ] 3 个冒烟文件行为正确
- [ ] 没有诡异性能退化

**如果有任何不通过，先回滚到 Phase 2 之前的版本。**

---

## 8. Phase 3：chunk 级别 lifecycle + 断点 v2（3-4h）

### 8.1 目标

把 FileResult/FileTask 扩成支持 chunk 数组，断点 schema 升 v2（旧 v1 自动迁移）。

### 8.2 改造点

#### 8.2.1 `app/utils.py` FileResult 扩字段

```python
@dataclass
class FileResult:
    # 现有字段保留（兼容旧断点）
    original: str
    corrected: str = ""
    token_count: int = 0
    elapsed: float = 0.0
    error: Optional[str] = None
    prompt_hash: str = ""
    # NEW: chunk 级别结果数组
    chunks_results: list["FileResult"] = field(default_factory=list)
    schema_version: int = 2
    
    @property
    def is_chunked(self) -> bool:
        """是否分块处理（多 chunk）。"""
        return len(self.chunks_results) > 0
    
    @property
    def corrected_full(self) -> str:
        """完整 corrected 文本（chunk 拼接或单字段）。"""
        if self.is_chunked:
            return "".join(r.corrected for r in self.chunks_results)
        return self.corrected
    
    @property
    def is_done(self) -> bool:
        """所有 chunk 都完成。"""
        if not self.chunks_results:
            return bool(self.corrected) and not self.error
        return all(not r.error for r in self.chunks_results)
```

#### 8.2.2 FileTask 保留现有结构

`FileTask.result` 字段保持单 FileResult（已是"完整文件"视图），内部通过 `result.chunks_results` 持有每个 chunk 的 result。

#### 8.2.3 断点 schema v2

```python
CHECKPOINT_SCHEMA_VERSION = 2

def save_checkpoint(file_path: Path, task: FileTask) -> None:
    """保存整文件任务状态（v2 schema）。
    
    旧 v1 schema: <safe_name>.json（含 FileResult）
    新 v2 schema: <safe_name>.json（FileResult.chunks_results 数组化）
    
    文件名不变,内部 schema 升级（to_dict 加 schema_version 字段）。
    """
    # ... 现有逻辑,加 schema_version

def load_checkpoint(file_path: Path) -> FileTask | None:
    """读断点,自动 v1→v2 迁移。"""
    # ... 现有读逻辑
    # 读出 dict 后:
    if data.get("schema_version", 1) == 1:
        # v1: 单 FileResult → 迁移为 v2 单 chunk
        result_dict = data.get("result", {})
        result = FileResult.from_dict(result_dict)
        # v1 视为单 chunk
        result.schema_version = 2
        # chunks_results 留空（旧 v1 不分块）
        ...
```

#### 8.2.4 chunk 失败语义（明文化，v0.2 修订）

```python
# 在 processor.py 顶部加常量
from openai import (
    APIError, APITimeoutError, RateLimitError,
    AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError,
)
_RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, ConnectionError, TimeoutError)
_NON_RETRYABLE_ERRORS = (AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError)

# _process_file_async 改造（保持现有整文件重试语义,v0.2 修订）
async def _process_file_async(self, key: str, task: FileTask) -> None:
    """处理单文件的所有 chunks。
    
    失败语义（v0.2 修订: 整文件重试,不在 chunk 内重试）:
    - 整文件级重试 N 次 (max_retries, 现有逻辑)
    - 每次重试清空 chunks_results,从 chunk 0 重新跑
    - 不可重试错误 (Auth/Permission/NotFound/BadRequest): 立即标 FAILED,不再重试
    - 可重试错误 (RateLimit/Timeout/Connection): 整文件重试
    
    chunk 失败处理:
    - 单 chunk 失败: 该 chunk 的 FileResult.corrected = chunk 原文
    - 整文件 result.chunks_results: 包含所有 chunk results (成功 + 失败的)
    - 整文件 result.corrected_full: 拼接"成功 chunk + 失败 chunk 原文"
    - 整文件 result.error: 失败的 chunk index 列表
    - 整文件 result.failed_chunks: list[int] (NEW,语义比 error 字符串更清晰)
    """
    ...
```

**重要**: 避免"chunk 内重试 × N chunks = N² 次重试"的重试风暴。整文件重试粒度与现有 `max_retries` 一致。

#### 8.2.5 取消语义（v0.2 修订：选项 A）

**决策**: 取消时**不**保留中间 chunk 断点（避免与"整文件重跑"矛盾）。

```python
async def _process_file_async(self, key: str, task: FileTask) -> None:
    """取消语义（v0.2 选项 A,简化）:
    - Esc 取消时:
      1. 当前正在处理的 chunk **不**写断点（脏数据丢弃）
      2. 整文件 status = CANCELLED
      3. 已写入的 chunks_results **全部丢弃**(不保留中间状态)
      4. 整文件 result.error = "用户取消"
    - 下次重跑: prepare_tasks 检测 status=CANCELLED,清空 chunks_results,从 chunk 0 重跑
    
    理由: 简化逻辑,避免"chunk 1 改但 chunk 2 引用旧 context"的不一致
    代价: 已完成 chunks 的工作丢失,但分块重跑成本低（最多几十秒）
    """
    ...
```

**配套**: `prepare_tasks` 增加 CANCELLED 状态检测:

```python
def prepare_tasks(self, file_paths):
    for fp in file_paths:
        cached = load_checkpoint(fp)
        if cached and cached.status == TaskStatus.CANCELLED:
            # v0.2: 取消状态强制重跑
            self._log(f"[重跑] {fp.name}: 上次被取消,从 chunk 0 重新开始")
            # 不读 chunks_results
            text = read_file_text(fp)
            task = FileTask(file_path=fp, original_text=text)
            self.tasks[str(fp)] = task
        elif cached and cached.is_done:
            # ... 现有逻辑
        # ...
```

#### 8.2.6 `_active_stream_keys` 改造

```python
# main_window.py
def _on_file_start(self, file_key: str):
    # 文件级 key 永驻（开始时 add,文件全部 chunk 完成才 discard）
    self._active_stream_keys.add(file_key)
    ...

def _on_file_done(self, file_key: str):
    # chunk 完成时不 discard,只更新 chunk 进度
    # 文件所有 chunk 完成时（_on_file_completed）才 discard
    ...

def _on_file_completed(self, file_key: str):  # NEW
    """所有 chunk 完成时触发,替代原 _on_file_done 的 discard 逻辑。"""
    if file_key in self._active_stream_keys:
        self._active_stream_keys.discard(file_key)
    ...
```

### 8.3 验收

- [ ] 50KB 文件分 5 chunk 跑通
- [ ] 旧 v1 断点（手造一个）能被自动迁移
- [ ] 取消时已完成的 chunk 数据**不**保留（v0.2 选项 A）
- [ ] 16+ 测试全过
- [ ] 整文件 `result.corrected_full` 拼接正确（长度等于 chunk.corrected 之和）
- [ ] `total_errors` 指标（main_window.py:517-521）兼容

### 8.3.1 Phase 3 阶段测试（v0.2 补充）

**新建** `test_chunk_lifecycle.py`，覆盖：

| 用例 | 验证 |
|------|------|
| mock `_stream_single` 让第 3 块抛 RateLimitError | 整文件重试 3 次后成功 |
| mock 让第 3 块抛 AuthenticationError | 立即标 FAILED,不再重试 |
| 手造 v1 断点 JSON | load 后 `result.chunks_results=[]`, `corrected` 有值 |
| 取消事件触发 | 当前 chunk 不写断点,整文件标 CANCELLED |
| 5 块全部完成 | `corrected_full == "".join(r.corrected for r in chunks_results)` |

### 8.4 借鉴合规

仅借鉴"段级断点"思路，代码全自己写。**0 合规风险**。

---

## 9. Phase 4：ContextBuilder 跨段 prefix（2h）

### 9.1 目标

新建 `app/context_builder.py`，把已完成的相邻 chunk 的 corrected 文本拼成 system prompt 前缀，消除段落孤岛。

### 9.2 新建 `app/context_builder.py`

```python
"""跨段上下文构造器。

借鉴 shreyan241/gpt-proofreader (MIT) 的"前文 context"思路:
https://github.com/shreyan241/gpt-proofreader

将已完成的相邻 chunk 的 corrected 文本拼成 system prompt 前缀,
消除 chunk 级别处理下的"段落孤岛"问题(无 overlap 设计的代价)。
"""
from app.utils import FileResult


class ContextBuilder:
    """跨段上下文构造器。"""
    
    def __init__(self, max_chars: int = 800, max_chunks: int = 2):
        self.max_chars = max_chars
        self.max_chunks = max_chunks
    
    def build(
        self,
        chunks_processed: list[FileResult],  # 已完成的 chunk results(顺序)
        current_chunk_index: int,
    ) -> str:
        """构造当前 chunk 的前文 prefix。
        
        规则:
        - 第一段 (index=0) 或无已完成 chunk → 返回 ""
        - 收集前 max_chunks 个 chunk 的 corrected
        - 总字符数不超过 max_chars
        - 超过时截断尾部(保留最近内容)
        """
        if current_chunk_index == 0 or not chunks_processed:
            return ""
        
        start = max(0, current_chunk_index - self.max_chunks)
        prev = chunks_processed[start:current_chunk_index]
        
        parts: list[str] = []
        used = 0
        for r in prev:
            text = r.corrected
            if not text:
                continue
            if used + len(text) > self.max_chars:
                remaining = self.max_chars - used
                if remaining < 50:
                    break
                text = "…" + text[-(remaining - 1):]
            parts.append(text)
            used += len(text)
        
        if not parts:
            return ""
        
        return (
            "上文(已校对,仅供风格/术语参考,请勿重复输出):\n"
            + "\n---\n".join(parts)
        )
```

### 9.3 集成进 `app/processor.py`

在 `_stream_chunked` 改造：

```python
# 顶部加
from app.context_builder import ContextBuilder

class ProcessingEngine:
    def __init__(self, config: ProjectConfig):
        # ... 现有 init
        self.context_builder = ContextBuilder(
            max_chars=getattr(config, "context_max_chars", 800),
            max_chunks=getattr(config, "context_max_chunks", 2),
        )

# _stream_chunked 改造
async def _stream_chunked(self, task_key: str, chunks: list[str]) -> tuple[str, int]:
    """chunk 串行处理,每 chunk 可注入跨段上下文。"""
    chunk_results: list[FileResult] = []
    total_tokens = 0
    
    for chunk_idx, chunk_text in enumerate(chunks):
        # 关键: 跨段上下文 prefix
        context = self.context_builder.build(
            chunks_processed=chunk_results,
            current_chunk_index=chunk_idx,
        )
        
        system_prompt = self._get_base_system_prompt()
        if context:
            system_prompt = f"{system_prompt}\n\n{context}"
        
        # 单 chunk 流式调用
        corrected, tokens = await self._stream_single(
            task_key,
            chunk_text,
            system_prompt_override=system_prompt,
        )
        chunk_result = FileResult(
            original=chunk_text,
            corrected=corrected,
            token_count=tokens,
        )
        chunk_results.append(chunk_result)
        total_tokens += tokens
    
    # 拼接
    full_corrected = "".join(r.corrected for r in chunk_results)
    return full_corrected, total_tokens
```

`_stream_single` 加可选参数 `system_prompt_override` 接受外部传入的 system prompt（避免内部重新选择 mode）。

### 9.4 配置扩展

`app/utils.py` ProjectConfig:
```python
@dataclass
class ProjectConfig:
    # ... 现有
    context_max_chars: int = 800   # NEW
    context_max_chunks: int = 2    # NEW
    schema_version: int = 2
```

`app/params_panel.py` 加两个 spin：
```python
self.context_chars_spin = QSpinBox()
self.context_chars_spin.setRange(0, 4000)
self.context_chars_spin.setValue(800)
self.context_chars_spin.setSuffix(" 字")

self.context_chunks_spin = QSpinBox()
self.context_chunks_spin.setRange(0, 5)
self.context_chunks_spin.setValue(2)
```

### 9.5 测试

新建 `test_context_builder.py`：

| 用例 | 期望 |
|------|------|
| 第一段（index=0） | 返回 "" |
| 无已完成 chunks | 返回 "" |
| 中间段，已有 1 个前文 | 包含前文 |
| 前文超 max_chars | 截断尾部，保留最近内容 |
| 前文含错误 | 原样保留（校对结果） |
| max_chunks=2 但只有 1 个前文 | 用 1 个 |
| 整文件预设（不分块） | 不调 build |

### 9.6 验收

- [ ] 5+ 段文档相邻 chunk 的 system prompt 包含前文
- [ ] max_chars 限制生效
- [ ] 整文件预设下不调 ContextBuilder（无开销）
- [ ] UI 上能调"上下文字符数"和"上下文 chunk 数"

### 9.7 借鉴合规

仅借鉴"前文 context"思路，代码全自己写。**0 合规风险**。

---

## 10. Phase 5：文档 + 端到端验证（1.5h）

### 10.1 任务

| 文档 | 改动 |
|------|------|
| `THIRD_PARTY_NOTICES.md` | 完善（Phase 0 已有草稿） |
| `README.md` | 加"分块模式"章节 + "上下文"功能说明 |
| `AGENTS.md` | 已 Phase 2 改过，Phase 5 复核 |
| `CHANGELOG.md` | 新建 v3.0 升级日志 |

### 10.2 README.md 关键更新

```markdown
## 分块模式 (v3.0+)

支持 5 档 chunking 预设（设置 → 处理参数 → 分块模式）：

| 模式 | 块大小 | 适用场景 |
|------|-------|---------|
| 快速 (fast) | 2000 字 | 大文件快速处理 |
| 均衡 (balanced) | 3000 字 | 默认推荐 |
| 高上下文 (high_context) | 4000 字 | 需要更强上下文 |
| 大块 (large) | 6000 字 | 短上下文模型适用 |
| 整文件 (whole_file) | 不分块 | 小于 2500 字 |

**注意**: 不使用 overlap（重叠区会被改两次产生不一致）。

## 跨段上下文 (v3.0+)

启用分块后，自动注入前 N 个 chunk 的校对结果作为当前 chunk 的 system prompt 前缀。
默认：前 2 个 chunk，最多 800 字符。

调整：设置 → 处理参数 → 上下文字符数 / 上下文 chunk 数
```

### 10.3 CHANGELOG.md

```markdown
# v3.0 (2026-09-04)

## 新增
- 5 档 chunking 预设（fast / balanced / high_context / large / whole_file）
- 跨段上下文 prefix 注入（解决段落孤岛）
- 段级断点续传（v1→v2 自动迁移）
- THIRD_PARTY_NOTICES.md（借鉴来源文档化）

## 改造
- 异步架构迁移到 qasync（删除 QThread + asyncio.run）
- FileResult 加 chunks_results 字段
- ProjectConfig 加 4 个新字段（chunking_preset, context_max_chars, context_max_chunks, schema_version）
- 断点 schema 升 v2

## 借鉴来源
- tianhm/ollama-batch-processor (MIT)
- shreyan241/gpt-proofreader (MIT)
- Xueheng-Li/proofreading (MIT)
```

### 10.4 端到端验证

| 场景 | 文件大小 | 预期 |
|------|---------|------|
| 小文件 | 1 KB | 整文件预设下行为同 v2.0 |
| 中等文件 | 50 KB | balanced 预设分 5-10 chunk，能跑完 |
| 大文件 | 200 KB | balanced 预设分 20-30 chunk，跨段 context 生效 |
| 旧 v1 断点 | 手工造 | 启动时自动迁移为 v2 |
| 取消场景 | 50 KB 跑到一半 Esc | 已完成 chunk 保留，未完成不写断点 |
| 重试 | 50 KB 跑挂 | 单 chunk 失败，整文件 result 拼接"成功 + 失败原文" |

### 10.5 最终验收

- [ ] 16+ 个测试全过（含 Phase 1/4 新增的）
- [ ] 端到端 6 场景全过
- [ ] README.md / AGENTS.md / CHANGELOG.md / THIRD_PARTY_NOTICES.md 完整
- [ ] git tag v3.0
- [ ] 移除 USE_QASYNC flag（qasync 稳定后）

---

## 11. 风险评估 + 缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| qasync 集成搞坏流程 | 🔴 高 | USE_QASYNC flag 切换 + Phase 2.5 回归验证 |
| 跨段 context token 涨太快 | 🟡 中 | max_chars=800 默认，UI 暴露可调，>2000 警告 |
| 大文件（100MB+）read_file_text OOM | 🟡 中 | Phase 1 顺手加 50MB 阈值提示（不强制阻断） |
| chunk 失败语义不清 | 🟡 中 | Phase 8.2.4 明文化 |
| Esc 取消时脏数据 | 🟡 中 | Phase 8.2.5 整文件重跑策略 |
| `_active_stream_keys` 生命周期 | 🟡 中 | Phase 8.2.6 改文件级 key 永驻 |
| 旧 v1 断点兼容性 | 🟡 中 | Phase 8.2.3 自动迁移 |
| 测试 QApplication 状态泄漏 | 🟢 低 | 现有 test_components.py 已处理 |
| 借鉴许可证变动 | 🟢 低 | 5 个上游均为 MIT，THIRD_PARTY_NOTICES 文档化 |

---

## 12. 关键设计决策（一次性敲定）

| 决策 | 选择 | 理由 |
|------|------|------|
| Overlap | **0（不重叠）** | 校对场景下重叠区会被改两次，结果冲突 |
| 跨段上下文 | **system prompt prefix** | 不污染 chunk 文本本身 |
| 整文件预设 | **保留** | 小文件不分块，质量更高 |
| chunk 失败重试 | **可重试 vs 不可重试分类** | RateLimit 重试，Auth 立即 fail |
| Esc 取消 | **整文件重跑** | 避免 chunk 1 改但 chunk 2 引用旧 context |
| 旧断点 | **v1→v2 自动迁移** | 保留用户历史数据 |
| qasync 集成 | **替换 QThread 方案** | 简化跨线程 |
| USE_QASYNC flag | **Phase 2-2.5 保留**，Phase 5 删除 | 阶段性安全网 |

---

## 13. 时间表 + 里程碑

```
Day 1 上午
  Phase 0 (30min)         — 核验 + 备份
  Phase 1 (2h)            — 5 档预设

Day 1 下午
  Phase 2 (4-5h)          — qasync 集成

Day 2 上午
  Phase 2.5 (1h)          — 回归验证
  Phase 3 (3-4h)          — chunk lifecycle + 断点 v2

Day 2 下午
  Phase 4 (2h)            — ContextBuilder
  Phase 5 (1.5h)          — 文档 + e2e
```

里程碑：
- M1: Phase 1 完成 → 5 档预设可用（独立可测）
- M2: Phase 2 + 2.5 完成 → qasync 跑通，16 测试全绿
- M3: Phase 3 完成 → 段级断点 + chunk lifecycle
- M4: Phase 4 + 5 完成 → 跨段 context + 文档

---

## 14. 验收总清单

### 14.1 功能验收
- [ ] 5 档 chunking 预设 UI 可选
- [ ] 整文件预设行为与 v2.0 一致
- [ ] qasync 模式下取消/暂停 < 100ms 响应
- [ ] 50KB 文件分 5+ chunk 跑通
- [ ] 200KB 文件跑通
- [ ] 跨段 context 自动注入
- [ ] 段级断点续传
- [ ] 旧 v1 断点自动迁移

### 14.2 代码验收
- [ ] 16+ 测试全过
- [ ] 无 `QThread` + `asyncio.run` 跨线程写法
- [ ] 无 `overlap > 0` 设计
- [ ] FileResult.chunks_results 字段正确填充
- [ ] `total_errors` 指标（main_window.py:517-521）兼容

### 14.3 文档验收
- [ ] README.md 含分块模式 + 跨段 context 章节
- [ ] AGENTS.md 含 qasync + 5 档 + 跨段 context 设计决策
- [ ] THIRD_PARTY_NOTICES.md 含 4 个上游 + 借鉴方式
- [ ] CHANGELOG.md 含 v3.0 升级日志

### 14.4 合规验收
- [ ] shreyan241 LICENSE 手动核验为 MIT
- [ ] qasync 许可证核验为 BSD-3-Clause
- [ ] 5 档预设代码全自写（不复制 tianhm）
- [ ] ContextBuilder 代码全自写（不复制 shreyan241）
- [ ] 断点 v2 代码全自写（不复制 Xueheng-Li）

### 14.5 部署验收
- [ ] git tag v3.0
- [ ] 端到端 6 场景全过
- [ ] `pyinstaller build.spec` 打包成功

---

## 15. 关键文件变更清单

| 文件 | 变更 |
|------|------|
| `requirements.txt` | + qasync |
| `main.py` | 用 qasync.QEventLoop |
| `app/main_window.py` | 删 ProcessingThread, _start_processing 改 ensure_future, _on_file_completed 新增, _active_stream_keys 改造 |
| `app/processor.py` | _split_text 加 preset 参数, _stream_chunked 改造接 ContextBuilder, _stream_single 加 system_prompt_override, 失败语义明文化 |
| `app/utils.py` | FileResult 加 chunks_results, ProjectConfig 加 4 字段, save_checkpoint/load_checkpoint 加 schema_version 字段 |
| `app/params_panel.py` | 加 chunking_combo + context_chars_spin + context_chunks_spin |
| `app/context_builder.py` | **新建** |
| `app/AGENTS.md` | qasync 决策 + 5 档 + 跨段 context |
| `README.md` | 分块 + 上下文章节 |
| `CHANGELOG.md` | **新建** v3.0 |
| `THIRD_PARTY_NOTICES.md` | **新建** |
| `test_chunker_presets.py` | **新建** |
| `test_context_builder.py` | **新建** |

---

## 16. 联系信息

- 立项：Mavis (mavis) on 2026-09-04
- 借鉴来源：见 THIRD_PARTY_NOTICES.md
- 用户：墨璟璟
- 工作区：`F:\AI\01_项目\新时代校对大师`
