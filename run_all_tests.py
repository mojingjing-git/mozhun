"""一键跑全部测试套件, 输出 UTF-8 BOM 格式避免 PowerShell 中文乱码。"""
import subprocess
import sys
from pathlib import Path

# 强制 UTF-8 输出 (Windows GBK 编码会乱码)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

tests = [
    "test_bugs.py",
    "test_components.py",
    "test_chunker_presets.py",
    "test_chunk_lifecycle.py",
    "test_context_builder.py",
    "test_web_backend.py",
    # v4.1.7: 12 个新测试已加到 test_web_backend.py (无需单独文件)
]

total_pass = 0
total_fail = 0
results = []

for t in tests:
    print(f"\n{'='*60}\n  {t}\n{'='*60}", flush=True)
    result = subprocess.run(
        [sys.executable, t],
        cwd=str(Path(__file__).parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = result.stdout
    # 统计 PASS/FAIL 个数
    pass_n = out.count("[PASS]")
    fail_n = out.count("[FAIL]")
    total_pass += pass_n
    total_fail += fail_n
    results.append((t, pass_n, fail_n))
    # 只输出最后几行 (结果行)
    for line in out.splitlines()[-3:]:
        print(line, flush=True)

print(f"\n{'='*60}", flush=True)
print(f"  全部测试汇总: {total_pass} 通过, {total_fail} 失败", flush=True)
print(f"{'='*60}", flush=True)
for t, p, f in results:
    status = "PASS" if f == 0 else "FAIL"
    print(f"  [{status}] {t}: {p} pass, {f} fail", flush=True)

sys.exit(0 if total_fail == 0 else 1)

