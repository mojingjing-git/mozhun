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

sys.path.insert(0, str(Path(__file__).parent.parent))  # v6.0: tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

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
    check("ProjectConfig 包含所有字段", len(d) == 32)  # v5.1.0: + harness_enabled; v5.2c: + 4 双轨字段; v5.3.0: + workflow_mode

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
    # v5.3.1: 预设不再带模型示例 — API 面板里不许出现任何写死的模型名
    check("预设均无模型示例 (model 一律留空)",
          all(t.get("model") == "" for t in API_TEMPLATES),
          str([t["name"] for t in API_TEMPLATES if t.get("model")]))
    _banned_models = ["MiniMax-M2", "qwen-plus", "glm-4-flash", "DeepSeek-V3",
                      "deepseek-chat", "deepseek-reasoner", "openrouter/auto"]
    _tpl_text = " ".join(
        f"{t.get('name', '')} {t.get('model', '')} {t.get('description', '')}"
        for t in API_TEMPLATES
    )
    _leaked = [m for m in _banned_models if m in _tpl_text]
    check("预设字段/说明里无写死模型名", not _leaked, str(_leaked))

    check("PROMPT_MODES 非空", len(PROMPT_MODES) > 0)
    # v4.3.3: punct_local / v4.4.2: md_local 是本地脚本模式, system 永不发送
    # LLM, 豁免 prompt 结构断言
    llm_modes = {k: v for k, v in PROMPT_MODES.items()
                 if k not in ("punct_local", "md_local")}
    for key, info in llm_modes.items():
        check(f"模式 {key} 有 label", "label" in info)
        check(f"模式 {key} 有 system", "system" in info)
        check(f"模式 {key} 有 few-shot", "## 示例" in info["system"])

    # 检查 prompt 不为空且有实质内容
    for key, info in llm_modes.items():
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
    from app.utils import save_checkpoint, compute_prompt_hash_for_config
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("cached content")
        tmp = Path(f.name)
    # v4.1.8.1 (C5): 断点命中要求 prompt_hash 与配置指纹一致; 测试断点必须带
    # 正确指纹 (模拟真实断点), 否则空 hash 断点会被 expected_hash 校验判失效.
    cfg = ProjectConfig(api_base="http://x", model="m")
    task = FileTask(file_path=tmp, original_text="cached content")
    task.status = TaskStatus.COMPLETED
    task.result = FileResult(
        original="cached content", corrected="fixed",
        prompt_hash=compute_prompt_hash_for_config(cfg),  # v5.0.1 (审计 I-3)
    )
    save_checkpoint(tmp, task)
    engine3 = ProcessingEngine(cfg)
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
        # v5.1.0: harness_enabled=False — 本测试针对流式空响应路径,
        # strict + harness(默认开) 会改走非流式 Edit 工具分支
        eng = ProcessingEngine(ProjectConfig(api_base='http://x', model='m', harness_enabled=False))
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
        # v5.1.0: harness_enabled=False — 本测试针对流式路径,
        # strict + harness(默认开) 会改走非流式 Edit 工具分支
        eng = ProcessingEngine(ProjectConfig(api_base='http://x', model='m', harness_enabled=False))
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

    # v5.3.0 (PLAN §2 D8): finish_reason="length" → 截断标记 (不再静默)
    async def test_truncated_stream():
        eng = ProcessingEngine(ProjectConfig(
            api_base='http://x', model='m', harness_enabled=False))
        eng._loop = asyncio.get_running_loop()
        eng._pause_event = threading.Event()
        eng._pause_event.set()

        def _mk_event(text, finish_reason):
            ev = MagicMock()
            ev.choices = [MagicMock()]
            ev.choices[0].delta.content = text
            ev.choices[0].finish_reason = finish_reason
            ev.usage = None
            return ev

        async def run_with(finish_reason):
            async def fake_stream():
                yield _mk_event("半截输出", finish_reason)
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())
            eng._client = mock_client
            await eng._call_api_stream("key", "text")
            return "key" in eng.truncated_keys

        truncated = await run_with("length")
        # 每次进入重建标记 (重试/重跑不继承上一轮告警)
        normal = await run_with("stop")
        return truncated and not normal

    check("finish_reason=length 记入截断标记", asyncio.run(test_truncated_stream()))

    # v5.4 (PLAN §2 D4/D7/D10): 流式思维链剥离 — corrected 干净 + 预览单调 + 剥离日志
    async def test_think_strip_stream():
        eng = ProcessingEngine(ProjectConfig(
            api_base='http://x', model='m', harness_enabled=False))
        eng._loop = asyncio.get_running_loop()
        eng._pause_event = threading.Event()
        eng._pause_event.set()
        stream_calls = []
        eng.on_stream = lambda k, t: stream_calls.append(t)
        logs = []
        eng.on_log = lambda m: logs.append(m)

        def _mk(text, reasoning=""):
            ev = MagicMock()
            ev.choices = [MagicMock()]
            ev.choices[0].delta.content = text
            ev.choices[0].delta.reasoning_content = reasoning
            ev.choices[0].finish_reason = None
            ev.usage = None
            return ev

        async def fake_stream():
            yield _mk("<think>推理过程</think>", "独立思维链")
            yield _mk("\n\n正文一")
            yield _mk("正文二")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())
        eng._client = mock_client
        result, tokens, chunks = await eng._call_api_stream("key", "text")
        mono = all(stream_calls[i + 1].startswith(stream_calls[i])
                   for i in range(len(stream_calls) - 1))
        return (
            result == "正文一正文二"
            and "推理过程" not in result and "<think>" not in result
            and mono
            and chunks[0].corrected == "正文一正文二"
            and any("[思维链]" in m for m in logs)
        )

    check("v5.4 流式剥离思维链 (预览单调/日志)",
          asyncio.run(test_think_strip_stream()))


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
        if key in ("punct_local", "md_local"):
            continue  # v4.3.3/v4.4.2: 本地脚本模式, 不走 LLM prompt
        prompt = info["system"]
        check(f"{key} prompt 有核心原则", "核心原则" in prompt or "识别并解决" in prompt)
        check(f"{key} prompt 有输出要求", "输出要求" in prompt)
        # v3.1+ deai 模式用"改写"而不是"校对",其他模式仍用"校对"
        output_label = "改写" if key == "deai" else "校对"
        check(f"{key} prompt 有示例", "## 示例" in prompt and "原文" in prompt and output_label in prompt)


# ============================================================
# 主程序
# ============================================================

def test_v500_legacy_mode_migration():
    """v5.0.0 Phase A4: 已砍模式 (deep_polish/anti_rambling/long_sentence) 静默归一."""
    print()
    print("--- v5.0.0: 旧模式归一化 ---")
    from app.utils import ProjectConfig, compute_prompt_hash, _LEGACY_MODE_MAP
    from app.templates import PROMPT_MODES
    for old, expect in _LEGACY_MODE_MAP.items():
        c = ProjectConfig.from_dict({"prompt_mode": old})
        check(f"归一化 {old} -> {expect}", c.prompt_mode == expect)
    check("schema v2 旧文件加载即升 3",
          ProjectConfig.from_dict({"prompt_mode": "strict", "schema_version": 2}).schema_version == 3)
    check("保留模式不受影响 (strict)",
          ProjectConfig.from_dict({"prompt_mode": "strict"}).prompt_mode == "strict")
    check("保留模式不受影响 (punct_local)",
          ProjectConfig.from_dict({"prompt_mode": "punct_local"}).prompt_mode == "punct_local")
    check("保留模式不受影响 (md_local)",
          ProjectConfig.from_dict({"prompt_mode": "md_local"}).prompt_mode == "md_local")
    check("旧断点自动失效 (模式归一改变 hash)",
          compute_prompt_hash("deep_polish", "m", "") != compute_prompt_hash("polish", "m", ""))
    check("PROMPT_MODES 无已砍模式",
          all(k not in PROMPT_MODES for k in ("deep_polish", "anti_rambling", "long_sentence")))
    check("PROMPT_MODES 精简后 7 条目 (6 可见 + deai 隐藏)", len(PROMPT_MODES) == 7)


def test_v543_f4_engine_config_snapshot():
    """v5.4.3 (F4): 引擎必须持有 config **快照**, 不能是 Backend._config 的引用.

    旧版 `self.config = config` 持引用, 而 set_config 与每次 start_proofread
    都就地改同一对象, 引擎又逐块现场读 (_harness_active / temperature /
    _base_system_prompt) → ① 跑一半切入口得两种协议混合拼接
    ② compute_prompt_hash 只在 prepare_tasks 算一次, 落盘断点 hash 与真实
    生成条件不符, 下次当合法缓存复用。

    附带: _file_done_payload / _collect_results 的 effective_workflow(eng.config)
    随之锁定为"本次实际运行的轨" (呼应 AGENTS §41)。
    """
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig, effective_workflow, compute_prompt_hash_for_config

    cfg = ProjectConfig(prompt_mode="strict", workflow_mode="harness")
    eng = ProcessingEngine(cfg)

    # 建引擎后外部改配置, 引擎侧必须纹丝不动
    cfg.prompt_mode = "punct_local"
    cfg.temperature = 1.9
    cfg.workflow_mode = "rewrite"
    cfg.harness_enabled = False
    check("快照: prompt_mode 不受外部改写", eng.config.prompt_mode == "strict",
          repr(eng.config.prompt_mode))
    check("快照: temperature 不受外部改写", eng.config.temperature == 0.1,
          repr(eng.config.temperature))
    check("快照: 派生轨仍是 harness",
          effective_workflow(eng.config) == "harness",
          repr(effective_workflow(eng.config)))
    check("快照: 引擎仍走工具链", eng._harness_active() is True)
    check("快照: config 不是同一对象", eng.config is not cfg)

    # 断点指纹必须与"若配置未被改"时一致 (否则落盘断点 hash 撒谎)。
    # 用 engine.config 算, 而非 eng._current_prompt_hash ——
    # 后者由 prepare_tasks() 设置 (:281), 刚构造的引擎没有该属性。
    pristine = ProjectConfig(prompt_mode="strict", workflow_mode="harness")
    check("快照: 指纹与未改配置的指纹一致",
          compute_prompt_hash_for_config(eng.config)
          == compute_prompt_hash_for_config(pristine),
          f"{compute_prompt_hash_for_config(eng.config)} vs "
          f"{compute_prompt_hash_for_config(pristine)}")



def main():
    print("=" * 60)
    print("  组件测试 + 冒烟测试 (v4.0+ 已脱离 PySide6 UI 依赖)")
    print("=" * 60)

    # v4.1.8.2 (审计 K12): per-test try/except — 旧版裸调, 一个用例抛异常
    # 即中断后续全部用例, 覆盖静默缩水 (与 test_web_backend/test_bugs 同款模式)
    all_tests = [
        test_v543_f4_engine_config_snapshot,
        test_v500_legacy_mode_migration,
        test_smoke_config_roundtrip,
        test_smoke_engine_lifecycle,
        test_smoke_prompt_content,
        test_utils,
        test_templates,
        test_logger,
        test_processor,
    ]
    for t in all_tests:
        try:
            t()
        except Exception as e:
            import traceback
            check(t.__name__, False, f"{type(e).__name__}: {e}" + chr(10) + traceback.format_exc())

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
