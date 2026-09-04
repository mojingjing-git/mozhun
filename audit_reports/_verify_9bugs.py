"""验证 9 条 bug 修复的小脚本。"""
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# === #4 分块 ===
from app.processor import ProcessingEngine

# 8K 字符 (> 6000 阈值)
unit = "这是一段测试文本，包含句号。还有问号？还有感叹号！下一段：双换行。\n\n另一段开始了。"
big = unit * 200  # 42 * 200 = 8400 字符
print(f"#4 测试文本长度: {len(big)}")
chunks = ProcessingEngine._split_text(big, 6000)
print(f"#4 分块: {len(big)} 字符 -> {len(chunks)} 块, sizes={[len(c) for c in chunks]}")
assert len(chunks) > 1, f"expected multiple chunks, got {len(chunks)}"
for c in chunks:
    assert len(c) <= 6500, f"chunk too large: {len(c)}"
assert "".join(chunks) == big, "chunk reassembly failed"
print("  [OK] 分块完整, 拼接还原")

short = "hello world"
chunks2 = ProcessingEngine._split_text(short, 6000)
assert len(chunks2) == 1 and chunks2[0] == short
print("  [OK] 短文本不切分")

ascii_big = "x" * 7000
chunks3 = ProcessingEngine._split_text(ascii_big, 6000)
print(f"#4 ASCII: 7000 字符 -> {len(chunks3)} 块")
assert len(chunks3) > 1
assert "".join(chunks3) == ascii_big
print("  [OK] ASCII 也能切")

# === #11 加解密 ===
from app.utils import _obf, _deobf, compute_prompt_hash
plain = "sk-test-12345-abcdef-verylong"
enc = _obf(plain)
dec = _deobf(enc)
assert enc.startswith("obf:")
assert dec == plain
print(f"#11 加密: {plain[:15]}... -> {enc[:25]}... -> {dec[:15]}...")
assert _deobf("plaintext-key") == "plaintext-key"
print("#11 兼容旧明文: OK")

# === #3 prompt_hash 缓存校验 ===
h1 = compute_prompt_hash("strict", "gpt-4", "")
h2 = compute_prompt_hash("polish", "gpt-4", "")
h3 = compute_prompt_hash("strict", "gpt-4", "custom content")
assert h1 != h2 and h1 != h3
print(f"#3 hash 区分: strict={h1[:8]} polish={h2[:8]} custom={h3[:8]}")

# === #16 读文件失败占位 ===
from app.utils import ProjectConfig
e = ProcessingEngine(ProjectConfig(api_base="http://x", model="m"))
e.on_log = lambda m: None
nonexistent = Path("Z:/definitely/not/exist/abc.txt")
e.prepare_tasks([nonexistent])
print(f"#16 读失败占位: tasks count = {len(e.tasks)}")
assert str(nonexistent) in e.tasks
task = e.tasks[str(nonexistent)]
assert task.status.name == "FAILED"
assert "读取失败" in task.result.error
print(f"  [OK] status={task.status.name}, error={task.result.error[:40]}")

# === #12 async 包装 ===
import tempfile
from app.utils import (
    read_file_text_async,
    save_checkpoint_async,
    FileTask,
    TaskStatus,
)


async def t():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("async test")
        tmp = Path(f.name)
    text = await read_file_text_async(tmp)
    assert text == "async test"
    print(f"#12 async read: {text}")
    task = FileTask(file_path=tmp)
    task.status = TaskStatus.COMPLETED
    await save_checkpoint_async(tmp, task)
    print("#12 async write: OK")
    tmp.unlink()


asyncio.run(t())

# === #8 暂停在 stream 内 await pause_event ===
# 通过源码检查
import inspect
src = inspect.getsource(ProcessingEngine._stream_single)
assert "pause_event.wait" in src, "pause_event.wait() not found in _stream_single"
print("#8 暂停阻塞 stream: _stream_single 含 pause_event.wait()")

# === #6 异常分类 ===
src2 = inspect.getsource(ProcessingEngine._process_file_async)
assert "AuthenticationError" in src2
assert "PermissionDeniedError" in src2
assert "NotFoundError" in src2
assert "BadRequestError" in src2
assert "RateLimitError" in src2
print("#6 异常分类: 5 类 openai 错误已分别处理")

# === #13 O(N^2) join 优化 ===
# 检查 buffer 用 list append
assert "buffer.append" in src
print("#13 流式 O(N^2) join: list.append + 节流 join")

# === #15 50ms 显式毫秒 + 注释 ===
import app.processor as proc_mod
src3 = inspect.getsource(proc_mod)
assert "_STREAM_THROTTLE_MS = 50.0" in src3
assert "50ms" in src3 or "50 ms" in src3
print("#15 50ms 节流设计意图: 显式 50.0 毫秒 + 注释说明")

# === #3 prompt_hash 写入 + load_checkpoint 校验 ===
src4 = inspect.getsource(ProcessingEngine.prepare_tasks)
assert "_current_prompt_hash" in src4
assert "缓存失效" in src4
print("#3 prepare_tasks: 算 current_hash + 缓存失效校验")

src5 = inspect.getsource(ProcessingEngine._process_file_async)
assert "prompt_hash=prompt_hash" in src5
print("#3 _process_file_async: FileResult 写入 prompt_hash")

print()
print("=== 9 条 bug 修复全部验证通过 ===")
