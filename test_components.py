"""
组件测试 + 冒烟测试
运行: python test_components.py
覆盖: 每个模块的独立功能、边界条件、集成路径
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

passed = 0
failed = 0
errors_list = []

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        errors_list.append(name)
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         -> {detail}")


# ============================================================
# 组件测试: utils.py
# ============================================================

def test_utils():
    print("\n--- utils.py ---")
    from app.utils import (
        ProjectConfig, FileTask, FileResult, TaskStatus, ProcessStats,
        save_config, load_config, save_checkpoint, load_checkpoint, read_file_text,
        CONFIG_FILE, CHECKPOINT_DIR,
    )

    # ProjectConfig 序列化完整往返
    c = ProjectConfig(
        api_base="http://test", api_key="sk-123", model="gpt-4",
        timeout=60, max_retries=5, concurrency=8,
        output_format="json", prompt_mode="polish",
        custom_prompt="custom system prompt", temperature=0.3,
    )
    d = c.to_dict()
    c2 = ProjectConfig.from_dict(d)
    check("ProjectConfig 往返完整", c == c2)
    check("ProjectConfig 包含所有字段", len(d) == 15)  # v3.0+ 加了 chunking_preset + schema_version + context_max_chars + context_max_chunks

    # ProjectConfig 边界值
    c_empty = ProjectConfig()
    check("ProjectConfig 空配置可序列化", c_empty.to_dict() is not None)
    check("ProjectConfig 空配置可反序列化", ProjectConfig.from_dict({}) is not None)

    # FileResult 序列化
    r = FileResult(original="a", corrected="b", token_count=10, elapsed=1.5, error=None)
    rd = r.to_dict()
    r2 = FileResult.from_dict(rd)
    check("FileResult 往返", r.original == r2.original and r.corrected == r2.corrected)

    # FileResult 带 error
    r_err = FileResult(original="a", corrected="a", error="ConnectionError: timeout")
    check("FileResult 带 error", r_err.to_dict()["error"] is not None)

    # FileTask.is_done
    t1 = FileTask(file_path=Path("/tmp/a.txt"), original_text="a")
    check("FileTask 新建 is_done=False", not t1.is_done)
    t1.result = FileResult(original="a", corrected="b")
    check("FileTask 有结果 is_done=True", t1.is_done)
    t1.result.error = "err"
    check("FileTask 有错误 is_done=False", not t1.is_done)

    # FileTask 序列化
    t2 = FileTask(file_path=Path("/tmp/b.txt"), original_text="hello")
    t2.status = TaskStatus.COMPLETED
    t2.result = FileResult(original="hello", corrected="hello fixed", token_count=5)
    td = t2.to_dict()
    t2r = FileTask.from_dict(td)
    check("FileTask 往返", t2r.result.corrected == "hello fixed")

    # ProcessStats
    s = ProcessStats(total_files=10, completed_files=5, total_tokens=1000, elapsed=20.0)
    check("ProcessStats speed", abs(s.speed - 50.0) < 0.1)
    check("ProcessStats progress", abs(s.progress_pct - 50.0) < 0.1)
    check("ProcessStats eta > 0", s.eta > 0)
    s0 = ProcessStats()
    check("ProcessStats 空 speed=0", s0.speed == 0.0)
    check("ProcessStats 空 eta=0", s0.eta == 0.0)
    check("ProcessStats 空 progress=0", s0.progress_pct == 0.0)

    # save/load config
    cfg = ProjectConfig(api_base="http://test", model="test-model")
    save_config(cfg)
    loaded = load_config()
    check("save/load config", loaded.api_base == "http://test" and loaded.model == "test-model")

    # save/load checkpoint
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("checkpoint test")
        tmp = Path(f.name)
    task = FileTask(file_path=tmp, original_text="checkpoint test")
    task.status = TaskStatus.COMPLETED
    task.result = FileResult(original="checkpoint test", corrected="fixed")
    save_checkpoint(tmp, task)
    loaded_cp = load_checkpoint(tmp)
    tmp.unlink(missing_ok=True)
    check("save/load checkpoint", loaded_cp is not None and loaded_cp.is_done)

    # read_file_text 多编码
    for encoding, content in [("utf-8", "Hello 世界"), ("gbk", "中文测试")]:
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(content.encode(encoding))
            tmp = Path(f.name)
        text = read_file_text(tmp)
        tmp.unlink()
        check(f"read_file_text {encoding}", len(text) > 0)

    # read_file_text 非法字节
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
        f.write(b'\x80\x81\x82\x83')
        tmp = Path(f.name)
    text = read_file_text(tmp)
    tmp.unlink()
    check("read_file_text 非法字节不崩溃", len(text) > 0)


# ============================================================
# 组件测试: templates.py
# ============================================================

def test_templates():
    print("\n--- templates.py ---")
    from app.templates import API_TEMPLATES, PROMPT_MODES

    check("API_TEMPLATES 非空", len(API_TEMPLATES) > 0)
    for t in API_TEMPLATES:
        check(f"模板 {t['name']} 有必需字段", all(k in t for k in ["name", "api_base", "model", "api_key"]))

    check("PROMPT_MODES 非空", len(PROMPT_MODES) > 0)
    for key, info in PROMPT_MODES.items():
        check(f"模式 {key} 有 label", "label" in info)
        check(f"模式 {key} 有 system", "system" in info)
        check(f"模式 {key} 有 few-shot", "## 示例" in info["system"])

    # 检查 prompt 不为空且有实质内容
    for key, info in PROMPT_MODES.items():
        check(f"模式 {key} prompt > 200 字符", len(info["system"]) > 200)


# ============================================================
# 组件测试: logger.py
# ============================================================

def test_logger():
    print("\n--- logger.py ---")
    from app.logger import setup_logging, LOG_FILE, LOG_DIR

    logger1 = setup_logging()
    logger2 = setup_logging()
    check("logger 单例", logger1 is logger2)
    check("logger 有 name", logger1.name == "Proofreader")
    check("LOG_DIR 存在", LOG_DIR.exists())


# ============================================================
# 组件测试: processor.py (async mock)
# ============================================================

def test_processor():
    print("\n--- processor.py ---")
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig, FileTask, FileResult, TaskStatus

    # 基本属性
    engine = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
    check("engine 有 tasks", hasattr(engine, 'tasks'))
    check("engine 有 stats", hasattr(engine, 'stats'))
    check("engine 有 on_stream", hasattr(engine, 'on_stream'))
    check("engine 有 on_file_done", hasattr(engine, 'on_file_done'))
    check("engine 初始 not running", not engine.is_running)
    check("engine 初始 not paused", not engine.is_paused)
    check("engine 初始 not cancelled", not engine.is_cancelled)

    # prepare_tasks 基本功能
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("test content for prepare")
        tmp = Path(f.name)
    engine2 = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
    engine2.prepare_tasks([tmp])
    tmp.unlink(missing_ok=True)
    check("prepare_tasks 创建 task", str(tmp) in engine2.tasks)
    check("prepare_tasks 设置 total_files", engine2.stats.total_files == 1)
    check("prepare_tasks 读取文本", engine2.tasks[str(tmp)].original_text == "test content for prepare")

    # prepare_tasks 断点缓存
    from app.utils import save_checkpoint
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("cached content")
        tmp = Path(f.name)
    task = FileTask(file_path=tmp, original_text="cached content")
    task.status = TaskStatus.COMPLETED
    task.result = FileResult(original="cached content", corrected="fixed")
    save_checkpoint(tmp, task)
    engine3 = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
    engine3.prepare_tasks([tmp])
    tmp.unlink(missing_ok=True)
    check("prepare_tasks 加载缓存", engine3.tasks[str(tmp)].is_done)
    check("prepare_tasks 缓存计数", engine3.stats.completed_files == 1)

    # cancel
    engine4 = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
    engine4.cancel()
    check("cancel 设置 cancel_event", engine4.is_cancelled)

    # _log 回调
    engine5 = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
    logs = []
    engine5.on_log = lambda m: logs.append(m)
    engine5._log("test msg")
    check("_log 调用回调", len(logs) == 1 and logs[0] == "test msg")
    check("_log 写入 logger", True)  # 不崩溃即可

    # _call_api_stream 空响应
    async def test_empty_stream():
        eng = ProcessingEngine(ProjectConfig(api_base='http://x', model='m'))
        eng._loop = asyncio.get_running_loop()
        # v4.0+: _pause_event 改 threading.Event (跨线程 pause/resume 线程安全)
        eng._pause_event = threading.Event()
        eng._pause_event.set()

        mock_event = MagicMock()
        mock_event.choices = [MagicMock()]
        mock_event.choices[0].delta.content = None
        mock_event.usage = None

        async def fake_stream():
            yield mock_event

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())
        eng._client = mock_client
        try:
            await eng._call_api_stream("key", "text")
            return False
        except ValueError:
            return True

    check("_call_api_stream 空响应抛异常", asyncio.run(test_empty_stream()))
    # Phase 3: _call_api_stream 返回 (str, int, list[FileResult]) — smoke 验证

    # _call_api_stream 正常流式
    async def test_normal_stream():
        eng = ProcessingEngine(ProjectConfig(api_base='http://x', model='m'))
        eng._loop = asyncio.get_running_loop()
        eng._pause_event = threading.Event()
        eng._pause_event.set()
        stream_calls = []
        eng.on_stream = lambda k, t: stream_calls.append((k, t))

        mock_event1 = MagicMock()
        mock_event1.choices = [MagicMock()]
        mock_event1.choices[0].delta.content = "Hello"
        mock_event1.usage = None

        mock_event2 = MagicMock()
        mock_event2.choices = [MagicMock()]
        mock_event2.choices[0].delta.content = " World"
        mock_event2.usage = MagicMock()
        mock_event2.usage.total_tokens = 5

        async def fake_stream():
            yield mock_event1
            yield mock_event2

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())
        eng._client = mock_client
        result, tokens, chunks = await eng._call_api_stream("key", "text")

        return (
            result == "Hello World"
            and tokens == 5
            and len(stream_calls) >= 1
            and len(chunks) == 1
            and chunks[0].corrected == "Hello World"
        )

    check("_call_api_stream 正常流式", asyncio.run(test_normal_stream()))


# ============================================================
# 冒烟测试: 配置 + 引擎 (v4.0+ 已脱离 PySide6 UI 依赖)
# ============================================================

def test_smoke_config_roundtrip():
    print("\n--- 冒烟: 配置往返 ---")
    from app.utils import ProjectConfig, save_config, load_config
    cfg = ProjectConfig(
        api_base="http://localhost:1234/v1",
        api_key="test-key",
        model="test-model",
        concurrency=4,
        prompt_mode="custom",
        custom_prompt="自定义 prompt 内容",
        temperature=0.2,
    )
    save_config(cfg)
    loaded = load_config()
    check("配置往返 api_base", loaded.api_base == "http://localhost:1234/v1")
    check("配置往返 model", loaded.model == "test-model")
    check("配置往返 concurrency", loaded.concurrency == 4)
    check("配置往返 custom_prompt", loaded.custom_prompt == "自定义 prompt 内容")
    check("配置往返 temperature", abs(loaded.temperature - 0.2) < 0.01)


def test_smoke_engine_lifecycle():
    print("\n--- 冒烟: 引擎生命周期 ---")
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig

    engine = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
    check("引擎创建成功", engine is not None)
    check("引擎初始状态", not engine.is_running and not engine.is_paused and not engine.is_cancelled)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("smoke test file")
        tmp = Path(f.name)

    engine.prepare_tasks([tmp])
    tmp.unlink(missing_ok=True)
    check("prepare_tasks 成功", len(engine.tasks) == 1)

    engine.cancel()
    check("cancel 成功", engine.is_cancelled)


def test_smoke_prompt_content():
    print("\n--- 冒烟: Prompt 内容 ---")
    from app.templates import PROMPT_MODES

    for key, info in PROMPT_MODES.items():
        prompt = info["system"]
        check(f"{key} prompt 有核心原则", "核心原则" in prompt or "识别并解决" in prompt)
        check(f"{key} prompt 有输出要求", "输出要求" in prompt)
        # v3.1+ deai 模式用"改写"而不是"校对",其他模式仍用"校对"
        output_label = "改写" if key == "deai" else "校对"
        check(f"{key} prompt 有示例", "## 示例" in prompt and "原文" in prompt and output_label in prompt)


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("  组件测试 + 冒烟测试 (v4.0+ 已脱离 PySide6 UI 依赖)")
    print("=" * 60)

    test_smoke_config_roundtrip()
    test_smoke_engine_lifecycle()
    test_smoke_prompt_content()

    test_utils()
    test_templates()
    test_logger()
    test_processor()

    print()
    print("=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败 (共 {passed+failed} 项)")
    print("=" * 60)

    if errors_list:
        print("\n失败项:")
        for name in errors_list:
            print(f"  - {name}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
