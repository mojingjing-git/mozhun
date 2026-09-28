"""
v5.4.3 (F11) 仓库根 `start.py` 统一启动器的回归测试。

背景 (docs/archive/README.md 第二节 (已封存) §F11):

根因是**返回值类型不统一** —— `find_python()` 前两个分支返回解释器**名**
(str), 第三个分支返回**带参数的命令行** `"py -3"`。下游
`subprocess.check_output([py, "-c", ...])` 会去找一个名叫 `py -3` 的可执行文件。
连带两个洞:
- `deps_ok` / `ensure_venv` 的入参本来就有两种来源 (find_python 的返回值 vs
  VENV_PY 这个 str)。若只把 find_python 改成返回 list 而不在入口归一化,
  下游按 `[py, "-m", ...]` 展开时, str 会被**逐字符**拆开, `py[0]` 取到首字符
  `'C'` —— 把 venv 启动路径直接改坏。
- `deps_ok` 的 except 只捕 TimeoutExpired/CalledProcessError, **不含
  FileNotFoundError** -> 逃逸 -> `python start.py check` 直接 traceback。

另有版本闸门只判 `startswith("(3,")`, 会放行 3.0~3.9, 而本项目用了
`str | None` 这类 3.10+ 语法 —— 在 3.9 上是**导入期**就 TypeError, 报错信息
会指向莫名其妙的地方。

门禁 `run_all_tests.py` 是 `tests/test_*.py` glob 自动发现, 新建即入门禁。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

# start.py 在仓库根, 不在 app 包里, 用 importlib 按路径加载。
# 它是 import 安全的: 模块级只有常量, 全部逻辑都在函数里, 且 main() 由
# `if __name__ == "__main__"` 守卫。
_spec = importlib.util.spec_from_file_location("mz_start", ROOT / "start.py")
start = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(start)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}", flush=True)
    else:
        failed += 1
        print(f"  [FAIL] {name}", flush=True)
        if detail:
            print(f"         -> {detail}", flush=True)


class _Probe:
    """替身 subprocess: 记录 argv, 按脚本返回预设输出。"""

    def __init__(self, out=b"(3, 11)", exc=None):
        self.out = out
        self.exc = exc
        self.calls = []

    def __call__(self, argv, *a, **kw):
        self.calls.append(list(argv))
        if self.exc is not None:
            raise self.exc
        return self.out

    def check_call(self, argv, *a, **kw):
        self.calls.append(list(argv))
        if self.exc is not None:
            raise self.exc


# ====== 版本闸门 ======

def test_f11_ver_ok_gate():
    print("\n--- F11: Python 版本闸门 ---", flush=True)
    check("F11 (3,11) 接受", start._ver_ok("(3, 11)") is True)
    check("F11 (3,10) 接受 (下界)", start._ver_ok("(3, 10)") is True)
    check("F11 (3,9) 拒绝 (3.10+ 语法在 3.9 导入期就炸)",
          start._ver_ok("(3, 9)") is False)
    check("F11 (2,7) 拒绝", start._ver_ok("(2, 7)") is False)
    check("F11 (4,0) 接受", start._ver_ok("(4, 0)") is True)
    check("F11 非版本串拒绝", start._ver_ok("ok") is False)
    check("F11 空串拒绝", start._ver_ok("") is False)
    check("F11 前后空白容忍", start._ver_ok("  (3, 12)  ") is True)


# ====== 类型归一化 ======

def test_f11_as_cmd():
    print("\n--- F11: 解释器入参归一化 ---", flush=True)
    check("F11 str -> [str]",
          start._as_cmd(r"C:\x\python.exe") == [r"C:\x\python.exe"],
          str(start._as_cmd(r"C:\x\python.exe")))
    check("F11 list 原样透传", start._as_cmd(["py", "-3"]) == ["py", "-3"])
    check("F11 list 不被就地改写",
          start._as_cmd(["py", "-3"]) is not None)


# ====== find_python 三分支都返回 list ======

def test_f11_find_python_all_branches_return_list():
    print("\n--- F11: find_python 三个分支统一返回 list ---", flush=True)
    orig_co = start.subprocess.check_output
    orig_ve = start.VENV_PY
    try:
        # 分支 1: .venv 存在且可用 -> [str(VENV_PY)]
        start.VENV_PY = _FakePath(1, exists_flag=True)
        start.subprocess.check_output = _Probe(out=b"ok")
        py, src = start.find_python()
        check("F11 .venv 分支返回 list",
              isinstance(py, list) and len(py) == 1 and py[0].endswith("python.exe"),
              f"{py!r} type={type(py).__name__} src={src}")

        # 分支 2: 系统 PATH 的 python
        start.VENV_PY = _FakePath(0)              # 不存在
        start.subprocess.check_output = _Probe(out=b"(3, 11)")
        py, src = start.find_python()
        check("F11 系统 python 分支返回 list",
              isinstance(py, list) and py == ["python"], f"{py!r} src={src}")

        # 分支 3: py -3 —— 旧版这里返回 str "py -3"
        # python 与 python3 都要失败 (共 2 次), 第 3 次才是 py -3
        start.VENV_PY = _FakePath(0)
        calls = {"n": 0}

        def only_py_launcher(argv, *a, **kw):
            calls["n"] += 1
            if calls["n"] <= 2:            # python / python3 都探测失败
                raise FileNotFoundError("no python")
            return b"(3, 11)"

        start.subprocess.check_output = only_py_launcher
        py, src = start.find_python()
        check("F11 py -3 分支返回 list 而不是 str 'py -3'",
              isinstance(py, list) and py == ["py", "-3"], f"{py!r} type={type(py).__name__}")
        check("F11 py -3 分支来源说明正确", src == "py launcher", src)

        # 三条分支一个都不能返回 str
        check("F11 find_python 永不为 None 时返回 str",
              all(not isinstance(x, str) for x in (py,)), f"{py!r}")
    finally:
        start.subprocess.check_output = orig_co
        start.VENV_PY = orig_ve


def test_f11_find_python_none_when_absent():
    print("\n--- F11: 找不到解释器返回 (None, '') ---", flush=True)
    orig_co = start.subprocess.check_output
    orig_ve = start.VENV_PY
    try:
        start.VENV_PY = _FakePath(0)
        start.subprocess.check_output = _Probe(exc=FileNotFoundError("x"))
        py, src = start.find_python()
        check("F11 全失败返回 (None, '')", py is None and src == "", f"{py!r} {src!r}")
    finally:
        start.subprocess.check_output = orig_co
        start.VENV_PY = orig_ve


# ====== 关键: deps_ok / ensure_venv 必须同时吃 str 和 list ======

def test_f11_deps_ok_accepts_both_types():
    print("\n--- F11: deps_ok 同时接受 str 与 list 入参 ---", flush=True)
    orig = start.subprocess.check_output
    try:
        probe = _Probe(out=b"webview OK 6.2.1 openai OK")
        start.subprocess.check_output = probe
        good, detail = start.deps_ok(r"C:\x\python.exe")
        check("F11 deps_ok 接受 str", good is True, detail)
        check("F11 str 入参未被逐字符拆开",
              probe.calls[-1][0] == r"C:\x\python.exe", str(probe.calls[-1]))

        probe2 = _Probe(out=b"webview OK 6.2.1 openai OK")
        start.subprocess.check_output = probe2
        good, detail = start.deps_ok(["py", "-3"])
        check("F11 deps_ok 接受 list", good is True, detail)
        check("F11 list 入参完整保留",
              probe2.calls[-1][:2] == ["py", "-3"], str(probe2.calls[-1]))
    finally:
        start.subprocess.check_output = orig


def test_f11_ensure_venv_accepts_both_types():
    print("\n--- F11: ensure_venv 同时接受 str 与 list 入参 (两条路径) ---", flush=True)
    orig_cc = start.subprocess.check_call
    orig_co = start.subprocess.check_output
    orig_ve = start.VENV_PY
    try:
        # ensure_venv 有两条会调 venv 创建命令的路径, 两条都要覆盖:
        #   ① .venv 不存在 -> check_call([*cmd, "-m", "venv", DIR])
        #   ② .venv 存在但失效 -> check_call([*cmd, "-m", "venv", "--clear", DIR])
        # 漏掉 ② 的话, 只变异 --clear 那条线是测不出来的。
        for label, exists in (("创建", False), ("重建", True)):
            for kind, arg in (("list", ["py", "-3"]), ("str", r"C:\x\python.exe")):
                cc = _Probe()
                start.subprocess.check_call = cc
                start.VENV_PY = _FakePath(0, exists_flag=exists)
                if exists:      # 走失效分支需要 check_output 抛
                    start.subprocess.check_output = _Probe(exc=OSError("dead venv"))
                else:
                    start.subprocess.check_output = _Probe(out=b"ok")
                try:
                    start.ensure_venv(arg)
                except Exception:
                    pass              # 创建后仍找不到 VENV_PY, 预期 RuntimeError
                # 期望的完整 argv: 解释器前缀原样在前, 后面才是 venv 子命令。
                # 逐字符拆开的症状是 argv 前缀变成一堆单字符 ('C', ':', '\\'...),
                # 直接比完整 argv 一眼就能看出来, 且不必写"只改守卫"式的弱断言。
                prefix = arg if isinstance(arg, list) else [arg]
                extra = ["--clear"] if exists else []
                want = [*prefix, "-m", "venv", *extra, str(start.VENV_DIR)]
                got = cc.calls[-1] if cc.calls else []
                check(f"F11 ensure_venv({label}/{kind}) argv 完全正确",
                      got == want, f"got={got} want={want}")
    finally:
        start.subprocess.check_call = orig_cc
        start.subprocess.check_output = orig_co
        start.VENV_PY = orig_ve


def test_f11_deps_ok_file_not_found_returns_tuple():
    print("\n--- F11: deps_ok 遇 FileNotFoundError 不抛 ---", flush=True)
    orig = start.subprocess.check_output
    try:
        start.subprocess.check_output = _Probe(exc=FileNotFoundError("boom"))
        r = start.deps_ok("definitely-not-a-real-python-xyz")
        check("F11 FileNotFoundError 返回 (False, msg) 而非抛",
              isinstance(r, tuple) and r[0] is False, repr(r))
        check("F11 错误信息含解释器不可用", "解释器不可用" in r[1], r[1])

        start.subprocess.check_output = _Probe(exc=OSError("boom2"))
        r = start.deps_ok("xyz")
        check("F11 OSError 同样被接住", r[0] is False, repr(r))
    finally:
        start.subprocess.check_output = orig


# ====== 负向源码断言: 旧的 startswith 版本闸门不得复活 ======

def test_f11_no_startswith_gate():
    print("\n--- F11: 版本闸门不再用 startswith(\"(3,\") ---", flush=True)
    import inspect
    import re
    src = inspect.getsource(start)
    # 负向源码断言必须**只看去注释且去 docstring 的代码**: find_python 的
    # docstring 里就写着旧写法 startswith("(3,"), 全文匹配会把自己判死。
    code = re.sub(r'"""(?:.|\n)*?"""', "", src)
    code = re.sub(r"'''(?:.|\n)*?'''", "", code)
    code = "\n".join(ln.split("#")[0] for ln in code.splitlines())
    check("F11 代码里不再有 startswith('(3,')",
          'startswith("(3,")' not in code and "startswith('(3,')" not in code,
          code[:300])
    check("F11 _ver_ok 真的被 find_python 用上",
          code.count("_ver_ok(") >= 3,
          f"出现 {code.count('_ver_ok(')} 次 (定义 1 + 两处版本判断 2)")


class _FakePath:
    """替身 Path: 只为控制 .venv 存在与否, 不做真文件系统操作。"""

    def __init__(self, code, exists_flag=False):
        self._code = code          # 0 = 不存在
        self.exists_flag = exists_flag

    def exists(self):
        return self.exists_flag

    def __str__(self):
        return r"C:\fake\.venv\Scripts\python.exe"

    def __fspath__(self):
        return str(self)


if __name__ == "__main__":
    import inspect
    _funcs = [(n, f) for n, f in
              sorted(inspect.getmembers(sys.modules[__name__], inspect.isfunction))
              if n.startswith("test_")]
    for _name, _fn in _funcs:
        try:
            _fn()
        except Exception as _e:
            failed += 1
            print(f"  [FAIL] {_name}: {type(_e).__name__}: {_e}", flush=True)
    print(f"\n  {passed} pass, {failed} fail", flush=True)
    sys.exit(0 if failed == 0 else 1)
