"""
回归测试 — 引擎层 (Bug#1-13 均为 v4.0+ 现行行为的回归锚点)
"""
import asyncio
import re
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


def test_bug1():
    from app.processor import ProcessingEngine
    from app.utils import (
        ProjectConfig, save_checkpoint, FileTask, FileResult, TaskStatus,
        compute_prompt_hash_for_config, compute_source_hash,
    )
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write('test'); tmp = Path(f.name)
    # v4.1.8.1 (C5): 断点命中现在要求 prompt_hash 与当前配置指纹一致 (load_checkpoint
    # 传 expected_hash), 测试断点必须带正确指纹, 否则空 hash 断点会被判失效.
    # v5.5 (I-1): 命中条件再加**输入指纹** source_hash —— fixture 必须与磁盘原文一致.
    cfg = ProjectConfig(api_base='http://x', model='m')
    # v5.0.1 (审计 I-3): 统一走 for_config helper — 14 字段一把传, 不再靠默认值
    ph = compute_prompt_hash_for_config(cfg)
    task = FileTask(file_path=tmp, original_text='test')
    task.status = TaskStatus.COMPLETED
    task.result = FileResult(original='test', corrected='fixed', token_count=10, prompt_hash=ph,
                             source_hash=compute_source_hash('test'))
    save_checkpoint(tmp, task)
    engine = ProcessingEngine(cfg)
    call_log = []
    import app.utils as utils_mod
    orig = utils_mod.load_checkpoint
    # v4.1.8.1 (C5): mock 改为透传签名, 跟上生产传 expected_hash 的契约
    def track(fp, *args, **kwargs):
        call_log.append(str(fp)); return orig(fp, *args, **kwargs)
    with patch('app.processor.load_checkpoint', side_effect=track):
        engine.prepare_tasks([tmp])
    tmp.unlink(missing_ok=True)
    check("Bug#1 checkpoint", len(call_log) == 1 and engine.tasks[str(tmp)].is_done)

def test_bug2():
    from app.utils import ProjectConfig
    c = ProjectConfig(prompt_mode='custom', custom_prompt='my prompt')
    r = ProjectConfig.from_dict(c.to_dict())
    check("Bug#2 custom_prompt", r.custom_prompt == "my prompt")

def test_bug3():
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig
    engine = ProcessingEngine(ProjectConfig(api_base='http://x', model='m'))
    logs = []
    engine.on_log = lambda m: logs.append(m)
    engine._log("test")
    check("Bug#3 on_log single", len(logs) == 1)

def test_bug4():
    from app.utils import FileTask
    tasks = {}; lock = threading.Lock(); errors = []
    def w():
        for i in range(500):
            with lock: tasks[f'f{i}'] = FileTask(file_path=Path(f'/t/{i}'), original_text=str(i))
    def r():
        for _ in range(500):
            try:
                with lock: s = dict(tasks)
                for k, t in s.items(): _ = t.result
            except RuntimeError as e: errors.append(str(e))
    t1 = threading.Thread(target=w); t2 = threading.Thread(target=r)
    t1.start(); t2.start(); t1.join(); t2.join()
    check("Bug#4 thread safe", len(errors) == 0)

def test_bug5():
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig
    async def run():
        # v5.1.0: harness_enabled=False — 本测试针对流式空响应路径,
        # strict + harness(默认开) 会改走非流式 Edit 工具分支
        eng = ProcessingEngine(ProjectConfig(api_base='http://x', model='m', harness_enabled=False))
        eng._loop = asyncio.get_running_loop()
        # v4.0+: _pause_event 改 threading.Event,异步等待走 _wait_if_paused
        eng._pause_event = threading.Event(); eng._pause_event.set()
        ev = MagicMock(); ev.choices = [MagicMock()]; ev.choices[0].delta.content = None; ev.usage = None
        async def fs(): yield ev
        mc = AsyncMock(); mc.chat.completions.create = AsyncMock(return_value=fs())
        eng._client = mc
        try: await eng._call_api_stream("k", "t"); return False
        except ValueError: return True
    check("Bug#5 empty raises", asyncio.run(run()))

def test_bug6():
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig
    e = ProcessingEngine(ProjectConfig(api_base='http://x', model='m'))
    e._cancel_event.clear(); e.stats.start_time = time.time()
    start = time.time(); e.cancel(); elapsed = time.time() - start
    check("Bug#6 cancel fast", elapsed < 0.5 and e.is_cancelled)

def test_bug7():
    import inspect
    from app.processor import ProcessingEngine
    src = inspect.getsource(ProcessingEngine._process_file_async)
    # v4.1.8.1 (B1): 原断言查 last_error/"未知错误" 兜底串 —— 重构后所有失败路径
    # (不可重试/RateLimit 耗尽/通用耗尽) 收敛到 _finalize_failed 统一收尾, 循环外
    # 兜底块已删. 新断言: 失败必走统一收尾 (含断点/回调/stats), B1+B2 源码级防回归.
    check("Bug#7 has fallback",
          src.count("_finalize_failed") >= 3
          and "_finalize_cancelled" in src
          and "save_checkpoint_async" in src)

def test_bug8():
    from app.utils import ProcessStats
    s = ProcessStats(); s.completed_files = 1; s.total_files = 10; s.elapsed = 0.0
    check("Bug#8 eta no div0", s.eta == 0.0)

def test_bug9():
    from app.utils import read_file_text
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
        f.write(b'\x80\x81\x82\x83'); tmp = Path(f.name)
    text = read_file_text(tmp); tmp.unlink()
    check("Bug#9 no latin1", '\ufffd' in text)

def test_bug10():
    import difflib
    big = 'test\n' * 10000; big2 = 'fixed\n' * 10000
    start = time.time()
    m = difflib.SequenceMatcher(None, big.splitlines(True), big2.splitlines(True))
    list(m.get_opcodes())
    check("Bug#10 line diff", time.time() - start < 1.0)

def test_bug11():
    """Bug#11: v4.0+ Phase 3 删除 PySide6 main_window.py.

    原 Bug#11 验证 _on_processing_finished 的 None 保护.
    现等价语义: 验证 web_backend._collect_results() 有 'not self._engine' 保护.
    同时验证 main_window.py 不再存在 (已迁 web 前端).
    v4.1.8.1 (H1): _collect_results 改为支持显式 engine 参数,
    None 保护写为 `if eng is None` (eng 默认取 self._engine).
    """
    # 1. 旧 PySide6 模块已删
    src_path = Path(__file__).parent.parent / "app" / "main_window.py"
    check("Bug#11 v4.0+ main_window.py 已删 (Phase 3 完成)", not src_path.exists())
    # 2. 等价保护逻辑搬到 web_backend._collect_results (engine=None 时返回空 dict)
    from app.web_backend import Backend
    import inspect
    src = inspect.getsource(Backend._collect_results)
    check(
        "Bug#11 _collect_results None 保护",
        "not self._engine" in src or "if not self._engine" in src or "if eng is None" in src,
    )
    # 行为级验证: 无 engine 时返回 {} 不抛
    b = Backend(window=None)
    b._engine = None
    check("Bug#11 _collect_results 无 engine 返回 {} 不抛", b._collect_results() == {})

def test_bug12():
    """Bug#12: v4.0+ Phase 3 删除 PySide6 input_panel.py.

    原 Bug#12 验证 InputPanel.clear 公开.
    现等价语义: 验证前端 app.js 有清空文件逻辑 (clearFiles) 且 input_panel.py 不存在.
    """
    src_path = Path(__file__).parent.parent / "app" / "input_panel.py"
    check("Bug#12 v4.0+ input_panel.py 已删 (Phase 3 完成)", not src_path.exists())
    # 前端 app.js 应有 clearFiles 方法
    app_js = (Path(__file__).parent.parent / "web" / "app.js").read_text(encoding="utf-8")
    check("Bug#12 前端 app.js 有 clearFiles 公开方法", "clearFiles" in app_js and "async clearFiles" in app_js)

def test_bug13():
    """Bug#13: v4.0+ Phase 3 删除 PySide6 main_window.py.

    原 Bug#13 验证 _export_report try/except.
    现等价语义: 验证 web_backend.export_result() 有 try/except + main_window.py 不存在.
    """
    src_path = Path(__file__).parent.parent / "app" / "main_window.py"
    check("Bug#13 v4.0+ main_window.py 已删 (Phase 3 完成)", not src_path.exists())
    from app.web_backend import Backend
    import inspect
    # v4.3.0: 对话框+写盘逻辑抽到 _export_via_dialog, 异常防护随之迁移 (等价语义)
    src = inspect.getsource(Backend._export_via_dialog)
    check("Bug#13 export_result try/except (经 _export_via_dialog)", "try" in src and "except" in src)

def test_fewshot():
    from app.templates import PROMPT_MODES
    for k, v in PROMPT_MODES.items():
        # v4.3.3: punct_local / v4.4.2: md_local 是本地脚本模式, system 永不发送
        # LLM, 豁免结构断言
        if k in ("punct_local", "md_local"):
            continue
        check(f"Few-shot {k}", "## 示例" in v['system'])


def test_v530_checkpoint_preserve_done():
    """v5.3.0 (PLAN §2 D9): 失败/取消收尾不覆盖已完成断点, 成功仍可覆盖。

    单结果槽 + 双入口场景下, 这是"另一条轨的好结果不会被冲掉"的唯一护栏。
    """
    from app.utils import (
        FileResult, FileTask, ProjectConfig, TaskStatus,
        compute_prompt_hash_for_config, load_checkpoint, save_checkpoint,
    )
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False,
                                     encoding='utf-8') as f:
        f.write('原文' * 50)
        tmp = Path(f.name)
    cfg = ProjectConfig(api_base='http://x', model='m', harness_enabled=False)
    h = compute_prompt_hash_for_config(cfg)

    # 1) 先落一个成功断点 (模拟"逐条校对跑完")
    done_task = FileTask(
        file_path=tmp, status=TaskStatus.COMPLETED, original_text='原文' * 50,
        result=FileResult(original='原文' * 50, corrected='改好了', prompt_hash=h),
    )
    save_checkpoint(tmp, done_task)

    # 2) 另一条轨失败/取消收尾 (preserve_done=True) → 不覆盖
    bad_task = FileTask(
        file_path=tmp, status=TaskStatus.CANCELLED, original_text='原文' * 50,
        result=FileResult(original='原文' * 50, corrected='', error='已取消',
                          prompt_hash=h),
    )
    save_checkpoint(tmp, bad_task, preserve_done=True)
    cached = load_checkpoint(tmp, expected_hash=h)
    check("失败/取消不覆盖已完成断点",
          cached is not None and cached.status == TaskStatus.COMPLETED
          and cached.result is not None and cached.result.corrected == '改好了')

    # 3) 新的成功结果仍可覆盖 (默认 preserve_done=False)
    rerun_task = FileTask(
        file_path=tmp, status=TaskStatus.COMPLETED, original_text='原文' * 50,
        result=FileResult(original='原文' * 50, corrected='重跑结果', prompt_hash=h),
    )
    save_checkpoint(tmp, rerun_task)
    cached2 = load_checkpoint(tmp, expected_hash=h)
    check("成功结果仍可覆盖 (重跑出口没被堵死)",
          cached2 is not None and cached2.result is not None
          and cached2.result.corrected == '重跑结果')

    # 4) 无历史断点时 preserve_done 照常写 (不能把首次失败也吞掉)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False,
                                     encoding='utf-8') as f:
        f.write('fresh')
        tmp2 = Path(f.name)
    fresh_fail = FileTask(
        file_path=tmp2, status=TaskStatus.FAILED, original_text='fresh',
        result=FileResult(original='fresh', corrected='', error='APITimeout',
                          prompt_hash=h),
    )
    save_checkpoint(tmp2, fresh_fail, preserve_done=True)
    raw = load_checkpoint(tmp2)
    check("无历史断点时 preserve_done 仍落盘 (失败状态可见)",
          raw is not None and raw.status == TaskStatus.FAILED)

    for p in (tmp, tmp2):
        try:
            p.unlink()
        except OSError:
            pass


def main():
    print("=" * 60)
    print("  回归测试 (v4.0+ 已脱离 PySide6/fluent 依赖)")
    print("=" * 60)
    tests = [
        test_bug1, test_bug2, test_bug3, test_bug4, test_bug5,
        test_bug6, test_bug7, test_bug8, test_bug9, test_bug10,
        test_bug11, test_bug12, test_bug13,
        test_fewshot,
        test_v530_checkpoint_preserve_done,
    ]
    for t in tests:
        try: t()
        except Exception as e: check(t.__name__, False, f"{type(e).__name__}: {e}")
    print()
    print("=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
