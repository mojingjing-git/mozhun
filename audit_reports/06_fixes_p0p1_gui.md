# P0/P1 Bug 修复报告（Round 2 — GUI 层）

**日期**: 2026-09-04  
**执行人**: Worker (bug 修复子代理 — GUI 部分)  
**任务范围**: main_window.py + progress_panel.py 共 6 条 bug  
**负责文件**: `app/main_window.py`, `app/progress_panel.py`

---

## 测试基线

| 测试文件 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_bugs.py` | 26/26 | **26/26** |
| `test_components.py` | 151/151 | **151/151** |

全部通过，无回归。注：测试运行前需清 `app/__pycache__/*.pyc`（旧字节码与新源码不一致会触发假失败）。

---

## Bug #2 — 流式 key 覆盖（concurrency≥2 时只看一个文件流）

**文件**: `app/main_window.py`  
**位置**: `_init_ui` (line 92), `_on_file_start` (line 477), `_on_stream` (line 482-484), `_on_file_done` (line 496-498)

### 改动
- `self._current_stream_key: str = ""` → `self._active_stream_keys: set[str] = set()`
- `_on_file_start`：单值赋值改为 `self._active_stream_keys.add(file_key)`
- `_on_stream`：`file_key == self._current_stream_key` 改为 `file_key in self._active_stream_keys`
- `_on_file_done`：匹配检查用 set；命中后 `self._active_stream_keys.discard(file_key)`

### Diff 风格
**Before**:
```python
self._current_stream_key = file_key
...
if file_key == getattr(self, '_current_stream_key', ''):
    self.diff_viewer.update_streaming(file_key, partial)
...
if file_key == getattr(self, '_current_stream_key', ''):
    self.diff_viewer.update_final(...)
```

**After**:
```python
self._active_stream_keys.add(file_key)
...
if file_key in self._active_stream_keys:
    self.diff_viewer.update_streaming(file_key, partial)
...
if file_key in self._active_stream_keys:
    self.diff_viewer.update_final(...)
    self._active_stream_keys.discard(file_key)
```

### 验证
- `grep "_current_stream_key" main_window.py` → 0 匹配（已完全替换）
- `grep "_active_stream_keys" main_window.py` → 5 处（init + 4 处使用）
- set 语义保证 concurrency=N 时 N 个文件流同时进入 diff_viewer
- `diff_viewer._current_key` 仍由 diff_viewer 自己维护（Worker C 会改成 dict），main_window 不再介入

---

## Bug #7 — completed_files 误导（失败文件被计入 100%）

**文件**: `app/progress_panel.py` (line 161-183), `app/main_window.py` (line 518-520)

### 改动
- `progress_panel.update_stats` 改用 `success_files / total_files` 算 progress
- 显示文本从 `f"{completed}/{total}"` 改为：
  - 有失败：`f"成功 {success}/{total} · 失败 {failed}"`
  - 无失败：`f"成功 {success}/{total}"`
- `main_window._on_processing_finished`：`success_count` 优先读 `stats.success_files`，缺失时 fallback `completed - failed`

### Diff 风格
**Before** (progress_panel.py:162-171):
```python
self.progress_bar.setValue(int(stats.progress_pct))
...
self.files_value.setText(f"{stats.completed_files}/{stats.total_files}")
```

**After**:
```python
success_files = getattr(stats, "success_files", None)
failed_files = getattr(stats, "failed_files", None)
if success_files is None: success_files = stats.completed_files
if failed_files is None: failed_files = 0

success_pct = (success_files / stats.total_files * 100) if stats.total_files > 0 else 0
self.progress_bar.setValue(int(success_pct))
...
if failed_files > 0:
    self.files_value.setText(f"成功 {success_files}/{stats.total_files} · 失败 {failed_files}")
else:
    self.files_value.setText(f"成功 {success_files}/{stats.total_files}")
```

### 验证
- `utils.py:180-181` 已由 utils worker 加 `success_files` / `failed_files` 字段
- `getattr` fallback 兼容中间态（字段未就位时仍能跑）
- 进度条 `setValue(success_pct)` —— 失败 3/10 成功时只显示 70%，不误导

---

## Bug #10 — _poll_timer 200ms 架构冗余

**文件**: `app/main_window.py`  
**位置**: `_start_processing` (line 402-429), `_poll_engine` (line 431-448), `closeEvent` (line 603-624)

### 改动
- **删除** `_start_processing` 里的 `self._poll_timer = QTimer(...)` + `start(200)` 三行
- **删除** `_last_completed = 0` 初始化（不再需要轮询对比）
- `_on_file_start` 和 `_on_file_done` 末尾直接调 `self.progress_panel.update_stats(self.engine.stats)`（line 480, 499）
- `_on_processing_finished` 末尾直接 update_stats 一次（line 507-509），不再调 `_poll_engine`
- `_poll_engine` 保留为 no-op-compatible 方法（test_components.py:390 要求 `hasattr(MainWindow, '_poll_engine')`），内部用 `getattr(self, "_last_completed", 0)` 兜底
- `closeEvent` 移除 `_poll_timer.stop()` 调用

### Diff 风格
**Before** (_start_processing line 400-404):
```python
self._poll_timer = QTimer(self)
self._poll_timer.timeout.connect(self._poll_engine)
self._poll_timer.start(200)
self._last_completed = 0
```

**After**:
```python
# (上述 4 行删除)
```

### 验证
- `grep "_poll_timer" main_window.py` → 0 匹配（已删除）
- `grep "_last_completed" main_window.py` → 2 匹配（仅在 _poll_engine 内部用 getattr 兜底）
- `grep "update_stats" main_window.py` → 4 匹配（start_processing init + on_file_start + on_file_done + on_processing_finished）
- 测试 `MainWindow 有 _poll_engine` 仍通过（保留方法）

---

## Bug #14 — QThread 清理（连续"重试失败"泄漏）

**文件**: `app/main_window.py`  
**位置**: `_start_processing` (line 402-407), `_on_processing_finished` (line 546-550), `closeEvent` (line 603-624)

### 改动
- `_start_processing` 开头：旧 thread 若还在跑就 `quit() → wait(2000) → deleteLater() → None`
- `_on_processing_finished` 末尾：同上清理（独立于 engine 是否为 None 的分支外）
- `closeEvent`：
  - 运行中分支：`self.engine.cancel() → thread.wait(3000) → self.thread = None`
  - 非运行中分支：`thread.wait(2000) → self.thread = None → save_config → accept`

### Diff 风格
**Before** (_start_processing 开头):
```python
def _start_processing(self, file_paths):
    self.engine = ProcessingEngine(self.config)
```

**After**:
```python
def _start_processing(self, file_paths):
    if self.thread and self.thread.isRunning():
        self.thread.quit()
        self.thread.wait(2000)
        self.thread.deleteLater()
        self.thread = None
    self.engine = ProcessingEngine(self.config)
```

**Before** (_on_processing_finished 末尾):
```python
        self.logger.info("处理结束")
```

**After**:
```python
        if self.thread:
            self.thread.quit()
            self.thread.wait(2000)
            self.thread.deleteLater()
            self.thread = None
        self.logger.info("处理结束")
```

### 验证
- `grep "self.thread = None" main_window.py` → 4 匹配（_start_processing 开头 + _on_processing_finished 末尾 + closeEvent 两个分支）
- `grep "deleteLater" main_window.py` → 2 匹配（_start_processing + _on_processing_finished）
- 连续"重试失败"时旧 thread 会被先 join 再丢弃，无 ZOMBIE
- `closeEvent` 已有 `thread.wait(3000)` 不变，新增 `self.thread = None` 防野指针

---

## Bug #17 — _auto_save_results try/except（任一失败中断全部）

**文件**: `app/main_window.py`  
**位置**: `_auto_save_results` (line 554-574)

### 改动
- `out_dir.mkdir` 包 try/except，失败只 log 不中断
- 每个 `_export_task` 调用包 try/except，单文件失败计数 + log
- 最后分别 log "已自动导出 N 个文件" 和 "导出失败 M 个文件"

### Diff 风格
**Before**:
```python
def _auto_save_results(self):
    out_dir = Path(self.config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for task in self.engine.tasks.values():
        if task.result and task.is_done:
            self.diff_viewer._export_task(task, out_dir)
            count += 1
    if count > 0:
        self.progress_panel.append_log(f"已自动导出 {count} 个文件到 {out_dir}")
        self.logger.info(f"自动导出 {count} 个文件到 {out_dir}")
```

**After**:
```python
def _auto_save_results(self):
    out_dir = Path(self.config.output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        self.progress_panel.append_log(f"[错误] 创建导出目录失败: {e}")
        return
    count = 0
    failed = 0
    for task in self.engine.tasks.values():
        if task.result and task.is_done:
            try:
                self.diff_viewer._export_task(task, out_dir)
                count += 1
            except Exception as e:
                failed += 1
                self.progress_panel.append_log(f"[错误] 导出 {task.file_path.name} 失败: {e}")
    if count > 0:
        self.progress_panel.append_log(f"已自动导出 {count} 个文件到 {out_dir}")
    if failed > 0:
        self.progress_panel.append_log(f"导出失败 {failed} 个文件")
```

### 验证
- 单文件权限不足 / 磁盘满 / 文件名冲突 → 仅该文件失败，其余继续导出
- 创建目录失败 → 早返回，不进入循环
- 与 processor.py / diff_viewer.py 改动解耦（用 getattr/try 兼容签名变化）

---

## Bug #19 — Esc 全局误触（编辑 prompt / 对话框按 Esc 取消任务）

**文件**: `app/main_window.py`  
**位置**: `_setup_shortcuts` (line 94-103), `_has_input_focus` (line 105-108)

### 改动
- Esc shortcut lambda 加守卫：`engine.is_running` 且 `_has_input_focus()` 为 False 时才 cancel
- 新增 `_has_input_focus` 方法：检查当前焦点控件是否 `QLineEdit / QTextEdit / QComboBox / QSpinBox / QDoubleSpinBox`

### Diff 风格
**Before**:
```python
QShortcut(QKeySequence("Escape"), self, lambda: self._on_cancel())
```

**After**:
```python
QShortcut(
    QKeySequence("Escape"), self,
    lambda checked=False: self._on_cancel() if (
        self.engine and self.engine.is_running and not self._has_input_focus()
    ) else None,
)

def _has_input_focus(self) -> bool:
    from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox
    fw = QApplication.focusWidget()
    return isinstance(fw, (QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox))
```

### 验证
- 编辑 prompt 时焦点在 QTextEdit → `_has_input_focus` 返回 True → Esc 被 lambda 吞掉（返回 None）
- QFileDialog / QMessageBox 弹窗时焦点在 dialog 内部 widget（QDialogButtonBox 内的 QPushButton，不在白名单内）→ `_has_input_focus` 返回 False → 但 `engine.is_running` 通常是 False（除非 dialog 是处理中弹的）→ Esc 不触发 cancel
- 主页正常运行时按 Esc → 焦点不在输入控件且 engine 在跑 → 正确 cancel

---

## 验证步骤回放

```powershell
cd "F:\AI\01_项目\新时代校对大师"
# 清旧 pyc（避免与新源码不一致的假失败）
Remove-Item "app\__pycache__\*.pyc" -Force
python test_bugs.py        # 26 通过, 0 失败
python test_components.py  # 151 通过, 0 失败
```

修改后用 `grep` 复核：
- `main_window.py:92` 含 `self._active_stream_keys: set[str] = set()`
- `main_window.py:98-103` 含 Esc lambda 守卫
- `main_window.py:105-108` 含 `_has_input_focus`
- `main_window.py:402-407` 含 thread cleanup
- `main_window.py:480, 499` 含 `update_stats` 直调
- `main_window.py:546-550` 含 thread cleanup
- `main_window.py:554-574` 含 try/except 包裹
- `main_window.py:614, 621` 含 `self.thread = None`
- `progress_panel.py:161-183` 含 success_files 计算 + "成功 X/Y · 失败 N" 显示

---

## 改动文件清单

| 文件 | 改动行数 | 改动范围 |
| --- | --- | --- |
| `app/main_window.py` | ~70 行 | 92, 94-108, 402-407, 431-448, 472-499, 501-552, 554-574, 603-624 |
| `app/progress_panel.py` | ~18 行 | 161-183 |

总计 2 个文件，未触碰 processor.py / diff_viewer.py / api_config.py / utils.py / theme.py / input_panel.py / params_panel.py；未引入新依赖；未改 Prompt、UI 样式、测试文件。

---

## 遇到的问题和折中

1. **`_poll_engine` 保留为兜底方法**：test_components.py:390 用 `hasattr(MainWindow, '_poll_engine')` 验证存在性。Bug #10 的本意是移除轮询架构，不是删除方法本身。保留方法 + `getattr(self, "_last_completed", 0)` 兜底，同时去掉 timer，兼容测试又满足需求。
2. **`success_files` / `failed_files` 用 `getattr` 兜底**：utils.py 改完字段（其他 worker 09:25:48 完成）后，progress_panel 和 main_window 都能直接读；但仍写 `getattr(stats, "success_files", None)` 是为了在字段添加窗口期内仍能运行，不出 `AttributeError`。这种"宽容输入"对并发 worker 协作最稳。
3. **Esc 守卫选 lambda 而非 eventFilter**：题目给了 3 个方案，lambda 守卫 + `_has_input_focus` 是最简洁且行为可预测的；eventFilter 需要在所有子控件装过滤器，对 prompt 之外的全局快捷键侵入大。QFileDialog 是模态的，焦点不在主页输入控件，lambda 守卫直接 cover。
4. **pyc 缓存陷阱**：`app/__pycache__/*.cpython-313.pyc` 与新源码不一致时 `test_bug1` 会假失败（mock 的 `track` 函数不带 `expected_hash` kwarg，但旧 pyc 调用方式不同）。最终结果运行前清 pyc 即可，但报告里留个注：部署侧需要在改源码后清 pyc。

---

## 结论

GUI 层 6 条 bug 全部修复，26+151 测试无回归。下一步可推进 P1 剩余 bug 或与 Worker C 联调 diff_viewer 的多文件流支持。
