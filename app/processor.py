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
from app.punct_fix import fix_punctuation_ex
from app.md_strip import strip_markdown
# v5.4 (PLAN-think-strip-v5.4.md): 思维链剥离 — 流式产出侧剥离入口
from app.think_strip import ThinkFilter, count_reasoning_fields, has_think_residue
# v5.1.0: harness 化 — Edit 工具链 (LLM 返回编辑建议, 客户端精确匹配应用)
from app.harness import (
    content_suspicious_noop,
    CHUNK_SCOPE_NOTE,
    EDIT_TOOLS,
    TOOL_CHOICE,
    TOOL_DISCIPLINE,
    apply_edits,
    audit_has_warnings,
    parse_tool_calls,
)
from app.utils import compute_prompt_hash_for_config
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
    split_text,
    CHUNKING_PRESETS_MAP,
    DEFAULT_CHUNK_PRESET,
    # v5.3.0: workflow 一等身份 + 按轨派生 (PLAN-workflow-split-v5.3.md §2 D4/D7)
    WORKFLOW_HARNESS,
    effective_workflow,
    workflow_allows_tools,
    resolve_chunk_preset,
    resolve_request_timeout,
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
        # v4.1.8.2 (审计 E12): 在 __init__ 即创建并置位 — 旧版在 _run_all 里才建,
        # 线程启动前 pause() 落在 None 上静默丢失, 且 _run_all 重建 event 会把
        # 暂停状态清掉.
        self._pause_event = threading.Event()
        self._pause_event.set()
        # v4.1.8.2 (审计 B2): 主任务句柄, cancel() 用它跨线程强制中断在途 HTTP await
        self._main_task: asyncio.Task | None = None
        self._lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._client: AsyncOpenAI | None = None
        # v4.3.4: 标点不平衡报告 (只报不改) — 桥接层在 prepare 后/run 结束后推送
        self.punct_reports: list[str] = []
        # v5.1.0: harness 编辑审计 (file_key -> 合并后的 audit 列表)。
        # 按设计决策不放 FileResult — 桥接层在 onFileDone/onTaskComplete 时
        # 从这里读取并附加到推送 payload; 会话内存态, 不落断点。
        self.file_audits: dict[str, list[dict]] = {}
        # v5.3.0: 本会话内被模型输出上限截断的文件 (finish_reason="length")。
        # 与 file_audits 同层: 会话内存态, 不落断点; 每次 _call_api_stream 重建。
        self.truncated_keys: set[str] = set()

        self.on_file_done: Optional[Callable[[str, str], None]] = None
        self.on_file_start: Optional[Callable[[str], None]] = None
        # v5.1.0: harness 非流式调用开始 (无 token 流, 前端显示等待文案)
        self.on_harness_wait: Optional[Callable[[str], None]] = None
        # NEW (v3.0+): 所有 chunk 完成 (v4.1.8.2 C2: 均附 status 参数)
        self.on_file_completed: Optional[Callable[[str, str], None]] = None
        self.on_stats_update: Optional[Callable[[ProcessStats], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_stream: Optional[Callable[[str, str], None]] = None
        # v4.3.1 (UX #7): 块级进度回调 (file_key, done_chunks, total_chunks) —
        # 单文件多 chunk 时前端进度条不再长时间停在 0% (文件数进度只随文件收敛).
        # 仅多 chunk 路径 (_stream_chunked) 触发; _call_api_stream 单块分支不触发.
        self.on_file_progress: Optional[Callable[[str, int, int], None]] = None
        # v4.3.1 (UX #7): 本次 prepare_tasks 命中断点缓存 (直接复用结果) 的文件
        # 路径列表 — start_proofread 返回给前端, 提示用户"秒完成"是缓存命中.
        self.cached_files: list[str] = []

        # v3.0 Phase 4: 跨段上下文构造器
        self.context_builder = ContextBuilder(
            max_chars=getattr(config, "context_max_chars", 800),
            max_chunks=getattr(config, "context_max_chunks", 2),
        )

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            self.on_log(msg)

    def _punct_options(self) -> dict:
        """从配置组装标点修复选项 (v4.3.4; 默认值与 punct_fix._DEFAULT_OPTIONS 一致)."""
        return {
            "quote_style": self.config.punct_quote_style,
            "fullwidth_alnum": self.config.punct_fullwidth_alnum,
            "repeat_compress": self.config.punct_repeat_compress,
            "dash_tilde": self.config.punct_dash_tilde,
        }

    def _collect_punct_reports(self, file_name: str, punct_stats: dict) -> None:
        """把引号不平衡报告转成可读日志行 (v4.3.4; 只报不改 — 宁漏勿误互补).

        v5.0.1 (审计 I-2): 每条同时走 _log — prepare 阶段 on_log 回调未注册时
        _log 静默丢弃 (该阶段有 web_backend 的专用 push), 运行期收集
        (punct_local/md_local 分支, 后台线程) 则即时到达前端 — 修复
        "运行期累积的报告无人推" 的断链."""
        for rep in punct_stats.get("imbalance", []):
            line_no = rep.get("line", "?")
            if "count" in rep:
                detail = f"引号落单 (共 {rep['count']} 个)"
            else:
                detail = f"引号不平衡 (开 {rep.get('open', 0)}/闭 {rep.get('close', 0)})"
            msg = f"{file_name} 第 {line_no} 行 {detail}: {rep.get('line_text', '')}"
            self.punct_reports.append(msg)
            self._log(f"[报告] {msg}")

    def _strip_md_guarded(self, text: str, file_name: str) -> str:
        """v4.4.2: strip_markdown 带空结果兜底 (评审 P2-16) — 纯标记文件
        (只含 ---/***/分隔行) 产出空文本会击穿 diff 与断点 is_done 语义,
        空结果回退保留原文并打日志."""
        stripped = strip_markdown(text)
        if not stripped.strip() and text.strip():
            self._log(f"[清洗] {file_name}: Markdown 剥离结果为空, 保留原文")
            return text
        return stripped

    def _emit(self, cb, *args) -> None:
        """统一回调保护.

        v4.1.8.2 (审计 E13): 回调直连 bridge 的 evaluate_js, 窗口关闭/导航时
        可能抛异常 — 裸调用下 on_stream 异常会被通用 except 捕获升级成整文件
        重试 (窗口已关仍继续打 API), on_file_start 异常则让任务无任何收尾.
        统一在此 try/except, 只记日志不上抛.
        """
        if cb is None:
            return
        try:
            cb(*args)
        except Exception as e:
            logger.error(f"回调异常 {getattr(cb, '__name__', 'cb')}: {e}")

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

    async def _sleep_interruptible(self, seconds: float) -> bool:
        """分段可取消的退避睡眠.

        v4.1.8.1 (审计 M5): asyncio.sleep 整体不可被 cancel 中断, 旧退避
        (Retry-After 可达几十秒) 会让用户 cancel 后任务仍卡住不退出. 拆 0.2s
        小步逐段查 _cancel_event.
        返回 True = 期间收到取消 (调用方应走取消收尾), False = 完整睡完.
        """
        if seconds <= 0:
            return self._cancel_event.is_set()
        step = 0.2
        remaining = float(seconds)
        while remaining > 0:
            if self._cancel_event.is_set():
                return True
            chunk = min(step, remaining)
            await asyncio.sleep(chunk)
            remaining -= chunk
        return self._cancel_event.is_set()

    def prepare_tasks(self, file_paths: list[Path], force_rerun: bool = False) -> None:
        """读取文件并加载断点缓存。

        缓存命中校验 (Bug#3 + v4.1.8.1 C2/C5): 指纹由 compute_prompt_hash 纳入
        prompt 模式 + 生成配置 (chunking/context/temperature) 计算, 传给
        load_checkpoint 的 expected_hash 统一比对; 不匹配即判缓存失效。

        v4.3.1 (UX #7): force_rerun=True 跳过 load_checkpoint (每文件重新
        read_file_text 走完整流程) — 已完成文件删掉重加会被缓存秒标完成、前端
        "开始"又只认 pending/failed/cancelled, 用户从此没有重跑通道. 命中缓存的
        文件路径记入 self.cached_files 供 bridge 上报; skip 占位与 stats 逻辑不变.

        读取失败 (Bug#16): 原来 silent fail (continue) 会让 UI 永远"等待中"。
        改为创建一个 FAILED 占位 task,UI 能立即看到该文件失败。
        """
        # v4.3.1 (UX #7): 每次调用重置, cached_files 只反映本次 prepare 的命中
        self.cached_files = []
        # 缓存 prompt/配置指纹 (后续 _process_file_async 写入 FileResult.prompt_hash 复用)
        # v4.1.8.1 (审计 C2): 纳入 chunking/context/temperature 等影响生成结果的字段
        # v4.1.8.2 (审计 E16): 补纳 api_base
        # v5.0.1 (审计 I-3): 统一走 compute_prompt_hash_for_config — 字段集
        # 与 compute_prompt_hash 相邻同步, 杜绝漏传靠默认值碰巧匹配
        self._current_prompt_hash = compute_prompt_hash_for_config(self.config)

        for fp in file_paths:
            key = str(fp)
            # v4.1.8.1 (审计 C5): 传 expected_hash, 由 load_checkpoint 统一做指纹比对.
            # 空 hash 的 v1 旧断点在校验下自然失效 (强制重跑); 原 prepare_tasks 手动
            # 二次校验 (Bug#3) 与 load_checkpoint 内部逻辑重复, 已删除.
            # v4.3.1 (UX #7): force_rerun 时整体跳过缓存查找.
            cached = None if force_rerun else load_checkpoint(
                fp, expected_hash=self._current_prompt_hash
            )
            # v5.4 (PLAN §2 D9): 旧断点定向失效 — corrected 含思维链残留 (原文自身不含)
            # 时忽略缓存强制重跑; 只烧脏文件, 不动 prompt_hash/schema (v2.1 复审口径)。
            if cached and cached.is_done and has_think_residue(cached.result):
                self._log(f"[思维链] {fp.name}: 旧断点含思维链残留, 忽略缓存强制重跑")
                cached = None
            if cached and cached.is_done:
                self.tasks[key] = cached
                # v4.3.1 (UX #7): 记录缓存命中, bridge 把它上报给前端
                self.cached_files.append(key)
                self._log(f"[缓存] {fp.name}: 已有校对结果，跳过")
                continue

            try:
                text = read_file_text(fp)
            except Exception as e:
                self._log(f"[错误] 无法读取文件 {fp.name}: {e}")
                # Bug#16: 占位 FAILED 任务,让 UI 知道此文件失败
                # v4.1.8.2 (审计 E2): 打 skip 标记 — 旧版占位会被 pending 重新
                # 纳入, 空文本照常打 API (400 覆盖真实错误, 或产出垃圾"成功").
                placeholder = FileTask(file_path=fp, original_text="")
                placeholder.status = TaskStatus.FAILED
                placeholder.skip = True
                placeholder.result = FileResult(
                    original="",
                    corrected="",
                    error=f"读取失败: {e}",
                    prompt_hash=self._current_prompt_hash,
                )
                placeholder.end_time = time.time()
                self.tasks[key] = placeholder
                continue
            # v4.3.3: 本地标点修复 (开关见 ProjectConfig.punct_fix) — 半角引号/
            # 逗号等确定性错误用脚本修, 不消耗 LLM; 修复计入指纹 (改开关自动重跑)
            # v4.3.3 (评审 E-1): 「仅标点修复」模式不在预处理阶段修 — 原文保持
            # 原始状态, 修复发生在 _call_api_stream 本地分支, 否则 corrected ==
            # original, 结果对比页 diff 完全为空 (无法审计改了什么)
            # v4.4.2: Markdown 剥离 (可选开关) 先于标点修复 — 剥掉 **/# 等标记后
            # 标点规则的 CJK 邻接上下文才准确; 本地双模式 (punct_local/md_local)
            # 跳过全部预处理 (E-1 同款: 原文作 diff 基线, 修复在本地分支发生)
            if self.config.prompt_mode not in ("punct_local", "md_local"):
                if self.config.md_strip_before_llm:
                    text = self._strip_md_guarded(text, fp.name)
                if self.config.punct_fix:
                    text, punct_stats = fix_punctuation_ex(text, self._punct_options())
                    if punct_stats["total"]:
                        self._log(f"[标点] {fp.name}: 本地修复 {punct_stats['total']} 处半角标点")
                    self._collect_punct_reports(fp.name, punct_stats)
            task = FileTask(file_path=fp, original_text=text)
            self.tasks[key] = task
            self._log(f"[就绪] {fp.name}: {len(text)} 字符")

        # v4.1.8.2 (审计 E2): skip 占位也已终态, 计入 completed 让 X/Y 收敛
        self.stats.total_files = len(self.tasks)
        self.stats.completed_files = sum(
            1 for t in self.tasks.values() if t.is_done or t.skip
        )

    async def run_async(self) -> None:
        """v4.0+ 入口：后台线程内 loop.run_until_complete 调用。"""
        # v4.1.8.2 (审计 E11): 不再无条件 clear 取消位 — engine 每次新建本可省略,
        # 而"bridge 已把 _engine 指向新引擎、线程尚未跑到这里"的窗口期内用户
        # 取消会被这里 clear 静默吞掉. 启动即取消由 _run_all 入口统一收尾.
        self.stats.start_time = time.time()
        await self._run_all()

    async def _run_all(self) -> None:
        """异步主循环，创建共享客户端并并发处理所有文件。"""
        self._loop = asyncio.get_running_loop()
        # v4.1.8.2 (审计 B2): 记录主任务句柄, cancel() 跨线程强制中断在途 await
        self._main_task = asyncio.current_task()
        # v4.0+ 修订: pause_event 改 threading.Event, 跨线程 pause/resume 线程安全
        # v4.1.8.2 (审计 E12): __init__ 已创建, 这里只重置为"运行中"
        self._pause_event.set()

        # v4.1.8.2 (审计 E11): 启动窗口期已取消 → 全量取消收尾, 而非照常跑完
        if self._cancel_event.is_set():
            for key, task in self.tasks.items():
                if not task.skip and task.result is None:
                    await self._finalize_cancelled(key, task, time.time())
            self.stats.elapsed = time.time() - self.stats.start_time
            self._emit(self.on_stats_update, self.stats)
            self._log("[取消] 任务启动前已取消")
            return

        # v4.3.3: 仅标点修复模式全程不触网 — 不建 AsyncOpenAI (空 api_key 会抛错)
        # v4.4.2: 仅 Markdown 清洗模式同款 (md_local 亦为纯本地)
        if self.config.prompt_mode in ("punct_local", "md_local"):
            self._client = None
        else:
            self._client = AsyncOpenAI(
                base_url=self.config.api_base,
                api_key=self.config.api_key,
                timeout=self._effective_timeout(),  # v5.2c: 双轨 timeout 派生
                max_retries=0,
            )

        # v4.1.8.2 (审计 E2): skip 占位 (读取失败) 不进 pending 重打 API
        pending = [
            (k, t) for k, t in self.tasks.items()
            if not t.is_done and not t.skip
        ]

        # v4.1.8.2 (审计 E2): skip 占位虽不处理, 但要补发完成事件让 UI 收敛
        for key, task in self.tasks.items():
            if task.skip:
                self._emit(self.on_file_done, key, TaskStatus.FAILED.value)
                self._emit(self.on_file_completed, key, TaskStatus.FAILED.value)
        if any(t.skip for t in self.tasks.values()):
            self._emit(self.on_stats_update, self.stats)

        # v4.1 (I1): try/finally 保证 _client.close() 一定被调, 避免 httpx 连接泄漏
        try:
            if not pending:
                self._log("[提示] 没有待处理的文件")
                self.stats.elapsed = 0
                self._emit(self.on_stats_update, self.stats)
                return

            # v4.1.8.2 (审计 E1): concurrency=0 会让 Semaphore(0) 永久死锁且
            # cancel 无法打破 (等待者到不了取消检查点) — 输入侧已钳制, 引擎兜底.
            concurrency = max(1, int(self.config.concurrency or 1))
            semaphore = asyncio.Semaphore(concurrency)

            async def limited(key, task):
                # v4.1.8.2 (审计 B2): 强制取消落在 semaphore 等待/早期 await 上时
                # 也要完整收尾 (这些位置不在 _process_file_async 的内部 try 内)
                try:
                    async with semaphore:
                        return await self._process_file_async(key, task)
                except asyncio.CancelledError:
                    await self._finalize_cancelled(key, task, time.time())
                    return None

            coros = [limited(k, t) for k, t in pending]
            try:
                results = await asyncio.gather(*coros, return_exceptions=True)
            except asyncio.CancelledError:
                # v4.1.8.2 (审计 B2): cancel() 强制 cancel 主任务以打断在途 HTTP
                # await; 子协程已各自收尾, 这里吞掉取消让线程正常退出 (join 不超时)
                self._log("[取消] 全部任务已中止")
                self.stats.elapsed = time.time() - self.stats.start_time
                self._emit(self.on_stats_update, self.stats)
                return

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Worker 异常: {result}", exc_info=result)

            self.stats.elapsed = time.time() - self.stats.start_time
            self._emit(self.on_stats_update, self.stats)
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

        chunk 失败处理 (v4.1.8.2 审计 E7 修正文档):
          - 任一 chunk 失败异常向上传播, 触发整文件重试 (与上方失败语义一致)
          - result.chunks_results 只含成功 chunk 的 FileResult, 因此
            result.failed_chunks 恒为空列表 (保留字段仅为断点 schema 兼容)
        """
        # v4.1.8.1 (审计 B2): start 提前到取消检查前, 让取消早退也能算 elapsed
        start = time.time()
        if self._cancel_event.is_set():
            # 排队文件拿到 semaphore 才进来; 若此时已取消, 走完整收尾 (result/
            # CANCELLED/断点/stats/回调), 否则 UI 永远卡"排队中"
            await self._finalize_cancelled(key, task, start)
            return

        await self._await_resume()
        if self._cancel_event.is_set():
            await self._finalize_cancelled(key, task, start)
            return

        self._emit(self.on_file_start, key)

        text = task.original_text
        # v4.1.8.2 (审计 E2): 空文本 (0 字节文件) 不打 API — 轻则 400 覆盖真实
        # 错误, 重则部分后端对空输入正常回复产出垃圾"成功"结果.
        if not text.strip():
            await self._finalize_failed(key, task, start, "EmptyText", "文件内容为空")
            return

        prompt_hash = getattr(self, "_current_prompt_hash", "")
        self._log(f"[处理中] {task.file_path.name} ({len(text)} 字符)")

        # 选 chunking 档位 (v5.2c: 双轨派生 — harness 模式走大块, 重写模式走原档)
        preset = self._effective_chunk_preset()
        if preset not in _CHUNK_PRESETS:
            preset = DEFAULT_CHUNK_PRESET
        max_chars = _CHUNK_PRESETS[preset]["max_chars"]
        chunks = self._split_text(text, max_chars, preset=preset)
        # v5.3.0 (PLAN §3.4): workflow 指明 harness 但模式不在白名单 →
        # 不静默换行为, 在日志里说清"本次按整篇输出执行"
        if effective_workflow(self.config) == WORKFLOW_HARNESS and not self._harness_active():
            self._log(
                f"[模式] prompt_mode={self.config.prompt_mode} 不在工具链白名单内, "
                f"本次按整篇输出执行"
            )
        if len(chunks) > 1:
            self._log(
                f"[分块] {task.file_path.name}: {len(chunks)} 块 "
                f"(preset={preset}, max_chars={max_chars})"
            )

        # v4.1.8.2 (审计 E6): max_retries<0 会让 range() 为空 → 函数静默返回,
        # 无状态/无断点/无回调, UI 永远"处理中". 输入侧已钳制, 引擎兜底.
        max_retries = max(0, int(self.config.max_retries or 0))

        for attempt in range(max_retries + 1):
            # v4.1.8.1 (审计 B2): attempt 顶部的取消点同样走完整收尾, 不再裸置状态
            if self._cancel_event.is_set():
                await self._finalize_cancelled(key, task, start)
                return
            await self._await_resume()
            if self._cancel_event.is_set():
                await self._finalize_cancelled(key, task, start)
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
                # v5.1.0: harness 部分成功 (边界 12) — 有未生效的编辑建议或
                # 整轮级告警时置 warnings (不新增 TaskStatus 枚举)
                result = FileResult(
                    original=text,
                    corrected=corrected,
                    token_count=token_count,
                    elapsed=elapsed,
                    prompt_hash=prompt_hash,
                    chunks_results=chunks_results,
                    failed_chunks=failed_chunks,
                    schema_version=2,
                    warnings=(
                        audit_has_warnings(self.file_audits.get(key, []))
                        # v5.3.0: 模型输出触顶 (finish_reason=length) 也算告警
                        or key in self.truncated_keys
                    ),
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
                self._emit(self.on_file_done, key, TaskStatus.COMPLETED.value)
                self._emit(self.on_file_completed, key, TaskStatus.COMPLETED.value)
                self._emit(self.on_stats_update, self.stats)
                return

            except asyncio.CancelledError:
                # v4.1.8.1 (审计 B2): 统一收尾 (流式中途取消原来就能走到这, 逻辑不变)
                await self._finalize_cancelled(key, task, start)
                return
            except _NON_RETRYABLE_ERRORS as e:
                # 不可重试错误: 立即标 FAILED, 不重试
                err_type = type(e).__name__
                err_msg = str(e)
                self._log(f"[不可重试] {task.file_path.name} — {err_type}: {err_msg}")
                await self._finalize_failed(key, task, start, err_type, err_msg)
                return
            except RateLimitError as e:
                # 速率限制 — 按 Retry-After 等待后整文件重试
                # v4.1.8.2 (审计 E17): RateLimitError 没有 retry_after 属性,
                # 服务端建议在 response.headers["Retry-After"] — 旧 getattr 恒
                # 返回 None, 建议从未生效.
                retry_after = None
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        retry_after = float(resp.headers.get("retry-after"))
                    except (TypeError, ValueError, AttributeError):
                        retry_after = None
                if retry_after is None:
                    retry_after = float(2 ** attempt)
                self._log(
                    f"[速率限制] {task.file_path.name} — {retry_after}s 后重试 "
                    f"(第 {attempt + 1}/{max_retries} 次)"
                )
                if attempt < max_retries:
                    # v4.1.8.1 (M5): 退避期间收到 cancel 立即走取消收尾, 不再傻等
                    if await self._sleep_interruptible(retry_after):
                        await self._finalize_cancelled(key, task, start)
                        return
                    continue
                # v4.1.8.1 (审计 B1): 重试耗尽走统一 FAILED 收尾. 旧代码 break 到
                # for 循环外只置状态/存断点/发回调, 漏 stats 计数 + on_stats_update
                # (进度永远少 1) — 生产最常见失败路径.
                self._log(
                    f"[速率限制耗尽] {task.file_path.name} — "
                    f"已达最大重试 {max_retries} 次, 标记失败"
                )
                err_type = type(e).__name__
                err_msg = str(e)
                await self._finalize_failed(key, task, start, err_type, err_msg)
                return
            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e)
                if attempt < max_retries:
                    delay = 2 ** attempt
                    self._log(f"[重试 {attempt + 1}/{max_retries}] {task.file_path.name} — {err_type}: {err_msg} — {delay}s 后重试")
                    # v4.1.8.1 (M5): 分段退避可被 cancel 中断
                    if await self._sleep_interruptible(delay):
                        await self._finalize_cancelled(key, task, start)
                        return
                else:
                    # v4.1.8.1 (审计 B1): 统一 FAILED 收尾 (原 else 内联收尾块已抽走)
                    self._log(f"[重试耗尽] {task.file_path.name} — {err_type}: {err_msg}")
                    await self._finalize_failed(key, task, start, err_type, err_msg)
                    return

        # v4.1.8.2 (审计 E6): 防御兜底 — 正常情况下循环内必然 return (成功/失败/
        # 取消), 走到这里说明收尾出现缺口, 补一次 FAILED 收尾避免 UI 卡"处理中".
        await self._finalize_failed(key, task, start, "InternalError", "重试循环异常退出")

    async def _finalize_cancelled(self, key: str, task: FileTask, start: float) -> None:
        """CANCELLED 统一收尾: result/断点/stats/回调 全齐.

        v4.1.8.1 (审计 B2): 排队文件/attempt 顶部/流式中途的取消点统一走这里.
        旧实现里排队文件 (semaphore 等待) 与 attempt 顶部取消只置 status 或裸
        return, 无 result/断点/stats/回调 -> UI 永远卡"排队中", 进度不收敛.
        CANCELLED 断点会被 load_checkpoint 判为强制重跑 (与既有取消语义一致).
        """
        elapsed = time.time() - start if start else 0.0
        text = task.original_text or ""
        result = FileResult(
            original=text,
            # v4.1.8.2 (审计 C3): 不再回填原文 — 旧版 corrected=original, 前端
            # "corrected 非空即可复制/导出"的判据会把未校对原文当结果导出
            corrected="",
            elapsed=elapsed,
            error="已取消",
            prompt_hash=getattr(self, "_current_prompt_hash", ""),
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
        # v5.3.0 (PLAN §2 D9): 取消不该冲掉另一条轨已完成的结果
        await save_checkpoint_async(task.file_path, task, preserve_done=True)
        self._emit(self.on_file_done, key, TaskStatus.CANCELLED.value)
        self._emit(self.on_file_completed, key, TaskStatus.CANCELLED.value)
        self._emit(self.on_stats_update, self.stats)

    async def _finalize_failed(self, key: str, task: FileTask, start: float,
                               err_type: str, err_msg: str) -> None:
        """FAILED 统一收尾: result/断点/stats/回调 全齐.

        v4.1.8.1 (审计 B1): 从 3 处重复失败收尾块 (不可重试/通用耗尽/RateLimit
        耗尽) 抽出的统一函数, 消除 RateLimit 耗尽路径漏补 stats.completed_files /
        failed_files + on_stats_update (进度永远少 1) 的 bug.
        """
        elapsed = time.time() - start
        text = task.original_text or ""
        detail = f"{err_type}: {err_msg}"
        result = FileResult(
            original=text,
            # v4.1.8.2 (审计 C3): 不再回填原文, 防止前端把原文当校对结果复制/导出
            corrected="",
            elapsed=elapsed,
            error=detail,
            prompt_hash=getattr(self, "_current_prompt_hash", ""),
            schema_version=2,
        )
        with self._lock:
            task.status = TaskStatus.FAILED
            task.result = result
            task.error_message = detail
            task.end_time = time.time()
        with self._stats_lock:
            self.stats.completed_files += 1
            self.stats.failed_files += 1
            self.stats.elapsed = time.time() - self.stats.start_time
        # v5.3.0 (PLAN §2 D9): 失败不该冲掉另一条轨已完成的结果
        await save_checkpoint_async(task.file_path, task, preserve_done=True)
        self._emit(self.on_file_done, key, TaskStatus.FAILED.value)
        self._emit(self.on_file_completed, key, TaskStatus.FAILED.value)
        self._emit(self.on_stats_update, self.stats)

    @staticmethod
    def _split_text(text: str, max_chars: int, preset: str = "balanced") -> list[str]:
        """按段落/句号边界切分 (v4.3.0: 实现平移到 utils.split_text, 此处委托).

        DeAI 长文本分块复用同一实现; 保留原签名兼容既有测试与外部调用。
        """
        return split_text(text, max_chars, preset=preset)

    async def _stream_single(
        self,
        task_key: str,
        text: str,
        system_prompt_override: Optional[str] = None,
        stream_prefix: str = "",
        harness_chunk_note: str = "",
    ) -> tuple[str, int]:
        """单块文本的流式调用。

        system_prompt_override: 外部传入的 system prompt（Phase 4 跨段上下文用）。
        为 None 时按 self.config 选 base system prompt。

        stream_prefix: 本块之前已完成的全文 (多 chunk 场景). v4.1.8.1 (审计 M4):
        每次 emit 推 prefix + 当前累积 -> 对前端单调增长, 消除多 chunk 时"块内只
        推本块 buffer 覆盖掉前面内容"造成的回缩/闪断. 单 chunk 时为空串, 行为不变.

        harness_chunk_note: v5.1.0 harness 分块时附加到 user 消息的 scope 说明
        (上下文只是参照物, 不可编辑); 非 harness 或单块时为空串。

        v5.1.0: strict/polish + harness_enabled 双条件生效时改走 Edit 工具链
        (_harness_call, 非流式) — LLM 返回编辑建议而非整篇全文。
        """
        if system_prompt_override is not None:
            system_prompt = system_prompt_override
        elif self.config.prompt_mode == "custom" and self.config.custom_prompt:
            # v4.1.8.1 (审计 H12): custom_prompt 只在模式显式选"自定义"时生效.
            # 旧实现 custom_prompt 非空即覆盖任意模式 -> 残留的旧自定义 prompt
            # 会让 strict/polish 等模式的用户跑在完全不同的 system 下.
            system_prompt = self.config.custom_prompt
        else:
            mode_info = PROMPT_MODES.get(self.config.prompt_mode)
            # v4.1.8.2 (审计 C4): "deai" 是去AI味视图专用的遗留占位模式, 不该作为
            # 校对 system prompt (settings 下拉已过滤, 这里兜底历史残留配置)
            if not mode_info:
                self._log(f"[警告] 未知校对模式 '{self.config.prompt_mode}'，回退到纯纠错模式")
                mode_info = PROMPT_MODES["strict"]
            elif mode_info.get("system") == "PLACEHOLDER":
                self._log(f"[警告] 校对模式 '{self.config.prompt_mode}' 为占位模式，回退到纯纠错模式")
                mode_info = PROMPT_MODES["strict"]
            system_prompt = mode_info["system"]

        # v5.1.0: harness 分支 — 非流式 tool_calls + 本地 apply (无 token 流需求,
        # 解析更简单; 烟测结论协议固定, 不做运行时降级)
        if self._harness_active():
            return await self._harness_call(
                task_key, text, system_prompt,
                stream_prefix=stream_prefix, chunk_note=harness_chunk_note,
            )

        # v4.1.8.2 (审计 E5): stream_options={"include_usage":True} 对旧版
        # LM Studio / Ollama / vLLM 的 OpenAI 兼容层返回 400, 且 BadRequest 被
        # 归类"不可重试"直接 FAILED — 检测到该报错后去掉参数降级重试一次.
        kwargs = dict(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=self.config.temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            if "stream_options" in str(e):
                self._log("[兼容] 服务端不支持 stream_options, 去除该参数重试")
                kwargs.pop("stream_options")
                stream = await self._client.chat.completions.create(**kwargs)
            else:
                raise

        # Bug#13: 收集用 list append,只节流时才 join,避免每 token O(N) join
        # v5.4 (PLAN §2 D4/D8): 思维链剥离 — 原文只进 ThinkFilter, 产出侧只见剥后文本
        think_filter = ThinkFilter()
        visible = ""          # 已产出 (剥后) 文本累计, 保持单调前缀
        reasoning_frames = 0  # D7: 独立字段出现帧数 (只看真假, 不落内容)
        token_count = 0
        emit_counter = 0
        last_emit_time = 0.0
        finish_reason: Optional[str] = None

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
                        think_filter.feed(delta)
                        emit_counter += 1
                        now = time.time()
                        if (
                            emit_counter % _STREAM_THROTTLE_TOKENS == 0
                            or (now - last_emit_time) >= _STREAM_THROTTLE_MS
                        ):
                            # v4.1.8.1 (M4): 推单调增长全量 (前缀复用同一 str, 不重复 join)
                            # v5.4: 只推剥后文本 — 思维链不闪现 (take 只在节流点求值)
                            visible += think_filter.take()
                            self._emit(self.on_stream, task_key, stream_prefix + visible)
                            last_emit_time = now
                    reasoning_frames += count_reasoning_fields(event.choices[0].delta)
                    # v5.3.0 (PLAN §2 D8): 记录结束原因 — "length" = 模型被输出
                    # 上限截断 (全仓无 max_tokens, 从前完全静默)
                    fr = getattr(event.choices[0], "finish_reason", None)
                    if fr:
                        finish_reason = fr

                if event.usage:
                    token_count = event.usage.total_tokens
        finally:
            try:
                await stream.close()
            except Exception:
                pass

        corrected = visible + think_filter.flush()
        name = self.tasks[task_key].file_path.name if task_key in self.tasks else task_key

        # v5.4 (PLAN §2 D5): 截断标记先记录, 再走空输出判定 (维持 v5.3.0 语义)
        if finish_reason == "length":
            self.truncated_keys.add(task_key)
            self._log(
                f"[截断] {name}: 模型输出触顶 (finish_reason=length), 结果可能短于原文"
            )

        # v5.4 (PLAN §2 D10): 剥离可观测
        n_blocks, n_chars = think_filter.stats()
        if n_blocks:
            self._log(f"[思维链] {name}: 丢弃 {n_blocks} 块 / {n_chars} 字符")
        if reasoning_frames:
            logger.debug(f"[思维链] {name}: 忽略独立字段 {reasoning_frames} 帧")

        if not corrected:
            raise ValueError("API 返回空内容 (stream 无 token 或输出仅含思维链)")

        self._emit(self.on_stream, task_key, stream_prefix + corrected)

        return corrected, token_count

    def _harness_active(self) -> bool:
        """harness (Edit 工具链) 生效判定 — v5.3.0 起以 workflow 为权威。

        生效条件 = `effective_workflow(config) == "harness"` **且**
        prompt_mode ∈ {strict, polish} (模式白名单, 见 AGENTS.md §36)。
        workflow 说是 harness 但模式不在白名单 (custom / tech_doc / 本地模式) 时
        退回整篇行为, 且**不改写**用户的 prompt_mode (PLAN §3.4)。
        harness_enabled 只在 workflow_mode 为空时参与派生 (老配置兼容)。
        """
        return workflow_allows_tools(self.config)

    def _effective_chunk_preset(self) -> str:
        """v5.2c / v5.3.0: 派生实际生效的 chunking 档。

        v5.3.0 起委托 `utils.resolve_chunk_preset` — 单点定义, 与 web_backend 的
        DeAI / 蒸馏路径共用; 非 harness 轨拿到 extra_large(50000) 会自动回退
        large (PLAN §2 D7 / §5-6)。调用方 (两处) 仍共用本 helper 保持一致。
        """
        return resolve_chunk_preset(self.config)

    def _effective_timeout(self) -> int:
        """v5.2c / v5.3.0: 派生实际生效的 request timeout (秒)。

        v5.3.0 起委托 `utils.resolve_request_timeout`, 与 `_effective_chunk_preset`
        配套共用同一条派生链。
        """
        return resolve_request_timeout(self.config)

    async def _harness_call(
        self,
        task_key: str,
        text: str,
        system_prompt: str,
        stream_prefix: str = "",
        chunk_note: str = "",
    ) -> tuple[str, int]:
        """v5.1.0: harness 分支 — 非流式 tool_calls 调用 + 客户端 apply。

        与 _stream_single 流式路径的分工:
          - 非流式 (无 token 流需求, 解析更简单; 协议由烟测选定 = OpenAI
            兼容 tools/function calling, 运行时不做任何降级 fallback)。
          - 在途取消由 B2 强制中断机制覆盖 (cancel() cancel 主任务打断
            非流式 await), 本函数不额外检查 cancel_event。
          - edits 空 → corrected=原文 (正常, 烟测证实模型对无错文本返回
            0 个 tool_calls); 全部编辑未生效 → raise ValueError (同
            "API 返回空内容" 语义, 走通用重试链, 耗尽后整文件 FAILED);
            部分成功 → audit 记录未生效条目, 由 _process_file_async 据
            file_audits 置 FileResult.warnings (边界 12)。
        """
        name = self.tasks[task_key].file_path.name if task_key in self.tasks else task_key
        self._emit(self.on_harness_wait, task_key)
        self._log(f"[harness] {name}: 已提交校对请求, 等待模型返回编辑建议 (非流式)")

        system_content = f"{system_prompt}\n\n{TOOL_DISCIPLINE}"
        user_content = f"{text}\n\n{chunk_note}" if chunk_note else text

        completion = await self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=self.config.temperature,
            tools=EDIT_TOOLS,
            tool_choice=TOOL_CHOICE,
            stream=False,
        )

        token_count = completion.usage.total_tokens if getattr(completion, "usage", None) else 0
        message = completion.choices[0].message
        edits, parse_audit = parse_tool_calls(message)

        # v5.4.1 (用户烟测 Q1): 0 tool_calls 防误报守卫 — 推理模型偶发不产
        # tool_calls 而把推理/答复写进 content。守卫判可疑 → raise 走通用重试链
        # (默认重试 1 次后 FAILED), 而不是静默判 "无需修改"。
        if not edits:
            _content = getattr(message, "content", None) or ""
            if content_suspicious_noop(_content):
                preview = _content.strip().replace("\n", " ")[:80]
                self._log(
                    f"[harness] {name}: 模型未产出编辑但 content 非空 "
                    f"({len(_content)} 字符, 疑似未走工具链) → 重试. 预览: {preview}"
                )
                raise ValueError(
                    f"harness 模型未走工具链 (content {len(_content)} 字符, "
                    f"无 tool_calls) — 疑似推理模型把答复写进了正文"
                )

        # 本块 audit = 参数解析失败条目 + apply 回执 (重编号保证 index 连续)
        chunk_audit: list[dict] = list(parse_audit)
        if edits:
            corrected, round_audit = apply_edits(text, edits)
            chunk_audit.extend(round_audit)
        else:
            corrected = text

        # index 重编号: 连续正整数标可解析编辑的顺序, -1 保留给整轮级告警
        seq = 0
        for entry in chunk_audit:
            if entry["index"] >= 0:
                entry["index"] = seq
                seq += 1

        # 边界 11: 存在有效编辑 (非 NOOP) 但全部未生效 → 与"API 返回空内容"
        # 同语义 raise, 交给通用重试链 (耗尽后整文件 FAILED)。
        effective = [
            e for e in edits
            if isinstance(e, dict) and e.get("old_text") and e.get("old_text") != e.get("new_text")
        ]
        if effective and corrected == text:
            self.file_audits[task_key] = self.file_audits.get(task_key, []) + chunk_audit
            skipped = sum(1 for e in chunk_audit if e["status"].startswith("SKIPPED"))
            raise ValueError(
                f"harness 全部编辑未生效 ({skipped} 条 SKIPPED, "
                f"NOT_FOUND/NOT_UNIQUE/CAP), 原文保持不变"
            )

        prev = self.file_audits.get(task_key, [])
        self.file_audits[task_key] = prev + chunk_audit
        if chunk_audit:
            ok_n = sum(1 for e in chunk_audit if e["status"] == "OK")
            skip_n = sum(1 for e in chunk_audit if e["status"].startswith("SKIPPED"))
            self._log(
                f"[harness] {name}: {len(edits)} 条编辑建议, 生效 {ok_n} 条"
                + (f", 未生效 {skip_n} 条 (见改动清单)" if skip_n else "")
            )
        else:
            self._log(f"[harness] {name}: 模型未提交编辑 (无需修改)")

        # 块级完成全量 emit (与流式路径同语义): prefix + 本块 corrected,
        # 多 chunk 时对前端保持单调增长
        self._emit(self.on_stream, task_key, stream_prefix + corrected)

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
                # v4.1.8.1 (审计 H12): custom_prompt 只在"自定义"模式下生效
                if self.config.prompt_mode == "custom" and self.config.custom_prompt:
                    base = self.config.custom_prompt
                else:
                    mode_info = PROMPT_MODES.get(self.config.prompt_mode)
                    if not mode_info:
                        mode_info = PROMPT_MODES["strict"]
                    base = mode_info["system"]
                system_prompt_override = f"{base}\n\n{context_prefix}"

            # v4.1.8.1 (M4): stream_prefix = 已完成块拼接, 让 _stream_single 每次
            # emit 都是单调增长的全文; 块间不再把 UI 内容缩回本块 buffer
            # v5.1.0: harness 分块时附 scope 说明 (上下文只是参照物, 不可编辑;
            # agent1 §3.4 "edit 跨块不允许")
            part, tokens = await self._stream_single(
                task_key, chunk,
                system_prompt_override=system_prompt_override,
                stream_prefix="".join(all_parts),
                harness_chunk_note=CHUNK_SCOPE_NOTE if self._harness_active() else "",
            )
            all_parts.append(part)
            total_tokens += tokens
            # 记录本 chunk 完成的 FileResult
            chunk_result = FileResult(
                original=chunk, corrected=part, token_count=tokens,
            )
            chunk_results.append(chunk_result)
            completed_chunks.append(chunk_result)
            # v4.3.1 (UX #7): 块级进度推送 (file_key, done/total) — 单文件多 chunk
            # 时前端进度条不再长时间 0%. 走 _emit 统一异常保护 (勿裸调);
            # _call_api_stream 单块分支不进这里, 无分块意义不触发.
            self._emit(self.on_file_progress, task_key, i + 1, total)
            # 块完成全量 emit 已由 _stream_single 末尾 emit (prefix+corrected) 保证,
            # 不再重复推 (旧"块内 buffer / 块完成全量"交替正是闪断来源之一)
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
        # v5.1.0: 每次进入 (含整文件重试) 重建 audit, 防跨 attempt 重复累积
        self.file_audits.pop(task_key, None)
        # v5.3.0: 截断标记同理重建 (重试成功后不该留着上一轮的截断告警)
        self.truncated_keys.discard(task_key)

        # v4.4.2: 仅 Markdown 清洗模式 — 纯本地规则 (app/md_strip.py), 不调用 LLM.
        # 整文件处理 (不切块): 围栏代码块是跨行状态, 分块可能把围栏切开 (评审 P1-6);
        # strip 为纯 regex 无调用限制, 整文件对任意体量都安全. 标点修复开关在此
        # 链式生效 (皆本地零成本, 选项不静默失效; md 先剥标记, 标点上下文更准).
        if self.config.prompt_mode == "md_local":
            cleaned = strip_markdown(text)
            if self.config.punct_fix:
                cleaned, punct_stats = fix_punctuation_ex(cleaned, self._punct_options())
                name = self.tasks[task_key].file_path.name if task_key in self.tasks else task_key
                # v5.0.1 (审计 I-2): 收集移出 total 门控 — 只有落单引号
                # (imbalance 非空) 而 total=0 的文件之前连累积都没有
                self._collect_punct_reports(name, punct_stats)
                if punct_stats["total"]:
                    self._log(f"[标点] 本地修复 {punct_stats['total']} 处半角标点")
            # 空结果兜底 (评审 P2-16): 纯标记文件产出空文本会击穿 diff/is_done
            if not cleaned.strip() and text.strip():
                cleaned = text
                self._log("[清洗] Markdown 剥离结果为空, 保留原文")
            self._log("[清洗] Markdown 清洗完成 (整文件, 未调用 LLM)")
            return cleaned, 0, [FileResult(original=text, corrected=cleaned)]

        # Phase 1: 按 chunking 预设决定 max_chars (v5.2c: 双轨派生 — 与 _stream_single L475 同源)
        preset = self._effective_chunk_preset()
        if preset not in _CHUNK_PRESETS:
            preset = DEFAULT_CHUNK_PRESET
        max_chars = _CHUNK_PRESETS[preset]["max_chars"]
        chunks = self._split_text(text, max_chars, preset=preset)

        # v4.3.3: 仅标点修复模式 — 纯本地规则 (app/punct_fix.py), 不调用 LLM.
        # 复用同一分块/结果管线 (进度/diff/断点全部一致); 即时完成故不做流式 emit
        # (书级大文本单帧全量 evaluate_js 会触发降级问题, 见 DeAI 评审#1).
        if self.config.prompt_mode == "punct_local":
            out_parts: list[str] = []
            local_results: list[FileResult] = []
            for c in chunks:
                fixed, punct_stats = fix_punctuation_ex(c, self._punct_options())
                # v5.0.1 (审计 I-1): 引号不平衡报告在此收集 — 旧版只认 strict
                # 路径, 「仅标点修复」模式(报告的最主用场)从不显示不平衡报告
                name = self.tasks[task_key].file_path.name if task_key in self.tasks else task_key
                self._collect_punct_reports(name, punct_stats)
                out_parts.append(fixed)
                local_results.append(FileResult(original=c, corrected=fixed))
            self._log(f"[标点] 本地修复完成 ({len(chunks)} 块, 未调用 LLM)")
            return "".join(out_parts), 0, local_results

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
        # v4.1.8.2 (审计 B2): 事件轮询只在"收到下一个流事件/暂停轮询点"才检查,
        # 在途 HTTP await (首字节最长达 timeout=120s) 无法被 Event 打断 — 旧实现
        # 下慢服务器会让 bridge 的 join(5s) 必超时, 用户被反复拒绝无法启动新任务.
        # 强制 cancel 主任务, 所有 await 立即抛 CancelledError, 各层统一收尾.
        if self._main_task is not None and self._loop is not None and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._main_task.cancel)
            except RuntimeError:
                pass  # loop 已关闭, 任务随线程退出
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
