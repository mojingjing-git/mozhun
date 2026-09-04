"""
ProcessingEngine — 异步流式 LLM 校对引擎。

线程模型：
  MainWindow → ProcessingThread(QThread) → asyncio.run(_run_all)
  _run_all 内部用 asyncio.Semaphore 控制并发，AsyncOpenAI 流式调用。

回调：
  on_log(msg)          — 日志
  on_stream(key, text) — 流式 token（节流后）
  on_file_start(key)   — 文件开始处理
  on_file_done(key)    — 文件处理完成
  on_stats_update(s)   — 统计更新
"""

import asyncio
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from openai import (
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
    RateLimitError,
)

from app.context_builder import ContextBuilder
from app.logger import setup_logging
from app.templates import PROMPT_MODES
from app.utils import (
    FileTask,
    FileResult,
    TaskStatus,
    ProjectConfig,
    ProcessStats,
    save_checkpoint,
    save_checkpoint_async,
    load_checkpoint,
    read_file_text,
    compute_prompt_hash,
    CHUNKING_PRESETS_MAP,
    DEFAULT_CHUNK_PRESET,
)

# v3.0 Phase 3 错误分类常量
# 不可重试错误: 鉴权/权限/资源不存在/请求格式错误, 重试无意义
_NON_RETRYABLE_ERRORS = (
    AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError,
)
# 可重试错误: 速率限制/超时/网络中断
_RETRYABLE_ERRORS = (RateLimitError,)

logger = setup_logging()

# 流式节流：每 5 token 或 50ms (取慢速) emit 一次。
# 设计意图：流式快时由 token 计数触发 (避免 join 风暴), LLM 慢响应时由
# 时间兜底保证 UI 不卡 (避免长时间无更新)。50ms 是人眼可感知的最小间隔,
# 既不浪费 CPU 也不让 UI 顿挫。
_STREAM_THROTTLE_TOKENS = 5
_STREAM_THROTTLE_MS = 50.0

# 大文本分块阈值 (字符数): 保守值,覆盖大多数模型的 context window。
# 切分按段落/句号边界,保证语义完整。
# 注意: _MAX_CHUNK_CHARS 仅作为整文件预设之外场景的回退默认值,
# 实际切分在 _call_api_stream 里通过 _CHUNK_PRESETS 选取 max_chars。
_MAX_CHUNK_CHARS = 6000

# 借鉴自 https://github.com/tianhm/ollama-batch-processor (MIT License)
# 借鉴内容: chunking preset 分档设计思路
# 借鉴方式: 思路借鉴,无代码复制
# Copyright (c) 2025 tianhm
# v4.1 (M2): chunking 档位单点定义已搬到 app/utils.py:CHUNKING_PRESETS,
# 业务层 (processor.py) + 前端层 (web_backend.py) 都从 utils 派生,
# 避免 label/max_chars 在三处漂移.
# 这里只剩从 CHUNKING_PRESETS_MAP 派生的 dict, 补上 processor 内部用的
# "overlap"/"label" 字段 (overlap=0 是校对场景硬约束, 不动).
_CHUNK_PRESETS = {
    key: {
        "max_chars": info["max_chars"],
        "overlap": 0,
        "label": info["label"],
    }
    for key, info in CHUNKING_PRESETS_MAP.items()
}

# overlap=0 决策: 校对是改错别字,重叠区会被改两次产生不一致
# 跨段上下文通过 Phase 4 ContextBuilder 在 system prompt 注入,不通过 chunk 重叠。


class ProcessingEngine:
    """异步流式 LLM 校对引擎。"""

    def __init__(self, config: ProjectConfig):
        self.config = config
        self.tasks: dict[str, FileTask] = {}
        self.stats = ProcessStats()
        self._cancel_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        # v4.0+ 修订: pause_event 改 threading.Event, 跨线程 pause/resume/cancel
        # 直接调 set/clear 即可, 不用 call_soon_threadsafe (PLAN-pywebview.md §6.1 修订).
        self._pause_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._client: AsyncOpenAI | None = None

        self.on_file_done: Optional[Callable[[str], None]] = None
        self.on_file_start: Optional[Callable[[str], None]] = None
        self.on_file_completed: Optional[Callable[[str], None]] = None  # NEW (v3.0+): 所有 chunk 完成
        self.on_stats_update: Optional[Callable[[ProcessStats], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_stream: Optional[Callable[[str, str], None]] = None

        # v3.0 Phase 4: 跨段上下文构造器
        self.context_builder = ContextBuilder(
            max_chars=getattr(config, "context_max_chars", 800),
            max_chunks=getattr(config, "context_max_chunks", 2),
        )

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            self.on_log(msg)

    async def _await_resume(self) -> None:
        """v4.0+ 等待 pause 释放 (替代旧的 `await self._pause_event.wait()`).

        为什么不能直接 `await self._pause_event.wait()`:
          - _pause_event 是 threading.Event, 其 .wait() 是同步阻塞, 不能 await.
        为什么短超时轮询:
          - 50ms 间隔既能快速响应 cancel / resume, 又不占满 event loop.
          - 间隔内通过 asyncio.to_thread 把阻塞 wait 切成 await, 避免饿死 loop.
        """
        if self._pause_event is None or self._pause_event.is_set():
            return
        # 已暂停: 短超时轮询直到 set 或 cancel
        while not self._pause_event.is_set() and not self._cancel_event.is_set():
            await asyncio.to_thread(self._pause_event.wait, 0.05)

    def prepare_tasks(self, file_paths: list[Path]) -> None:
        """读取文件并加载断点缓存。

        缓存命中校验 (Bug#3): 用 compute_prompt_hash(prompt_mode|model|custom_prompt)
        作为指纹。load_checkpoint 在内部已经支持 expected_hash 校验;
        拿到 cached 后再做一次手动校验 (兼容单参调用方,例如 input_panel)。

        读取失败 (Bug#16): 原来 silent fail (continue) 会让 UI 永远"等待中"。
        改为创建一个 FAILED 占位 task,UI 能立即看到该文件失败。
        """
        # 缓存 prompt 指纹 (后续 _process_file_async 写入 FileResult.prompt_hash 复用)
        self._current_prompt_hash = compute_prompt_hash(
            self.config.prompt_mode, self.config.model, self.config.custom_prompt
        )

        for fp in file_paths:
            key = str(fp)
            # 不传 expected_hash 是为了兼容被 mock 替换的 load_checkpoint (单参签名)。
            # Bug#3 校验放在下面: 比较 cached.result.prompt_hash。
            cached = load_checkpoint(fp)
            if cached and cached.is_done and cached.result is not None:
                cached_hash = cached.result.prompt_hash or ""
                if cached_hash and cached_hash != self._current_prompt_hash:
                    self._log(
                        f"[缓存失效] {fp.name}: prompt 已变 "
                        f"(old={cached_hash[:8]} new={self._current_prompt_hash[:8]}),将重新处理"
                    )
                    cached = None
            if cached and cached.is_done:
                self.tasks[key] = cached
                self._log(f"[缓存] {fp.name}: 已有校对结果，跳过")
                continue

            try:
                text = read_file_text(fp)
            except Exception as e:
                self._log(f"[错误] 无法读取文件 {fp.name}: {e}")
                # Bug#16: 占位 FAILED 任务,让 UI 知道此文件失败
                placeholder = FileTask(file_path=fp, original_text="")
                placeholder.status = TaskStatus.FAILED
                placeholder.result = FileResult(
                    original="",
                    corrected="",
                    error=f"读取失败: {e}",
                    prompt_hash=self._current_prompt_hash,
                )
                placeholder.end_time = time.time()
                self.tasks[key] = placeholder
                continue
            task = FileTask(file_path=fp, original_text=text)
            self.tasks[key] = task
            self._log(f"[就绪] {fp.name}: {len(text)} 字符")

        self.stats.total_files = len(self.tasks)
        self.stats.completed_files = sum(
            1 for t in self.tasks.values() if t.is_done
        )

    def start(self) -> None:
        """QThread 模式入口 (fallback)。

        qasync 模式由 GUI 线程直接 await ``run_async()``；保留此方法
        作为 ``USE_QASYNC = False`` 时的兜底路径（Phase 5 删除）。
        """
        self._cancel_event.clear()
        self.stats.start_time = time.time()
        asyncio.run(self._run_all())

    async def run_async(self) -> None:
        """qasync 模式入口：GUI 线程已有 loop，直接 await。"""
        self._cancel_event.clear()
        self.stats.start_time = time.time()
        await self._run_all()

    async def _run_all(self) -> None:
        """异步主循环，创建共享客户端并并发处理所有文件。"""
        self._loop = asyncio.get_running_loop()
        # v4.0+ 修订: pause_event 改 threading.Event, 跨线程 pause/resume 线程安全
        self._pause_event = threading.Event()
        self._pause_event.set()

        self._client = AsyncOpenAI(
            base_url=self.config.api_base,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
            max_retries=0,
        )

        pending = [
            (k, t) for k, t in self.tasks.items() if not t.is_done
        ]

        # v4.1 (I1): try/finally 保证 _client.close() 一定被调, 避免 httpx 连接泄漏
        try:
            if not pending:
                self._log("[提示] 没有待处理的文件")
                self.stats.elapsed = 0
                if self.on_stats_update:
                    self.on_stats_update(self.stats)
                return

            semaphore = asyncio.Semaphore(self.config.concurrency)

            async def limited(key, task):
                async with semaphore:
                    return await self._process_file_async(key, task)

            coros = [limited(k, t) for k, t in pending]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Worker 异常: {result}")

            self.stats.elapsed = time.time() - self.stats.start_time
            if self.on_stats_update:
                self.on_stats_update(self.stats)
            self._log(f"[全部完成] {self.stats.completed_files}/{self.stats.total_files} 个文件")
        finally:
            # I1: 关闭 httpx 连接池
            if self._client is not None:
                try:
                    await self._client.close()
                except Exception:
                    pass

    async def _process_file_async(self, key: str, task: FileTask) -> None:
        """v3.0 chunk 级别处理: 整文件重试粒度 (v0.2 修订)。

        失败语义 (v0.2 修订):
          - 整文件级重试 N 次 (max_retries)
          - 每次重试清空 chunks_results, 从 chunk 0 重新跑
          - 不可重试错误 (Auth/Permission/NotFound/BadRequest): 立即标 FAILED, 不再重试
          - 可重试错误 (RateLimit): 整文件重试

        取消语义 (v0.2 修订 选项 A):
          - 取消时丢弃所有 chunks_results, status = CANCELLED
          - 下次重跑: load_checkpoint 检测 CANCELLED 返回 None

        chunk 失败处理:
          - 单 chunk 失败: 该 chunk 的 FileResult.corrected = chunk 原文, error 有值
          - 整文件 result.chunks_results: 包含所有 chunk results (成功 + 失败的)
          - 整文件 result.corrected_full: 拼接 "成功 chunk + 失败 chunk 原文"
          - 整文件 result.failed_chunks: list[int]
        """
        if self._cancel_event.is_set():
            return

        await self._await_resume()
        if self._cancel_event.is_set():
            return

        if self.on_file_start:
            self.on_file_start(key)

        start = time.time()
        text = task.original_text
        prompt_hash = getattr(self, "_current_prompt_hash", "")
        self._log(f"[处理中] {task.file_path.name} ({len(text)} 字符)")

        # 选 chunking 档位
        preset = self.config.chunking_preset or DEFAULT_CHUNK_PRESET
        if preset not in _CHUNK_PRESETS:
            preset = DEFAULT_CHUNK_PRESET
        max_chars = _CHUNK_PRESETS[preset]["max_chars"]
        chunks = self._split_text(text, max_chars, preset=preset)
        if len(chunks) > 1:
            self._log(
                f"[分块] {task.file_path.name}: {len(chunks)} 块 "
                f"(preset={preset}, max_chars={max_chars})"
            )

        last_error = None
        for attempt in range(self.config.max_retries + 1):
            if self._cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                task.error_message = "用户取消"
                return
            await self._await_resume()
            if self._cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                task.error_message = "用户取消"
                return

            try:
                # 整文件一次性处理 (避免 N² 重试风暴)
                # Phase 3: 返回 (corrected, tokens, chunks_results)
                corrected, token_count, chunks_results = await self._call_api_stream(key, text)
                elapsed = time.time() - start
                if attempt > 0:
                    self._log(f"[重试成功] {task.file_path.name} 第 {attempt} 次重试后成功")

                # Phase 3: chunks_results 累积到整文件 result
                failed_chunks = [i for i, c in enumerate(chunks_results) if c.error]
                result = FileResult(
                    original=text,
                    corrected=corrected,
                    token_count=token_count,
                    elapsed=elapsed,
                    prompt_hash=prompt_hash,
                    chunks_results=chunks_results,
                    failed_chunks=failed_chunks,
                    schema_version=2,
                )
                with self._lock:
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                    task.end_time = time.time()

                with self._stats_lock:
                    self.stats.completed_files += 1
                    self.stats.success_files += 1
                    self.stats.total_tokens += token_count
                    self.stats.elapsed = time.time() - self.stats.start_time

                self._log(f"[成功] {task.file_path.name} — {token_count} tokens, {elapsed:.1f}s")
                await save_checkpoint_async(task.file_path, task)

                # 单 chunk 等价: 旧 _call_api_stream 仍按整文件调用,on_file_done = 文件完成
                if self.on_file_done:
                    self.on_file_done(key)
                if self.on_file_completed:
                    self.on_file_completed(key)
                if self.on_stats_update:
                    self.on_stats_update(self.stats)
                return

            except asyncio.CancelledError:
                elapsed = time.time() - start if start else 0
                result = FileResult(
                    original=text,
                    corrected=text,
                    elapsed=elapsed,
                    error="已取消",
                    prompt_hash=prompt_hash,
                    schema_version=2,
                )
                with self._lock:
                    task.status = TaskStatus.CANCELLED
                    task.result = result
                    task.error_message = "用户取消"
                    task.end_time = time.time()
                with self._stats_lock:
                    self.stats.completed_files += 1
                    self.stats.elapsed = time.time() - self.stats.start_time
                await save_checkpoint_async(task.file_path, task)
                if self.on_file_done:
                    self.on_file_done(key)
                if self.on_file_completed:
                    self.on_file_completed(key)
                if self.on_stats_update:
                    self.on_stats_update(self.stats)
                return
            except _NON_RETRYABLE_ERRORS as e:
                # 不可重试错误: 立即标 FAILED, 不重试
                err_type = type(e).__name__
                err_msg = str(e)
                elapsed = time.time() - start
                self._log(f"[不可重试] {task.file_path.name} — {err_type}: {err_msg}")
                result = FileResult(
                    original=text,
                    corrected=text,
                    elapsed=elapsed,
                    error=f"{err_type}: {err_msg}",
                    prompt_hash=prompt_hash,
                    schema_version=2,
                )
                with self._lock:
                    task.status = TaskStatus.FAILED
                    task.result = result
                    task.error_message = f"{err_type}: {err_msg}"
                    task.end_time = time.time()
                with self._stats_lock:
                    self.stats.completed_files += 1
                    self.stats.failed_files += 1
                    self.stats.elapsed = time.time() - self.stats.start_time
                await save_checkpoint_async(task.file_path, task)
                if self.on_file_done:
                    self.on_file_done(key)
                if self.on_file_completed:
                    self.on_file_completed(key)
                if self.on_stats_update:
                    self.on_stats_update(self.stats)
                return
            except RateLimitError as e:
                # 速率限制 — 按 Retry-After 等待后整文件重试
                retry_after = getattr(e, "retry_after", None)
                if retry_after is None:
                    retry_after = float(2 ** attempt)
                self._log(
                    f"[速率限制] {task.file_path.name} — {retry_after}s 后重试 "
                    f"(第 {attempt + 1}/{self.config.max_retries} 次)"
                )
                if attempt < self.config.max_retries:
                    await asyncio.sleep(retry_after)
                    continue
                last_error = e
                break
            except Exception as e:
                last_error = e
                err_type = type(e).__name__
                err_msg = str(e)
                if attempt < self.config.max_retries:
                    delay = 2 ** attempt
                    self._log(f"[重试 {attempt + 1}/{self.config.max_retries}] {task.file_path.name} — {err_type}: {err_msg} — {delay}s 后重试")
                    await asyncio.sleep(delay)
                else:
                    elapsed = time.time() - start
                    self._log(f"[重试耗尽] {task.file_path.name} — {err_type}: {err_msg}")
                    result = FileResult(
                        original=text,
                        corrected=text,
                        elapsed=elapsed,
                        error=f"{err_type}: {err_msg}",
                        prompt_hash=prompt_hash,
                        schema_version=2,
                    )
                    with self._lock:
                        task.status = TaskStatus.FAILED
                        task.result = result
                        task.error_message = f"{err_type}: {err_msg}"
                        task.end_time = time.time()

                    with self._stats_lock:
                        self.stats.completed_files += 1
                        self.stats.failed_files += 1
                        self.stats.elapsed = time.time() - self.stats.start_time

                    await save_checkpoint_async(task.file_path, task)
                    if self.on_file_done:
                        self.on_file_done(key)
                    if self.on_file_completed:
                        self.on_file_completed(key)
                    if self.on_stats_update:
                        self.on_stats_update(self.stats)
                    return

        # 重试耗尽 (RateLimitError 等可重试错误走到这里)
        elapsed = time.time() - start
        err_msg = f"{type(last_error).__name__}: {last_error}" if last_error else "未知错误"
        result = FileResult(
            original=text,
            corrected=text,
            elapsed=elapsed,
            error=err_msg,
            prompt_hash=prompt_hash,
            schema_version=2,
        )
        with self._lock:
            task.status = TaskStatus.FAILED
            task.result = result
            task.error_message = err_msg
            task.end_time = time.time()
        await save_checkpoint_async(task.file_path, task)
        if self.on_file_done:
            self.on_file_done(key)
        if self.on_file_completed:
            self.on_file_completed(key)

    @staticmethod
    def _split_text(text: str, max_chars: int, preset: str = "balanced") -> list[str]:
        """按段落/句号边界切分文本,每块不超过 max_chars 字符。

        优先级: \\n\\n (段落) > \\n (行) > 。！？ (句号) > 强制切分。
        切分点保留在段尾 (即不丢标点),保证拼接时语义完整。
        overlap=0（Phase 1 决策）：校对场景下重叠区会被改两次,结果冲突。

        preset 参数仅在 ``whole_file`` / ``max_chars == 0`` 时生效,直接
        返回 ``[text]``（整文件不分块）。其他 preset 仅用于记录当前档位,
        切分阈值由调用方通过 ``max_chars`` 决定。
        """
        # 整文件预设
        if preset == "whole_file" or max_chars == 0:
            return [text]

        if len(text) <= max_chars:
            return [text]
        chunks: list[str] = []
        remaining = text
        while len(remaining) > max_chars:
            # 尝试在 max_chars 范围内找最佳切分点
            window = remaining[:max_chars]
            cut = -1
            for sep in ("\n\n", "\n", "。", "！", "？", ".", "!", "?"):
                idx = window.rfind(sep)
                if idx > max_chars // 2:  # 至少切在前半段,避免小块
                    cut = idx + len(sep)
                    break
            if cut <= 0:
                cut = max_chars  # 实在没合适切分点,硬切
            chunks.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            chunks.append(remaining)
        return chunks

    async def _stream_single(
        self,
        task_key: str,
        text: str,
        system_prompt_override: Optional[str] = None,
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

        stream = await self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=self.config.temperature,
            stream=True,
            stream_options={"include_usage": True},
        )

        # Bug#13: 收集用 list append,只节流时才 join,避免每 token O(N) join
        buffer: list[str] = []
        token_count = 0
        emit_counter = 0
        last_emit_time = 0.0

        try:
            async for event in stream:
                # Bug#8: 暂停时阻塞,恢复后立即继续
                await self._await_resume()
                if self._cancel_event.is_set():
                    try:
                        await stream.close()
                    except Exception:
                        pass
                    raise asyncio.CancelledError()

                if event.choices:
                    delta = event.choices[0].delta.content
                    if delta:
                        buffer.append(delta)
                        emit_counter += 1
                        now = time.time()
                        if self.on_stream and (
                            emit_counter % _STREAM_THROTTLE_TOKENS == 0
                            or (now - last_emit_time) >= _STREAM_THROTTLE_MS
                        ):
                            # 节流触发时才 "".join 一次 (O(buffer_size))
                            self.on_stream(task_key, "".join(buffer))
                            last_emit_time = now

                if event.usage:
                    token_count = event.usage.total_tokens
        finally:
            try:
                await stream.close()
            except Exception:
                pass

        corrected = "".join(buffer)
        if not corrected:
            raise ValueError("API 返回空内容 (stream 无 token)")

        if self.on_stream:
            self.on_stream(task_key, corrected)

        return corrected, token_count

    async def _stream_chunked(self, task_key: str, chunks: list[str]) -> tuple[str, int, list[FileResult]]:
        """v3.0 多块串行 + 跨段上下文注入 + chunks_results 累积。

        Phase 4: 每 chunk 调 _stream_single 时, system_prompt 注入跨段 context,
        context 由 self.context_builder.build 拼出 (取前 max_chunks 个 chunk 的 corrected,
        总长不超过 max_chars)。

        进度 emit 用 partial = "".join(all_collected_so_far),
        让 UI 看到完整已校对内容的滚动效果。

        返回 (full_corrected, total_tokens, chunks_results):
        - chunks_results: 每块的 FileResult (含 original/corrected/token_count)
        - 调用方 (通常是 _process_file_async) 把它填到 task.result.chunks_results
        """
        all_parts: list[str] = []
        total_tokens = 0
        total = len(chunks)
        # Phase 4: 已完成 chunk 的 FileResult 列表 (供 ContextBuilder 拼接)
        completed_chunks: list[FileResult] = []
        chunk_results: list[FileResult] = []

        for i, chunk in enumerate(chunks):
            if self._cancel_event.is_set():
                raise asyncio.CancelledError()
            await self._await_resume()
            if self._cancel_event.is_set():
                raise asyncio.CancelledError()

            self._log(f"[分块] {task_key} 块 {i + 1}/{total} ({len(chunk)} 字符)")

            # Phase 4: 构造跨段 context prefix
            context_prefix = self.context_builder.build(
                chunks_processed=completed_chunks,
                current_chunk_index=i,
            )
            system_prompt_override: Optional[str] = None
            if context_prefix:
                # 取 base system prompt (按 _stream_single 的内部逻辑)
                if self.config.custom_prompt:
                    base = self.config.custom_prompt
                else:
                    mode_info = PROMPT_MODES.get(self.config.prompt_mode)
                    if not mode_info:
                        mode_info = PROMPT_MODES["strict"]
                    base = mode_info["system"]
                system_prompt_override = f"{base}\n\n{context_prefix}"

            part, tokens = await self._stream_single(
                task_key, chunk, system_prompt_override=system_prompt_override
            )
            all_parts.append(part)
            total_tokens += tokens
            # 记录本 chunk 完成的 FileResult
            chunk_result = FileResult(
                original=chunk, corrected=part, token_count=tokens,
            )
            chunk_results.append(chunk_result)
            completed_chunks.append(chunk_result)
            # 块完成后 emit 一次完整 partial
            if self.on_stream:
                self.on_stream(task_key, "".join(all_parts))
        return "".join(all_parts), total_tokens, chunk_results

    async def _call_api_stream(self, task_key: str, text: str) -> tuple[str, int, list[FileResult]]:
        """v3.0 chunk 串行 + 跨段上下文注入 + chunks_results 返回。

        Phase 1: 通过 ``config.chunking_preset`` 选取切分档位;
        未知 preset 自动回退到 ``DEFAULT_CHUNK_PRESET = "balanced"``。

        Phase 3: 每个 chunk 串行处理, 累积到 ``chunks_results`` 列表并返回。
        Phase 4: 每个 chunk 调 _stream_single 时, system_prompt 注入跨段 context。

        整文件预设 (whole_file): chunks=[text], 走 _stream_single, 无 context 注入。

        返回 (full_corrected, total_tokens, chunks_results)
        """
        # Phase 1: 按 chunking 预设决定 max_chars
        preset = self.config.chunking_preset or DEFAULT_CHUNK_PRESET
        if preset not in _CHUNK_PRESETS:
            preset = DEFAULT_CHUNK_PRESET
        max_chars = _CHUNK_PRESETS[preset]["max_chars"]
        chunks = self._split_text(text, max_chars, preset=preset)
        if len(chunks) == 1:
            # 整文件/小文件: 1 个 chunk, 但仍按 FileResult 格式返回
            corrected, tokens = await self._stream_single(task_key, chunks[0])
            chunk_result = FileResult(
                original=chunks[0], corrected=corrected, token_count=tokens,
            )
            return corrected, tokens, [chunk_result]
        return await self._stream_chunked(task_key, chunks)

    def pause(self) -> None:
        # v4.0+ 修订: threading.Event.set/clear 跨线程安全, 不用 call_soon_threadsafe
        if self._pause_event:
            self._pause_event.clear()
        self._log("[暂停] 处理已暂停")

    def resume(self) -> None:
        if self._pause_event:
            self._pause_event.set()
        self._log("[继续] 处理已恢复")

    def cancel(self) -> None:
        self._cancel_event.set()
        # 取消时同时 set _pause_event, 让正在 _await_resume() 轮询的协程能跳出
        if self._pause_event:
            self._pause_event.set()
        self.stats.elapsed = time.time() - self.stats.start_time
        self._log("[取消] 处理已取消")

    @property
    def is_paused(self) -> bool:
        if self._pause_event:
            return not self._pause_event.is_set()
        return False

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def is_running(self) -> bool:
        return self._loop is not None and self._loop.is_running()
