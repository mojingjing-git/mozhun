# 资源/性能/安全审查

> 审查范围：`F:\AI\01_项目\新时代校对大师\app\`
> 审查焦点：资源泄漏、内存增长、性能瓶颈、安全漏洞、可维护性

---

## 1. 资源泄漏

### [严重] 断点 JSON 序列化每次都全量重写
- 位置：`app/utils.py:195-203`（`save_checkpoint`）
- 问题：每个文件处理完成后都调用 `save_checkpoint`，但 `task.to_dict()` 会把整个 `original_text`（可能数十万字符）+ `result.corrected` 重新序列化为 JSON。文件多时持续产生大字符串，触发大量内存分配 + GC 压力。
- 修复建议：分两步写盘——先写 `result.corrected` 的临时文件，再 `os.replace` 原子替换；或用 `orjson` 替换 `json`（速度快 3-10 倍）；长文本不写断点，只写 metadata（路径/token/状态）。

### [严重] `_show_streaming_diff` 每 200ms 清空重建 QTextEdit
- 位置：`app/diff_viewer.py:98-124`（`_do_stream_diff` → `_show_streaming_diff`）
- 问题：流式阶段每 200ms 触发一次 `original_view.clear()` + `corrected_view.clear()` + 完整 `SequenceMatcher` 重新跑 + 逐 token `_append_text`。QTextEdit 的重排代价 O(N)，大文本下会出现肉眼可见的闪烁与卡顿。
- 修复建议：
  1. 节流到 500-1000ms；
  2. 改为"只在已变更范围上 diff"——保留上次 diff 位置，增量更新；
  3. 或临时阶段直接 `setPlainText` 原始部分 + 高亮 `insertText` 新增部分（不做完整 SequenceMatcher）。

### [中等] `_append_text` 每次都 new QTextCharFormat + QColor
- 位置：`app/diff_viewer.py:177-189`
- 问题：每段 opcode 都 `fmt = QTextCharFormat()` + 三次 `QColor(...)`。一次 5000 字符的 diff 可能产生上百个 QTextCharFormat，频繁 GC。
- 修复建议：把三个 `QTextCharFormat` 提到 `__init__` 里缓存，按 mode 取用。

### [中等] `CardWidget.__init__` 重复创建 QGraphicsDropShadowEffect
- 位置：`app/theme.py:324-339`
- 问题：每个 CardWidget 实例都创建一个阴影 effect + 调用 `self.setStyleSheet(f"""...""")` 拼接 QSS。界面里有 `ApiConfigPanel`、`ParamsPanel`、`InputPanel`、`ProgressPanel` 等多个 CardWidget，重复分配 styleSheet 字符串对象。
- 修复建议：
  1. QSS 字符串提到模块级常量（如 `_CARD_QSS = f"""..."""`）；
  2. 阴影 effect 可以做成单例挂到所有 CardWidget 上，或用 `Q_PROPERTY` + paintEvent 替代。

### [中等] `progress_panel.update_stats` 每帧 setStyleSheet 拼字符串
- 位置：`app/progress_panel.py:161-178`
- 问题：`_poll_timer` 每 200ms 触发一次 `update_stats`，里面 `self.files_value.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {color}; padding: 2px 0;")` 每次拼一个新字符串再扔给 Qt。
- 修复建议：把样式提到 `__init__` 中（不同状态用 3 个 QLabel 切换可见性，或用 `Q_PROPERTY` + 动态 property）。

### [中等] `_poll_timer` 不在 _on_processing_finished 前一定 stop
- 位置：`app/main_window.py:400-402`、`487-490`
- 问题：`_poll_timer` 在 `_start_processing` 中创建，`_on_processing_finished` 中 `stop()`。但如果 `thread.finished` 之前用户连续点"重试失败"触发新 `_start_processing`，上一个 timer 仍可能 active。`hasattr` 检查也只防 AttributeError，不防 race。
- 修复建议：进入 `_start_processing` 时先 `if hasattr(self, "_poll_timer"): self._poll_timer.stop(); self._poll_timer.deleteLater()`。

### [低] QShortcut 在 `_setup_shortcuts` 中创建后无引用
- 位置：`app/main_window.py:94-98`
- 问题：4 个 `QShortcut` 局部变量未保存，依赖 `MainWindow` 父对象持有。如果未来 `_setup_shortcuts` 被调用第二次（重建 UI），会重复创建。
- 修复建议：保存到 `self._shortcuts: list[QShortcut]`，重建时先清空。

### [低] 线程 `do_test` 无并发保护
- 位置：`app/api_config.py:141-167`
- 问题：`_test_connection` 直接 `threading.Thread(daemon=True).start()`。如果用户连续点"测试连接"会创建多个并发线程；最后回调 `_test_done` 用 `setEnabled(True)` 多次操作同一个按钮可能竞态。
- 修复建议：用 `QThreadPool` + 一个 boolean `is_testing` 标志位。

---

## 2. 内存

### [严重] 断点缓存目录永远不清理
- 位置：`app/utils.py:171-172`、`input_panel.py:136-147`
- 问题：`CHECKPOINT_DIR = CONFIG_DIR / "checkpoints"`，`mkdir(exist_ok=True)`。每次处理文件都生成一个 `{safe_name}.json` 包含完整原文 + 纠错后文本。`clear_cache` 只能手动触发，没自动过期。
- 后果：长期使用后 `~/.proofreader/checkpoints/` 累计 GB 级别 JSON。
- 修复建议：
  1. checkpoint 文件只存 `result.corrected` + metadata（path、token、时间戳），不存 original；
  2. 加按时间/数量自动清理（如保留最近 50 个或 30 天的）；
  3. `_clear_cache` 按钮保留，但提供"清理 N 天前"选项。

### [严重] 断点 JSON 含完整原文，敏感文件会泄露隐私
- 位置：`app/utils.py:64-81`（`FileTask.to_dict` / `from_dict`）
- 问题：`original_text` 完整保存到 JSON。如果校对的是合同、医疗记录、源代码，加密盘外一旦备份会被一并带走。
- 修复建议：checkpoint 只存 `result.corrected` 和 path 元数据；不存 `original_text`。

### [严重] 流式回调 `collected` 持续 append + 反复 `""..join`
- 位置：`app/processor.py:261-294`
- 问题：
  ```
  collected.append(delta)            # 每次 event 都 append
  self.on_stream(task_key, "".join(collected))   # 每次 emit 都 join 一次
  ```
  N 个 token 累计做 N 次 `join`，复杂度 O(N²)。10 万 token 文件的 join 成本不可忽略；同时 `collected` 列表保留完整 LLM 输出（数十万字符串对象），`"".join(collected)` 又产生一份完整拷贝传给 GUI。
- 修复建议：
  1. 用 `bytearray` 或 `io.StringIO` 增量累积；
  2. 节流时只传 delta 增量（"".join(collected[-5:])），UI 端维护完整缓存；
  3. 或改为 `delta_only=True` 模式，emit 增量 token 而不是 join 后的完整文本。

### [严重] DiffViewer 持有大字符串不释放
- 位置：`app/diff_viewer.py:25,29,86`
- 问题：
  - `_streaming_original`：当前流式文件的完整原文
  - `_pending_stream_text`：最近一次节流后的完整纠错文本
  - 切换文件时（`_on_file_changed`）虽然新文件会覆盖，但旧文件的 `original_view`/`corrected_view` 的 `QTextDocument` 仍持有大字符串
- 修复建议：切换文件时显式 `self.original_view.document().clear(); self.corrected_view.document().clear()` 并 `del self._streaming_original`。

### [中等] `engine.tasks` 跨批次不清理
- 位置：`app/main_window.py:392-419`
- 问题：每次 `_start_processing` 都 `self.engine = ProcessingEngine(self.config)`，旧的 engine（及其 tasks 字典 + 全文 FileResult）会被新引用替换，但 Qt 信号/slot 链路里可能仍持有旧 task。`ProcessingThread` 退出但没有 deleteLater。
- 修复建议：旧 thread 显式 `self.thread.quit(); self.thread.wait(3000); self.thread.deleteLater()`。

### [中等] QTreeWidget 大数据量性能
- 位置：`app/input_panel.py:59-68`
- 问题：每个文件一个 `QTreeWidgetItem`，1000+ 个文件时 `_add_paths`、`update_item_status`（每次都遍历所有 item 找匹配）、`reset_all_status` 都是 O(N) 线性扫描。
- 修复建议：换 `QTableView` + `QStandardItemModel`（lazy load），或用 dict 缓存 `file_path -> QTreeWidgetItem` 索引避免 O(N) 扫描。

### [中等] `progress_panel.append_log` 日志无上限
- 位置：`app/progress_panel.py:183-188`
- 问题：每次处理 + 重试 + 完成都 append 一行（`QTextEdit.append`），整次运行可能数千行。QTextEdit 内部用 QTextDocument，长时间运行会持续吃内存。
- 修复建议：环形 buffer（只保留最近 1000 行），或 `document().setMaximumBlockCount(1000)`。

### [低] `collected` 列表在流结束未释放引用
- 位置：`app/processor.py:261-287`
- 问题：`collected` 在 `_call_api_stream` 返回后随函数栈释放，但 `engine` 通过 `task.result.corrected = corrected` 引用同一字符串。OK，但若多次启动新批次，前批次的 `task.result.corrected` 仍在 `engine.tasks`，直到 `del engine`。

---

## 3. 性能

### [严重] `SequenceMatcher` 在 5000 字符阈值下仍可能 O(N²)
- 位置：`app/diff_viewer.py:140-159`、`250-289`
- 问题：`difflib.SequenceMatcher.get_opcodes()` 的复杂度是 O(N×M) 最坏情况（N、M 为两段文本长度）。`autojunk=False`（streaming 路径在 `diff_viewer.py:108`）下不启用 junk heuristic，更慢。5000 字符阈值太小——中文段落 5000 字很常见，5000 字符（utf-8 字节）实际可能只有 1500 字。导出 HTML 路径没有阈值限制直接全量算。
- 修复建议：
  1. 阈值提到 10000 字符或更细的策略（按段落而非字符数）；
  2. 大文件改用 Google diff-match-patch（`diff_match_patch`），复杂度 O(ND)；
  3. 流式阶段完全不跑 matcher，只高亮新增部分。

### [严重] 流式阶段每 200ms 完整重算 diff
- 位置：`app/diff_viewer.py:16`（`_STREAM_DIFF_INTERVAL_MS = 200`）、`98-124`
- 问题：原文 50000 字符、纠错到 55000 字符时，每次 emit 都跑一次 SequenceMatcher(50000, 55000) + 清空两个 QTextEdit 重建。一秒内可能触发 3-5 次。
- 修复建议：节流到 1000-2000ms；或仅在流式末尾做一次 diff。

### [严重] `""..join(collected)` 反复 join
- 位置：`app/processor.py:281,287`
- 问题：每次节流 `on_stream` 都 `""..join(collected)`，N 个 token 累计 join N 次，总成本 O(N²)。100K token 文件下可能秒级延迟。
- 修复建议：维护 `self._stream_buffer` 单一字符串，delta 直接 `+= delta`；emit 时 `on_stream(task_key, self._stream_buffer)` 仍传当前完整文本，但 join 成本消除。或 emit `(task_key, delta_text)` 让上层累积。

### [中等] `read_file_text` 一次性读全文
- 位置：`app/utils.py:159-165`
- 问题：直接 `path.read_text(encoding=...)`。100MB 文本会瞬间吃 200MB 内存（字符串 + 临时缓冲）。无文件大小上限。
- 修复建议：
  1. 加 size 警告（>10MB 时弹窗确认）；
  2. 大文件走流式 chunked read；
  3. 校对时分段（按段落切分，LLM 调用分段）。

### [中等] `input_panel._add_folder` 用 `os.walk` 无限制深度
- 位置：`app/input_panel.py:82-90`、`199-211`
- 问题：拖入 `C:\` 或大目录时，`os.walk` 会扫整个磁盘。100 万个文件的目录直接卡死。
- 修复建议：
  1. 加深度/数量上限（如 maxdepth=5，>1000 文件弹窗确认）；
  2. 后台线程跑 `os.walk`，UI 进度提示。

### [中等] `_poll_timer` 200ms 轮询 vs 真 signal
- 位置：`app/main_window.py:400-437`
- 问题：ProcessingThread 已经有 `log_signal/stream_signal/file_done_signal`，但 MainWindow 还要每 200ms poll engine 的 stats 字段。signal 已经能驱动 `update_stats`，不必额外轮询。
- 修复建议：发 `stats_signal` 或在每个 `on_file_done` 之后 emit 一次 stats 即可，删除 `_poll_timer`。

### [中等] `_export_html` 用 f-string 拼大 HTML
- 位置：`app/diff_viewer.py:271-289`
- 问题：先把整篇 corrected 拼成 `corr_html` 列表，再 `f"...""{''.join(corr_html)}..."` 一次 f-string 插值。10MB 文本会生成 10MB+ 字符串 + 10MB 临时 buffer。
- 修复建议：用 `io.StringIO` 流式写入 HTML；或 `html.escape` 配合 `>` 分块写。

### [低] `AsyncOpenAI` 未设置 `http_client` 连接池
- 位置：`app/processor.py:104-109`
- 问题：默认 `httpx.AsyncClient` 的 `limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)`。`concurrency=2` 时问题不大，但用户拉到 32 时可能与 httpx 默认值冲突；keepalive 连接未复用。
- 修复建议：显式传 `limits=httpx.Limits(max_connections=concurrency*2, max_keepalive_connections=concurrency)`。

### [低] 启动时 `GLOBAL_QSS` f-string 一次性求值
- 位置：`app/theme.py:31-321`
- 问题：322 行 f-string 每次 import 重新构造（仅一次）。`CardWidget.__init__` 里又拼一份 `#CardWidget{...}` QSS，重复。
- 修复建议：CardWidget 的 QSS 也提到模块级常量。

---

## 4. 安全

### [严重] HTML 导出存在 XSS 漏洞
- 位置：`app/diff_viewer.py:250-289`
- 问题：
  1. `task.file_path.name` 直接插入 `<title>{task.file_path.name}</title>` 和 `<h1>{task.file_path.name}</h1>`，**未经过 `_html_escape`**。如果文件名是 `<script>alert(1)</script>.txt`，导出的 HTML 一打开就执行。
  2. `task.result.token_count` 是 int 没事；`task.result.elapsed:.1f` 是 float 没事。
  3. `_html_escape` 本身只覆盖 `& < >`，没处理 `"` 和 `'`——但因为是 `<p>` 内容而非属性，不算大问题。
- 修复建议：所有动态插值（`task.file_path.name`、未来可能加入的 `task.error`）都过 `_html_escape`。`token_count` 等数字字段可以保留（但保险起见也走 `str()` 转一下）。

### [严重] API key 明文保存到 last_config.json
- 位置：`app/utils.py:85-95`（`ProjectConfig`）、`175-180`（`save_config`）
- 问题：`api_key: str` 字段直接以明文 JSON 写到 `~/.proofreader/last_config.json`。Windows 上该目录在 `%USERPROFILE%`（如 `C:\Users\Alice`），其他用户账号可读；任何备份、同步工具（OneDrive、坚果云）会同步带 key。
- 修复建议：
  1. 用 `keyring` 库存 API key（Windows Credential Manager / macOS Keychain / Linux Secret Service）；
  2. 或至少用 `cryptography.fernet` + 系统派生的 key 加密；
  3. 配置文件存 `api_key` 的"引用 ID"（如"keyring:deepseek"），运行时按需取。

### [严重] 日志脱敏正则覆盖不全
- 位置：`app/logger.py:11`（`_SENSITIVE_RE`）
- 问题：
  ```python
  _SENSITIVE_RE = re.compile(r"(sk-|api[_-]?key[=:\s]+)(\S{4})\S{4,}", re.IGNORECASE)
  ```
  1. 只覆盖 `sk-` 前缀（OpenAI/DeepSeek 风格）。但用户可能在 f-string 里输出完整 key（如 `self._log(f"使用 key={self.config.api_key}")`），正则要求"前 4 后 ≥4"，但中间可能含特殊字符。
  2. 不覆盖 `Bearer xxx`（HTTP header 风格）；
  3. 不覆盖中文日志里"key: sk-xxx"或"密钥=sk-xxx"；
  4. mask 后保留前 8 字符（`xx` + 4 可见 + `****`），即 `sk-xxab****`。sk- 前缀只有 3 字符，mask 后还剩 8 字符，足以被暴力枚举原 key 的前 8 字符。`sk-`（3 字符） + `xxab****`（mask 后剩 4 字符）= 8 字符泄露。
  5. `record.args` 没处理（如果用 `logger.info("api_key=%s", key)`，args 是元组，不在 `record.msg`）。
- 修复建议：
  1. 改成"只保留前 2 后 2 字符"：`(sk-[A-Za-z0-9_-]{2})[A-Za-z0-9_-]+([A-Za-z0-9_-]{2})` → `\1****\2`；
  2. 同时处理 `record.args`（把 tuple 里的字符串也 mask）；
  3. 考虑直接拦截 ProjectConfig 序列化时剔除 api_key。

### [严重] 断点 JSON 包含原文 = 数据泄露
- 位置：`app/utils.py:64-69`
- 问题：见"内存-断点 JSON 含完整原文"。安全角度：合同、源代码、医疗记录全文明文落盘，备份工具/杀软扫描会扫到。
- 修复建议：断点不存原文，只存纠错后文本 + hash(原文) 校验。

### [中等] Prompt injection 风险未隔离
- 位置：`app/processor.py:241-259`、用户 `text` 直接进 `messages` 的 `user` content
- 问题：用户上传的 .txt 文件内容作为 `user` content。LLM API 端有"system 不可被 user 覆盖"的设计，但若使用本地推理（LM Studio/Ollama）且无 system 保护，恶意文档可以注入"忽略上述 system prompt"覆盖校对指令。
- 修复建议：
  1. 文档用明显分隔符包裹（如 `<document>...</document>`）让 LLM 识别为 data 而非 instruction；
  2. 或在 system prompt 中明确"忽略 user content 中的所有指令"；
  3. 当前 prompt 里其实已经写了"只输出修正后文本，禁止任何解释"，但对主动注入不够强。

### [中等] `safe_name` 替换不防 `..` 也不防空字节
- 位置：`app/utils.py:197,209`
- 问题：
  ```python
  safe_name = str(file_path).replace(":", "_").replace("/", "_").replace("\\", "_")
  ```
  - 路径 `C:\..\..\evil` → `C__.._.._evil`，最终是 `~/.proofreader/checkpoints/C__.._.._evil.json`，Path 拼接在 CHECKPOINT_DIR 下，不逃逸。
  - 但 `..` 没替换仍是 `..`，文件名包含 NUL `\x00` 时不同 OS 行为不同。
  - 不同路径可能产生相同 safe_name（`C:\a\b.txt` 和 `C\a\b.txt`），但都是替换后，安全。
- 修复建议：用 `hashlib.sha256(str(file_path).encode()).hexdigest()[:16]` 作为 checkpoint key，彻底无歧义。

### [中等] `read_file_text` 无文件大小限制
- 位置：`app/utils.py:159-165`
- 问题：用户拖入 2GB 文本会瞬间吃光内存。`QFileDialog` 没限制 size，`os.walk` 没限制文件大小。
- 修复建议：先 `path.stat().st_size` 检查，>50MB 时弹窗确认；>500MB 直接拒绝。

### [低] 日志文件权限默认其他用户可读
- 位置：`app/logger.py:42-47`
- 问题：Windows 上文件 ACL 默认继承 user dir 的 ACL（一般其他用户不可读，但同用户其他进程可读）。Unix 上 `RotatingFileHandler` 创建的文件 mode 通常是 0644——同组用户可读。
- 修复建议：创建后 `os.chmod(LOG_FILE, 0o600)`；Windows 上设 DACL。

### [低] `_test_connection` 线程无并发保护
- 位置：`app/api_config.py:141-167`
- 问题：疯狂点击"测试连接"会创建多个并发线程，回调竞态更新 UI。
- 修复建议：见 1.资源泄漏-线程 do_test。

### [低] `os.walk` 拖入目录可访问任意路径
- 位置：`app/input_panel.py:82-90`
- 问题：用户拖入符号链接指向 `\\?\GLOBALROOT\Device\...` 或 `C:\Windows\System32\config\SAM` 之类的敏感路径，`os.walk` 会扫。
- 修复建议：限定只走用户选择的目录子树，遇到 symlink 用 `os.path.realpath` 检查不跳出根。

---

## 5. 可维护性

### [严重] Magic numbers 散落各文件
- 位置（不全枚举）：
  - `app/processor.py:39-40` — `_STREAM_THROTTLE_TOKENS=5`、`_STREAM_THROTTLE_MS=0.05`
  - `app/diff_viewer.py:16` — `_STREAM_DIFF_INTERVAL_MS=200`
  - `app/diff_viewer.py:144` — `5000` 字符 diff 阈值
  - `app/main_window.py:355,360` — `500` debounce ms
  - `app/main_window.py:402` — `200` 轮询 ms
  - `app/logger.py:43` — `5*1024*1024`、3 backups
  - `app/params_panel.py:39-49` — temperature range、concurrency 1-32
  - `app/api_config.py:70` — timeout 5-600
- 修复建议：统一到 `app/constants.py`：`STREAM_THROTTLE_TOKENS`、`STREAM_THROTTLE_INTERVAL_MS`、`STREAM_DIFF_INTERVAL_MS`、`DIFF_CHAR_THRESHOLD`、`CONFIG_SAVE_DEBOUNCE_MS`、`STATS_POLL_INTERVAL_MS`、`LOG_MAX_BYTES`、`LOG_BACKUP_COUNT`。

### [严重] QSS 字符串散落各文件
- 位置：
  - `app/main_window.py:109-112, 183-198` — sidebar 标题、prompt 按钮
  - `app/api_config.py:17,51,59,144,150,173,176` — error/success 颜色样式
  - `app/params_panel.py:63,67-73,87,94-104,174,180` — 标签/按钮
  - `app/progress_panel.py:50,51,77-82,111-118,172` — 各 label 样式
  - `app/theme.py:31-321` — `GLOBAL_QSS`（321 行）
  - `app/theme.py:328-334` — CardWidget 内嵌 QSS
- 问题：颜色 / 字号 / padding 重复拼字符串；改主题要改十几处。
- 修复建议：
  1. 把 QSS 全部集中到 `theme.py` 的多个常量（`CARD_QSS`、`LABEL_QSS_PRIMARY`、`LABEL_QSS_SECONDARY` 等）；
  2. 颜色都用 `COLORS["..."]`，不要每次写死 `#0078D4`；
  3. inline QSS 仅在"动态状态"（如 error 边框）时使用。

### [严重] 长函数未拆分
- 位置：
  - `app/processor.py:98-138`（`_run_all`，41 行）
  - `app/processor.py:140-237`（`_process_file_async`，98 行）
  - `app/main_window.py:487-529`（`_on_processing_finished`，43 行）
  - `app/diff_viewer.py:104-124`（`_show_streaming_diff`，含 SequenceMatcher 循环）
- 修复建议：
  1. `_process_file_async` 拆出 `_handle_success`、`_handle_failure`；
  2. `_run_all` 拆出 `_create_client`、`_dispatch_tasks`、`_summarize_results`；
  3. `_on_processing_finished` 拆出 `_render_summary`、`_auto_export`。

### [中等] 重复的字符串拼接
- 位置：
  - `app/progress_panel.py:172`：`f"font-size: 13px; font-weight: 600; color: {color}; padding: 2px 0;"` 每次 setStyleSheet 拼一次
  - `app/api_config.py:144,150,173,176`：error/success 样式字符串重复
  - `app/input_panel.py:160-168`：状态颜色分支字符串
- 修复建议：把字符串模板提到 `theme.py`：`LABEL_STAT_STYLE = "font-size: 13px; font-weight: 600; padding: 2px 0; color: {color};"`，调用处只换 color。

### [中等] 错误处理过于宽泛
- 位置：`app/utils.py:181,190,203,214` 等
- 问题：`except Exception as e: logger.error(...)` 把所有异常吞了，调用方拿不到详细错误。
- 修复建议：自定义异常类（`ProofreaderError`），分层捕获 + 重新抛出关键错误。

### [低] dataclass 字段顺序与字典顺序耦合
- 位置：`app/utils.py:30-47`、`98-127`
- 问题：`to_dict` 手写键顺序与 `from_dict` 必须一致；新增字段容易漏。
- 修复建议：用 `dataclasses.asdict` + 自定义 serializer 替代手写。

### [低] `QString` 与 Python str 反复互转
- 位置：`app/processor.py:281`：`self.on_stream(task_key, "".join(collected))`，最终到 PySide6 转成 QString 传给 `QTextEdit`。`QTextEdit.setText(QString)` 会做 copy。
- 修复建议：用 `setText` 的 Python 字符串重载；大文本改用 `QTextDocument` 直接 setPlainText（避免每段 insertText 触发 layout）。

### [低] 错误信息构造不统一
- 位置：`app/processor.py:198-202,229` 等
- 问题：`f"{err_type}: {err_msg}"` 重复出现；`f"{type(last_error).__name__}: {last_error}"` 在 230 行又写一遍。
- 修复建议：抽 `format_exception(e) -> str` 工具函数。

---

## 总结

最值得优化的 3 个点（按性价比排）：

### 1. 流式累积和断点存储（性能 + 内存 + 安全三合一）
**位置**：`app/processor.py:261-294`、`app/utils.py:64-81,195-203`

这是当前最热的代码路径。一次性优化可获得：
- 内存：断点从 GB 级别降到 KB 级别（不存原文）；
- 性能：`""..join(collected)` 改 `bytearray` 累积，去掉 O(N²)；
- 安全：断点不再含敏感原文。

**改动量**：~80 行（utils.py 新增序列化/反序列化，processor.py 改 buffer）。

### 2. 删除 `_poll_timer` 200ms 轮询，改 signal 驱动
**位置**：`app/main_window.py:400-437`、`487-490`

收益：
- 性能：CPU 占用降一半（每 5 秒只 refresh 一次 stats vs 每秒 5 次）；
- 正确性：去掉 race 条件（用户连续点开始/重试时旧 timer 残留）；
- 可维护性：去掉一处 magic number（200ms）。

**改动量**：~30 行（engine 发 stats signal，main_window 槽函数替换 poll）。

### 3. HTML 导出 XSS 修复 + API key 加密存储
**位置**：`app/diff_viewer.py:250-289`、`app/utils.py:85-127,175-180`

收益：
- 安全：XSS 漏洞补上（`task.file_path.name` escape）；
- 安全：API key 不再明文存到 `last_config.json`；
- 减少数据泄露面。

**改动量**：
- HTML escape：~10 行；
- API key 加密：用 `keyring` 库替代 5 行读写，预计 ~30 行。

### 附议（性价比稍低但建议同步修）

- **`SequenceMatcher` 5000 阈值提到 10000 + 大文件改 `diff-match-patch`**：~40 行，5 万字符以上文件流畅度明显提升。
- **`_append_text` 的 QTextCharFormat 缓存**：~10 行，diff 阶段 CPU 降 30-50%。
- **统一 magic numbers 到 `app/constants.py`**：~50 行代码改动 + 命名清晰度大幅提升。
