# 错误处理 + 边界条件审查

> 审查范围：`app/processor.py`、`app/utils.py`、`app/main_window.py`、`app/api_config.py`、`app/params_panel.py`、`app/input_panel.py`、`app/diff_viewer.py`
>
> 审查目标：异常分类、边界值、断点缓存一致性、取消/暂停语义、配置校验、业务正确性
>
> 严重度：🔴 严重 · 🟠 高 · 🟡 中 · 🟢 低

---

## 1. API 错误处理

### 🔴 1.1 异常类型全分类为 `Exception`，无差异化重试策略
- 位置：`app/processor.py:196-202`
- 问题：`_process_file_async` 用 `except Exception as e:` 笼统捕获所有异常，并把退避策略统一写成 `delay = 2 ** attempt`。这导致几类**不可重试**的错误会浪费 1+2+4+8 = 15 秒并产生 4 次无效请求：
  - `openai.BadRequestError`（含 `context_length_exceeded`、`invalid_api_key`、`model_not_found`）—— 重试必死
  - `openai.AuthenticationError`（401/403）—— 重试必死
  - `openai.PermissionDeniedError` —— 重试必死
- 触发场景：用户粘贴大文本文件后点开始，第一次请求立刻返回 `context_length_exceeded`，程序仍然傻乎乎地等 1s/2s/4s/8s 才告诉用户失败。
- 修复建议：按异常类型分流，例如：
  ```python
  except openai.BadRequestError as e:  # 包含 context_length / invalid_request
      if "context_length_exceeded" in str(e):
          return self._fail(task, text, "文本超过模型上下文长度，请切分")
      return self._fail(task, text, f"请求格式错误: {e}")
  except openai.AuthenticationError as e:
      return self._fail(task, text, "API Key 无效或已过期")
  except (openai.APITimeoutError, openai.APIConnectionError, asyncio.TimeoutError) as e:
      # 仅对瞬态错误重试
      if attempt < self.config.max_retries:
          await asyncio.sleep(2 ** attempt)
          continue
  ```

### 🟠 1.2 rate limit 退避忽略 `Retry-After` header
- 位置：`app/processor.py:200-202`
- 问题：`2 ** attempt` 固定退避。OpenAI / DeepSeek 等服务在 429 时会在 `Retry-After` header 返回建议等待秒数，固定 2^n 既可能太短（继续被限流）也可能太长（浪费配额窗口）。
- 触发场景：并发数 = 4 跑大批量时容易触发 429，1s→2s→4s 退避与实际窗口不匹配。
- 修复建议：捕获 `openai.RateLimitError`，读取 `e.response.headers.get("retry-after")` 后再 sleep；未提供时回退到指数退避。

### 🟡 1.3 空响应检测只防"完全空"，防不住"全是 None delta"
- 位置：`app/processor.py:266-289`
- 问题：`if event.choices:` 处理了 choices 为空；`if delta:` 处理了 `delta.content is None`。但**如果整个 stream 只有结束帧 / role frame**，则 `collected` 是空字符串，第 287-289 行 `if not corrected` 才会 `raise ValueError`。
- 触发场景：API 限流后悄悄返回 200 + 空 body（少数代理服务）；或 SSE 连接在中途被代理 server 切断。
- 影响：会触发重试 → 4 次同样失败 → 15s 后失败，这是**预期行为**。但因为没区分错误类型，错误信息只是 "API 返回空内容"，没告诉用户"可能是网络截断"或"API 异常"。
- 修复建议：保留空响应检测，但在 `raise ValueError` 时附带 chunk 计数（`collected` 是否真的收到了 0 个 delta），便于定位是模型偷懒还是传输问题。

### 🟡 1.4 `token_count=0` 仍视为成功
- 位置：`app/processor.py:169-192`、`app/utils.py:62`
- 问题：成功条件只判断 `corrected` 非空 + 无异常。`token_count=0`（本地 vLLM 关闭了 usage 统计，或代理服务不返回 usage）完全不会触发任何警告。结果仍被持久化到 checkpoint，`is_done=True`，下次直接跳过。
- 触发场景：vLLM 默认 `enable_usage_stats=False`；LM Studio 不返回 usage 字段。
- 影响：用户看到 "Token: 0" 但不知道是正常还是异常；账单无法核对。
- 修复建议：在 `_call_api_stream` 末尾 `if token_count == 0:` 时打 `[警告]` 日志，但**不**把任务标记为失败（让用户决定）。

### 🟢 1.5 已知未知 prompt_mode 会回退但不持久化
- 位置：`app/processor.py:245-248`
- 问题：未知 `prompt_mode` 时回退到 `"strict"`，log warning。后续 `save_checkpoint` 缓存的是**当前真实**使用的 prompt（`self.config.custom_prompt` 或 `mode_info["system"]`），而不是用户选择的未知模式，所以**没有持久化污染**。
- 评价：行为正确，仅记录，不视为 bug。

---

## 2. 文件 IO 错误

### 🟠 2.1 读文件失败被静默吞掉，UI 永远显示"等待中"
- 位置：`app/processor.py:78-85`
- 问题：
  ```python
  try:
      text = read_file_text(fp)
  except Exception as e:
      self._log(f"[错误] 无法读取文件 {fp.name}: {e}")
      continue
  ```
  - 读失败时 `self.tasks` 里没有这个文件的 entry
  - `total_files` 不含它
  - UI 的文件列表里这项状态保持 "等待中"（input_panel 加文件时的初始状态）
  - **不会触发 on_file_done，也不会写任何错误状态**
- 触发场景：用户拖入被 Word 占用的 `.txt`（共享锁）、权限不足、`os.walk` 中途被中断但 list 已被收下。
- 影响：用户看到 N/N 全部完成，但点开某些文件发现没结果，**没有明确提示哪个文件失败**。
- 修复建议：把读失败的文件也加到 `self.tasks`，但 `status=FAILED`、`result.error = "读取失败: ..."`，并 emit `on_file_done` 让 UI 标红。

### 🟠 2.2 encoding fallback 末项"实际总是成功"，掩盖真错
- 位置：`app/utils.py:159-165`
- 问题：
  ```python
  for encoding in ["utf-8", "gbk", "gb2312", "gb18030"]:
      try:
          return path.read_text(encoding=encoding)
      except (UnicodeDecodeError, UnicodeError):
          continue
  return path.read_text(encoding="utf-8", errors="replace")
  ```
  - `gb18030` 是 GBK 的超集，所以前 3 个失败时第 4 个**几乎必成功**（除非二进制文件）
  - 真正兜底的 `errors="replace"` 永远不会执行（因为 `gb18030` 一定能解码）
  - **坑**：GB18030 把所有字节都映射为某个字符（包括控制字符、未定义码位），所以二进制文件（如图、压缩包改后缀）会被读成"乱码文本"并送进 LLM，浪费 token
- 触发场景：用户把 `document.zip` 改后缀成 `document.txt` 拖进来；嵌入大量二进制数据的"假文本文件"。
- 修复建议：先按 BOM 探测；都不匹配时按 `chardet` 概率；纯二进制（`\0` 比例 > 5%）直接拒绝并报错。

### 🟠 2.3 输出目录写入失败会让整个收尾流程崩溃
- 位置：`app/main_window.py:531-541`、`app/diff_viewer.py:205-225`
- 问题：
  - `_auto_save_results` 调 `out_dir.mkdir(parents=True, exist_ok=True)`（无 try/except）
  - `diff_viewer._export_task` 调 `folder.mkdir(exist_ok=True)` 和 `out_path.write_text(...)`（无 try/except）
  - **单个文件写入失败（权限、磁盘满、Windows 保留名）会让整个循环 raise，污染 `_on_processing_finished`**
  - 整个处理总结（"X/Y 成功"日志）都不会打印
- 触发场景：
  - 选定的 `output_dir` 在外接 U 盘上，U 盘被拔出
  - 选定目录为只读（如 C:\Program Files\）
  - 原文件名是 Windows 保留名（`CON.txt`、`PRN.txt`、`NUL.txt`、`COM1.txt`）
- 修复建议：每个文件的导出独立 try/except，失败累计到一个 `failed_exports: list[str]`，最后给用户提示"已导出 X 个，Y 个失败：[names]"。

### 🟡 2.4 Windows 保留名没有过滤
- 位置：`app/diff_viewer.py:213-225, 288`
- 问题：`_export_task` 用 `task.file_path.stem` 拼 `{stem}_corrected.{ext}`。如果 `stem` 是 `CON`（如 `CON.md`）或 `PRN`、`NUL`、`AUX`、`COM1`-`COM9`、`LPT1`-`LPT9`，在 Windows 上**任何后缀**的写入都会因设备保留名失败（`PermissionError: [Errno 22]` 或 `[WinError 5]`）。
- 触发场景：用户偶尔在 docx 转 txt 时遇到自动生成 `~$CON.txt` 类的临时文件，或脚本批量导出时遇到保留名。
- 修复建议：导出前用 `re.sub(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", r"\1_", stem, flags=re.I)` 重命名，或文件名里加前缀 `proofread_`。

### 🟡 2.5 路径含特殊字符 / 中文 / 大小写差异时去重失效
- 位置：`app/input_panel.py:92-97`
- 问题：`if str(p) not in self._file_map` 用字符串相等比较。Windows 下 `C:/test/file.txt` 和 `C:\test\file.txt`、`C:\Test\file.txt` 是同一文件，但**字符串不同**——会被加两次，UI 显示两个条目，processor 那边 `str(fp)` 也不同会真跑两次。
- 触发场景：用户从资源管理器拖入（`\`），再从"添加文件"对话框加（`/`），或大小写不同的快捷方式。
- 修复建议：用 `Path(p).resolve()` 规范化后再比较。resolve 也会处理符号链接/相对路径。

### 🟡 2.6 处理过程中文件被删/锁没被察觉
- 位置：`app/processor.py:78`、`app/utils.py:159`
- 问题：启动时成功读取后，API 调用期间**不会**重新读文件，所以**正常情况下没问题**。但 `_export_task` 写文件时如果 `task.file_path.parent / "corrected"` 因权限失败（如家长控制），整个循环崩溃（同 2.3）。
- 评价：原文件被删不影响主流程（结果都已在内存里），但导出阶段会因父目录被删而崩。

### 🟢 2.7 `nul`、`null` 文本被算作保留名但被文件名作 stem 处理
- 评价：用户通常不会刻意建这类文件，不是常见 bug。

---

## 3. 断点缓存一致性

### 🔴 3.1 修改 prompt 模式后旧缓存被无声复用
- 位置：`app/processor.py:68-86`、`app/utils.py:60-62, 195-204`
- 问题：缓存文件名是 `safe_name.json`（`utils.py:197`），`safe_name` 来自 `str(file_path)`，**不含 prompt 模式、custom_prompt 文本、temperature、model 任何业务参数**。`FileResult` 也不存这些参数。
- 触发场景：
  1. 用户用 `strict` 模式跑过 `a.txt` → 缓存 `a.txt_corrected` = 已校正
  2. 切换到 `polish` 模式 + 自定义 prompt
  3. 重新开始处理 → `a.txt` 被 `is_done` 判断为已完成，**直接跳过**
  4. UI 列表显示 "已缓存 ✓"，但实际缓存内容是用旧 prompt 跑的
  5. 用户对照新 prompt 预期看结果完全不符，**不知道是缓存问题**
- 影响：用户信任"断点续传"是按时间/输入复用，但实际是按"全文件 hash（其实是路径）"复用，导致新配置不生效。
- 修复建议（任选）：
  - **方案 A**：缓存 key 包含 `prompt_mode + hash(custom_prompt) + model` 的 hash，拼到文件名
  - **方案 B**：在 `FileResult` 中存 `prompt_signature`（同上），加载时校验，不一致则视为无效缓存
  - **方案 C**：UI 顶层加"忽略缓存重新处理"勾选，强制忽略 `is_done`

### 🟠 3.2 缓存文件损坏时静默退回"重新处理"
- 位置：`app/utils.py:207-215`
- 问题：
  ```python
  try:
      ...
      data = json.loads(cp_file.read_text(encoding="utf-8"))
      return FileTask.from_dict(data)
  except Exception as e:
      logger.error(f"加载断点失败 [{file_path}]: {e}")
  return None
  ```
  - 损坏 → 返回 None → `prepare_tasks` 把文件当新任务处理
  - 但**用户没被告知缓存损坏**（error 日志只在 logger）
- 触发场景：磁盘满/异常断电/用户手动编辑 .json 导致 JSON 损坏。
- 影响：用户可能疑惑"为什么我这个文件第二次跑还是要重跑？"，但找不到原因。
- 修复建议：损坏时把原文件 rename 为 `<name>.corrupt-<timestamp>`，并弹一个非阻塞提示"发现 X 个损坏缓存，已隔离"。

### 🟠 3.3 失败的缓存会被覆盖，但缓存内容没区分成功/失败
- 位置：`app/processor.py:222-235`、`app/utils.py:60-62`
- 问题：
  - 失败时 `save_checkpoint` 也写一份（`error=...`），下次 `load_checkpoint` 返回带 error 的 task
  - `is_done` 检查 `not self.result.error`，所以失败缓存正确触发重试 ✓
  - 但**没有"上次失败原因"提示**——第二次失败时日志只说"重试耗尽"，不告诉用户上次也失败了同样的原因
- 评价：行为正确，但 UX 有改进空间。

### 🟡 3.4 缓存目录无 size 限制，长期使用会膨胀
- 位置：`app/utils.py:168-172`
- 问题：每个 `~10K 字符`的文件缓存约 20-30KB JSON，1 万个文件 = 300MB。`~/.proofreader/checkpoints/` 没有 size 限制、没有 LRU、没有 TTL。
- 触发场景：校对仓库 6 个月以上，含数千个文件。
- 修复建议：启动时检查目录总大小 > 500MB 时提示清理；或按 mtime 90 天清理。

### 🟡 3.5 `save_checkpoint` 失败但内存 task.result 仍为成功
- 位置：`app/processor.py:186, 222, 235`
- 问题：`save_checkpoint` 内部 try/except，失败只 log。任务状态已经是 `COMPLETED`，UI 显示"已完成"。
- 触发场景：磁盘满 / `~/.proofreader/checkpoints/` 不可写。
- 影响：用户不知道结果没有持久化，下次启动会重跑（虽然结果一致）。如果用户以为"已经完成"就重装系统，数据全丢。
- 修复建议：checkpoint 失败时打 `[严重]` 日志，并在 UI 状态加"未缓存"标记。

### 🟢 3.6 同一文件被同时加入两次（大小写/正反斜杠差异）
- 详见 2.5，属于同一类问题。

### 🟢 3.7 路径规范化未做，迁移文件后缓存全失效
- 评价：不是 bug，是设计选择。改用 hash(content) 可同时解决 3.1 和 3.7，但需读全文以算 hash。

---

## 4. 取消/暂停的边界

### 🟠 4.1 暂停时正在 stream 的文件**不会被立即暂停**
- 位置：`app/processor.py:145, 160, 266`、`app/processor.py:296-304`
- 问题：
  - `_pause_event` 阻塞点：`_process_file_async:145`（协程入口）、`_process_file_async:160`（重试循环前）
  - **完全没有覆盖到 `_call_api_stream:266 async for event in stream`**
  - 暂停后**当前文件继续运行**直到下一个 network chunk 来完（几十毫秒-几秒）
  - 暂停后**其他等待的协程**（在 semaphore 上等待）会卡住，因为它们没走到 `_pause_event.wait()`
- 触发场景：用户按暂停，期望 1 秒内停；实际"当前文件"还在跑，"等待中的文件"立即停（但既然没在 stream，"停"和"等"等价）
- 影响：暂停语义不精确，**UX 上会让用户困惑"为什么按了暂停还在动"**。
- 修复建议：在 `_call_api_stream:266` 循环里也加 `if not self._pause_event.is_set(): await self._pause_event.wait()`，或通过 `client.close()` 主动断开连接。

### 🟠 4.2 取消时只关 stream 不清资源，AsyncOpenAI 连接未关闭
- 位置：`app/processor.py:266-269`、`app/processor.py:306-311`
- 问题：
  ```python
  if self._cancel_event.is_set():
      await stream.close()
      raise asyncio.CancelledError()
  ```
  - `stream.close()` 本身是异步操作，依赖 OpenAI SDK 实现，**可能 hang**
  - `AsyncOpenAI` 客户端在 `_run_all:104-109` 创建后**整个生命周期都不关闭**
  - `asyncio.run(...)` 退出时不会自动清理未关闭的 httpx 客户端
- 触发场景：用户按 Esc / 关闭程序。
- 影响：连接泄漏（OS 层 TIME_WAIT），高频取消时端口耗尽。
- 修复建议：在 `_run_all` 结尾 `try/finally` 块里 `await self._client.close()`。

### 🟠 4.3 取消后 `on_file_done` 不触发，UI 状态卡在"处理中..."
- 位置：`app/processor.py:194-195`
- 问题：
  ```python
  except asyncio.CancelledError:
      return
  ```
  - 取消后**直接 return**，没调 `on_file_done`，没设置 `task.status = CANCELLED`
  - `main_window.py:_poll_engine:429-437` 检查 `task.result is not None`，没 result 的 task 不会被更新
  - `_on_file_start` 之前已经标 "处理中..."（accent 色），现在永远不变
- 触发场景：用户取消一个正在处理的 5MB 文件。
- 修复建议：取消时把 `task.status = CANCELLED`，`task.result = FileResult(original=text, error="用户取消")`，并 emit `on_file_done` 让 UI 标灰/标取消。

### 🟡 4.4 取消期间 `asyncio.sleep(delay)` 退避被立即打断
- 位置：`app/processor.py:200-203`
- 问题：取消 → `asyncio.sleep` 抛 `CancelledError` → 被外层 `except asyncio.CancelledError: return` 捕获 → **task.result 还是 None**。
- 行为：下次 `prepare_tasks` 会重试。这其实是**正确的**（用户取消 ≠ 文件失败）。
- 评价：不是 bug，但应配合 4.3 让 UI 标"已取消"。

### 🟡 4.5 关闭程序时正在 stream 的请求被 kill，token 已被服务端计费
- 位置：`app/main_window.py:570-585`
- 问题：
  ```python
  if self.engine and self.engine.is_running:
      reply = QMessageBox.question(...)
      if reply == Yes:
          self.engine.cancel()
          event.accept()  # 不等 thread 结束，立即关窗
  ```
  - QThread 在窗口销毁时**不会**优雅结束，event loop 直接被 `sys.exit`
  - 已经在 network 上飞了一半的请求**服务端会算 usage**
  - **客户端 token_count 拿不到 → 也不会计进 `ProcessStats.total_tokens`**
- 触发场景：用户处理大文件中途直接关窗口。
- 影响：用户角度"免费"了几千 token，但服务商已扣费（账单对不齐）。
- 修复建议：`closeEvent` 中 `event.accept()` 之前 `self.thread.wait(3000)` 等待线程结束；或至少有明确警告"关闭会中断正在进行的请求"。

### 🟡 4.6 `_pause_event` 初始在 `_run_all` 内创建，但 engine 启动前调用 `pause()` 会 NPE
- 位置：`app/processor.py:50-52, 296-298`
- 问题：
  - `self._pause_event` 初始为 None
  - `pause()` 检查 `if self._loop and self._pause_event:` 保护 ✓
  - 但 `is_paused` 同样保护 ✓
  - `_run_all` 内 `self._pause_event = asyncio.Event()` 是在 `asyncio.run(self._run_all())` 内部
- 评价：已经有 None 保护，没问题。

### 🟢 4.7 `_run_all` 在 `pending` 为空时不会触发 `on_stats_update` 之外的事件
- 位置：`app/processor.py:115-120`
- 问题：当所有文件都已缓存时，`_run_all` 立即返回，**不调用** `on_file_done`（这无所谓因为没新文件），但**`stats.elapsed` 设为 0** 触发 `on_stats_update` 一次。
- 评价：行为正确。

---

## 5. 配置相关

### 🟡 5.1 `api_key` 为空也能点"开始"
- 位置：`app/api_config.py:130-139`、`app/main_window.py:381-385`
- 问题：
  ```python
  def validate(self) -> tuple[bool, str]:
      url = ...
      if not url: return False, "请填写 API 基础 URL"
      if not _VALID_URL_RE.match(url): return False, "API URL 格式无效"
      if not model: return False, "请填写模型名称"
      return True, ""  # 注意：没检查 api_key
  ```
  - 空 api_key → validate 通过 → `_on_start` 启动 → AsyncOpenAI 第一次调用 401 → 重试 4 次都 401 → 15 秒后失败
  - 测试连接用 `api_key or "test"`（`api_config.py:158`），**所以测试连接不会暴露这个问题**
- 触发场景：用户选模板"自定义"（`api_key=""`）后直接点开始。
- 修复建议：`validate` 加 `if not self.api_key_edit.text().strip(): return False, "请填写 API Key"`。

### 🟡 5.2 配置文件损坏/版本不兼容时静默回到默认
- 位置：`app/utils.py:185-192`
- 问题：
  ```python
  def load_config() -> ProjectConfig:
      try:
          ...
          return ProjectConfig.from_dict(data)
      except Exception as e:
          logger.error(f"加载配置失败: {e}")
      return ProjectConfig()
  ```
  - 损坏时只 log，**用户的所有配置（api_key、prompt 等）静默丢失**
  - 没有版本字段——未来加新字段时无法识别旧配置
- 触发场景：用户手动编辑 `~/.proofreader/last_config.json` 出错；未来版本升级。
- 修复建议：损坏时 `backup as last_config.json.broken-<ts>`，弹非阻塞提示；加 `"version": 1` 字段以便将来迁移。

### 🟡 5.3 `temperature` 越界没运行时校验
- 位置：`app/utils.py:113-127` (`from_dict`)、`app/params_panel.py:38` (UI 限制)
- 问题：UI `setRange(0.0, 2.0)` 限制，但旧 config 被人手改成 5.0 时：
  - `from_dict` 直接 `temperature=d.get("temperature", 0.1)` 接受
  - 传给 OpenAI API 会返回 400 invalid_request_error
- 评价：低频但应该有 sanity check。

### 🟡 5.4 `concurrency=0` 会死锁
- 位置：`app/utils.py:121`、`app/processor.py:122`
- 问题：
  - `asyncio.Semaphore(0)`：**所有 acquire 永远等待**
  - UI 限制 `setRange(1, 32)`，但 config 文件可绕过
  - `params_panel.get_concurrency` 直接 `return self.concurrency_spin.value()`
- 触发场景：旧 config + 旧 UI 升级不兼容。
- 修复建议：在 `_run_all` 入口 `if self.config.concurrency < 1: raise ValueError(...)`；或 `Semaphore(max(1, ...))`。

### 🟢 5.5 `temperature` 上限 2.0 与 OpenAI 接口允许值一致
- 评价：行为正确。

### 🟢 5.6 `output_format` 写入路径直接拼 ext，无 sanitize
- 位置：`app/diff_viewer.py:212, 224, 288`
- 问题：`output_format` 来自 `format_combo.currentText()`，UI 只有 `["txt", "json"]` 选项，正常不会有问题。
- 评价：低风险。

---

## 6. 业务逻辑

### 🔴 6.1 大文本文件超模型 context 时必败且 4 次重试浪费 15s
- 位置：`app/processor.py:250-259`
- 问题：整个 `text` 一次性塞进 `messages[1].content`：
  ```python
  messages=[
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": text},  # 整段原文
  ]
  ```
  - 没有分块（chunking）逻辑
  - 没有任何"先估算 token 数"的预检
  - 用户拖入一个 50K 字符的中文文章（约 75K tokens）→ 触发 `context_length_exceeded` → 重试 4 次 → 15 秒后才告诉用户
  - 用户的真实使用场景是"批量校对长文"，**这是核心场景**
- 触发场景：任何超过模型 context window 的文件。
- 修复建议（按推荐度排序）：
  1. **预检**：根据 model 名查 context window（如 8K/16K/32K/128K），超长时提示用户
  2. **分块校对**：按段落/句号切分，每块独立调用，合并结果
  3. **分块 + 上下文**：每块带前后各 200 字符 overlap，提示模型保持一致
  4. 退而求其次：捕获 `BadRequestError("context_length_exceeded")` 后**立即**标记失败，不重试（详见 1.1）

### 🟠 6.2 `completed_files` 含义混乱：成功 + 失败都算"完成"
- 位置：`app/processor.py:181, 219, 87-90`
- 问题：
  - 成功：`self.stats.completed_files += 1`（line 181）
  - 失败：`self.stats.completed_files += 1`（line 219）**（也算！）**
  - `prepare_tasks` 初始化时 `self.stats.completed_files = sum(1 for t in self.tasks.values() if t.is_done)`（line 87-90）
  - `progress_panel` 用 `f"{stats.completed_files}/{stats.total_files}"` 显示
  - 假设：3 个文件，2 成功 1 失败 → UI 显示 "3/3 已完成"，**用户以为全部成功**
  - 实际靠 `input_panel.update_item_status(key, "已完成" if not task.result.error else "失败")` 区分（`main_window.py:435, 479`），但这要求用户看文件列表
- 影响：日志总结 "文件: 2/3 成功"（`main_window.py:511-519`）正确，但进度条和文件 X/Y 计数**严重误导**。
- 修复建议：
  - 拆分 `completed_files` 为 `success_count` + `failed_count`
  - `progress_panel` 显示 `success_count / total_files`，并把失败文件的 `progress_panel` 卡片背景标红
  - ETA 计算只用 success_count

### 🟠 6.3 API 返回原文（无修改）算"成功"且被永久缓存
- 位置：`app/utils.py:60-62`、`app/processor.py:169-192`
- 问题：
  - `is_done` = `result is not None and not self.result.error`
  - `corrected == original` 完全不触发任何异常，正常存为成功
  - 实际场景：
    - 极简 prompt / 模型偷懒 / temperature=0 + 内容太短 → 模型直接复读原文
    - 用户用 `polish` 模式跑，发现所有"错字"都没改 → 误以为是模式问题
  - 下次启动会直接加载这个"成功"缓存，**用户改 prompt 也救不回来**（叠加 3.1）
- 触发场景：文本本来就 OK，模型遵循"无错即原样返回"指令（这其实是 prompt 设计的预期行为），但用户期望"已校对" ≠ "已检查且无错"。
- 评价：**对纯纠错模式是设计预期**，但对 `polish`/`deep_polish` 模式是 bug。建议：
  - 把 `corrected == original` 标记为"无修改"，在结果卡片显示 `0 处修改`
  - 但**不**视为失败（仍然 is_done），否则纯纠错模式 90% 的文件都会"失败"

### 🟡 6.4 进度统计不含"读失败的文件"
- 位置：`app/processor.py:78-90`
- 问题：详见 2.1。`total_files` 是 `len(self.tasks)`，但读失败的文件**没进** `self.tasks`，所以 5 个文件 → 1 个读失败 → `total_files=4` → UI 显示 4 个 → 失败的 1 个永远在"等待中"。
- 触发场景：详见 2.1。
- 修复建议：与 2.1 一起，把读失败的文件也加进 `self.tasks` 但 `status=FAILED`。

### 🟡 6.5 diff viewer 的 `_current_key` 与 `_current_stream_key` 不一致
- 位置：`app/main_window.py:461-472, 466-467`、`app/diff_viewer.py:91-96`
- 问题：
  - `_on_file_start` 把 `self._current_stream_key = file_key`（main_window.py:466）
  - `_on_stream` 用 `if file_key == getattr(self, '_current_stream_key', '')` 过滤
  - 用户**手动改 file_combo**切换文件时，diff_viewer 的 `_current_key` 变了，但 main_window 的 `_current_stream_key` 没变
  - 后续 stream 来的 token 仍写入**旧文件**的 diff 视图，用户在**新文件**面板上看不到流
- 触发场景：用户处理 3 个文件，第 2 个开始 stream 时用户手动切到第 1 个看结果——后续 stream 还在写第 2 个，但写入按钮被切到第 1 个面板 → 用户以为卡住
- 修复建议：把 `_current_stream_key` 逻辑统一到 diff_viewer 内部；或在 file_combo 切换时同步更新 main_window 的 _current_stream_key。

### 🟡 6.6 切换 prompt 模式时 main_page 与 settings_page 双向同步可能死循环或乱序
- 位置：`app/main_window.py:362-367, 342-347`
- 问题：
  - settings page 改 → `_on_params_changed` → 同步 main_page combo
  - main_page 改 → `_on_main_prompt_mode_changed` → 改 `self.config.custom_prompt`
  - 但 `_on_main_prompt_mode_changed` **直接改 `self.config.custom_prompt`**，没走 `_on_config_changed`/`_on_params_changed`，所以**不触发 debounce 存盘**
  - 用户在 main_page 切了模式但**没保存**（500ms debounce 没触发就关掉应用）
- 评价：低风险但有 bug。

### 🟡 6.7 `stream` 中途网络错误时 `collected` 已有部分内容被丢失
- 位置：`app/processor.py:266-289`
- 问题：stream 中途断开（如 TCP RST）→ `event` 抛 `httpx.ReadError`/`APIConnectionError` → 整个 `_call_api_stream` 抛 → **已 collect 的 token 全丢**，从零重试。
- 触发场景：网络抖动、代理重置。
- 评价：可接受，但理想方案是 partial save（按句子边界存 checkpoint）。

### 🟢 6.8 同一文件由不同 prompt_mode 处理时，无任何 UI 提示
- 同 3.1 的子问题。

---

## 7. Top 3 最严重问题

### 🥇 #1 [严重] 缓存复用不区分 prompt 模式，新配置不生效
- 位置：`app/processor.py:73-76`、`app/utils.py:60-62, 195-204`
- 现象：用户改了 prompt（甚至模型）后，处理"已完成"文件被缓存直接跳过，看起来"新配置无效"。
- 根因：缓存 key 是文件路径 + 完成状态，不含任何业务参数。
- 影响：用户**信任但被欺骗**——是"看似成功但内容没改"的典型 bug。
- 修复优先级：**P0**——影响业务正确性，且用户无感。

### 🥈 #2 [严重] 大文本文件无分块，context 超限必败且重试浪费
- 位置：`app/processor.py:250-259`
- 现象：超过模型 context window 的文件 100% 失败，且 4 次重试浪费 15s。
- 根因：整段文本直接塞进 user message，无 chunking、无预检。
- 影响：核心场景（长文校对）不可用；用户每次都要手动切文件。
- 修复优先级：**P0**——核心功能缺失。

### 🥉 #3 [严重] 异常类型全分类为 `Exception`，不可重试错误被浪费 15s
- 位置：`app/processor.py:196-202`
- 现象：`context_length_exceeded` / `invalid_api_key` / `model_not_found` 这些"重试必死"的错误也会触发 4 次重试。
- 根因：单一 `except Exception` + 统一退避。
- 影响：每次失败体验差（用户要等 15s 看错误），token 被浪费（每次都发送同样请求）。
- 修复优先级：**P1**——影响所有失败场景的体验。

### 关注度次高：进度统计 `completed_files` 含义混乱（6.2）+ 取消后 UI 卡死（4.3）

---

## 8. 修复优先级总结

| 优先级 | ID | 问题 | 位置 |
|---|---|---|---|
| P0 | 3.1 | 缓存不区分 prompt | processor.py:73 / utils.py:62 |
| P0 | 6.1 | 大文本无分块 | processor.py:250 |
| P1 | 1.1 | 异常无分类 | processor.py:196 |
| P1 | 6.2 | completed_files 含失败 | processor.py:181, 219 |
| P1 | 4.1 | 暂停不暂停 stream | processor.py:266 |
| P1 | 4.3 | 取消后 UI 卡死 | processor.py:194 |
| P1 | 2.3 | 导出失败污染收尾 | main_window.py:531 |
| P2 | 1.2 | 退避忽略 Retry-After | processor.py:200 |
| P2 | 1.4 | token_count=0 不警告 | processor.py:169 |
| P2 | 2.1 | 读文件失败 UI 静默 | processor.py:78 |
| P2 | 2.2 | GB18030 兜底掩盖真错 | utils.py:159 |
| P2 | 2.4 | Windows 保留名未过滤 | diff_viewer.py:213 |
| P2 | 3.2 | 缓存损坏静默退回 | utils.py:207 |
| P2 | 3.4 | 缓存无 size 限制 | utils.py:168 |
| P2 | 4.2 | AsyncOpenAI 未关闭 | processor.py:104 |
| P2 | 4.5 | 关闭程序不等线程 | main_window.py:570 |
| P2 | 5.1 | api_key 允许空 | api_config.py:130 |
| P2 | 5.4 | concurrency=0 死锁 | processor.py:122 |
| P3 | 2.5 | 路径规范化/大小写 | input_panel.py:92 |
| P3 | 3.5 | checkpoint 失败不告警 | processor.py:186 |
| P3 | 5.2 | 配置损坏静默 | utils.py:185 |
| P3 | 5.3 | temperature 越界 | utils.py:113 |
| P3 | 6.3 | corrected==original 不区分 | utils.py:60 |
| P3 | 6.5 | stream_key 不一致 | main_window.py:466 |
| P3 | 6.6 | main/settings 同步死循环 | main_window.py:362 |
| P3 | 6.7 | stream 错误丢失 partial | processor.py:266 |

---

## 9. 验证建议

- 单元测试：
  - `test_error_classification`：mock OpenAI 返回 `BadRequestError(context_length_exceeded)`，断言**只调用 1 次**
  - `test_cache_prompt_invalidation`：用 strict 跑过 → 改 polish → 重跑 → 断言第二次**真的被处理**（result 不复用）
  - `test_concurrency_zero`：config.concurrency=0 → 断言启动时 raise
  - `test_export_reserved_name`：task.file_path = `CON.md` → 断言导出成功（rename 为 CON_.md）
  - `test_pause_during_stream`：mock 慢流 → 调 pause() → 断言 200ms 内 stream 关闭
  - `test_cancel_ui_cleanup`：mock 长 stream → 调 cancel() → 断言 `on_file_done` 被触发且 task.status == CANCELLED
  - `test_read_failure_ui`：mock `read_file_text` 抛 PermissionError → 断言 UI 显示"失败"且 stats 含此文件
- 集成验证（手动）：
  - 拖入 1MB 文本 → 触发 context 超限 → 观察重试次数 = 1
  - 跑完后立刻改 prompt 重跑 → 观察所有文件被重新处理
  - 按 Esc 在 stream 中 → 观察文件状态变为"已取消"（灰）而非卡"处理中"
  - 输出目录设为只读 → 观察一个失败不影响其他 + 失败列表
