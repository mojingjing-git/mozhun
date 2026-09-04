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
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
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
