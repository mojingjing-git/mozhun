# GUI/异步架构审查

> 审查范围：`app/main_window.py` / `app/processor.py` / `app/diff_viewer.py` / `app/api_config.py` / `app/params_panel.py` / `app/input_panel.py` / `app/progress_panel.py` / `app/utils.py`
> 审查焦点：Signal/Slot、QThread 生命周期、QTimer、asyncio/Qt 集成、GUI 线程安全、流式回调时序

---

## 1. Signal/Slot 问题

### [严重] 1.1 流式回调 key 被并发覆盖，导致其他文件的 streaming 全部被丢弃

- 位置：`app/main_window.py:466-467` / `app/main_window.py:471-472` / `app/diff_viewer.py:91-93`
- 代码片段：

  ```python
  # main_window.py:466-467
  self._current_stream_key = file_key
  self.diff_viewer._current_key = file_key
  # main_window.py:470-472
  def _on_stream(self, file_key: str, partial: str):
      if file_key == getattr(self, '_current_stream_key', ''):
          self.diff_viewer.update_streaming(file_key, partial)
  ```

  ```python
  # diff_viewer.py:91-93
  def update_streaming(self, file_key: str, partial_text: str):
      if file_key != self._current_key:
          return
      self._pending_stream_text = partial_text
  ```

- 为什么是 bug：
  - `concurrency` 默认值为 2（`utils.py:91`），`params_panel.py:50` 也默认 2。
  - `processor.py:122-128` 用 `asyncio.Semaphore(self.config.concurrency)` 并发处理。
  - 当文件 A 还在流式输出时，文件 B 的 `_on_file_start` 触发 → `_current_stream_key` 被覆盖为 B。
  - 之后 A 的所有 `on_stream(token)` 都在 `file_key == _current_stream_key` 校验处被丢弃。
  - 用户看到的现象：**A 的 diff 面板永远停在 B 切上来的那一瞬间，再也不会更新**，即使 A 实际完成了。
  - `diff_viewer._current_key` 也是同样问题，影响 `update_streaming` 内部 `file_key != self._current_key` 的早退路径。
  - 真正在 GUI 上能流式看到结果的永远只是"最后一个 start 的文件"，其余并发任务退化成"完成才一次性显示"。

- 修复建议：
  1. **方案 A（推荐）**：在 DiffViewer 中维护 `dict[key, partial_text]`，按 file_key 分桶缓存 streaming 状态；在 `_on_file_changed`（combo 切换）或 `_on_file_start` 时把对应 key 的最新 partial 渲染出来。
  2. **方案 B**：把 streaming 实时显示在 `progress_panel.current_file_label` 附近的小预览框，diff 面板只在完成时刷新一次（避开并发冲突）。
  3. **方案 C（临时绕过）**：把 `concurrency` 强制 = 1，但损失并发收益。

---

### [严重] 1.2 `_on_file_done` 同样以 `_current_stream_key` 过滤，导致并发文件最终结果不显示

- 位置：`app/main_window.py:474-485`
- 代码片段：

  ```python
  def _on_file_done(self, file_key: str):
      ...
      if file_key == getattr(self, '_current_stream_key', ''):
          self.diff_viewer.update_final(file_key, task.result.original, task.result.corrected)
  ```

- 为什么是 bug：
  - 与 1.1 同一根源：A 还在跑时 B 来了，`_current_stream_key = B`。
  - A 完成后 emit `on_file_done("A")`，但 `_current_stream_key` 是 B → `update_final(A)` 被跳过。
  - 后果：A 在 diff 面板上既看不到流式过程（被 1.1 截断），完成时也不显示最终结果（被本 bug 截断）。
  - 唯一的"恢复路径"是用户手动在 `diff_viewer.file_combo` 里点 A 才看到结果，UX 严重降级。

- 修复建议：
  - 取消 `_current_stream_key` 这个全局过滤；让 `update_final` 总是执行（DiffViewer 内部按 file_key 决定要不要重绘）。
  - 或者改成"以 DiffViewer 当前 combo 选中的 key 为准"，combo 切换由用户主动触发。

---

### [中等] 1.3 `ProcessingThread.run()` 中 lambda 闭包绑定 `self.engine`，与 QThread 信号机制混用导致 race

- 位置：`app/main_window.py:30-48`
- 代码片段：

  ```python
  class ProcessingThread(QThread):
      ...
      def run(self):
          self.engine.on_log = lambda m: self.log_signal.emit(m)
          self.engine.on_stream = lambda k, t: self.stream_signal.emit(k, t)
          self.engine.on_file_start = lambda k: self.file_start_signal.emit(k)
          self.engine.on_file_done = lambda k: self.file_done_signal.emit(k)
          self.engine.start()
          self.finished.emit()
  ```

- 为什么有隐患：
  - 这里的 lambda 把"engine 的 callback 字段"和"QThread signal"绑成 1:1 转发，但 `engine.on_log = ...` 这个赋值是**在子线程内**发生的。
  - 如果 GUI 线程（如 `_on_processing_finished` → `self.engine = None`）和子线程 `run()` 在同一瞬间操作 `self.engine` 字段，会出现可见性问题。
  - 更隐蔽的是：这些 callback 在 `_on_processing_finished` 之后仍然挂在 `engine` 上不被清理（因为 lambda 引用 `self`，engine 又引用 lambda，engine 析构时 lambda 才被回收，但 engine 是被 MainWindow `self.engine` 强引用的，可能长时间不释放）。
  - 同时，lambda 闭包捕获了 `self`（ProcessingThread 实例），导致 QThread 对象直到所有信号槽断开才能被 GC。

- 修复建议：
  - 把 callback 绑定从 `run()` 移到 `__init__`（GUI 线程内），这样生命周期清晰：
    ```python
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.engine.on_log = lambda m: self.log_signal.emit(m)
        # ...
    ```
  - 或者干脆让 ProcessingEngine 直接持有 `Signal`（QObject 化），跨线程通过 queued connection 通信，避免 lambda 闭包。

---

### [中等] 1.4 `MainWindow.closeEvent` 中 cancel 后立即 accept，lambda 仍可能在子线程中触发 emit

- 位置：`app/main_window.py:570-585`
- 代码片段：

  ```python
  def closeEvent(self, event):
      if self.engine and self.engine.is_running:
          reply = QMessageBox.question(...)
          if reply == QMessageBox.StandardButton.Yes:
              self.engine.cancel()
              event.accept()
          ...
  ```

- 为什么是 bug：
  - `engine.cancel()` 只是设置 `_cancel_event` 并 `call_soon_threadsafe` 解开 pause；`asyncio.run()` 中的 task 仍在退出过程中，可能还会有一两个 `on_log` 触发。
  - `event.accept()` 后窗口立即销毁，Qt 析构 widget 树，子线程的 lambda `lambda m: self.log_signal.emit(m)` 还引用着 `self`（ProcessingThread），`log_signal` 仍 connect 到 `MainWindow._on_stream` 等 slot。
  - 在子线程中 `emit` queued 信号时，Qt 主事件循环已经在退出，slot 不会再被调度执行——但 `deleteLater` 时机依赖事件循环，可能在子线程 emit 时 MainWindow 已部分析构，导致 slot 执行时访问已删除的子对象。
  - 更糟：`self.thread` 没有 `deleteLater()`，MainWindow 析构后 QThread 仍然存活，子线程可能在野指针上 emit。

- 修复建议：
  - `event.accept()` 之前先 `self.thread.quit()` 并 `self.thread.wait(3000)`，确保子线程完全退出。
  - `self.engine` 在 cancel 后 `self.engine.on_log = None` 等解绑回调。
  - `self.thread.deleteLater()` 断开信号连接。

---

### [低] 1.5 `QShortcut` lambda 直接调用私有方法

- 位置：`app/main_window.py:94-98`
- 代码片段：

  ```python
  QShortcut(QKeySequence("Ctrl+O"), self, lambda: self.input_panel._add_files())
  QShortcut(QKeySequence("Ctrl+Enter"), self, lambda: self._on_start())
  ```

- 为什么有问题：
  - 调 `input_panel._add_files()`（私有方法）绕过封装。
  - `Ctrl+Return` 和 `Ctrl+Enter` 都触发同一逻辑，可能产生重复触发。
  - 不算 GUI 线程 bug，但属于可维护性 + 偶发重复事件问题（QShortcut 在某些平台会双发）。

- 修复建议：
  - 把 `_add_files` 改为 `add_files`（公开）。
  - 保留一个快捷键即可。

---

## 2. QThread 生命周期

### [严重] 2.1 `_on_processing_finished` 中 `self.thread` 未清理 / 未 `wait`，存在野指针 + 重入风险

- 位置：`app/main_window.py:413-419` / `app/main_window.py:487-490`
- 代码片段：

  ```python
  # 创建
  self.thread = ProcessingThread(self.engine)
  self.thread.log_signal.connect(lambda m: self.progress_panel.append_log(m))
  ...
  self.thread.start()
  ```

  ```python
  # 收尾
  def _on_processing_finished(self):
      if hasattr(self, "_poll_timer"):
          self._poll_timer.stop()
      self._poll_engine()
      ...
  ```

- 为什么是 bug：
  - `_on_processing_finished` 是由 `self.thread.finished` 触发的，**触发的瞬间 thread.run() 已经返回，但 QThread 仍在 join 阶段**。
  - 没有 `self.thread.wait()`，没有 `self.thread.deleteLater()`，没有 `self.engine = None`。
  - 用户点"重试失败" → `_on_retry_failed` → `_start_processing` 重新 `self.thread = ProcessingThread(self.engine)`，**新 thread 对象覆盖旧引用，但旧 QThread 仍可能在底层 join**。
  - 同时旧的 `self.engine` 还在被 `self.thread` 通过 lambda 引用着，**新旧 engine 的 lambda 会同时挂在不同 thread 的回调上**，但 `_on_processing_finished` 已经把 `self.engine` 字段重置为新 engine，旧的 lambda 还在飞（已 emit 但 slot 还在事件队列里）。
  - 极端场景：连续点"重试失败"多次，旧 thread + 旧 engine 链全在堆里没人回收。

- 修复建议：
  ```python
  def _on_processing_finished(self):
      ...
      if self.thread:
          self.thread.quit()
          self.thread.wait(5000)
          self.thread.deleteLater()
          self.thread = None
      self.engine = None
  ```

---

### [严重] 2.2 `closeEvent` 中 `event.accept()` 后子线程未 `wait`，进程退出时强杀

- 位置：`app/main_window.py:570-585`
- 代码片段：

  ```python
  if reply == QMessageBox.StandardButton.Yes:
      self.engine.cancel()
      event.accept()
  ```

- 为什么是 bug：
  - `cancel()` 异步，`asyncio.run()` 的 task 还没退出，PySide6 主窗口已开始销毁。
  - 进程在 `sys.exit(app.exec())` 返回时不会主动 join Python 子线程，Python 解释器退出时由 `Py_AtExit` 暴力终止。
  - 表现：日志可能写一半，checkpoint 文件可能写一半，下次启动加载断点报错。
  - 偶发：UI 关闭后 1~2 秒内 IDE/任务管理器显示"Python 进程残留"。

- 修复建议：
  ```python
  if reply == QMessageBox.StandardButton.Yes:
      self.engine.cancel()
      if self.thread:
          self.thread.quit()
          self.thread.wait(5000)   # 关键
      event.accept()
  ```

---

### [中等] 2.3 `ProcessingThread` 无 `parent`，生命周期不可控

- 位置：`app/main_window.py:413`
- 代码片段：

  ```python
  self.thread = ProcessingThread(self.engine)
  ```

- 为什么是问题：
  - `QThread(parent=None)`：MainWindow 销毁时 Qt 不会自动 delete QThread。
  - 必须手动 `deleteLater()` 才能正常释放；当前代码完全没有这一步。

---

### [中等] 2.4 `QThread.start()` 多次调用保护缺失

- 位置：`app/main_window.py:419`
- 为什么是问题：
  - 用户如果在 thread 还没退出时（`finished` 还没触发）连点"开始处理"，会再 `self.thread.start()` 一次。
  - 第二次 `start()` 在 Qt 中会直接抛出 `RuntimeError: QThread: Destroyed while thread is still running` 或 `start: thread already started`。
  - 没有 `isRunning()` 守卫。

- 修复建议：
  ```python
  if self.thread and self.thread.isRunning():
      QMessageBox.warning(self, "提示", "上一批任务尚未结束")
      return
  ```

---

## 3. QTimer 泄漏 / 状态残留

### [中等] 3.1 `_poll_timer` 在新一轮 `_start_processing` 时被覆盖，旧 timer 状态残留

- 位置：`app/main_window.py:400-402`
- 代码片段：

  ```python
  self._poll_timer = QTimer(self)
  self._poll_timer.timeout.connect(self._poll_engine)
  self._poll_timer.start(200)
  ```

- 为什么是问题：
  - 旧 `_poll_timer` 是 `MainWindow` 的子对象，引用计数还被旧字段保留，新赋值后旧对象在 GC 时才被 deleteLater。
  - 但旧 timer 的 `timeout` 信号仍连接到 `_poll_engine`，**如果旧 timer 还在 active 状态（200ms 周期内被覆盖），那一帧 `_poll_engine` 仍会被旧信号触发**，而此时 `self.engine` 已经是新 engine 了——`_poll_engine` 里 `eng._stats_lock`、`eng.tasks` 都指向新 engine，瞬间不一致。
  - 旧 timer 不会泄漏，但会在切换瞬间出现一帧"旧 engine 不存在 / 新 engine 还没准备好"的抖动。

- 修复建议：
  ```python
  if hasattr(self, "_poll_timer") and self._poll_timer:
      self._poll_timer.stop()
      self._poll_timer.deleteLater()
  self._poll_timer = QTimer(self)
  ...
  ```

---

### [低] 3.2 `DiffViewer._stream_timer` 关闭时未显式 stop

- 位置：`app/diff_viewer.py:26-30`
- 为什么是问题：
  - `_stream_timer` 是 `DiffViewer` 的子对象，widget 销毁时 Qt 会自动停止。
  - 但如果在 widget 销毁瞬间有 pending `_do_stream_diff`，可能在已析构的 `original_view` / `corrected_view` 上调用 `clear()` / `append`，**理论上有竞态**。
  - 实测不易触发，但属于防御性遗漏。

- 修复建议：在 `DiffViewer` 加 `__del__` 或 `closeEvent` 显式 `self._stream_timer.stop()`。

---

### [低] 3.3 `_debounce_timer` 不会泄漏

- 位置：`app/main_window.py:88-90`
- 说明：单次创建作为 MainWindow 子对象，窗口销毁时一起释放，无问题。
- 顺带：`start(500)` 每次都重新设置 timeout，是正确用法。

---

## 4. asyncio 与 Qt 集成

### [严重] 4.1 `prepare_tasks` 在 GUI 线程执行同步文件 IO，UI 卡顿

- 位置：`app/main_window.py:392-394` / `app/processor.py:68-90`
- 代码片段：

  ```python
  # main_window.py:392-394
  def _start_processing(self, file_paths: list[Path]):
      self.engine = ProcessingEngine(self.config)
      self.engine.prepare_tasks(file_paths)
  ```

  ```python
  # processor.py:78-82
  try:
      text = read_file_text(fp)
  ...
  ```

- 为什么是 bug：
  - `read_file_text`（`utils.py:159-165`）是同步 IO，最多尝试 4 种编码的 `path.read_text`。
  - `load_checkpoint`（`utils.py:207-215`）也是同步 IO。
  - 这些都在 GUI 线程执行。**用户添加 100 个文件后点"开始"，UI 会卡死几秒到几十秒**。
  - 同时 `load_checkpoint` 中如果 checkpoint 文件很大（原文长），`json.loads` 也会卡。

- 修复建议：
  - 把 `prepare_tasks` 改为 `async`，移到 `_run_all` 的开头，或者在另一个 QThread 中执行。
  - 或者在 GUI 线程只做"快速 add"（不读文件），把读文件推迟到 `asyncio.to_thread` 中。

---

### [严重] 4.2 async 上下文中调用同步 IO `save_checkpoint`，阻塞 event loop

- 位置：`app/processor.py:186` / `app/processor.py:222` / `app/processor.py:235`
- 代码片段：

  ```python
  # processor.py:186
  save_checkpoint(task.file_path, task)
  ```

- 为什么是 bug：
  - `save_checkpoint`（`utils.py:195-204`）用 `path.write_text` 同步写文件。
  - 这是在 `_process_file_async` 中调用，`asyncio.Semaphore` 控制并发——但 IO 阻塞会让同批次其他 task 跟着等。
  - 假设 checkpoint 写盘 50ms，concurrency=4，单批次就被串行化增加 50ms × 4 的延迟。
  - 更严重：在 Windows 上磁盘 IO 抖动时可能阻塞几百 ms，期间 `pause_event` / `cancel_event` 都不能响应。

- 修复建议：
  ```python
  await asyncio.to_thread(save_checkpoint, task.file_path, task)
  ```

---

### [中等] 4.3 `pause` / `resume` / `cancel` 在 `_pause_event` 未初始化时静默失败 + 假日志

- 位置：`app/processor.py:296-311`
- 代码片段：

  ```python
  def pause(self) -> None:
      if self._loop and self._pause_event:
          self._loop.call_soon_threadsafe(self._pause_event.clear)
      self._log("[暂停] 处理已暂停")
  ```

  ```python
  @property
  def is_paused(self) -> bool:
      if self._pause_event:
          return not self._pause_event.is_set()
      return False
  ```

- 为什么是 bug：
  - 用户在 thread 启动后、`_run_all` 跑起来前的极短窗口点"暂停"。
  - 此时 `self._pause_event` 仍是 `None`（`processor.py:52` 初始化，line 101 才赋值），`pause()` 啥也不做，但日志说"已暂停"。
  - `is_paused` 返回 `False`，于是 `main_window.py:441-444` 的判断逻辑错误：
    ```python
    if self.engine.is_paused:  # 实际是 False（pause 失效）
        self.engine.resume()    # 不会执行
    else:
        self.engine.pause()     # 又调一次 pause，依然失败
    ```
  - 用户看到"已暂停"但实际跑得飞快。

- 修复建议：
  - `pause()` 返回 `bool`，让上层知道是否成功。
  - 或者在 `ProcessingEngine.__init__` 中提前建好 `_pause_event = asyncio.Event()`（但 asyncio.Event 必须在 loop 里创建，所以需要 lazy init）。
  - 把 `self._log("[暂停] ...")` 移到 `call_soon_threadsafe` 回调内执行，确保只在真正暂停时才打日志。

---

### [中等] 4.4 `cancel()` 后 `_call_api_stream` 已 raise `CancelledError`，但 `on_file_done` 仍会触发（最终态 = 部分内容）

- 位置：`app/processor.py:267-269` / `app/processor.py:194-195`
- 代码片段：

  ```python
  # processor.py:267-269
  if self._cancel_event.is_set():
      await stream.close()
      raise asyncio.CancelledError()
  ```

  ```python
  # processor.py:194-195（在 _process_file_async 的 try 块里）
  except asyncio.CancelledError:
      return
  ```

- 为什么是 bug：
  - `_call_api_stream` raise 后，外层 `_process_file_async` 直接 `return`，**没有给 task.result 赋值，也没有 increment `stats.completed_files`**。
  - 但同时**也没有保存 partial 状态到 checkpoint**——下次启动时 cancel 时的 partial 就丢了。
  - 顺便：`_run_all` 顶部的 `if self._cancel_event.is_set(): return`（行 142）和 `await self._pause_event.wait()`（行 145）会快速跳过 cancel 后的剩余 task，但这些 task 不会被 mark 为 CANCELLED 状态，输入面板状态卡在"处理中..."。

- 修复建议：
  - cancel 路径统一把 task 标 `CANCELLED`，更新 `input_panel.update_item_status(file_key, "已取消")`。
  - cancel 时把 partial 内容存到 checkpoint，下次启动可以选择续传。

---

### [低] 4.5 `_run_all` 中 `asyncio.gather(..., return_exceptions=True)` 异常仅打 logger.error，UI 不可见

- 位置：`app/processor.py:128-133`
- 代码片段：

  ```python
  results = await asyncio.gather(*coros, return_exceptions=True)
  for result in results:
      if isinstance(result, Exception):
          logger.error(f"Worker 异常: {result}")
  ```

- 为什么有问题：
  - Worker 内部异常已经在 `_process_file_async` 中捕获并标 FAILED，这里再 catch 一遍只是兜底。
  - 但兜底异常**没传到 GUI**，用户看不到堆栈。

- 修复建议：异常也走 `self._log(...)`，进 progress_panel 日志面板。

---

## 5. GUI 线程安全

### [严重] 5.1 `_poll_engine` 读 `eng.tasks` 不持锁，遍历过程中 engine 线程可能修改 task 字段

- 位置：`app/main_window.py:421-437`
- 代码片段：

  ```python
  def _poll_engine(self):
      if not self.engine:
          return
      eng = self.engine
      with eng._stats_lock:
          eng.stats.elapsed = time.time() - eng.stats.start_time
      self.progress_panel.update_stats(eng.stats)
      if eng.stats.completed_files > self._last_completed:
          self._last_completed = eng.stats.completed_files
          with eng._lock:
              snapshot = dict(eng.tasks)
          for key, task in snapshot.items():
              if task.result is not None:
                  self.input_panel.update_item_status(key, "已完成" if not task.result.error else "失败")
  ```

- 为什么是 bug：
  - `dict(eng.tasks)` 的复制是**部分加锁部分不加锁**：
    - `with eng._lock` 只覆盖了 `dict(eng.tasks)` 这一句。
    - 拿到 snapshot 后遍历 `snapshot.items()` 时，**每个 `task.result` 字段的读取没有锁**。
  - engine 线程（`processor.py:175-178`）：
    ```python
    with self._lock:
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.end_time = time.time()
    ```
    三个字段赋值在锁内，但**主线程读 `task.result` 不在锁内**——CPython 引用计数 + GIL 下大概率安全，但 GIL 可能在 read 中途让出（理论可能），且 dataclass 字段不是 atomic。
  - 实际表现：偶发 "已完成" 状态没及时显示（但很快会被下次 poll 修复）。
  - **更严重的**：如果 `task.result` 是个 `FileResult`，里面有 `corrected: str = ""`（mutable default），多线程同时 append 时会出问题——但目前 `FileResult` 是赋值后不再修改，所以这点 OK。

- 修复建议：
  - 整个 snapshot + 字段读取都在 `with eng._lock` 内。
  - 或者在 engine 端给每个 task 维护 `task._view_lock`，读取时加锁。

---

### [中等] 5.2 `_on_processing_finished` 直接读 `self.engine.tasks` 不持锁

- 位置：`app/main_window.py:499-535`
- 代码片段：

  ```python
  stats = self.engine.stats
  tasks = self.engine.tasks
  ...
  for task in self.engine.tasks.values():
      if task.result and task.is_done:
          self.diff_viewer._export_task(task, out_dir)
  ```

- 为什么有隐患：
  - `finished` signal 是在子线程 `run()` 末尾 emit 的（`processor.py` 实际是 `self.engine.start()` 内 `asyncio.run()` 跑完后回到 `run()`，然后 `self.finished.emit()`）。
  - 此时 `asyncio.run()` 已经返回，所有 task 都已完成，理论上 engine 不会再修改 tasks。
  - **但**：CPython 的 dict 引用在跨线程"读"时理论上需要 GIL 同步语义，这里已经安全（run() 退出后 happens-before 关系）。
  - 实际不是 bug，但属于"靠 GIL 保护"的代码，可读性差。

- 修复建议：在 `_on_processing_finished` 中通过 `with self.engine._lock` 读，或者在 `engine` 端加 `wait_for_done()` 同步方法。

---

### [中等] 5.3 `params_changed` / `config_changed` 信号在 `set_config` 期间未完全 blockSignals，可能在初始化时触发 _debounce

- 位置：`app/main_window.py:324-351` / `app/main_window.py:88-90`
- 代码片段：

  ```python
  def _apply_config_to_ui(self):
      self.api_config_panel.set_config(self.config)
      self.params_panel.concurrency_spin.setValue(self.config.concurrency)
      self.params_panel.temperature_spin.setValue(self.config.temperature)
      ...
      self.params_panel.prompt_mode_combo.blockSignals(True)
      self.params_panel.prompt_mode_combo.setCurrentIndex(pidx)
      self.params_panel.prompt_mode_combo.blockSignals(False)
      self.params_panel._on_mode_changed(pidx)
  ```

- 为什么是问题：
  - `set_config`（`api_config.py:202-207`）会逐个 `setText` / `setValue`，**每个 setter 都触发 `textChanged` / `valueChanged`**，进而触发 `config_changed.emit()`。
  - 初始化时 config_changed 会连发 4~5 次，触发 `_debounce_timer.start(500)`。
  - 如果用户在 500ms 内退出，`_do_save_config` 还没执行就把窗口关掉，会写一个**空的或半初始化的 config** 到磁盘（覆盖用户之前的 config）。
  - 更隐蔽：初始化阶段 `_debounce_timer` 被启动，但 `_do_save_config` 仍会执行（500ms 后），把内存中刚初始化的 config 写回磁盘——看起来没事但实际上 init 期间的 _on_config_changed 会跑 `_update_status_bar` 等副作用。

- 修复建议：
  - `_apply_config_to_ui` 整段 `self.api_config_panel.blockSignals(True)` / `self.params_panel.blockSignals(True)` 包裹。
  - 或者在 `_init_ui` 末尾才创建 `_debounce_timer` 并 connect（确保 init 阶段不触发）。

---

### [低] 5.4 `api_config.py:167` 用裸 `threading.Thread` 测试连接，跨线程访问 widget

- 位置：`app/api_config.py:153-167`
- 代码片段：

  ```python
  def do_test():
      try:
          ...
          self._test_done(True, "连接成功")
      except Exception as e:
          self._test_done(False, f"{type(e).__name__}: {str(e)[:80]}")
  threading.Thread(target=do_test, daemon=True).start()
  ```

- 为什么有 bug：
  - `self._test_done` 在子线程中调用，内部操作 `self.test_btn` / `self.test_result`（QWidget）。
  - 直接跨线程访问 Qt widget，**Qt 不保证线程安全**，会偶发崩溃或样式错乱。
  - 应该用 `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` 或 `QTimer.singleShot(0, ...)` 把结果切回主线程。

- 修复建议：
  ```python
  from PySide6.QtCore import QMetaObject, Qt as QtNS, Q_ARG
  def do_test():
      try:
          ...
          QMetaObject.invokeMethod(self, "_test_done_slot", QtNS.ConnectionType.QueuedConnection, Q_ARG(bool, True), Q_ARG(str, "连接成功"))
      except Exception as e:
          QMetaObject.invokeMethod(self, "_test_done_slot", QtNS.ConnectionType.QueuedConnection, Q_ARG(bool, False), Q_ARG(str, str(e)))
  ```

---

## 6. 流式回调时序问题

### [严重] 6.1 on_stream 节流逻辑 + 关闭 stream 时机可能漏掉最后一个 token

- 位置：`app/processor.py:266-292`
- 代码片段：

  ```python
  async for event in stream:
      if self._cancel_event.is_set():
          await stream.close()
          raise asyncio.CancelledError()
      if event.choices:
          delta = event.choices[0].delta.content
          if delta:
              collected.append(delta)
              emit_counter += 1
              now = time.time()
              if self.on_stream and (
                  emit_counter % _STREAM_THROTTLE_TOKENS == 0
                  or (now - last_emit_time) >= _STREAM_THROTTLE_MS
              ):
                  self.on_stream(task_key, "".join(collected))
                  last_emit_time = now
      if event.usage:
          token_count = event.usage.total_tokens
  ```

- 为什么是 bug：
  - 节流用 `emit_counter % 5 == 0` 判断，但**只有 `delta` 非空时才 increment `emit_counter`**。
  - 假设流末尾有 2 个 chunk：第 1 个有 content（emit_counter=1, 不 emit），第 2 个只有 usage 标记（无 choices，emit_counter 不变）。
  - 末尾 `corrected = "".join(collected)` 有内容，但**最后一次 on_stream 没 emit，UI 上是倒数第 5 之前的旧 partial**。
  - 后面 line 291-292 确实有 `self.on_stream(task_key, corrected)` 作为兜底，但**只在函数即将 return 时调用**。如果用户在中途 `_on_file_start` 切到别的文件，这条兜底信号仍会发到旧 file_key，但因为 1.1 的 `_current_stream_key` 过滤被丢。

- 修复建议：
  - 把 `emit_counter` 的 increment 移到 `async for` 循环顶部（每个 chunk 都 +1，不依赖 choices）。
  - 或者在节流前判断 `last_emit_time` 是否过久，强制 flush。

---

### [中等] 6.2 `DiffViewer.show_original` 被并发 `on_file_start` 反复 clear，原文被打断

- 位置：`app/diff_viewer.py:85-89` / `app/main_window.py:461-468`
- 代码片段：

  ```python
  def show_original(self, file_key: str, original_text: str):
      self._streaming_original = original_text
      self.original_view.setPlainText(original_text)
      self.corrected_view.clear()
      self.corrected_view.setPlaceholderText("生成中...")
  ```

- 为什么是 bug：
  - 并发时 B 的 `on_file_start` 会调用 `show_original(B, ...)`，把 A 的原文清掉。
  - 此时如果用户切回 A（A 已 done），`_on_file_changed` 触发 `_show_diff` 重新渲染——OK。
  - 但**如果 A 还在流式过程中**，B 切走导致 A 的 streaming 被 1.1 截断，A 的 `_current_key` 不是 A 了，下一次 A 的 `update_streaming` 早退。
  - 后续 A 完成时，1.2 的 `update_final(A)` 也被截断。
  - 用户在 combo 切回 A 时，`_on_file_changed` 调 `_show_diff(A.original, A.corrected)` 能显示**最终结果**，但中间过程全丢。

- 修复建议：见 1.1 方案 A，按 file_key 分桶缓存。

---

### [低] 6.3 `_pending_stream_text` 简单覆盖，最后一个 partial 可能覆盖不到

- 位置：`app/diff_viewer.py:91-97`
- 代码片段：

  ```python
  def update_streaming(self, file_key: str, partial_text: str):
      if file_key != self._current_key:
          return
      self._pending_stream_text = partial_text
      if not self._stream_timer.isActive():
          self._stream_timer.start(_STREAM_DIFF_INTERVAL_MS)
  ```

- 为什么有问题：
  - 节流 200ms + 引擎端 50ms 双重节流，**单文件流式**情况下问题不大。
  - 但若引擎连续发 10 个 token，timer 触发时 `_pending_stream_text` 是最新的，渲染也 OK。
  - 隐患是 timer 触发的瞬间 `_do_stream_diff` 中：
    ```python
    text = self._pending_stream_text
    if not text or not self._streaming_original:
        return
    ```
    如果 `original_text` 为空（`show_original` 没及时调），会早退。理论上 `on_file_start` 必先于第一次 `on_stream`，但**跨线程时序不能 100% 保证**——on_file_start 走 queued connection，on_stream 也走 queued connection，**两个 signal 在主线程队列里谁先谁后不确定**。

- 修复建议：
  - 在 `update_streaming` 内部如果 `_streaming_original` 为空，主动调用 `self._show_streaming_diff` 的退化版本（不显示 diff，只显示 raw text）。

---

## 7. 其他次要问题

### [低] 7.1 `MainWindow._last_completed` 未在 `__init__` 初始化

- 位置：`app/main_window.py:404`
- 为什么是问题：
  - `__init__` 中没初始化 `_last_completed`。
  - 第一次 `_start_processing` 之前如果（理论上不可能但）触发 `_poll_engine`，会 `AttributeError`。
  - 当前逻辑 `_poll_timer` 是在 `_start_processing` 中创建，所以实际不会触发。但 `_on_processing_finished` 中调用 `_poll_engine()` 一次，此时 `_last_completed` 已被设置。
  - 防御性差。

---

### [低] 7.2 `params_panel.set_custom_prompt` 方法定义但 `main_window._apply_config_to_ui` 没调用

- 位置：`app/params_panel.py:160-161` / `app/main_window.py:337-340`
- 代码片段：

  ```python
  # params_panel.py:160-161
  def set_custom_prompt(self, text: str):
      self.prompt_edit.setPlainText(text)
  ```

  ```python
  # main_window.py:337-340
  if self.config.custom_prompt:
      self.params_panel.prompt_edit.blockSignals(True)
      self.params_panel.prompt_edit.setPlainText(self.config.custom_prompt)
      self.params_panel.prompt_edit.blockSignals(False)
  ```

- 为什么是问题：
  - `_apply_config_to_ui` 直接操作 `self.params_panel.prompt_edit`（私有属性），没用公开方法。
  - 封装违反，但功能 OK。

---

### [低] 7.3 `progress_panel.append_log` 中"自动展开日志"误判

- 位置：`app/progress_panel.py:183-188`
- 代码片段：

  ```python
  def append_log(self, msg: str):
      self.log_output.append(msg)
      if not self._log_visible and any(k in msg for k in ("失败", "错误", "成功", "完成")):
          self._log_visible = True
          self.log_output.setVisible(True)
          self.log_toggle.setText("收起日志")
  ```

- 为什么有问题：
  - 关键字匹配 `any(k in msg for k in ("失败", ...))` 可能误中——比如"已失败文件已成功重试"含"失败"和"成功"都会命中。
  - 更糟：用户主动"收起日志"想静音，被一条普通日志强制展开。

- 修复建议：用 set() 关键字白名单 + 严格匹配（`msg.startswith("[错误]")` 等）。

---

### [低] 7.4 `InputPanel` 拖拽时 `os.walk` 在 GUI 线程

- 位置：`app/input_panel.py:199-211`
- 为什么是问题：
  - 拖入一个含 10k 文件的目录会卡 UI。
  - 同 4.1 类型问题，但没那么严重（用户主动操作）。

---

## N. 总结

### 最严重的 3 个问题

1. **流式并发时 `_current_stream_key` 过滤导致多文件 streaming 全部丢失（1.1 / 1.2 / 6.2）**
   - 现象：concurrency ≥ 2 时，UI 上只能看到"最后一个开始的文件"的流式过程，其他并发文件的 diff 在面板上完全停滞直到用户手动 combo 切换。
   - 根因：`main_window._current_stream_key` 和 `DiffViewer._current_key` 是单值字段，被 `on_file_start` 覆盖；`on_stream` 回调用 `file_key == _current_stream_key` 早退。
   - 影响：核心 UI 功能（实时 diff 预览）在并发场景下失效，是用户最频繁踩到的 bug。

2. **`prepare_tasks` 在 GUI 线程执行同步文件 IO（4.1）+ `save_checkpoint` 阻塞 event loop（4.2）**
   - 现象：文件多时点"开始"按钮后 UI 几秒到几十秒不响应；并发处理时 IO 抖动放大 cancel/pause 延迟。
   - 根因：`read_file_text` / `load_checkpoint` / `save_checkpoint` 全部用同步 IO。
   - 影响：100+ 文件场景下明显卡顿；cancel 响应延迟 100ms~1s。

3. **`self.thread` / `self.engine` 生命周期未清理 + `closeEvent` 不 `wait`（2.1 / 2.2 / 1.4）**
   - 现象：连续点"重试失败"会创建多个 QThread 实例，旧对象泄漏；关闭窗口时子线程被强杀，checkpoint 可能写一半。
   - 根因：没有 `wait()` / `deleteLater()` / `engine = None`。
   - 影响：内存泄漏 + 数据损坏风险。

### 次要但应修的 3 个问题

4. `_on_processing_finished` 中 `self.thread = None` / `self.engine = None` 缺失导致旧 engine 引用不释放（2.1）。
5. `api_config._test_connection` 跨线程直接改 widget（5.4）——理论 crash。
6. `_apply_config_to_ui` 期间未 `blockSignals` 触发 debounce_timer 误启动（5.3）——可能覆盖用户磁盘 config。

### 整体建议

- 把 `ProcessingEngine` 改为 QObject 子类，通过 queued signal 与 GUI 通信，避免 lambda 闭包。
- DiffViewer 改为按 file_key 分桶的 streaming 状态机。
- 所有同步 IO 用 `asyncio.to_thread` 包裹。
- QThread + 引擎的生命周期管理加 helper：`start_engine()`, `stop_engine(timeout=5)`，集中处理 wait/deleteLater。
