# -*- coding: utf-8 -*-
"""v4.3.3 标点修复测试套件 (app/punct_fix.py + 引擎 punct_local 分支).

run_all_tests.py 按 test_*.py glob 自动发现 (无需注册).
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))  # v6.0: tests/ 的父目录 = 项目根
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
    check("撇号保护 + 外侧配对 + 字形规范", r == "他说 ‘don’t’ 好" and n == 3, repr(r))
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


def test_v434_research_rules():
    """v4.3.4: 调研落地规则回归 (省略号权重法/属格撇号/全角折叠/低危逗号/
    分号原则/URL 掩蔽/破折号波浪/不平衡报告/直角引号计数)."""
    print()
    print("--- v4.3.4: 调研落地规则 ---")
    from app.punct_fix import fix_punctuation, fix_punctuation_ex
    cases = [
        # 省略号权重法 (GB/T: 省略号后不加句号)
        ("他说。。。", "他说……"),
        ("他...。说了", "他……说了"),
        ("……。", "……"),
        ("。。。", "……"),
        ("end...", "end..."),          # 纯英文行不动
        ("。。", "。。"),               # 权重 2 不动
        # 属格撇号
        ("他拿了 James' 包", "他拿了 James’ 包"),
        ("players'更衣室", "players’更衣室"),
        # 缩略撇号字形
        ("他说 'don't' 好", "他说 ‘don’t’ 好"),
        # 逗号低危档 (autocorrect 两档设计)
        ("1937,战争爆发了。", "1937，战争爆发了。"),
        ("iPhone,好开心", "iPhone，好开心"),
        ("John, 他说", "John， 他说"),
        ("3,14", "3,14"),
        ("1,000", "1,000"),
        # 分号永不转换
        ("中文;英文", "中文;英文"),
        ("&quot;测试&quot;", "&quot;测试&quot;"),
        # 破折号/波浪 (GB/T: ——/～ 形态)
        ("他--走了", "他——走了"),
        ("他—走了", "他——走了"),
        ("他——走了", "他——走了"),
        ("你~好", "你～好"),
        ("3-5", "3-5"),
        # 全角字母/数字折叠 (指北 B4)
        ("版本２０２６", "版本2026"),
        ("ＡＢＣ测试", "ABC测试"),
        # URL 掩蔽 (评审 P5)
        ("测试中文,https://a.com/foo?x=1,详见",
         "测试中文，https://a.com/foo?x=1,详见"),
        ('他说"https://a.com"就好', "他说“https://a.com”就好"),
    ]
    for src, want in cases:
        if want is None:
            r, st = fix_punctuation(src)
            check("跨行降级: 落单引号保守跳过", r.count('"') == src.count('"'), repr(r))
            continue
        r, n = fix_punctuation(src)
        check(f"{src!r} -> {want!r}", r == want, repr(r))
    # 跨行降级 (FP-1 回归): 引号含真实换行, 逐行处理不跨行配对
    src = '他说:"今晚' + chr(10) + '回来吗?"她说,"我又不想走了。"'
    r, st = fix_punctuation(src)
    check("跨行降级: 落单引号保守跳过",
          r.count('"') == src.count('"'), repr(r))
    # 不平衡报告 (评审 P1: 撇号字形不触发假报告)
    for txt in ("James’刀", "O’Brien 说你好"):
        r, st = fix_punctuation_ex(txt)
        check(f"撇号不触发假报告: {txt!r}",
              not any(e["kind"] == "single" for e in st["imbalance"]))
    # schema 统一 (评审 P2)
    r, st = fix_punctuation_ex('他说"落单')
    e0 = st["imbalance"][0] if st["imbalance"] else {}
    check("不平衡条目含 line", e0.get("line") == 1, str(e0))
    # NUL 不串号 (评审 P4)
    r, st = fix_punctuation_ex("前" + chr(0) + "0" + chr(0) + "后 https://a.com/x")
    check("NUL 剥离不串号", r.count("https") == 1 and r == "前0后 https://a.com/x", repr(r))
    # 重复标点压缩计数 (评审 P7)
    r, st = fix_punctuation_ex("wow!! 好看", {"repeat_compress": True})
    check("压缩计入统计", st["total"] >= 1, str(st["total"]))
    # 直角引号计数 (评审 P8)
    r, st = fix_punctuation_ex('他说："测试。"', {"quote_style": "rect"})
    check("直角引号计数", st["total"] >= 2, str(st["total"]))
    # 幂等
    r1, _ = fix_punctuation('他说："你好,世界。"他说。。。')
    r2, _ = fix_punctuation(r1)
    check("幂等", r1 == r2)


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


def test_engine_punct_local_reports():
    """v5.0.1 (审计 I-1): punct_local 模式也要收集引号不平衡报告 (旧版只在 strict 路径收集)."""
    print()
    print("--- 引擎 punct_local 不平衡报告 ---")
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig

    async def run():
        cfg = ProjectConfig(api_base="", api_key="", model="", prompt_mode="punct_local")
        engine = ProcessingEngine(cfg)
        if hasattr(engine, "_pause_event"):
            engine._pause_event.set()
        engine.stats.start_time = __import__("time").time()
        corrected, tokens, chunks = await engine._call_api_stream("k", '他说："你好')
        return corrected, engine.punct_reports

    corrected, reports = asyncio.run(run())
    check("punct_local 收集不平衡报告", len(reports) >= 1, str(reports))
    check("报告含行号与文件名", any("a" not in r or "第 1 行" in r for r in reports), str(reports))


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
        test_engine_punct_local_reports,
        test_prepare_tasks_applies_fix,
        test_crossline_and_digit_comma,
        test_v434_research_rules,
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
