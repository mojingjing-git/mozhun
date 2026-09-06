# -*- coding: utf-8 -*-
"""v4.3.3 标点修复测试套件 (app/punct_fix.py + 引擎 punct_local 分支).

run_all_tests.py 按 test_*.py glob 自动发现 (无需注册).
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import test_isolate  # noqa: F401  测试隔离, 防止污染真实 ~/.proofreader

passed = 0
failed = 0
errors_list = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        errors_list.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def test_quote_pairing():
    """双引号: 成对转换 / 落单不动 / 跨行不配对."""
    print("\n--- 引号配对 ---")
    from app.punct_fix import fix_punctuation
    r, n = fix_punctuation('他说："你好。"')
    check("成对双引号转换", r == '他说：“你好。”' and n == 2, repr(r))
    r, n = fix_punctuation('他说："你好')
    check("落单引号不猜 (保持原样)", r == '他说："你好' and n == 0, repr(r))
    r, n = fix_punctuation('"甲"和"乙"')
    check("多对交替配对", r == '“甲”和“乙”' and n == 4, repr(r))
    # 跨行不配对: 第一行落单, 第二行落单 — 都不动
    r, n = fix_punctuation('第一行"开\n第二行"合')
    check("引号不跨行配对", r == '第一行"开\n第二行"合' and n == 0, repr(r))
    # 纯英文行不动
    r, n = fix_punctuation('He said "hello" to me')
    check("纯英文行双引号不动", r == 'He said "hello" to me' and n == 0, repr(r))


def test_single_quote_apostrophe():
    """单引号: 字母间撇号保护."""
    print("\n--- 单引号/撇号 ---")
    from app.punct_fix import fix_punctuation
    r, n = fix_punctuation("他说 'don't' 好")
    check("撇号保护 + 外侧配对", r == "他说 ‘don't’ 好" and n == 2, repr(r))
    r, n = fix_punctuation("it's fine")
    check("纯英文撇号不动", r == "it's fine" and n == 0, repr(r))


def test_ascii_punct_context():
    """半角标点: 中文上下文转换 / 数字与英文形态保护."""
    print("\n--- 半角标点上下文 ---")
    from app.punct_fix import fix_punctuation
    cases = [
        ("你好,世界", "你好，世界"),
        ("3,14", "3,14"),
        ("John,他说", "John，他说"),
        ("他说:你好", "他说：你好"),
        ("12:30", "12:30"),
        ("你好?", "你好？"),
        ("are you?", "are you?"),
        ("真的!", "真的！"),
        ("这是测试.", "这是测试。"),
        ("3.14", "3.14"),
        ("他...说了", "他……说了"),
        ("end...", "end..."),
        ("他(中文)说", "他（中文）说"),
        ("(english only)", "(english only)"),
    ]
    for src, want in cases:
        r, n = fix_punctuation(src)
        check(f"{src!r} -> {want!r}", r == want, repr(r))


def test_book_scale_performance():
    """书级文本性能 (< 2 秒 / 60 万字)."""
    print("\n--- 书级性能 ---")
    import time
    from app.punct_fix import fix_punctuation
    big = '他说："你好，世界。" 这是测试句子,含标点...' * 20000  # ~66 万字
    t0 = time.time()
    fixed, n = fix_punctuation(big)
    elapsed = time.time() - t0
    check(f"66 万字耗时 {elapsed:.2f}s < 2s", elapsed < 2.0)
    check("修复处数 > 0", n > 0)


def test_crossline_and_digit_comma():
    """v4.3.3 评审修复回归: FP-1 跨行引号保守降级 + FN-1 数字逗号+中文."""
    print("\n--- 评审回归: 跨行引号/数字逗号 ---")
    from app.punct_fix import fix_punctuation
    # FP-1: 第一行落单(未闭合), 第二行引号序列 [closer, opener, closer] —
    # 修复前会被整体反向配对; 现保守降级为两行引号都保持原样
    multi = '他说:"今晚\n回来吗?"她说,"我又不想走了。"'
    r, n = fix_punctuation(multi)
    check("跨行未闭合: 引号保守跳过", r.count('"') == multi.count('"'), repr(r))
    # FN-1: 数字+半角逗号+中文 (修复前被前邻数字守卫挡住)
    r, n = fix_punctuation('1937,战争爆发了。')
    check("数字+逗号+中文转换", r == '1937，战争爆发了。', repr(r))
    r, n = fix_punctuation('"1000,成交!"他喊道。')
    check("引号内数字+逗号+中文转换", r == '“1000，成交！”他喊道。', repr(r))
    # 千分位仍然安全
    r, n = fix_punctuation('共 1,000 人')
    check("千分位 1,000 不动", r == '共 1,000 人' and n == 0, repr(r))
    r, n = fix_punctuation('3,14万')
    check("3,14万 不动", r == '3,14万' and n == 0, repr(r))


def test_config_and_hash():
    """punct_fix 配置字段 + 指纹纳入."""
    print("\n--- 配置与指纹 ---")
    from app.utils import ProjectConfig, compute_prompt_hash
    cfg = ProjectConfig()
    check("punct_fix 默认 True", cfg.punct_fix is True)
    d = cfg.to_dict()
    cfg2 = ProjectConfig.from_dict(d)
    check("punct_fix 往返", cfg2.punct_fix is True)
    cfg3 = ProjectConfig.from_dict({k: v for k, v in d.items() if k != "punct_fix"})
    check("旧配置缺字段默认 True", cfg3.punct_fix is True)
    h_on = compute_prompt_hash("strict", "m", "", punct_fix=True)
    h_off = compute_prompt_hash("strict", "m", "", punct_fix=False)
    check("开关改变指纹", h_on != h_off)


def test_engine_punct_local_mode():
    """引擎 punct_local 分支: 不调 LLM、纯本地修复、复用分块."""
    print("\n--- 引擎仅标点修复模式 ---")
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig, TaskStatus

    async def run():
        cfg = ProjectConfig(
            api_base="", api_key="", model="",
            prompt_mode="punct_local", chunking_preset="balanced",
        )
        engine = ProcessingEngine(cfg)
        engine._pause_event.set() if hasattr(engine, "_pause_event") else None
        engine.stats.start_time = __import__("time").time()
        with patch("app.processor.AsyncOpenAI") as fake_ctor:
            corrected, tokens, chunks = await engine._call_api_stream(
                "k", '他说："你好。" 这是一段比较长的测试文本,含半角标点。' * 50
            )
            # v4.3.3 (评审 E-2): 客户端创建点在 _run_all — 端到端验证本地模式
            # 不建 AsyncOpenAI (空 api_key 下若回归会直接抛 ValidationError)
            engine.tasks = {}
            await engine._run_all()
            ctor_called = fake_ctor.called
            client_after = engine._client
        return corrected, tokens, chunks, ctor_called, client_after

    corrected, tokens, chunks, ctor_called, client_after = asyncio.run(run())
    check("本地模式不创建 LLM 客户端 (_run_all 端到端)", ctor_called is False and client_after is None)
    check("不消耗 token", tokens == 0)
    check("引号已修复", "“你好。”" in corrected, repr(corrected[:60]))
    check("半角逗号已修复", "测试文本，" in corrected)
    check("chunks_results 与分块一致", len(chunks) >= 1 and all(c.corrected for c in chunks))


def test_prepare_tasks_applies_fix():
    """prepare_tasks: 开关开启时读入即修复 (含日志), 关闭时不改原文."""
    print("\n--- prepare_tasks 标点修复 ---")
    import tempfile
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write('他说："你好,世界。"')
        tmp = Path(f.name)

    try:
        cfg = ProjectConfig(api_base="http://x", model="m", punct_fix=True)
        engine = ProcessingEngine(cfg)
        engine.prepare_tasks([tmp])
        t = engine.tasks[str(tmp)]
        check("开关开启: 读入即修复", t.original_text == '他说：“你好，世界。”', repr(t.original_text))

        cfg2 = ProjectConfig(api_base="http://x", model="m", punct_fix=False)
        engine2 = ProcessingEngine(cfg2)
        engine2.prepare_tasks([tmp])
        t2 = engine2.tasks[str(tmp)]
        check("开关关闭: 保持原文", t2.original_text == '他说："你好,世界。"', repr(t2.original_text))
    finally:
        tmp.unlink(missing_ok=True)


def main():
    print("=" * 60)
    print("  本地标点修复测试 (app/punct_fix.py + 引擎接线)")
    print("=" * 60)
    tests = [
        test_quote_pairing,
        test_single_quote_apostrophe,
        test_ascii_punct_context,
        test_book_scale_performance,
        test_config_and_hash,
        test_engine_punct_local_mode,
        test_prepare_tasks_applies_fix,
        test_crossline_and_digit_comma,
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
    if errors_list:
        print("\n失败项:")
        for name in errors_list:
            print(f"  - {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
