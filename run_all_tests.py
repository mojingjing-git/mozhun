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
#   ① 从 unittest 套件自己打印的汇总行 `[PASS] test_x (63/63)` 里**直接读括号数字**,
#      补足该套件的通过数 —— 不解析 stderr、不依赖 TextTestRunner 的 stream 默认值、
#      也不依赖"pass_n == 1"这种魔法数 (三者都是隐式契约, 演进一步就会静默失效)
#   ② 回显行从 [-3:] 改为"最后 3 行 + unittest 的 Ran/OK/FAILED 行"
#   ③ 子进程 env 预置 PROOFREADER_HOME (F0-② 防复发) —— 任何测试文件将来漏写
#      import test_isolate 也污染不到用户真实 ~/.proofreader
#
# 仍保留 stderr 的 "Ran N tests" 作为**交叉校验**: 括号里的分母与 unittest 自报的
# N 不一致时判失败, 防"套件自己把数字打错"这类静默错误。
_RE_SELF_SUMMARY = re.compile(r"^\[(PASS|FAIL)\] test_\w+ \((\d+)/(\d+)\b", re.MULTILINE)
_RE_RAN = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)
_RE_UNIT_OK = re.compile(r"^OK(?:\s|$)", re.MULTILINE)   # 只认 OK, 不认 FAILED
#   (旧版 (OK|FAILED) 会让失败套件也走 pass_n = ran_n, 虚增通过数)
_RE_UNIT_FAILED = re.compile(r"^FAILED \((?:failures|errors)=(\d+)", re.MULTILINE)

total_pass = 0
total_fail = 0
results = []

# 每个套件一个隔离 home —— 旧版靠 test_isolate.py 逐个 mkdtemp, 预置 env 后
# 降级成了"整轮共用", 顺序依赖的隐患会回来。挪进循环恢复原粒度。
# 每个套件一个隔离 home —— 旧版靠 test_isolate.py 逐个 mkdtemp, 预置 env 后
# 降级成了"整轮共用", 顺序依赖的隐患会回来。挪进循环恢复原粒度。
# 外层 try/finally: Ctrl+C / OSError 时也要清干净, 否则临时目录里会留下
# checkpoint 与日志 (原版没有临时目录, 这是新增的泄漏面)。
try:
    for t in tests:
        home = tempfile.mkdtemp(prefix="mozhun_gate_")
        try:
            print(f"\n{'='*60}\n  {t}\n{'='*60}", flush=True)
            result = subprocess.run(
                [sys.executable, 'tests/' + t],
                cwd=str(Path(__file__).parent),
                env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent),
                     'PROOFREADER_HOME': home},
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

            # v5.4.3 (F0-①): unittest 套件只打印一行汇总 -> 直接读它自己打的
            #   括号数字 [PASS] test_novel_splitter (63/63)  => pass_n=63
            # 不依赖 stderr (TextTestRunner 默认写 stderr)、也不依赖
            # "pass_n==1" 这种魔法数 (两者都是隐式契约, 演进一步就会静默失效)。
            # 仍用 stderr 的 "Ran N tests" 做**交叉校验**: 括号分母与 unittest
            # 自报数不一致说明套件自己把数字打错了, 必须判失败而非照单全收。
            m = _RE_SELF_SUMMARY.search(out)
            if m:
                passed, total = int(m.group(2)), int(m.group(3))
                ran_m = _RE_RAN.search(err)
                if total == 0:
                    # 假绿: unittest.wasSuccessful() 对空 suite 返回 True
                    print(f"  !!! 套件自报 0 个用例 (类名/方法名被误改?), 已计入失败",
                          flush=True)
                    fail_n += 1
                elif ran_m and int(ran_m.group(1)) != total:
                    print(f"  !!! 自报 {total} 用例, 但 unittest 跑了 "
                          f"{ran_m.group(1)} 个, 数字不一致, 已计入失败",
                          flush=True)
                    fail_n += 1
                else:
                    pass_n = passed
                    if m.group(1) == "FAIL" and fail_n == 0:
                        fail_n += 1

            # v4.1.8.1 (审计 M12): returncode != 0 必须计入失败. 旧实现只看
            # stdout 文本, 套件 import/顶层崩溃 (stdout 无 [FAIL]) 会被报成
            # "0 pass, 0 fail" 且 exit 0 -> 门禁假绿 (regression 检测形同虚设).
            crashed = rc != 0 and fail_n == 0
            if crashed:
                fail_n = 1
            total_pass += pass_n
            total_fail += fail_n
            results.append((t, pass_n, fail_n, rc))

            # 回显"最后 3 行 (stdout) + unittest 汇总行 (stderr)",
            # 否则 N tests / OK / FAILED 永远看不见
            tail = out.splitlines()[-3:]
            extra_tail = [ln for ln in err.splitlines()
                          if _RE_RAN.match(ln) or _RE_UNIT_OK.match(ln)
                          or _RE_UNIT_FAILED.match(ln)]
            seen = set()
            for line in tail + extra_tail:
                if line in seen:
                    continue
                seen.add(line)
                print(line, flush=True)
            if crashed:
                print(f"  !!! 子进程异常退出 rc={rc} (无 [FAIL] 文本, 已计入失败)",
                      flush=True)
                for line in err.splitlines()[-8:]:
                    print(f"      | {line}", flush=True)
        finally:
            shutil.rmtree(home, ignore_errors=True)
except KeyboardInterrupt:
    print("\n[中断] 用户取消, 已清理临时目录", flush=True)
    sys.exit(130)

print(f"\n{'='*60}", flush=True)
print(f"  全部测试汇总: {total_pass} 通过, {total_fail} 失败", flush=True)
print(f"{'='*60}", flush=True)
for t, p, f, rc in results:
    status = "PASS" if f == 0 and rc == 0 else "FAIL"
    extra = f" (rc={rc})" if rc != 0 else ""
    print(f"  [{status}] {t}: {p} pass, {f} fail{extra}", flush=True)

sys.exit(0 if total_fail == 0 else 1)
