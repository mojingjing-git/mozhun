"""一键跑全部测试套件, 输出 UTF-8 BOM 格式避免 PowerShell 中文乱码。"""
import subprocess
import sys
from pathlib import Path

# 强制 UTF-8 输出 (Windows GBK 编码会乱码)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# v4.1.8.2 (审计 K14): 自动发现 test_*.py — 旧版硬编码清单, 新增测试文件
# 忘记登记时对门禁完全不存在 (静默盲区). test_isolate.py 是隔离样板无 main, 排除.
# v6.0 (Phase C0): test_*.py 移到 tests/ 目录, glob 路径 + cwd 同步调整.
tests = sorted(
    p.name for p in Path(__file__).parent.glob("tests/test_*.py")
    if p.name != "test_isolate.py"
)

total_pass = 0
total_fail = 0
results = []

for t in tests:
    print(f"\n{'='*60}\n  {t}\n{'='*60}", flush=True)
    result = subprocess.run(
        [sys.executable, 'tests/' + t],
        cwd=str(Path(__file__).parent),
        env={**__import__('os').environ, 'PYTHONPATH': str(Path(__file__).parent)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = result.stdout
    err = result.stderr or ""
    rc = result.returncode
    # 统计 PASS/FAIL 个数
    pass_n = out.count("[PASS]")
    fail_n = out.count("[FAIL]")
    # v4.1.8.1 (审计 M12): returncode != 0 必须计入失败. 旧实现只看 stdout 文本,
    # 套件 import/顶层崩溃 (stdout 无 [FAIL]) 会被报成 "0 pass, 0 fail" 且 exit 0
    # -> 门禁假绿 (regression 检测形同虚设).
    crashed = rc != 0 and fail_n == 0
    if crashed:
        fail_n = 1
    total_pass += pass_n
    total_fail += fail_n
    results.append((t, pass_n, fail_n, rc))
    # 只输出最后几行 (结果行)
    for line in out.splitlines()[-3:]:
        print(line, flush=True)
    if crashed:
        print(f"  !!! 子进程异常退出 rc={rc} (无 [FAIL] 文本, 已计入失败)", flush=True)
        for line in err.splitlines()[-8:]:
            print(f"      | {line}", flush=True)

print(f"\n{'='*60}", flush=True)
print(f"  全部测试汇总: {total_pass} 通过, {total_fail} 失败", flush=True)
print(f"{'='*60}", flush=True)
for t, p, f, rc in results:
    status = "PASS" if f == 0 and rc == 0 else "FAIL"
    extra = f" (rc={rc})" if rc != 0 else ""
    print(f"  [{status}] {t}: {p} pass, {f} fail{extra}", flush=True)

sys.exit(0 if total_fail == 0 else 1)
