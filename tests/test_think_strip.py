# -*- coding: utf-8 -*-
"""v5.4 思维链剥离测试套件 (app/think_strip.py).

覆盖 PLAN-think-strip-v5.4.md §3.2 边界表 T1-T28 + §3.3 流式契约:
- 全切点遍历 (所有 2 段切点 + 3 段抽样): 完整性 / 前缀单调 / 切分无关
- 纯正文 property: 逐字节不变 (过滤器不能动正常结果)
- 惰性 / 幂等 / 性能 / has_think_residue (D9)
run_all_tests.py 按 tests/test_*.py glob 自动发现 (无需注册).
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))  # v6.0: tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离, 防止污染真实 ~/.proofreader

from app.think_strip import THINK_TAGS, ThinkFilter, has_think_residue, strip_thinking

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


# §3.2 边界表 (PLAN v2.1 两轮审计后口径)
_TABLE = [
    ("T1", "<think>a</think>正文", "正文"),
    ("T2", "<THINK>a</THINK>\n\n正文", "正文"),
    ("T3", '<think foo="1">a</think>正文', "正文"),
    ("T4a", "<think>a</think><think>b</think>正文", "正文"),
    ("T4b", "前言\n<think>a</think><think>b</think>正文", "前言\n正文"),
    ("T5", "前言<think>a</think>正文", "前言<think>a</think>正文"),
    ("T6", "前言\n<think>a</think>\n正文", "前言\n\n正文"),
    ("T7", "  <think>a</think>正文", "正文"),
    ("T8", "<think>a", ""),
    ("T9", "<thi", "<thi"),
    ("T10", "<think>a</thinking>正文", ""),
    ("T11", "```\n<think>样例</think>\n```", "```\n<think>样例</think>\n```"),
    ("T12", "```\n<think>x", "```\n<think>x"),
    ("T13", '<think a="x>1">a</think>正文', "正文"),
    ("T14", '<think a="x></think>2">BODY</think>TAIL', "TAIL"),
    ("T15", "<think>outer<think>inner</think>middle</think>TAIL", "TAIL"),
    ("T16", "`<think>a</think>`", "`<think>a</think>`"),
    ("T17", "`<think>secret</think>TAIL`", "`<think>secret</think>TAIL`"),
    ("T18", "<think>a</think>\r\n\r\n正文", "正文"),
    ("T18b", "```\r\ncode\r\n```\r\n<think>a</think>正文", "```\r\ncode\r\n```\r\n正文"),
    ("T19", "<analysis>a</analysis>正文", "<analysis>a</analysis>正文"),
    ("T20", "正文 <think>a</think> 正文", "正文 <think>a</think> 正文"),
    ("T21a", "", ""),
    ("T21b", "   ", "   "),
    ("T21c", "这是一段纯正文。\n第二行", "这是一段纯正文。\n第二行"),
    ("T22a", "<thought>a</thought>正文", "正文"),
    ("T22b", "<reasoning>a</reasoning>正文", "正文"),
    ("T23", '<think data="1">a</think>正文', "正文"),
    ("T24", "  <think>a", ""),
    ("T25", "<think>a<think>b</think>TAIL", ""),
    ("T26", "<think>a\n```\n</think>TAIL", "TAIL"),
    ("T27", "<think>a</think>```\n<think>b</think>\n```TAIL", "```\n<think>b</think>\n```TAIL"),
    ("T27b", "```\ncode\n```\n<think>a</think>TAIL", "```\ncode\n```\nTAIL"),
]

_PURE = [
    "这是一段纯正文。\n第二行, 含标点: 引号“x”、省略号……\n\n第三行  有空格。",
    "Hello, world!\n\n第二段\r\nCRLF 行。",
    "   ",
    "\n\n\n",
    "no newline",
    "doc:\n\n```\ncode\n```\n\ndone.",
]


def _frames(deltas):
    """按 deltas 顺序 feed/take, 末尾 flush; 返回逐次输出序列."""
    flt = ThinkFilter()
    outs = []
    for d in deltas:
        flt.feed(d)
        outs.append(flt.take())
    outs.append(flt.flush())
    return outs


def _check_stream(name, deltas, whole):
    """完整性 (join+flush == whole) + 前缀单调 (累计 take 是 whole 前缀)."""
    outs = _frames(deltas)
    joined = "".join(outs)
    acc = ""
    mono = True
    for o in outs:
        acc += o
        if not whole.startswith(acc):
            mono = False
    check(name, joined == whole and mono,
          f"joined={joined!r} whole={whole!r} mono={mono} outs={outs}")


def test_table():
    """§3.2 T1-T28: 一次性剥离逐条."""
    print("\n--- 边界表 T1-T28 ---")
    check("THINK_TAGS 白名单", THINK_TAGS == ("think", "thinking", "reasoning", "thought"))
    for tid, raw, exp in _TABLE:
        got = strip_thinking(raw)
        check(f"{tid} 一次性剥离", got == exp, f"got={got!r} exp={exp!r}")


def test_stream_split_invariance():
    """§3.3-1/2/4: 所有 2 段切点全量 + 3 段抽样."""
    print("\n--- 全切点遍历 (2 段全量 / 3 段抽样) ---")
    bad2 = []
    for tid, raw, exp in _TABLE:
        whole = strip_thinking(raw)
        for k in range(len(raw) + 1):
            outs = _frames([raw[:k], raw[k:]])
            if "".join(outs) != whole:
                bad2.append((tid, k, outs))
                break
            acc = ""
            for o in outs:
                acc += o
                if not whole.startswith(acc):
                    bad2.append((tid, k, outs))
                    break
    check("2 段切点: 完整性+前缀单调 0 破例", not bad2, repr(bad2[:2]))

    bad3 = []
    for tid, raw, exp in _TABLE:
        whole = strip_thinking(raw)
        step = max(1, len(raw) // 6)
        pts = list(range(0, len(raw) + 1, step))
        for a in pts:
            for b in pts:
                if a > b:
                    continue
                outs = _frames([raw[:a], raw[a:b], raw[b:]])
                if "".join(outs) != whole:
                    bad3.append((tid, a, b, outs))
                    break
            if bad3:
                break
        if bad3:
            break
    check("3 段切点: 完整性 0 破例", not bad3, repr(bad3[:1]))


def test_delta_cases():
    """B1 回归 (T17)、V1 反例 (T28)、属性跨帧 (T23)、CRLF 中间切 (T2/T18)."""
    print("\n--- 定向 deltas ---")
    _check_stream("T17 B1 回归: 反引号配对不翻转",
                  ["`<think>secret</think>TAIL", "`"],
                  "`<think>secret</think>TAIL`")
    _check_stream("T23 属性跨帧",
                  ['<think data="1', '">a</think>正文'],
                  "正文")
    _check_stream("T28 V1 混合坐标反例: 第一帧不得 emit <thi",
                  ["<think>a</think><thi", "nk>b</think>正文"],
                  "正文")
    outs = _frames(["<think>a</think><thi", "nk>b</think>正文"])
    check("T28 第一帧为空", outs[0] == "" and outs[1] == "正文", repr(outs))
    _check_stream("T2 大小写+头部空行",
                  ["<THINK>a</TH", "INK>\n\n", "正文"],
                  "正文")
    _check_stream("T18 CRLF 在 \\r|\\n 之间切",
                  ["<think>a</think>\r", "\n\r\n正文"],
                  "正文")
    _check_stream("T14 属性含 </think> 跨帧",
                  ['<think a="x></thi', 'nk>2">BODY</think>TAIL'],
                  "TAIL")


def test_pure_text_property():
    """§3.3-2 纯正文: 全切点逐字节不变 (过滤器不能动正常结果)."""
    print("\n--- 纯正文 property ---")
    bad = []
    for raw in _PURE:
        if strip_thinking(raw) != raw:
            bad.append((raw, "one-shot", strip_thinking(raw)))
            continue
        for k in range(len(raw) + 1):
            outs = _frames([raw[:k], raw[k:]])
            if "".join(outs) != raw:
                bad.append((raw, k, outs))
                break
    check("纯正文全切点逐字节不变", not bad, repr(bad[:2]))


def test_contract_edges():
    """§3.3-3 幂等 / 空输入 / None 容忍."""
    print("\n--- 流式契约边界 ---")
    flt = ThinkFilter()
    flt.feed("<think>a</think>正文")
    first = flt.take()
    rest = flt.flush()
    check("flush 返回差额", first + rest == "正文", repr((first, rest)))
    check("flush 幂等 (二次为空)", flt.flush() == "")
    check("flush 后 take 为空", flt.take() == "")
    flt2 = ThinkFilter()
    flt2.feed("")
    flt2.feed(None)  # type: ignore[arg-type]
    flt2.feed("正文")
    check("空/None delta 容忍", flt2.flush() == "正文")
    flt3 = ThinkFilter()
    check("未 feed 直接 flush", flt3.flush() == "")
    check("空串一次性", strip_thinking("") == "")


def test_lazy_structural():
    """惰性锁 (结构性): feed 只追加, take 才产出; 无重复产出."""
    print("\n--- 惰性 (结构性) ---")
    flt = ThinkFilter()
    raw = "<think>" + "推理" * 20 + "</think>\n\n正文段落。"
    step = 3
    for k in range(0, len(raw), step):
        flt.feed(raw[k:k + step])
    out = flt.take()
    check("多次 feed 后一次 take 得全部", out == "正文段落。", repr(out))
    check("无新增时 take 为空", flt.take() == "")


def test_perf():
    """性能 (PLAN §6.1): 50K 单次 < 200ms; 规模翻倍不呈二次增长; 流式不重扫."""
    print("\n--- 性能 ---")
    block = "<think>推理" + "思" * 40 + "</think>\n\n"
    body50 = block * 5 + "正文内容。" * 9990      # ~50K, 含 5 块
    body100 = block * 5 + "正文内容。" * 19990    # ~100K
    strip_thinking(body50)  # 预热
    t = time.perf_counter()
    strip_thinking(body50)
    t50 = time.perf_counter() - t
    t = time.perf_counter()
    strip_thinking(body100)
    t100 = time.perf_counter() - t
    check("50K 单次剥离 < 200ms", t50 < 0.2, f"{t50 * 1000:.1f}ms")
    check("50K→100K 耗时比 < 3 倍 (防二次退化)", t100 < t50 * 3 + 0.05,
          f"t50={t50 * 1000:.1f}ms t100={t100 * 1000:.1f}ms")

    flt = ThinkFilter()
    parts = []
    t = time.perf_counter()
    step = max(1, len(body50) // 250)
    for k in range(0, len(body50), step):
        flt.feed(body50[k:k + step])
        parts.append(flt.take())
    parts.append(flt.flush())
    t_stream = time.perf_counter() - t
    check("流式 250 次 take 总耗时 < 2s", t_stream < 2.0, f"{t_stream * 1000:.1f}ms")
    check("流式 50K 结果 == 一次性剥离",
          "".join(parts) == strip_thinking(body50))


def test_has_think_residue():
    """D9 单点口径: corrected 会被剥 + 原文不会被剥 才判残留."""
    print("\n--- D9 has_think_residue ---")
    check("残留命中", has_think_residue(
        SimpleNamespace(corrected="<think>x</think>正文", original="正文")))
    check("干净不命中", not has_think_residue(
        SimpleNamespace(corrected="正文", original="正文")))
    check("原文自带行首块不命中 (防永久重跑)", not has_think_residue(
        SimpleNamespace(corrected="<think>x</think>正文", original="<think>x</think>正文")))
    check("围栏内不命中 (继承围栏豁免)", not has_think_residue(
        SimpleNamespace(corrected="```\n<think>x</think>\n```", original="```\n<think>x</think>\n```")))
    check("空 corrected 不命中", not has_think_residue(
        SimpleNamespace(corrected="", original="x")))

    class _Chunked:
        original = "原文"
        corrected = ""
        chunks_results = []

        @property
        def corrected_full(self):
            return "<think>y</think>改写"

    check("chunked (corrected_full) 命中", has_think_residue(_Chunked()))


def test_stats_and_reasoning_count():
    """D10 stats (块数/字符数) + D7 独立字段存在性计数."""
    print("\n--- stats / 独立字段计数 ---")
    from unittest.mock import MagicMock
    from app.think_strip import count_reasoning_fields

    flt = ThinkFilter()
    flt.feed("<think>abc</think>\n")
    flt.feed("<thought>x</thought>正文")
    flt.flush()
    blocks, chars = flt.stats()
    check("stats: 2 块", blocks == 2, str(flt.stats()))
    check("stats: 字符数 = 两块跨度",
          chars == len("<think>abc</think>") + len("<thought>x</thought>"),
          str(flt.stats()))
    check("stats: 纯正文 0 块", ThinkFilter().stats() == (0, 0))
    check("独立字段: str 非空计 1", count_reasoning_fields(
        SimpleNamespace(reasoning_content="推理")) == 1)
    check("独立字段: 空串不计", count_reasoning_fields(
        SimpleNamespace(reasoning="")) == 0)
    check("独立字段: list 非空计 1", count_reasoning_fields(
        SimpleNamespace(reasoning_details=[{"t": "x"}])) == 1)
    check("独立字段: 普通 delta 不计", count_reasoning_fields(
        SimpleNamespace(content="正文")) == 0)
    check("独立字段: MagicMock 桩不计 (兼容既有测试)", count_reasoning_fields(MagicMock()) == 0)


def main():
    tests = [
        test_table,
        test_stream_split_invariance,
        test_delta_cases,
        test_pure_text_property,
        test_contract_edges,
        test_lazy_structural,
        test_has_think_residue,
        test_stats_and_reasoning_count,
        test_perf,
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
