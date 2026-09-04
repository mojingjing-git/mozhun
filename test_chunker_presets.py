"""5 档 chunking 预设测试。借鉴自 tianhm/ollama-batch-processor (MIT) 的分档思路。"""
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

from app.processor import ProcessingEngine, _CHUNK_PRESETS, DEFAULT_CHUNK_PRESET
from app.utils import ProjectConfig

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


def test_presets_exist():
    print("\n--- 5 档预设存在性 ---")
    for key in ["fast", "balanced", "high_context", "large", "whole_file"]:
        check(f"preset {key} 存在", key in _CHUNK_PRESETS)
    check("balanced 是默认", DEFAULT_CHUNK_PRESET == "balanced")
    check("所有 overlap=0", all(v["overlap"] == 0 for v in _CHUNK_PRESETS.values()),
          detail="校对场景不能用 overlap")


def test_whole_file():
    print("\n--- 整文件预设 ---")
    # 注: _split_text 是 staticmethod,可以直接类上调用
    chunks = ProcessingEngine._split_text("任意文本" * 1000, max_chars=0, preset="whole_file")
    check("整文件预设: 1 个 chunk", len(chunks) == 1)
    check("整文件预设: 内容完整", len(chunks[0]) == 4 * 1000)


def test_small_text():
    print("\n--- 小于 max_chars 的文本 ---")
    text = "短文本"
    chunks = ProcessingEngine._split_text(text, max_chars=3000, preset="balanced")
    check("短文本: 1 个 chunk", len(chunks) == 1)
    check("短文本: 内容一致", chunks[0] == text)


def test_balanced_preset():
    print("\n--- balanced 预设 (max_chars=3000) ---")
    # 模拟 3 段共 5000 字符
    para1 = "第一段。" * 300  # 1200 字
    para2 = "第二段。" * 300  # 1200 字
    para3 = "第三段。" * 200  # 800 字
    text = para1 + "\n\n" + para2 + "\n\n" + para3
    chunks = ProcessingEngine._split_text(text, max_chars=3000, preset="balanced")
    check("balanced 切分: 至少 2 个 chunk", len(chunks) >= 2)
    check("balanced 切分: 拼接后内容完整", "".join(chunks) == text)
    check("balanced 切分: 无 overlap", all(len(c) <= 3000 for c in chunks))


def test_unknown_preset_fallback():
    print("\n--- 未知 preset 回退 ---")
    text = "测试文本。" * 500
    # 在 _call_api_stream 里会回退,直接调 _split_text 不回退(因为是 staticmethod)
    # 这里只测不崩
    try:
        chunks = ProcessingEngine._split_text(text, max_chars=3000, preset="unknown_preset")
        check("未知 preset 不崩", len(chunks) >= 1)
    except Exception as e:
        check("未知 preset 不崩", False, detail=str(e))


def test_preset_serialization():
    print("\n--- ProjectConfig 序列化 ---")
    c = ProjectConfig(chunking_preset="fast")
    d = c.to_dict()
    check("to_dict 包含 chunking_preset", "chunking_preset" in d)
    check("to_dict 值正确", d["chunking_preset"] == "fast")
    c2 = ProjectConfig.from_dict(d)
    check("from_dict 还原", c2.chunking_preset == "fast")


def test_backward_compat():
    print("\n--- 向后兼容（旧配置无 chunking_preset 字段）---")
    # 模拟旧 last_config.json 没有 chunking_preset 字段
    old_data = {
        "api_base": "http://test",
        "api_key": "sk-test",
        "model": "gpt-4",
    }
    c = ProjectConfig.from_dict(old_data)
    check("旧配置: chunking_preset 默认为 balanced", c.chunking_preset == "balanced")


def test_all_presets_preset():
    """5 档都跑一遍:每档的 max_chars 与 _CHUNK_PRESETS 保持一致。"""
    print("\n--- 5 档 max_chars 一致性 ---")
    expected = {
        "fast": 2000,
        "balanced": 3000,
        "high_context": 4000,
        "large": 6000,
        "whole_file": 0,
    }
    for key, want in expected.items():
        check(f"{key} 的 max_chars == {want}",
              _CHUNK_PRESETS[key]["max_chars"] == want,
              detail=f"got {_CHUNK_PRESETS[key]['max_chars']}")


def test_call_api_stream_uses_preset():
    """模拟 _call_api_stream 切分逻辑:按 preset 选 max_chars 后调 _split_text。"""
    print("\n--- _call_api_stream 切分逻辑 ---")
    # 准备 10000 字符文本
    text = "段一。" * 1000  # 3000 字
    text += "\n\n段二。" * 1000  # 6000 字
    text += "\n\n段三。" * 500  # 1500 字
    # balanced 切 3000
    chunks_b = ProcessingEngine._split_text(text, _CHUNK_PRESETS["balanced"]["max_chars"],
                                            preset="balanced")
    check("balanced 切分: 多块", len(chunks_b) >= 2)
    check("balanced 切分: 每块 <= 3000", all(len(c) <= 3000 for c in chunks_b))
    check("balanced 切分: 拼接完整", "".join(chunks_b) == text)

    # fast 切 2000
    chunks_f = ProcessingEngine._split_text(text, _CHUNK_PRESETS["fast"]["max_chars"],
                                            preset="fast")
    check("fast 切分: 多块", len(chunks_f) >= 2)
    check("fast 切分: 每块 <= 2000", all(len(c) <= 2000 for c in chunks_f))
    check("fast 切分: 拼接完整", "".join(chunks_f) == text)

    # whole_file 不切
    chunks_w = ProcessingEngine._split_text(text, _CHUNK_PRESETS["whole_file"]["max_chars"],
                                            preset="whole_file")
    check("whole_file: 1 个 chunk", len(chunks_w) == 1)
    check("whole_file: 内容完整", chunks_w[0] == text)


def main():
    print("=" * 60)
    print("  5 档 chunking 预设测试")
    print("=" * 60)
    tests = [
        test_presets_exist,
        test_whole_file,
        test_small_text,
        test_balanced_preset,
        test_unknown_preset_fallback,
        test_preset_serialization,
        test_backward_compat,
        test_all_presets_preset,
        test_call_api_stream_uses_preset,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            check(t.__name__, False, f"{type(e).__name__}: {e}")
    print()
    print("=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
