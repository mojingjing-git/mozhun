# 06 — DiffViewer & API 配置 bug 修复报告

**Worker**: 修复 DiffViewer（#2）+ API 配置（#20）+ HTML 转义（#23）
**日期**: 2026-09-04
**文件范围**: 仅 `app/diff_viewer.py` 和 `app/api_config.py`

---

## 修复清单

### #2 流式 key 覆盖（diff_viewer.py）

**根因**: `_current_key` 是单值，concurrency ≥ 2 时 `update_streaming` 在 `diff_viewer.py:92-93` 直接 `return`，
只能渲染当前文件。其他文件即使在 stream 中也看不到，要切到对应 combo 才能看，体验断档。

**修法**:
1. `__init__` 用三个独立 dict：
   - `_stream_original: dict[str, str]` — 原文缓存
   - `_stream_data: dict[str, str]` — 最新 streaming 片段缓存（按 key 隔离）
   - `_final_data: dict[str, tuple[str, str]]` — 已完成结果缓存
2. UI 用 `QTabWidget` 替代 `QComboBox`：`file_combo` 改为 `file_tabs`，每个文件一个 tab。
   - tab 标题用 `⏳ filename`（streaming 中）/ `✓ filename`（已完成）
   - tab 用 0 高度 `QWidget` 占位（Qt API 要求），实际内容在共享 splitter
3. `update_streaming(key, partial)` **无条件**更新 `self._stream_data[key]`；
   只有当前 tab 才 `_stream_timer.start(200ms)` 触发 UI 刷新——避免 N 个 key 抢着刷 UI。
4. `update_final(key, orig, corr)` 把 key 从 `_stream_data/_stream_original` 移除，写入 `_final_data`，
   tab 标题前缀变 `✓`，当前 tab 立即切到最终 diff。
5. `show_original(key, text)` 不再清空其他 key 的状态——只更新本 key 的原文缓存并切到对应 tab。
6. 切换 tab（`_on_tab_changed`）触发 `_refresh_current_tab`：
   - 已完成 → `_show_diff(orig, corr)`
   - streaming 中 → `_show_streaming_diff(orig, partial)`（用最新缓存）
   - 仅有原文 → 显示原文 + "生成中..."

**代码定位**（diff_viewer.py）:
- L31-42 `__init__`：三 dict + `_tab_keys`
- L44-86 `_init_ui`：QTabWidget 替换 QComboBox
- L88-127 tab 管理辅助方法
- L131-187 公共 API（`set_tasks`/`show_original`/`update_streaming`/`update_final`）
- L195-241 tab 切换/刷新逻辑

**验证**:
```
$ python _tmp_smoke.py
concurrent stream OK; keys: ['/fake/path/file3.txt', '/fake/path/file4.txt']
  key3 cached: 'partial3 v2'   # 不被 key4 覆盖 ✓
  key4 cached: 'partial4 v1'
update_final OK; final keys: [..., '/fake/path/file3.txt']
  tab label for key3: \u2713 file3.txt  # 完成时 ✓ 前缀
  key3 in _stream_data after final? False  # 从 streaming 状态清除
```

### #20 _test_connection 跨线程 widget（api_config.py）

**根因**: `app/api_config.py:153-167` 用 `threading.Thread` 跑 OpenAI 客户端，
`do_test` 闭包直接调 `self._test_done(...)`，后者在子线程里改 `setEnabled/setStyleSheet/setText`。
PySide6 规定 widget 只能在创建它的主线程中操作，跨线程访问会触发警告甚至崩溃。

**修法**:
1. 顶部 `from PySide6.QtCore import Signal, QObject, QThread`；删 `import threading`。
2. 新增 `_ApiTestWorker(QObject)`，在 `run()` 里跑 `client.models.list()`，结果通过 `finished = Signal(bool, str)` 送回。
3. `ApiConfigPanel.__init__` 加 `self._test_thread: QThread | None` 和 `self._test_worker: _ApiTestWorker | None`。
4. `_test_connection` 改为：
   - 重入守卫：`if self._test_thread is not None and self._test_thread.isRunning(): return`
   - 创建 `QThread` + worker，`moveToThread` 搬过去
   - `started → worker.run`；`worker.finished → thread.quit + worker.deleteLater`
   - `thread.finished → thread.deleteLater`
   - `worker.finished → self._on_test_finished`（slot 自动 QueuedConnection，跨线程安全）
5. `_test_done` 改名 `_on_test_finished`，逻辑不变（widget 操作现在在主线程）。

**代码定位**（api_config.py）:
- L6 import 加 `QObject, QThread`
- L20-42 新增 `_ApiTestWorker`
- L48-53 `__init__` 加线程/worker 引用
- L167-195 `_test_connection` 重写为 QThread 模式
- L197-205 `_on_test_finished` 替代 `_test_done`

**验证**:
```
$ python _tmp_api_smoke.py
after _test_connection: thread running? True
test finished; result label: ✗ APIConnectionError: Connection error.  # 失败信息显示
test_btn enabled? True text: 测试连接  # 按钮恢复
thread still running? False  # 线程正确结束
```

### #23 HTML escape 不防引号（diff_viewer.py）

**根因**: `_html_escape` 只 escape `& < >`，未来加 `<a href="...">` 或 `<img title='...'>` 时，
属性值里的 `"` 或 `'` 会突破属性边界，构成 attribute XSS 隐患。

**修法**:
```python
def _html_escape(text: str) -> str:
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;"))
```

**代码定位**: `app/diff_viewer.py:415-422`

**验证**:
```
_html_escape <script>: &lt;script&gt;alert(1)&lt;/script&gt;
_html_escape with quotes: &lt;a href=&quot;x&quot; title=&#x27;y&#x27;&gt;&quot;hi&quot;&lt;/a&gt;
_html_escape plain &: a &amp; b
```

---

## 测试结果

| 套件 | 修改前 | 修改后 | 备注 |
|------|--------|--------|------|
| `test_bugs.py` | 25 通过 / 1 失败 | **26 通过 / 0 失败** | test_bug1 由其他 worker 顺带修复 |
| `test_components.py` | 149 通过 / 2 失败 | **151 通过 / 0 失败** | `prepare_tasks 加载缓存/计数` 由其他 worker 顺带修复 |

回归测试和组件测试全部通过，本次修改**未引入任何新失败**。

---

## 改动行数

| 文件 | 改动类型 | 关键行 |
|------|----------|--------|
| `app/diff_viewer.py` | 重写 | #2 L21-241（tab + 多 key 缓存），#23 L415-422 |
| `app/api_config.py` | 重构 | #20 L1-53（imports + worker），L167-205（_test_connection + slot） |

仅 2 个文件，与 worker 分工严格一致。

---

## 与其他 worker 的兼容性

- `main_window.py` 当前仍引用 `self.diff_viewer.file_combo` / `self.diff_viewer._current_key = file_key` /
  `self.diff_viewer._tasks = ...`，这些直接访问在我新设计里不存在，会 `AttributeError`。
- Worker B 已经在 `_on_file_start/_on_stream/_on_file_done` 里用 `_active_stream_keys` 集合，
  正在重构 main_window.py 以**只通过 `update_streaming` / `update_final` 与 DiffViewer 交互**，
  会清理上述遗留访问。本次修改为其新接口让路。
- 我没有改 `main_window.py`，保持职责隔离。

---

## 阻塞 / 风险

- **遗留风险**：在 Worker B 完成 `main_window.py` 清理前，运行 app 并触发 diff_viewer
  仍会 `AttributeError: 'DiffViewer' object has no attribute 'file_combo'`。
  这是预期的——本次改动是 Worker B 重构的前置条件，不是独立可用的修复。
- **HTML 转义**目前还没人用 `_html_escape` 拼 `<a>`，#23 是预防性修复，无直接触发路径。
