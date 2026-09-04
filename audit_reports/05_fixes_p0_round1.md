# P0 Bug 修复报告（Round 1）

**日期**: 2026-09-04  
**执行人**: Worker (bug 修复子代理)  
**任务范围**: 4 个 P0 bug，每个 bug 先确认行号再改，最后跑全套测试

---

## 测试基线

| 测试文件 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_bugs.py` | 26/26 | **26/26** |
| `test_components.py` | 151/151 | **151/151** |

全部通过，无回归。

---

## Bug 1（#5）— HTML 导出 XSS 修复

**文件**: `app/diff_viewer.py`  
**位置**: `_export_task_html` (line 271-289)

### 改动
- Line 272：`<title>{task.file_path.name}</title>` → `<title>{_html_escape(task.file_path.name)}</title>`
- Line 280：`<h1>{task.file_path.name}</h1>` → `<h1>{_html_escape(task.file_path.name)}</h1>`

### Diff 风格

**Before** (line 272, 280):
```html
<html><head><meta charset="utf-8"><title>{task.file_path.name}</title>
...
<h1>{task.file_path.name}</h1>
```

**After** (line 272, 280):
```html
<html><head><meta charset="utf-8"><title>{_html_escape(task.file_path.name)}</title>
...
<h1>{_html_escape(task.file_path.name)}</h1>
```

### 验证
- `grep "task.file_path.name" diff_viewer.py` → 第 78/79 行（`addItem`，Qt API 接受纯文本不构成 XSS），第 272/280 行已改为 `_html_escape(...)`
- `_html_escape` 函数原本就在 line 292-293，直接调用即可，无需新增

---

## Bug 2（#18）— stream.close 异常吞掉 CancelledError

**文件**: `app/processor.py`  
**位置**: `_call_api_stream` (line 266-269 → 修正后 285-291)

### 改动
采用方案 1（最小变更、最确定）：把 `await stream.close()` 包进 try/except，确保 `raise asyncio.CancelledError()` 一定被执行。

### Diff 风格

**Before** (line 266-269):
```python
async for event in stream:
    if self._cancel_event.is_set():
        await stream.close()
        raise asyncio.CancelledError()
```

**After** (line 285-291):
```python
async for event in stream:
    if self._cancel_event.is_set():
        try:
            await stream.close()
        except Exception:
            pass
        raise asyncio.CancelledError()
```

### 验证
- 取消路径：`_cancel_event.is_set() → try close → raise CancelledError`，最坏情况下 close 抛异常也只被吞掉，CancelledError 一定会被外层 `except asyncio.CancelledError`（line 194）捕获，进入我们新增的"已取消"状态分支
- 不会落到 line 215 的 `except Exception`，不再触发 4 次重试

---

## Bug 3（#1）— closeEvent 不 wait 子线程

**文件**: `app/main_window.py`  
**位置**: `closeEvent` (line 570-585 → 修正后 570-587)

### 改动
在 `self.engine.cancel()` 之后、`event.accept()` 之前，加 `self.thread.wait(3000)`（最多等 3 秒）。

### Diff 风格

**Before** (line 577-579):
```python
if reply == QMessageBox.StandardButton.Yes:
    self.engine.cancel()
    event.accept()
```

**After** (line 577-581):
```python
if reply == QMessageBox.StandardButton.Yes:
    self.engine.cancel()
    if self.thread and self.thread.isRunning():
        self.thread.wait(3000)
    event.accept()
```

### 验证
- `self.thread` 在 `main_window.py:413` 定义为 `ProcessingThread(self.engine)`，是 QThread 实例，`isRunning()`/`wait()` 都是标准方法
- 加了 `if self.thread and self.thread.isRunning()` 守卫，避免 `self.thread` 为 None 或已结束时调用 `wait()` 抛异常
- 3 秒超时足够让 cancel 信号传到 async 循环并跳出 stream；超过 3 秒则 `wait()` 返回 false，不阻塞用户关闭窗口（避免 UI 卡死）

---

## Bug 4（#9）— 取消时 on_file_done 不触发，UI 卡"处理中"

**文件**: `app/processor.py`  
**位置**: `_process_file_async` (line 194-195 → 修正后 194-214)

### 改动
将 `except asyncio.CancelledError: return` 替换为完整的状态保存 + checkpoint + emit 流程，与 line 204-226 的失败分支对齐。

### Diff 风格

**Before** (line 194-195):
```python
except asyncio.CancelledError:
    return
except Exception as e:
```

**After** (line 194-214):
```python
except asyncio.CancelledError:
    elapsed = time.time() - start if start else 0
    result = FileResult(
        original=text,
        corrected=text,
        elapsed=elapsed,
        error="已取消",
    )
    with self._lock:
        task.status = TaskStatus.CANCELLED
        task.result = result
        task.end_time = time.time()
    with self._stats_lock:
        self.stats.completed_files += 1
        self.stats.elapsed = time.time() - self.stats.start_time
    save_checkpoint(task.file_path, task)
    if self.on_file_done:
        self.on_file_done(key)
    if self.on_stats_update:
        self.on_stats_update(self.stats)
    return
except Exception as e:
```

### 验证
- `start` 在 line 152 定义（`start = time.time()`），`text` 在 line 153 定义（`text = task.original_text`），都在 try 块之前就已赋值，安全
- `self._lock` / `self._stats_lock` / `self.stats` / `self.config` / `self.on_file_done` / `self.on_stats_update` 都在 `__init__` 或 `run()` 中初始化（line 49-54），全部可用
- `TaskStatus.CANCELLED` 在 `utils.py:19` 已定义
- 取消后 `task.is_done` 会返回 True（因为 CANCELLED 是终止态），input_panel 不会再显示"处理中..."蓝色
- 顺手把 `stats.completed_files += 1`，让"已完成"统计包含已取消文件（与原 FAILED 路径行为一致，line 219）

---

## 验证步骤回放

```powershell
cd "F:\AI\01_项目\新时代校对大师"
python test_bugs.py 2>&1        # 26 通过, 0 失败
python test_components.py 2>&1  # 151 通过, 0 失败
```

修改后用 `grep` 复核行号：
- `diff_viewer.py:272, 280` 已含 `_html_escape(...)`
- `processor.py:194-214` 已扩展 CancelledError 处理
- `processor.py:285-291` 已用 try/except 包裹 `stream.close()`
- `main_window.py:577-581` 已插入 `thread.wait(3000)`

---

## 改动文件清单

| 文件 | 改动行数 | 改动范围 |
| --- | --- | --- |
| `app/diff_viewer.py` | 2 行 | 272, 280 |
| `app/processor.py` | ~22 行 | 194-214, 285-291 |
| `app/main_window.py` | 3 行 | 577-581 |

总计 3 个文件，未触碰其他模块；未引入新依赖；未改 Prompt、API、UI 行为；未改测试文件。

---

## 遇到的问题和折中

1. **Bug 3 wait 超时选择 3 秒**：考虑过 5/10 秒，最终选 3 秒，因为 `engine.cancel()` 是同步设 event，async 循环在 `await stream.close()` 处最多几百毫秒就退出；3 秒是 10x 缓冲且不阻塞用户关闭窗口。
2. **Bug 2 选方案 1 而非方案 2**：方案 1 改动最小（只动 4 行），不需要重排外层 except 顺序，行为最确定。
3. **Bug 4 `stats.completed_files` 计入已取消**：与原 FAILED 路径（line 219）行为对齐，保持"已完成 + 失败 = total_files"的不变量。

---

## 结论

4 个 P0 bug 全部修复，无测试回归。下一步可推进 P1。
