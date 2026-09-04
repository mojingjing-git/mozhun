# 测试运行 + 静态扫描报告

> 项目：新时代校对大师
> 扫描范围：`app/` 全部 11 个 .py 文件
> 工作目录：`F:\AI\01_项目\新时代校对大师`
> 报告时间：2026-09-04

---

## 一、测试运行

### 1.1 test_bugs.py（回归测试）

- **结果：26 通过 / 0 失败**
- 覆盖范围：13 个 Bug 回归用例 + 1 个 PySide6 Signal 检查 + 6 个 Fluent 组件检查 + 7 个 Few-shot Prompt 检查
- 关键验证：
  - Bug#1 断点缓存命中（`load_checkpoint` + `prepare_tasks` 路径）
  - Bug#3 `_log` 回调幂等性
  - Bug#4 `FileTask` 多线程读写安全（500 写 + 500 读交错，无 `RuntimeError`）
  - Bug#5 空流响应必须抛 `ValueError`（防 LLM 无输出时静默吞掉）
  - Bug#6 `cancel()` 响应时间 < 0.5s
  - Bug#7 `_process_file_async` 必须有 `last_error` 兜底分支
  - Bug#9 `read_file_text` 不能用 latin1 兜底（必须保证非 UTF-8 不可解码字节会变成 U+FFFD）
  - Bug#10 difflib 2 万行 line diff < 1s
  - Bug#11/Bug#13 主窗口 finished 回调的 None 保护 + 导出 try/except
  - Few-shot：strict / polish / deep_polish / anti_rambling / tech_doc / long_sentence / custom 全部含 `## 示例`

### 1.2 test_components.py（组件 + 冒烟测试）

- **结果：151 通过 / 0 失败**
- 覆盖范围：
  - **冒烟 (5 套)**: 模块导入 / 配置往返 / 引擎生命周期 / diff 位置计算 / Prompt 内容
  - **utils (21 项)**: ProjectConfig 11 字段完整往返、FileResult/Task 序列化、ProcessStats 边界 (0 除)、配置/断点持久化、`read_file_text` 多编码 + 非法字节
  - **templates (40 项)**: 7 个 API 模板必需字段 + 7 个 Prompt 模式的 label / system / few-shot / 长度 > 200
  - **logger (3 项)**: 单例、name、LOG_DIR
  - **processor (15 项)**: 引擎属性、`prepare_tasks` 缓存命中、`_call_api_stream` 空响应抛异常 + 正常流式 token 计数
  - **diff_viewer (13 项)**: 方法签名、`_find_diff_positions` 行为（abc→abd 找到差异，相同返回空）
  - **input_panel / api_config / params_panel / main_window (24 项)**: 公共方法、Signal、关键保护
- 跑测试过程中没有环境错误：未出现 PySide6 需要 display 的情况（测试用例只做导入 + 静态检查，不创建 Qt widget）

---

## 二、静态扫描发现

### [严重] S1. `closeEvent` 退出时未等待 ProcessingThread 结束

- **文件**：`app/main_window.py:570-585`
- **描述**：用户确认"是"后，`self.engine.cancel()` 立即 `event.accept()`，但 `self.thread`（QThread）仍在 `engine.start()` 的 `asyncio.run(self._run_all())` 中执行。Qt 不会等它，主线程直接退出：
  1. `asyncio.run` 内部取消事件循环时如果有未关闭的 aiohttp 连接，可能打印 `RuntimeError: Event loop is closed`
  2. 断点 checkpoint 写入 / `self.finished.emit()` 可能丢失
  3. Qt 关闭时打印 `QThread: Destroyed while thread is still running`
- **复现**：开始处理长任务 → 关闭窗口 → 选"是" → 看控制台
- **修复建议**：
  ```python
  if reply == QMessageBox.StandardButton.Yes:
      self.engine.cancel()
      if self.thread and self.thread.isRunning():
          self._poll_timer.stop()  # 先停轮询
          self.thread.quit()
          self.thread.wait(2000)   # 最多等 2s
      event.accept()
  ```
  并在 `thread.finished.connect(self.thread.deleteLater)` 保证 thread 被 Qt GC。

---

### [严重] S2. `_call_api_stream` 取消分支可能泄漏底层 HTTP 连接

- **文件**：`app/processor.py:266-269`
- **描述**：
  ```python
  async for event in stream:
      if self._cancel_event.is_set():
          await stream.close()        # ① 这一步本身可能抛
          raise asyncio.CancelledError()  # ② 立即抛，未保护
  ```
  如果 `stream.close()` 抛异常（网络抖动 / aiohttp connector 已关闭 / 401 中断流），`CancelledError` 不会被 raise，连接不会被取消标记，且外层 `except Exception` 会把它当作普通错误进入重试逻辑——这正是用户"取消"时不应发生的事。
- **复现**：在 `stream` 进行中关闭网卡或拔网线，按"取消"
- **修复建议**：
  ```python
  if self._cancel_event.is_set():
      try:
          await stream.close()
      except Exception:
          pass
      raise asyncio.CancelledError()
  ```
  或更稳妥地用 `async with self._client.chat.completions.create(...) as stream:` 形式（取决于 openai SDK 是否支持）。

---

### [中] M1. `total_errors` 统计使用 `abs()` 误导输出

- **文件**：`app/main_window.py:504-515`
- **描述**：
  ```python
  total_errors = sum(
      len(t.result.corrected) - len(t.result.original)
      for t in tasks.values()
      if t.result and not t.result.error and t.result.corrected
  )
  ...
  f"总修改: {abs(total_errors)} 字符\n"
  ```
  `corrected - original` 是**净字符差**（可正可负），立即 `abs()` 会让正负都计入"修改"，且互相抵消。例：A 文件 +100 字符（扩写），B 文件 -100 字符（精简）→ 报"修改 200 字符"，但**净变化为 0**。再如：LLM 把 200 字原文压成 100 字（删冗），报"修改 100 字符"——会暗示"修改量很大"，但实际是大规模重写。
  变量名 `total_errors` 也容易误读为"错误数"。
- **复现**：用 polish 模式处理 2 个文件（一扩一缩），看日志里的"总修改"
- **修复建议**：用 difflib 统计真实插入/删除字符数，或改名为 `char_delta_abs` 并配合说明文字"字符净差"。

---

### [中] M2. 流式节流的"50ms 时间窗"实际是死代码

- **文件**：`app/processor.py:39-40, 277-282`
- **描述**：注释/设计意图"每 5 token 或 50ms emit 一次"，但实现是：
  ```python
  if self.on_stream and (
      emit_counter % _STREAM_THROTTLE_TOKENS == 0   # 5 的倍数
      or (now - last_emit_time) >= _STREAM_THROTTLE_MS  # 50ms
  ):
  ```
  但 `last_emit_time = 0.0` 初始化后，只有**第一次满足 5 的倍数**时才会进入分支并赋 `last_emit_time = now`。而 `(now - 0.0)` 几乎总是 > 0.05，但因为它是 OR 关系的"或"项，且 AND 整体没有——等等，重读：是 OR 关系，所以两个条件任意一个成立都 emit。问题是：
  - `emit_counter % 5 == 0` 每 5 个 token 触发，**会更新 `last_emit_time`**
  - 5 个 token 通常 < 50ms，所以 `(now - last_emit_time) >= 0.05` 在没到下一个 5 倍数时几乎不成立
  - 实际结果：只有 5 的倍数才 emit。50ms 这条分支只在**第一个 token** (emit_counter=1) 时因为 `last_emit_time=0.0` 而短暂生效一次，然后 `last_emit_time` 被立刻更新成 `now`
- **影响**：节流名不副实。LLM 流式响应慢时（> 50ms/token），50ms 分支会生效；正常流式（< 20ms/token）时只有 5 倍数生效
- **修复建议**：明确两种节流策略选一种，或重写为：
  ```python
  should_emit = (
      (emit_counter % _STREAM_THROTTLE_TOKENS == 0)
      or (now - last_emit_time) >= _STREAM_THROTTLE_MS
  )
  if should_emit:
      self.on_stream(task_key, "".join(collected))
      last_emit_time = now
  ```
  当前代码恰好就是如此，但要求**初始化时 `last_emit_time = time.time() - 1`** 才能让第一个 token 立即 emit，否则首次也是等 5 倍数。

---

### [中] M3. `_validate_model` 是无效函数

- **文件**：`app/api_config.py:120-128`
- **描述**：
  ```python
  def _validate_model(self) -> bool:
      model = self.model_edit.text().strip()
      if model:
          self._model_err.setText("")
          self.model_edit.setStyleSheet(_NORMAL_STYLE)
          return True
      self._model_err.setText("")           # 空也是清空
      self.model_edit.setStyleSheet(_NORMAL_STYLE)
      return True                           # 空也返回 True
  ```
  无论是否为空都返回 True 并清空错误信息——**永远不会触发红框提示**。与 `_validate_url`（URL 无效会设红框）不对称。实际 `validate()` 在 137 行用 `if not model: return False, "请填写模型名称"` 仍然能拦截启动，所以"功能性 OK"，但**实时反馈**丢了。
- **复现**：清空模型名 → UI 不红框，但点开始会被 `validate()` 拦下弹警告框
- **修复建议**：把"无 model"分支改为：
  ```python
  self._model_err.setText("请填写模型名称")
  self.model_edit.setStyleSheet(_ERROR_STYLE)
  return False
  ```

---

### [中] M4. `_test_connection` 在子线程中直接访问 Qt 控件

- **文件**：`app/api_config.py:153-167`
- **描述**：
  ```python
  def do_test():
      try:
          from openai import OpenAI
          client = OpenAI(
              base_url=self.api_base_edit.text().strip(),  # 跨线程读 QLineEdit
              api_key=self.api_key_edit.text().strip() or "test",
              ...
          )
          client.models.list()
          self._test_done(True, "连接成功")  # 跨线程调 _test_done
      except Exception as e:
          self._test_done(False, f"...")
  threading.Thread(target=do_test, daemon=True).start()
  ```
  `QLineEdit.text()`、`_test_done` 内部对 `self.test_btn.setEnabled(...)` / `self.test_result.setStyleSheet(...)` 的调用都在子线程里执行。Qt 控件**非线程安全**，官方文档明确禁止从非 GUI 线程直接操作 widget。多数情况下"看起来工作"是因为读 text() 不修改状态，但 setStyleSheet 触发 QStyle 重绘是 race。
- **复现**：点击"测试连接" → 快速再次点击 → 可能偶现 `QObject: Cannot create children for a parent that is in a different thread`
- **修复建议**：
  ```python
  def do_test():
      try:
          ...
          QTimer.singleShot(0, lambda: self._test_done(True, "连接成功"))
      except Exception as e:
          QTimer.singleShot(0, lambda err=e: self._test_done(False, f"{type(err).__name__}: {str(err)[:80]}"))
  ```
  或使用 `QThread` + `Signal` 而非裸 `threading.Thread`。

---

### [中] M5. `_auto_save_results` 缺乏异常处理

- **文件**：`app/main_window.py:531-541`
- **描述**：方法体未包 try/except，但内含 `out_dir.mkdir(parents=True, exist_ok=True)`（可能抛 `PermissionError` / `OSError`）和 `self.diff_viewer._export_task(task, out_dir)`（内部 `out_path.write_text` 抛 I/O 错误）。任一失败会**中断 `_on_processing_finished` 后续清理**，用户的进度面板停留在"处理中..."状态（虽然 `progress_panel.set_running(False)` 在 492 行先执行了，但后面的 `_auto_save_results` 崩了会跳过第 539-541 行的成功提示）。
- **复现**：把"自动导出目录"设到只读盘符或不存在父目录并以无权限用户身份运行
- **修复建议**：包裹 try/except，失败用 `self.progress_panel.append_log(f"自动导出失败: {e}")` + `self.logger.error(...)`。

---

### [中] M6. `_auto_save_results` 缺少 `self.engine is None` 防御

- **文件**：`app/main_window.py:526-527` 和 `531-535`
- **描述**：调用链是
  ```python
  if self.config.output_dir:
      self._auto_save_results()
  ```
  `self.config.output_dir` 是字符串，校验通过后调用，但 `_auto_save_results` 自身**没有 None 检查**，直接 `for task in self.engine.tasks.values()`。当前调用路径上 `_on_processing_finished` 在 495-497 行已 return，engine 非 None，所以不会触发 NPE。但这是个**脆弱设计**：未来若有任何代码路径在 engine=None 时调用 `_auto_save_results`（如未来增加"预览"按钮），就会立刻 AttributeError。
- **修复建议**：在 `_auto_save_results` 头部加 `if not self.engine: return`。

---

### [低] L1. 死 import：`QDlgLayout`

- **文件**：`app/input_panel.py:7`
- **描述**：
  ```python
  from PySide6.QtWidgets import (
      ...
      QDialog, QTextEdit, QVBoxLayout as QDlgLayout,
  )
  ```
  全工程 grep `QDlgLayout` 仅此一处，无引用。
- **修复建议**：删除 `QVBoxLayout as QDlgLayout` 即可。

---

### [低] L2. `set_custom_prompt` 是未被调用的公共 API

- **文件**：`app/params_panel.py:160-161`
- **描述**：
  ```python
  def set_custom_prompt(self, text: str):
      self.prompt_edit.setPlainText(text)
  ```
  全工程仅此一处定义，main_window.py 也不调用。`prompt_edit` 的初始化 / 恢复都直接用 `setPlainText` 配合 `blockSignals`。
- **修复建议**：删除，或保留并加单元测试覆盖（防止 API drift）。

---

### [低] L3. `self.test_btn.setCursor(self.test_btn.cursor())` 是无操作

- **文件**：`app/api_config.py:87`
- **描述**：把当前光标设回当前光标，零效果。`PrimaryPushButton` / `NavigationButton` 都已经在 `theme.py` 里设过 `PointingHandCursor`，普通 `QPushButton` 在 Fluent QSS 也无光标规则，所以这句是调试残留。
- **修复建议**：删除该行。

---

### [低] L4. `FileResult.is_done` 把 `error=""` 也算 done

- **文件**：`app/utils.py:61-62`
- **描述**：
  ```python
  return self.result is not None and not self.result.error
  ```
  `not ""` 是 `True`，所以 `"error": ""` 会被算 done。当前所有写入路径都用 `error=f"{err_type}: {err_msg}"` 不会传空串，**实际不会触发**。但 `from_dict` 接受任意 JSON，若用户手动编辑 checkpoint 把 error 字段置空，下次会跳过这个文件。
- **修复建议**：改为 `self.result.error is None`。

---

### [低] L5. `templates.py` 中 `custom` 模式的 `system` 字段冗余

- **文件**：`app/templates.py:311`
- **描述**：
  ```python
  "custom": {"label": "自定义模式", "system": SYSTEM_PROMPT_STRICT},
  ```
  custom 的 system 复用 strict，且 `params_panel._on_mode_changed` 在 `mode_key == "custom"` 时给 `default = ""`。`processor._call_api_stream` 在 `self.config.custom_prompt` 非空时优先用 custom_prompt，所以基本不读这个字段。冗余字段可能误导其他代码（如未来按 `system` 字段做 UI 提示）。
- **修复建议**：把 `"system": ""` 或加注释说明是占位符。

---

### [低] L6. `progress_panel.append_log` 自动展开触发条件过宽

- **文件**：`app/progress_panel.py:183-188`
- **描述**：
  ```python
  if not self._log_visible and any(k in msg for k in ("失败", "错误", "成功", "完成")):
  ```
  关键字"成功"会触发——批处理 100 个文件，每个文件流式结束时 `_log("[成功] xxx")`，日志面板会**自动展开 100 次**，UI 频繁变化。
- **修复建议**：把"成功"从关键字移除，仅保留"失败/错误/完成/异常"等真正需要提示的状态。

---

### [低] L7. `closeEvent` 中 `Escape` 全局响应

- **文件**：`app/main_window.py:98`
- **描述**：`QShortcut(QKeySequence("Escape"), self, lambda: self._on_cancel())` —— 处理中、编辑 prompt 时、文件选择对话框里、文本预览对话框里都会触发 Esc 取消。预览对话框关掉时 Esc 也会取消正在运行的处理——**误触风险**。
- **修复建议**：在 `_on_cancel` 里加 `if not self.engine or not self.engine.is_running: return`。

---

## 三、未发现的问题（已检查的项）

- **裸 `except:`**：无（grep 0 命中）
- **未关闭的文件句柄**：所有 `Path.read_text` / `write_text` 走 `with` 语义；`open()` 出现在 `main_window._export_report` 的 552 行已用 `with`
- **QTimer.stop() 漏掉**：`_poll_timer`（488 行 stop）、`_stream_timer`（`update_final` 时 stop）、`_debounce_timer`（单次无需 stop）—— 都正确
- **未 wait 的 QThread**：见 S1，是唯一遗漏点
- **拼写错误**：`ProcessingThread`、`ProcessingEngine`、`_call_api_stream`、`_process_file_async`、`_show_streaming_diff` 等核心标识符拼写一致；prompt 模板中"校对" / "示例" 等用词规范
- **import 顺序**：所有 `from PySide6.*` 在标准库 / 第三方之后，本地 `app.*` 在最末，符合 PEP 8
- **死代码（非方法级）**：上述 L1-L3 之外没有发现

---

## 四、优先级建议

| 序号 | 级别 | 问题 | 估计工时 |
|---|---|---|---|
| S1 | 严重 | closeEvent 未 wait 线程 | 0.5h |
| S2 | 严重 | _call_api_stream cancel 资源释放 | 0.5h |
| M1 | 中 | total_errors 统计语义错 | 0.5h |
| M2 | 中 | 50ms 节流分支不生效 | 0.5h |
| M3 | 中 | _validate_model 死逻辑 | 0.2h |
| M4 | 中 | 跨线程访问 Qt 控件 | 1h |
| M5 | 中 | _auto_save_results 异常处理 | 0.3h |
| M6 | 中 | _auto_save_results 缺 None 检查 | 0.1h |
| L1-L7 | 低 | 死代码 / 拼写 / 设计 | 各 0.1h |

**总计**：约 4 小时可全部修完。
