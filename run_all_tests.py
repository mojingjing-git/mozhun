"""一键跑全部测试套件, 输出 UTF-8 BOM 格式避免 PowerShell 中文乱码。"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

# v5.4.3 (F0-①): 门禁计数失真 — 17 个手写套件逐条 check() 打印, 计数 = 断言数;
# 2 个 unittest 套件 (test_novel_splitter / test_harness_split) 只在 runner 结尾
# 打印一行汇总, out.count("[PASS]") 把 63 / 35 个 test 方法各折算成 1
# (实测合计 98 个真实方法被门禁看成 2 个, 总基线少报 96)。
#
# 失效方向比"数字不准"更严重: unittest.wasSuccessful() 对 0 个用例返回 True,
# 故类名写错 / 用例被误重命名的套件会打印 [PASS] test_x (0/0) 且 exit 0 -> 静默绿灯。
#
# 修法 (只改本文件, 不动任何测试文件):
#   ① 额外解析 unittest 的 "Ran N tests" / "OK" / "FAILED", 用 N 补足该套件的通过数
#   ② 回显行从 [-3:] 改为"最后 3 行 + 含 Ran/OK/FAILED 的行"
#   ③ 子进程 env 预置 PROOFREADER_HOME (F0-② 防复发) —— 任何测试文件将来漏写
#      import test_isolate 也污染不到用户真实 ~/.proofreader
_ISOLATE_HOME = tempfile.mkdtemp(prefix="mozhun_gate_")
_RE_RAN = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)
_RE_UNIT_OK = re.compile(r"^(OK|FAILED)(?:\s|$)", re.MULTILINE)

total_pass = 0
total_fail = 0
results = []

for t in tests:
    print(f"\n{'='*60}\n  {t}\n{'='*60}", flush=True)
    result = subprocess.run(
        [sys.executable, 'tests/' + t],
        cwd=str(Path(__file__).parent),
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent),
             'PROOFREADER_HOME': _ISOLATE_HOME},
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
    # v5.4.3 (F0-①): unittest 套件只打印一行汇总 -> 按 "Ran N tests" 补足计数。
    # 只在该行出现时补 (手写套件不打印它), 避免双计。
    # ⚠ 关键: unittest.TextTestRunner 的 stream **默认是 sys.stderr**, 不是 stdout ——
    #   "Ran N tests" / "OK" 都在 err 里 (已实测), 搜 out 会永远搜不到。
    ran_m = _RE_RAN.search(err)
    if ran_m and pass_n == 1:
        ran_n = int(ran_m.group(1))
        # 0 用例 = 假绿 (unittest 对 0 用例 wasSuccessful() 为 True), 必须判失败
        if ran_n == 0:
            fail_n += 1
        elif _RE_UNIT_OK.search(err):
            pass_n = ran_n
    # v4.1.8.1 (审计 M12): returncode != 0 必须计入失败. 旧实现只看 stdout 文本,
    # 套件 import/顶层崩溃 (stdout 无 [FAIL]) 会被报成 "0 pass, 0 fail" 且 exit 0
    # -> 门禁假绿 (regression 检测形同虚设).
    crashed = rc != 0 and fail_n == 0
    if crashed:
        fail_n = 1
    total_pass += pass_n
    total_fail += fail_n
    results.append((t, pass_n, fail_n, rc))
    # v5.4.3 (F0-①): 回显"最后 3 行 (stdout) + unittest 汇总行 (stderr)",
    # 否则 N tests / OK 永远看不见
    tail = out.splitlines()[-3:]
    extra_tail = [ln for ln in err.splitlines()
                  if _RE_RAN.match(ln) or _RE_UNIT_OK.match(ln)]
    seen = set()
    for line in tail + extra_tail:
        if line in seen:
            continue
        seen.add(line)
        print(line, flush=True)
    if crashed:
        print(f"  !!! 子进程异常退出 rc={rc} (无 [FAIL] 文本, 已计入失败)", flush=True)
        for line in err.splitlines()[-8:]:
            print(f"      | {line}", flush=True)

shutil.rmtree(_ISOLATE_HOME, ignore_errors=True)

print(f"\n{'='*60}", flush=True)
print(f"  全部测试汇总: {total_pass} 通过, {total_fail} 失败", flush=True)
print(f"{'='*60}", flush=True)
for t, p, f, rc in results:
    status = "PASS" if f == 0 and rc == 0 else "FAIL"
    extra = f" (rc={rc})" if rc != 0 else ""
    print(f"  [{status}] {t}: {p} pass, {f} fail{extra}", flush=True)

sys.exit(0 if total_fail == 0 else 1)
