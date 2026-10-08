"""chunk 级别 lifecycle 测试 (Phase 3)。

覆盖:
- FileResult 新字段 (chunks_results, failed_chunks, schema_version)
- FileResult property (is_chunked, corrected_full, is_done)
- 序列化往返 (含 chunks_results 嵌套)
- v1 → v2 断点迁移 (旧 dict 缺新字段时默认空)
- CANCELLED 状态断点不加载
- 整文件 _process_file_async 的重试/取消语义
"""
import sys
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))  # v6.0: tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

from app.utils import (
    FileTask, FileResult, TaskStatus, ProjectConfig,
    save_checkpoint, load_checkpoint, CHECKPOINT_DIR,
)
from app.processor import ProcessingEngine, _CHUNK_PRESETS

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         -> {detail}")


def test_fileresult_chunks_results():
    """FileResult 字段 + property 正确。"""
    print("\n--- FileResult 字段 ---")
    r = FileResult(original="abc", corrected="xyz")
    check("默认 chunks_results=[]", r.chunks_results == [])
    check("默认 failed_chunks=[]", r.failed_chunks == [])
    check("默认 schema_version=2", r.schema_version == 2)
    check("is_chunked=False (空)", not r.is_chunked)
    check("corrected_full=corrected (单)", r.corrected_full == "xyz")

    r2 = FileResult(original="abc")
    r2.chunks_results = [
        FileResult(original="a", corrected="A"),
        FileResult(original="b", corrected="B"),
    ]
    check("is_chunked=True (2 块)", r2.is_chunked)
    check("corrected_full 拼接", r2.corrected_full == "AB")
    check("is_done (无 error)", r2.is_done)


def test_fileresult_serialization():
    """FileResult.to_dict/from_dict 包含新字段。"""
    print("\n--- FileResult 序列化 ---")
    r = FileResult(original="x", corrected="y", elapsed=1.0)
    r.chunks_results = [FileResult(original="a", corrected="A", elapsed=0.5)]
    r.failed_chunks = [1]
    r.schema_version = 2
    d = r.to_dict()
    check("to_dict 包含 chunks_results", "chunks_results" in d)
    check("to_dict 包含 failed_chunks", "failed_chunks" in d)
    check("to_dict schema_version=2", d["schema_version"] == 2)
    check("to_dict chunks_results 是 list", isinstance(d["chunks_results"], list))
    check("to_dict chunks_results[0] 是 dict", isinstance(d["chunks_results"][0], dict))
    r2 = FileResult.from_dict(d)
    check("from_dict 还原 chunks_results", len(r2.chunks_results) == 1)
    check("from_dict 还原 failed_chunks", r2.failed_chunks == [1])
    check("from_dict 还原 schema_version", r2.schema_version == 2)
    check("from_dict 还原 corrected", r2.corrected == "y")


def test_v1_checkpoint_migration():
    """旧 v1 断点 (无 schema_version / chunks_results 字段) 自动迁移。"""
    print("\n--- v1 → v2 断点迁移 ---")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test content'); tmp = Path(f.name)

    # 模拟 v1 断点: 没有 schema_version / chunks_results 字段
    safe_name = str(tmp).replace(":", "_").replace("/", "_").replace("\\", "_")
    v1_data = {
        "file_path": str(tmp),
        "status": "completed",
        "original_text": "test content",
        "result": {
            "original": "test content",
            "corrected": "fixed content",
            "token_count": 10,
            "elapsed": 1.0,
            "error": None,
            # 注意: v1 没有 chunks_results / failed_chunks / schema_version
        },
    }
    (CHECKPOINT_DIR / f"{safe_name}.json").write_text(
        json.dumps(v1_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 读
    loaded = load_checkpoint(tmp)
    check("v1 断点可读", loaded is not None)
    check("v1 断点 status=COMPLETED", loaded.status == TaskStatus.COMPLETED)
    check("v1 断点 result.corrected 有值", loaded.result.corrected == "fixed content")
    check("v1 断点 result.chunks_results=[]", loaded.result.chunks_results == [])
    check("v1 断点 result.failed_chunks=[]", loaded.result.failed_chunks == [])
    check("v1 断点 result.schema_version=2 (默认)", loaded.result.schema_version == 2)

    # 清理
    (CHECKPOINT_DIR / f"{safe_name}.json").unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)


def test_cancelled_status_no_reload():
    """CANCELLED 状态断点不加载 (强制重跑)。"""
    print("\n--- CANCELLED 状态 ---")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test'); tmp = Path(f.name)

    safe_name = str(tmp).replace(":", "_").replace("/", "_").replace("\\", "_")
    cancelled_data = {
        "file_path": str(tmp),
        "status": "cancelled",
        "original_text": "test",
        "result": {
            "original": "test",
            "corrected": "test",
            "error": "用户取消",
        },
    }
    (CHECKPOINT_DIR / f"{safe_name}.json").write_text(
        json.dumps(cancelled_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    loaded = load_checkpoint(tmp)
    check("CANCELLED 断点不加载", loaded is None)

    (CHECKPOINT_DIR / f"{safe_name}.json").unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)


def test_chunked_file_result_is_done():
    """分块文件 is_done 逻辑: 失败时为 False。"""
    print("\n--- is_done 逻辑 ---")
    r = FileResult(original="abc", corrected="ABC")
    r.chunks_results = [
        FileResult(original="a", corrected="A"),
        FileResult(original="b", corrected="B"),
        FileResult(original="c", corrected="C", error="Auth failed"),  # 失败
    ]
    check("有 error 的 chunk → is_done=False", not r.is_done)

    r2 = FileResult(original="abc", corrected="ABC")
    r2.chunks_results = [
        FileResult(original="a", corrected="A"),
        FileResult(original="b", corrected="B"),
        FileResult(original="c", corrected="C"),
    ]
    check("全部无 error → is_done=True", r2.is_done)

    # 单 chunk 场景
    r3 = FileResult(original="abc", corrected="ABC")
    check("单 chunk 无 chunks_results 走 bool(corrected) && !error", r3.is_done)

    r4 = FileResult(original="abc", corrected="")
    check("单 chunk 空 corrected → is_done=False", not r4.is_done)


def test_projectconfig_context_fields():
    """ProjectConfig context 字段默认 + 序列化。"""
    print("\n--- ProjectConfig context 字段 ---")
    c = ProjectConfig()
    check("默认 context_max_chars=800", c.context_max_chars == 800)
    check("默认 context_max_chunks=2", c.context_max_chunks == 2)
    d = c.to_dict()
    check("to_dict 包含 context_max_chars", "context_max_chars" in d)
    check("to_dict 包含 context_max_chunks", "context_max_chunks" in d)
    c2 = ProjectConfig.from_dict(d)
    check("from_dict 还原 context_max_chars", c2.context_max_chars == 800)
    check("from_dict 还原 context_max_chunks", c2.context_max_chunks == 2)

    # 旧 config 缺这字段时回退默认
    c3 = ProjectConfig.from_dict({"api_base": "x"})
    check("旧 config 缺字段 → context_max_chars=800", c3.context_max_chars == 800)
    check("旧 config 缺字段 → context_max_chunks=2", c3.context_max_chunks == 2)


def test_process_file_chunks_results_filled():
    """_process_file_async 完成后 task.result.chunks_results 真正被填充。"""
    print("\n--- 整文件处理 chunks_results 填充 ---")
    import asyncio

    async def fake_call_api_stream(self, task_key, text):
        """mock: 返回 (corrected, tokens, [FileResult])。"""
        chunks = [FileResult(original=text, corrected=text.upper(), token_count=10)]
        return text.upper(), 10, chunks

    async def run():
        with patch.object(ProcessingEngine, '_call_api_stream', fake_call_api_stream):
            engine = ProcessingEngine(ProjectConfig(
                api_base="http://x", model="m", max_retries=0, concurrency=1,
                chunking_preset="balanced",
            ))
            engine._loop = asyncio.get_running_loop()
            engine._pause_event = threading.Event()
            engine._pause_event.set()

            # mock save_checkpoint_async 避免 IO
            with patch('app.processor.save_checkpoint_async', new=AsyncMock()):
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False, encoding='utf-8'
                ) as f:
                    f.write("hello world")
                    tmp = Path(f.name)

                task = FileTask(file_path=tmp, original_text="hello world")
                engine.tasks[str(tmp)] = task
                await engine._process_file_async(str(tmp), task)
                tmp.unlink(missing_ok=True)

                return task

    task = asyncio.run(run())
    check("task.status=COMPLETED", task.status == TaskStatus.COMPLETED)
    check("task.result 存在", task.result is not None)
    check("task.result.chunks_results 不空",
          len(task.result.chunks_results) > 0)
    check("task.result.schema_version=2", task.result.schema_version == 2)
    check("task.result.corrected_full 非空", len(task.result.corrected_full) > 0)
    check("task.result.corrected 全大写", task.result.corrected == "HELLO WORLD")


def test_process_file_non_retryable_error_no_retry():
    """不可重试错误 (AuthError) 立即标 FAILED, 不重试。"""
    print("\n--- 不可重试错误不重试 ---")
    import asyncio
    from openai import AuthenticationError

    call_count = 0

    async def fake_call_api_stream(self, task_key, text):
        nonlocal call_count
        call_count += 1
        # 直接构造一个 AuthenticationError 实例 (用 stub 避开 openai 库 __init__ 复杂性)
        err = AuthenticationError.__new__(AuthenticationError)
        Exception.__init__(err, "invalid api key")
        err.status_code = 401
        raise err

    async def run():
        with patch.object(ProcessingEngine, '_call_api_stream', fake_call_api_stream):
            engine = ProcessingEngine(ProjectConfig(
                api_base="http://x", model="m", max_retries=3, concurrency=1,
            ))
            engine._loop = asyncio.get_running_loop()
            engine._pause_event = threading.Event()
            engine._pause_event.set()
            with patch('app.processor.save_checkpoint_async', new=AsyncMock()):
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False, encoding='utf-8'
                ) as f:
                    f.write("test")
                    tmp = Path(f.name)
                task = FileTask(file_path=tmp, original_text="test")
                engine.tasks[str(tmp)] = task
                await engine._process_file_async(str(tmp), task)
                tmp.unlink(missing_ok=True)
                return task

    task = asyncio.run(run())
    check("AuthError 只调 1 次 (不重试)", call_count == 1)
    check("task.status=FAILED", task.status == TaskStatus.FAILED)
    check("task.result.error 包含 AuthenticationError",
          "AuthenticationError" in (task.result.error or ""))


def test_process_file_rate_limit_retries():
    """可重试错误 (RateLimit) 整文件重试。"""
    print("\n--- RateLimit 整文件重试 ---")
    import asyncio
    from openai import RateLimitError

    call_count = 0

    async def fake_call_api_stream(self, task_key, text):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # 前两次 RateLimit — 用 stub 避开 openai __init__ 复杂性
            err = RateLimitError.__new__(RateLimitError)
            Exception.__init__(err, "rate limit")
            err.status_code = 429
            raise err
        # 第三次成功
        return text, 10, [FileResult(original=text, corrected=text, token_count=10)]

    async def run():
        with patch.object(ProcessingEngine, '_call_api_stream', fake_call_api_stream):
            # 短 max_retries 避免测试太慢
            engine = ProcessingEngine(ProjectConfig(
                api_base="http://x", model="m", max_retries=2, concurrency=1,
            ))
            engine._loop = asyncio.get_running_loop()
            engine._pause_event = threading.Event()
            engine._pause_event.set()
            with patch('app.processor.save_checkpoint_async', new=AsyncMock()):
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False, encoding='utf-8'
                ) as f:
                    f.write("test")
                    tmp = Path(f.name)
                task = FileTask(file_path=tmp, original_text="test")
                engine.tasks[str(tmp)] = task
                await engine._process_file_async(str(tmp), task)
                tmp.unlink(missing_ok=True)
                return task

    task = asyncio.run(run())
    # max_retries=2, 1 + 2 = 3 次调用
    check("RateLimit 重试 3 次 (1+2)", call_count == 3)
    check("task.status=COMPLETED", task.status == TaskStatus.COMPLETED)


def test_rate_limit_exhausted_finalizes_stats():
    """B1 (v4.1.8.1): RateLimit 重试耗尽必须补 stats 计数 + on_stats_update。

    旧 bug: 429 分支耗尽 break 到 for 循环外只置 FAILED/存断点/发回调, 漏
    completed_files/failed_files 自增与 on_stats_update -> 进度永远少 1
    (生产最常见失败路径).
    """
    print("\n--- RateLimit 耗尽收尾 (B1) ---")
    import asyncio
    from openai import RateLimitError

    call_count = 0
    stats_updates = []

    async def fake_call_api_stream(self, task_key, text):
        nonlocal call_count
        call_count += 1
        err = RateLimitError.__new__(RateLimitError)
        Exception.__init__(err, "rate limit")
        err.status_code = 429
        err.retry_after = 0.01  # 快速耗尽, 不等真实退避
        raise err

    async def run():
        with patch.object(ProcessingEngine, '_call_api_stream', fake_call_api_stream):
            engine = ProcessingEngine(ProjectConfig(
                api_base="http://x", model="m", max_retries=1, concurrency=1,
            ))
            engine._pause_event = threading.Event()
            engine._pause_event.set()
            engine.stats.start_time = time.time()
            engine.on_stats_update = lambda s: stats_updates.append(s)
            with patch('app.processor.save_checkpoint_async', new=AsyncMock()) as mock_save:
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False, encoding='utf-8'
                ) as f:
                    f.write("test")
                    tmp = Path(f.name)
                task = FileTask(file_path=tmp, original_text="test")
                engine.tasks[str(tmp)] = task
                await engine._process_file_async(str(tmp), task)
                tmp.unlink(missing_ok=True)
                return engine, task, mock_save

    engine, task, mock_save = asyncio.run(run())
    check("RateLimit 耗尽调 2 次 (1+1)", call_count == 2)
    check("task.status=FAILED", task.status == TaskStatus.FAILED)
    check("completed_files 已自增 (B1)", engine.stats.completed_files == 1)
    check("failed_files 已自增 (B1)", engine.stats.failed_files == 1)
    check("on_stats_update 已推送 (B1)", len(stats_updates) >= 1)
    check("断点已存 (save_checkpoint_async)", mock_save.await_count >= 1)
    check("result.error 含 RateLimitError",
          bool(task.result) and "RateLimitError" in (task.result.error or ""))


def test_cancel_before_start_finalizes():
    """B2 (v4.1.8.1): cancel 落在处理起点/排队的文件必须完整收尾。

    旧 bug: 文件进入 _process_file_async 时若已取消 (排队文件拿到 semaphore
    才进来, cancel 期间常见), 裸 return -> 无 result/CANCELLED/断点/stats/
    回调, UI 永远卡"排队中", 进度不收敛.
    """
    print("\n--- cancel 早退完整收尾 (B2) ---")
    import asyncio

    async def run():
        engine = ProcessingEngine(ProjectConfig(
            api_base="http://x", model="m", concurrency=1,
        ))
        engine._pause_event = threading.Event()
        engine._pause_event.set()
        engine.stats.start_time = time.time()
        engine.cancel()  # 处理开始前就取消
        done_calls = []
        engine.on_file_done = lambda k, status: done_calls.append(k)  # v4.1.8.2 (C2): 回调附 status
        with patch('app.processor.save_checkpoint_async', new=AsyncMock()) as mock_save:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', delete=False, encoding='utf-8'
            ) as f:
                f.write("test")
                tmp = Path(f.name)
            task = FileTask(file_path=tmp, original_text="test")
            engine.tasks[str(tmp)] = task
            await engine._process_file_async(str(tmp), task)
            tmp.unlink(missing_ok=True)
            return engine, task, done_calls, mock_save

    engine, task, done_calls, mock_save = asyncio.run(run())
    check("task.status=CANCELLED", task.status == TaskStatus.CANCELLED)
    check("task.result 已落 (不留空壳)", task.result is not None)
    check("error_message=用户取消", task.error_message == "用户取消")
    check("completed_files 已自增", engine.stats.completed_files == 1)
    check("on_file_done 已回调", len(done_calls) == 1)
    check("CANCELLED 断点已存", mock_save.await_count == 1)


def test_custom_prompt_only_when_mode_custom():
    """H12 (v4.1.8.1): custom_prompt 残留不再无条件覆盖 prompt 模式.

    旧 bug: _stream_single 里 custom_prompt 非空即覆盖任意模式 -> 切回 strict/
    polish 后实际仍跑旧自定义 prompt (与 UI 承诺矛盾). 现仅 prompt_mode=custom 生效.
    """
    print("\n--- H12: custom_prompt 只在自定义模式生效 ---")
    import asyncio
    from app.templates import PROMPT_MODES

    async def run(mode, custom):
        # v5.1.0: harness_enabled=False — 本测试针对流式路径的 prompt 选择,
        # strict + harness(默认开) 会改走非流式 Edit 工具分支
        engine = ProcessingEngine(ProjectConfig(
            api_base="http://x", model="m", prompt_mode=mode, custom_prompt=custom,
            harness_enabled=False,
        ))
        engine._pause_event = threading.Event()
        engine._pause_event.set()
        ev = MagicMock()
        ev.choices = [MagicMock()]
        ev.choices[0].delta.content = "ok"
        ev.usage = None

        async def fs():
            yield ev

        mc = AsyncMock()
        mc.chat.completions.create = AsyncMock(return_value=fs())
        engine._client = mc
        await engine._stream_single("k", "文本")
        return mc.chat.completions.create.await_args.kwargs["messages"][0]["content"]

    # strict 模式 + custom_prompt 残留 -> 用 strict system, 不用残留文本
    sys1 = asyncio.run(run("strict", "残留的旧自定义prompt"))
    check("strict 忽略残留 custom_prompt (H12)",
          sys1 == PROMPT_MODES["strict"]["system"] and "残留的旧自定义prompt" not in sys1)
    # custom 模式 + custom_prompt 有值 -> 用 custom
    sys2 = asyncio.run(run("custom", "我的自定义prompt"))
    check("custom 模式用 custom_prompt (H12)", sys2 == "我的自定义prompt")
    # custom 模式 + custom_prompt 空 -> 兜底 strict system
    sys3 = asyncio.run(run("custom", ""))
    check("custom 空 prompt 兜底 strict (H12)", sys3 == PROMPT_MODES["strict"]["system"])


def test_m4_stream_monotonic_fulltext():
    """M4 (v4.1.8.1): 多 chunk 流式 on_stream 单调增长 (前缀链), 不闪断.

    旧 bug: 块内推本块 buffer、块完成推全量 -> 前端替换渲染时块2中途把
    已显示的块1覆盖成短片段 (回缩). 修后每次 emit = 已完成前缀 + 当前累积.
    """
    print("\n--- M4: 多 chunk 流式单调全量 ---")
    import asyncio

    async def run():
        # v5.1.0: harness_enabled=False — 本测试针对流式 on_stream 前缀链,
        # strict + harness(默认开) 会改走非流式 Edit 工具分支
        cfg = ProjectConfig(api_base="http://x", model="m", chunking_preset="fast",
                            harness_enabled=False)
        eng = ProcessingEngine(cfg)
        eng._pause_event = threading.Event()
        eng._pause_event.set()
        received = []
        eng.on_stream = lambda k, t: received.append(t)

        def make_ev(content, total_tokens=None):
            ev = MagicMock()
            ev.choices = [MagicMock()]
            ev.choices[0].delta.content = content
            ev.usage = None
            if total_tokens:
                ev.usage = MagicMock()
                ev.usage.total_tokens = total_tokens
            return ev

        calls = {"n": 0}

        async def gen(items):
            for it in items:
                yield it

        async def fake_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return gen([make_ev("块一甲", 1), make_ev("块一乙", 2)])
            return gen([make_ev("块二甲", 3), make_ev("块二乙", 4)])

        mc = AsyncMock()
        mc.chat.completions.create = AsyncMock(side_effect=fake_create)
        eng._client = mc
        # >2000 字符, 强制拆多块
        text = "第一段内容。\n\n" + ("第二段足够长要拆开的句子。" * 250)
        result, tokens, chunks = await eng._call_api_stream("k", text)
        return result, received, chunks

    result, received, chunks = asyncio.run(run())
    check("M4 多块输出完整", "块一甲块一乙" in result and "块二甲块二乙" in result)
    check("M4 确实拆了 ≥2 块", len(chunks) >= 2)
    mono = all(received[i + 1].startswith(received[i]) for i in range(len(received) - 1))
    check("M4 emit 单调前缀链 (不闪断)", len(received) >= 1 and mono)
    check("M4 最终 emit = 全量", received[-1] == result)


def test_m6_think_only_output_failed():
    """v5.4 (PLAN §2 D5): 纯思维链输出剥后为空 → 走既有失败链 → FAILED (不静默成功)."""
    print("\n--- M6: 纯思维链输出剥后为空 → FAILED ---")
    import asyncio

    async def run():
        cfg = ProjectConfig(api_base="http://x", model="m", chunking_preset="fast",
                            harness_enabled=False, max_retries=0)
        engine = ProcessingEngine(cfg)
        engine._loop = asyncio.get_running_loop()
        engine._pause_event = threading.Event()
        engine._pause_event.set()

        def make_ev(content):
            ev = MagicMock()
            ev.choices = [MagicMock()]
            ev.choices[0].delta.content = content
            ev.choices[0].finish_reason = None
            ev.usage = None
            return ev

        async def gen():
            yield make_ev("<think>只有推理过程, 没有正文</think>")

        mc = AsyncMock()
        mc.chat.completions.create = AsyncMock(return_value=gen())
        engine._client = mc

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8'
        ) as f:
            f.write("原文内容。")
            tmp = Path(f.name)
        try:
            task = FileTask(file_path=tmp, original_text="原文内容。")
            engine.tasks[str(tmp)] = task
            await engine._process_file_async(str(tmp), task)
        finally:
            tmp.unlink(missing_ok=True)
        return task

    task = asyncio.run(run())
    check("纯思维链 → FAILED (不静默成功)", task.status == TaskStatus.FAILED, str(task.status))
    check("corrected 不回填原文", task.result.corrected == "")
    check("error 含思维链语义", "思维链" in (task.result.error or ""), task.result.error)


def test_m5_backoff_cancel_interrupts():
    """M5 (v4.1.8.1): 退避 asyncio.sleep 可被 cancel 中断.

    旧 bug: retry_after 5s 的 RateLimit 退避不可中断, cancel 后任务仍卡 5s.
    修后 0.2s 分段感知 cancel, 立即走 CANCELLED 完整收尾.
    """
    print("\n--- M5: 退避可被 cancel 中断 ---")
    import asyncio
    from openai import RateLimitError

    async def fake_call_api_stream(self, task_key, text):
        err = RateLimitError.__new__(RateLimitError)
        Exception.__init__(err, "rate limit")
        err.status_code = 429
        err.retry_after = 5.0  # 旧实现会傻等 5s
        raise err

    async def run():
        with patch.object(ProcessingEngine, '_call_api_stream', fake_call_api_stream):
            engine = ProcessingEngine(ProjectConfig(
                api_base="http://x", model="m", max_retries=2, concurrency=1,
            ))
            engine._pause_event = threading.Event()
            engine._pause_event.set()
            engine.stats.start_time = time.time()
            with patch('app.processor.save_checkpoint_async', new=AsyncMock()):
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False, encoding='utf-8'
                ) as f:
                    f.write("test")
                    tmp = Path(f.name)
                task = FileTask(file_path=tmp, original_text="test")
                engine.tasks[str(tmp)] = task
                worker = asyncio.create_task(engine._process_file_async(str(tmp), task))
                await asyncio.sleep(0.3)
                engine.cancel()
                # 2s 兜底: 旧实现 5s 才退出会触发 TimeoutError 暴露 bug
                await asyncio.wait_for(worker, timeout=2.0)
                tmp.unlink(missing_ok=True)
                return engine, task

    engine, task = asyncio.run(run())
    check("M5 cancel 中断退避 (<2s 内 CANCELLED)", task.status == TaskStatus.CANCELLED)
    check("M5 取消完整收尾", task.result is not None)


def test_v530_preserve_done_and_force_rerun():
    """v5.3.0 (PLAN §2 D9 / §6.1): 引擎收尾的断点保护 + 强制重跑出口。

    单结果槽 + 双入口的核心护栏:
      - 另一条轨失败/取消收尾 **不覆盖** 磁盘上已完成的结果 (回原轨仍能命中断点)
      - 强制重跑 (force_rerun → 重新执行 → 成功写点) **仍然能覆盖** 被保护的结果
    """
    print("\n--- v5.3.0: 断点保护 + 强制重跑出口 ---")
    import asyncio
    from app.utils import compute_prompt_hash_for_config

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False,
                                     encoding='utf-8') as f:
        f.write("原文内容。" * 40)
        tmp = Path(f.name)

    # 逐条轨跑完 → 磁盘上是"逐条结果"
    cfg_harness = ProjectConfig(api_base="http://x", model="m", max_retries=0,
                                concurrency=1, chunking_preset_harness="large",
                                workflow_mode="harness")
    h_harness = compute_prompt_hash_for_config(cfg_harness)
    save_checkpoint(tmp, FileTask(
        file_path=tmp, status=TaskStatus.COMPLETED, original_text="原文内容。" * 40,
        result=FileResult(original="原文内容。" * 40, corrected="逐条结果",
                          prompt_hash=h_harness),
    ))

    async def run_fail_then_rerun():
        # 整篇轨尝试 → 失败收尾 (preserve_done=True)
        cfg_rewrite = ProjectConfig(api_base="http://x", model="m", max_retries=0,
                                    concurrency=1, chunking_preset_rewrite="balanced",
                                    workflow_mode="rewrite")
        eng = ProcessingEngine(cfg_rewrite)
        eng._loop = asyncio.get_running_loop()
        eng._pause_event = threading.Event()
        eng._pause_event.set()
        key = str(tmp)
        task = FileTask(file_path=tmp, original_text="原文内容。" * 40)
        eng.tasks[key] = task
        eng._current_prompt_hash = compute_prompt_hash_for_config(cfg_rewrite)
        await eng._finalize_failed(key, task, time.time(), "BadRequest",
                                   "模拟整篇轨失败")

        # 回到逐条轨: 旧结果仍在, 且仍能命中该轨断点
        cached = load_checkpoint(tmp, expected_hash=h_harness)
        kept = (cached is not None and cached.status == TaskStatus.COMPLETED
                and cached.result is not None
                and cached.result.corrected == "逐条结果")

        # 强制重跑: 重新执行 + 成功写点 (默认 preserve_done=False) → 覆盖
        async def fake_stream(self, task_key, text):
            return text.replace("内容", "正文"), 10, [
                FileResult(original=text, corrected=text.replace("内容", "正文"))
            ]

        eng2 = ProcessingEngine(cfg_harness)
        eng2._loop = asyncio.get_running_loop()
        eng2._pause_event = threading.Event()
        eng2._pause_event.set()
        eng2._current_prompt_hash = h_harness
        task2 = FileTask(file_path=tmp, original_text="原文内容。" * 40)
        eng2.tasks[key] = task2
        with patch.object(ProcessingEngine, '_call_api_stream', fake_stream):
            await eng2._process_file_async(key, task2)
        after = load_checkpoint(tmp, expected_hash=h_harness)
        overwritten = (after is not None and after.result is not None
                       and after.result.corrected == "原文正文。" * 40)
        return kept, overwritten

    kept, overwritten = asyncio.run(run_fail_then_rerun())
    tmp.unlink(missing_ok=True)
    check("另一条轨失败不覆盖已完成结果", kept)
    check("强制重跑仍能覆盖 (出口没被堵死)", overwritten)


def test_v550_truncated_not_reused_d9_kept():
    """v5.5 (I-3): 截断结果**不复用**, 但 **D9 判据不被削弱**。

    两条必须同时成立:
      1. load_checkpoint 见 truncated=True → None (视为未完成, 下次重跑);
      2. _checkpoint_is_done 仍认它是"有成功结果" → 后续失败/取消收尾的
         preserve_done 不会把它冲掉 (D9 保护"另一条轨的好结果")。
    只做 1 不做 2 会把 D9 打掉; 只做 2 不做 1 则截断结果永久锁死。
    """
    print("\n--- v5.5: 截断结果 × D9 保护 ---")
    import json
    import tempfile
    from pathlib import Path
    from app.utils import (
        FileResult, FileTask, ProjectConfig, TaskStatus,
        _checkpoint_file, _checkpoint_is_done, compute_prompt_hash_for_config,
        load_checkpoint, save_checkpoint,
    )

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False,
                                     encoding='utf-8') as f:
        f.write('原文' * 50)
        tmp = Path(f.name)
    try:
        cfg = ProjectConfig(api_base='http://x', model='m', harness_enabled=False)
        h = compute_prompt_hash_for_config(cfg)
        cp_file = _checkpoint_file(tmp)

        # 1) 截断但成功的断点
        save_checkpoint(tmp, FileTask(
            file_path=tmp, status=TaskStatus.COMPLETED, original_text='原文' * 50,
            result=FileResult(original='原文' * 50, corrected='半篇结果',
                              prompt_hash=h, truncated=True),
        ))
        check("截断结果不复用 (load_checkpoint → None)",
              load_checkpoint(tmp, expected_hash=h) is None)
        check("D9 判据仍认它 (有成功结果)", _checkpoint_is_done(cp_file) is True)

        # 2) 失败/取消收尾 (preserve_done=True) 不得覆盖它
        save_checkpoint(tmp, FileTask(
            file_path=tmp, status=TaskStatus.CANCELLED, original_text='原文' * 50,
            result=FileResult(original='原文' * 50, corrected='', error='已取消',
                              prompt_hash=h),
        ), preserve_done=True)
        data = json.loads(cp_file.read_text(encoding='utf-8'))
        check("取消收尾未覆盖截断结果",
              data["status"] == "completed"
              and data["result"]["corrected"] == "半篇结果", str(data.get("status")))

        # 3) 成功写点仍可覆盖 (下次真跑完能落新结果)
        save_checkpoint(tmp, FileTask(
            file_path=tmp, status=TaskStatus.COMPLETED, original_text='原文' * 50,
            result=FileResult(original='原文' * 50, corrected='新结果', prompt_hash=h),
        ))
        check("成功结果仍可覆盖截断结果",
              load_checkpoint(tmp, expected_hash=h) is not None)
        check("覆盖后不再标截断",
              load_checkpoint(tmp, expected_hash=h).result.truncated is False)
    finally:
        tmp.unlink(missing_ok=True)


def main():
    print("=" * 60)
    print("  chunk 级别 lifecycle 测试")
    print("=" * 60)
    tests = [
        test_fileresult_chunks_results,
        test_fileresult_serialization,
        test_v1_checkpoint_migration,
        test_cancelled_status_no_reload,
        test_chunked_file_result_is_done,
        test_projectconfig_context_fields,
        test_process_file_chunks_results_filled,
        test_process_file_non_retryable_error_no_retry,
        test_process_file_rate_limit_retries,
        test_rate_limit_exhausted_finalizes_stats,
        test_cancel_before_start_finalizes,
        test_custom_prompt_only_when_mode_custom,   # v4.1.8.1 H12
        test_m4_stream_monotonic_fulltext,          # v4.1.8.1 M4
        test_m6_think_only_output_failed,           # v5.4 D5: 剥后为空 → FAILED
        test_m5_backoff_cancel_interrupts,          # v4.1.8.1 M5
        test_v530_preserve_done_and_force_rerun,    # v5.3.0 D9 + 强制重跑出口
        test_v550_truncated_not_reused_d9_kept,     # v5.5 I-3: 截断 × D9
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            check(t.__name__, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    print()
    print("=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
