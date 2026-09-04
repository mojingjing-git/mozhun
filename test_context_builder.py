"""ContextBuilder 跨段 prefix 测试 (Phase 4)。"""
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

from app.context_builder import ContextBuilder
from app.utils import FileResult

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


def test_first_chunk():
    """第一段 (index=0) 不应有 prefix。"""
    print("\n--- 第一段 ---")
    cb = ContextBuilder()
    result = cb.build([], 0)
    check("空 list + index=0 → 空", result == "")


def test_no_chunks_processed():
    """没有已完成 chunks 时返回空。"""
    print("\n--- 无已完成 chunks ---")
    cb = ContextBuilder()
    result = cb.build([], 5)
    check("空 list + index=5 → 空", result == "")


def test_single_predecessor():
    """1 个前文, 取 1 个 chunk。"""
    print("\n--- 1 个前文 ---")
    cb = ContextBuilder(max_chars=800, max_chunks=2)
    prev = [FileResult(original="A", corrected="这是已校对的前文。")]
    result = cb.build(prev, 1)
    check("包含 '上文' 标签", "上文" in result)
    check("包含 '这是已校对的前文'", "这是已校对的前文" in result)
    check("包含 '请勿重复输出' 提示", "请勿重复输出" in result)


def test_truncation():
    """max_chars 限制生效, 超长时截断尾部。"""
    print("\n--- 截断 ---")
    cb = ContextBuilder(max_chars=120, max_chunks=2)
    # 两个 chunk 一个 60 字符一个 80 字符
    prev = [
        FileResult(original="A" * 60, corrected="A" * 60),
        FileResult(original="B" * 80, corrected="B" * 80),
    ]
    result = cb.build(prev, 2)
    # max_chars=120, 已用 60 (第一个), 第二个 80 字符: remaining=60, 60>=50 不 break,
    # text = "…" + text[-(60-1):] = "…" + 59 字符 (含省略号)
    check("包含省略号 '…'", "…" in result)
    # 总字符数应该 <= 120 + 标签长度
    check("总长 < 250 (受 max_chars 限制)", len(result) < 250)


def test_max_chunks_limit():
    """max_chunks 限制取几个前文。"""
    print("\n--- max_chunks=1 只取 1 个 ---")
    cb = ContextBuilder(max_chars=800, max_chunks=1)
    prev = [
        FileResult(original="", corrected="前 1"),
        FileResult(original="", corrected="前 2"),
        FileResult(original="", corrected="前 3"),
    ]
    result = cb.build(prev, 3)
    check("只取最近 1 个 '前 3'", "前 3" in result)
    check("不含 '前 2'", "前 2" not in result)
    check("不含 '前 1'", "前 1" not in result)


def test_empty_corrected_skipped():
    """前文 corrected 为空时跳过。"""
    print("\n--- 空 corrected 跳过 ---")
    cb = ContextBuilder()
    prev = [
        FileResult(original="", corrected=""),  # 空, 跳过
        FileResult(original="", corrected="实际内容"),
    ]
    result = cb.build(prev, 2)
    check("跳过空 chunk", "实际内容" in result)


def test_returns_empty_when_all_skipped():
    """所有前文都空 → 返回空串。"""
    print("\n--- 全部空 corrected ---")
    cb = ContextBuilder()
    prev = [
        FileResult(original="", corrected=""),
        FileResult(original="", corrected=""),
    ]
    result = cb.build(prev, 5)
    check("全空 → 返回空", result == "")


def test_separator():
    """多个前文用 --- 分隔。"""
    print("\n--- 多个前文用 --- 分隔 ---")
    cb = ContextBuilder(max_chars=800, max_chunks=3)
    prev = [
        FileResult(original="", corrected="A 段"),
        FileResult(original="", corrected="B 段"),
    ]
    result = cb.build(prev, 2)
    check("包含 --- 分隔符", "---" in result)
    check("A 在 B 前", result.index("A 段") < result.index("B 段"))


def main():
    print("=" * 60)
    print("  ContextBuilder 测试")
    print("=" * 60)
    tests = [
        test_first_chunk,
        test_no_chunks_processed,
        test_single_predecessor,
        test_truncation,
        test_max_chunks_limit,
        test_empty_corrected_skipped,
        test_returns_empty_when_all_skipped,
        test_separator,
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
