"""
v5.4.3 (F8 / F9 / F15) 事件推送通道 + 视图事件委派 + 命名空间回归。

背景 (PLAN-defect-fix-2026-09-27.md §F8 / §F9 / §F15):

F8 — `Backend._flush` 丢事件
    旧版先 `clear()` buffer 再序列化, 且 `json.dumps` 在 `try` 之外。
    `evaluate_js` 抛异常 (WebView 关闭中) 就永久丢事件; 丢的是
    onTaskComplete / onFileDone → 前端 isProcessing 永不复位、开始按钮永久禁用。
    v1 的回灌方案有四个洞: 回灌后没人重新 arm Timer (失败的恰是最后一批时
    事件永不送达, 正是本项要修的 bug)、非幂等 handler 会被重复投递、
    重试风暴 + buffer 单调增长 (O(n²))、毒丸批次回灌后永久毒住通道。
    → 改法四件事一起做: 重投后重新 arm / 重试预算 2 次 / 序列化失败直接丢弃
      绝不回灌 / buffer 上限 2000 条。

F9 — `MULTI_ALLOWED` 漏 3 个离散事件
    onChunkProgress / onDeaiTextDrop / onSplitterProgress 原先落"同名覆盖"类,
    同 33ms 窗口内只留最后一条。onSplitterProgress 更糟: 前端连 case 都没有,
    是个死事件 (切分进度条只能 0% 直接跳 100%)。
    → 后端补进 MULTI_ALLOWED; 前端**不加 case**, 走 app.js `default:` 分支
      委派给 splitter.onEvent, 保持 app.js 零 splitter 知识。

F15 — `web/views/novel-splitter.js` 的 `window.App` 与 app.js 的 `window.app`
    是两个对象 → log/toast 的 typeof 守卫恒假, 切分日志与 toast 永久走
    console 分支 (build.spec console=False, 用户什么都看不到)。

⚠ 本文件里 2 / 2000 / 5 三个数是**初始拍定值, 未做真实样本校准**
  (AGENTS.md §34 口径)。这里只断言「代码里写的那个数」的行为,
  不断言「这个数是对的」—— 后者需要真实样本, 不由单元测试负责。
"""
import re
import sys
import inspect
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))  # tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

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


# ====== 工具 ======

def make_failing_window(attempts, exc_factory):
    """建一个每次 evaluate_js 都抛异常的 mock window, 记录尝试次数。"""
    attempts["n"] = 0
    attempts["payloads"] = []

    class FailingWindow:
        def evaluate_js(self, js):
            attempts["n"] += 1
            attempts["payloads"].append(js)
            raise exc_factory()

    return FailingWindow()


def make_ok_window(calls, boom=None):
    """建一个记录调用的 mock window; boom 若是 callable 则在序列化时炸。"""
    calls["js"] = []
    calls["count"] = 0

    class OkWindow:
        def evaluate_js(self, js):
            calls["count"] += 1
            calls["js"].append(js)

    return OkWindow()


def code_only(path: Path) -> str:
    """只留可执行代码: 去掉 /* */ 块注释与 // 行注释。

    负向断言 (「不该出现 window.App」) 必须基于代码而非全文 ——
    修复时写的说明注释里往往就含被禁的字面量, 全文子串匹配会把自己判死
    (批次 1 的 820080f 踩过这个坑)。
    """
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out = []
    for line in src.splitlines():
        i = line.find("//")
        if i >= 0:
            line = line[:i]
        out.append(line)
    return "\n".join(out)


# ====== F8-①  投递失败 → 回灌 + 重新 arm ======

def test_f8_reraises_timer_on_failure():
    """evaluate_js 抛异常时: 批次被回灌, 且**没有任何新事件**也会自己重试。

    这是本项最核心的一条: 旧版回灌只做 `buffer[:0] = events`, 而 Timer 只在
    `_push` 里创建 —— 若失败的正是最后一批 (onTaskComplete), 之后再无 push,
    事件永不送达。修法是失败路径也要走 `_arm_push_timer_locked`。
    """
    from app.web_backend import Backend

    b = Backend(window=None)
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("webview 已关闭"))

    b._push("onTaskComplete", {"task_id": "t1"})
    # 不再 push 任何东西 —— 只靠回灌自带的 Timer 就要把这一批重试掉
    time.sleep(0.5)

    check("F8 失败后至少投递 3 次 (首发 + 2 次重试)", att["n"] >= 3, f"attempts={att['n']}")
    check("F8 重试有界, 无 33ms 风暴", att["n"] <= 5, f"attempts={att['n']}")
    check("F8 超出预算后停止重试", b._push_retry_slot is None,
          repr(b._push_retry_slot))
    check("F8 超出预算后重试计数停在预算上限",
          b._push_retry_count == 2, f"retry_count={b._push_retry_count}")
    check("F8 未误熔断 (重试预算是 2, 熔断阈值 5)",
          b._push_disabled is False, f"disabled={b._push_disabled}")
    # 每一轮都带上了完整的 task_id —— 说明回灌的是同一批, 不是新造的空批
    check("F8 每轮都带 onTaskComplete",
          all('"onTaskComplete"' in p for p in att["payloads"]),
          str(att["payloads"])[:200])


def test_f8_budget_exhaustion_drops_batch():
    """重试预算耗尽 → 丢弃该批 (而非无限重投), 且 buffer 不残留。"""
    from app.web_backend import Backend
    from app.web_backend import _PUSH_RETRY_BUDGET, _PUSH_RETRY_BUDGET as _B

    b = Backend(window=None)
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("dead"))
    b._push("onFileDone", {"file_key": "f1", "status": "completed"})
    time.sleep(0.5)

    check("F8 预算耗尽后精确尝试 1+预算 次", att["n"] == 1 + _B, f"attempts={att['n']}")
    check("F8 预算常量是 2", _PUSH_RETRY_BUDGET == 2, str(_PUSH_RETRY_BUDGET))
    check("F8 丢弃后 buffer 为空", b._push_buffer == [], str(b._push_buffer))
    check("F8 丢弃后重投槽为空", b._push_retry_slot is None, repr(b._push_retry_slot))


def test_f8_poison_batch_dropped_not_requeued():
    """json.dumps 抛错 (自引用 → Circular reference) → 丢弃, 绝不回灌。

    回灌毒丸的后果: 此后每次 flush 都在它上面失败, 整条事件通道对该会话
    永久死掉 (v1 的回归用例恰好把这个坏行为写成了期望)。
    """
    from app.web_backend import Backend

    b = Backend(window=None)
    calls = {}
    b._window = make_ok_window(calls)

    loop = []
    loop.append(loop)          # 自引用 → json.dumps 抛 ValueError
    b._push("onStream", loop)
    time.sleep(0.3)

    check("F8 毒丸批次未进入 evaluate_js", calls["count"] == 0, f"count={calls['count']}")
    check("F8 毒丸批次未被回灌", b._push_retry_slot is None, repr(b._push_retry_slot))
    check("F8 毒丸批次未滞留 buffer", b._push_buffer == [], str(b._push_buffer))
    check("F8 毒丸未计入失败streak (不误熔断)", b._push_fail_streak == 0,
          f"streak={b._push_fail_streak}")

    # 通道必须还能正常工作
    b._push("onStatsUpdate", {"done": 1})
    time.sleep(0.3)
    check("F8 毒丸之后通道仍可用", calls["count"] == 1, f"count={calls['count']}")
    check("F8 毒丸之后正常事件送达",
          calls["js"] and '"done": 1' in calls["js"][0], str(calls["js"])[:200])


def test_f8_buffer_cap_prefers_onlog():
    """buffer 超上限: 优先丢最旧的 onLog, 离散事件保住。"""
    from app.web_backend import Backend, _PUSH_MAX_BUFFER

    b = Backend(window=None)
    calls = {}
    b._window = make_ok_window(calls)

    check("F8 buffer 上限常量是 2000", _PUSH_MAX_BUFFER == 2000, str(_PUSH_MAX_BUFFER))
    # 先塞满 onLog, 再塞一个离散事件 (它必须活到最后)
    for i in range(_PUSH_MAX_BUFFER + 50):
        b._push("onLog", f"log-{i}")
    b._push("onTaskComplete", {"task_id": "keep-me"})

    check("F8 buffer 不超上限", len(b._push_buffer) <= _PUSH_MAX_BUFFER,
          f"len={len(b._push_buffer)}")
    check("F8 溢出时优先丢 onLog 而非离散事件",
          b._push_buffer and b._push_buffer[-1] == ("onTaskComplete", {"task_id": "keep-me"}),
          str(b._push_buffer[-1]) if b._push_buffer else "(空)")
    check("F8 最早的日志已被丢弃", b._push_buffer[0][1] != "log-0", str(b._push_buffer[0]))


def test_f8_buffer_cap_drops_oldest_when_no_logs():
    """全是离散事件时超额 → 丢最旧的一条 (并留 logger.error, 不静默)。"""
    from app.web_backend import Backend, _PUSH_MAX_BUFFER

    b = Backend(window=None)
    calls = {}
    b._window = make_ok_window(calls)
    for i in range(_PUSH_MAX_BUFFER + 5):
        b._push("onFileDone", {"i": i})
    check("F8 无日志可丢时也收敛到上限内", len(b._push_buffer) <= _PUSH_MAX_BUFFER,
          f"len={len(b._push_buffer)}")
    check("F8 丢的是最旧的几条",
          b._push_buffer[0][1] == {"i": 5}, str(b._push_buffer[0]))


def test_f8_circuit_breaker_on_repeated_failure():
    """连续失败达阈值 → 熔断本会话推送, 不再无界堆积。"""
    from app.web_backend import Backend, _PUSH_FAIL_STREAK_MAX

    check("F8 熔断阈值常量是 5", _PUSH_FAIL_STREAK_MAX == 5, str(_PUSH_FAIL_STREAK_MAX))

    b = Backend(window=None)
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("dead"))
    # 每轮: 首发 1 次 + 重试 2 次 = 3 次失败 → streak 累到 3; 再一轮即触发熔断
    for _ in range(2):
        b._push("onLog", "boom")
        time.sleep(0.4)
    check("F8 连续失败后已熔断", b._push_disabled is True,
          f"disabled={b._push_disabled} streak={b._push_fail_streak}")
    before = att["n"]
    b._push("onLog", "after breaker")
    time.sleep(0.3)
    check("F8 熔断后不再投递", att["n"] == before, f"{before} -> {att['n']}")
    check("F8 熔断后不攒 buffer", b._push_buffer == [], str(b._push_buffer))


def test_f8_normal_path_three_classes_unchanged():
    """正常路径行为不变: 累积类 / 多事件类 / 默认覆盖类。"""
    from app.web_backend import Backend

    b = Backend(window=None)
    calls = {}
    b._window = make_ok_window(calls)
    b._push("onLog", "a")
    b._push("onLog", "b")
    b._push("onFileStart", "f1")
    b._push("onFileStart", "f2")
    b._push("onStream", {"p": "v1"})
    b._push("onStream", {"p": "v2"})
    time.sleep(0.3)
    js = calls["js"][-1]
    check("F8 onLog 累积成 1 条", js.count('"onLog"') == 1, js[:200])
    # 累积后两条日志合成**一个** JSON 字符串 "a\nb" (payload 里是转义的 \n),
    # 不是各自带引号的两个元素 —— 断言必须按合成后的形态写。
    check("F8 onLog 两条合并且都在", '"a\\nb"' in js, js[:200])
    check("F8 onFileStart 保留 2 条", js.count('"onFileStart"') == 2, js[:200])
    check("F8 onStream 覆盖为最后一条",
          js.count('"onStream"') == 1 and '"v2"' in js and '"v1"' not in js, js[:200])
    check("F8 成功后重试计数归零", b._push_retry_count == 0, str(b._push_retry_count))
    check("F8 成功后失败计数归零", b._push_fail_streak == 0, str(b._push_fail_streak))


# ====== F9  事件分类 ======

def test_f9_discrete_events_not_merged():
    """同窗口内 3 个新补的离散事件全部保留 (原先同名覆盖只剩最后一个)。"""
    from app.web_backend import Backend

    b = Backend(window=None)
    calls = {}
    b._window = make_ok_window(calls)
    b._push("onChunkProgress", {"file_key": "f1", "chunk": 1, "total": 3})
    b._push("onChunkProgress", {"file_key": "f1", "chunk": 2, "total": 3})
    b._push("onDeaiTextDrop", {"target": "deai", "paths": ["p1"]})
    b._push("onDeaiTextDrop", {"target": "deai", "paths": ["p2"]})
    b._push("onSplitterProgress", {"stage": "processing", "current": 1, "total": 2})
    b._push("onSplitterProgress", {"stage": "done", "current": 2, "total": 2})
    time.sleep(0.3)
    js = calls["js"][-1]
    check("F9 onChunkProgress 2 条都保留", js.count('"onChunkProgress"') == 2, js[:300])
    check("F9 onChunkProgress 两条内容都在",
          '"chunk": 1' in js and '"chunk": 2' in js, js[:300])
    check("F9 onDeaiTextDrop 2 条都保留", js.count('"onDeaiTextDrop"') == 2, js[:300])
    check("F9 onDeaiTextDrop 两条 paths 都在", '"p1"' in js and '"p2"' in js, js[:300])
    check("F9 onSplitterProgress 2 条都保留", js.count('"onSplitterProgress"') == 2, js[:300])
    check("F9 onSplitterProgress 两形态都在",
          '"processing"' in js and '"done"' in js, js[:300])


def test_f9_order_preserved():
    """MULTI_ALLOWED 事件之间保持推送顺序 (前端按序应用)。"""
    from app.web_backend import Backend

    b = Backend(window=None)
    calls = {}
    b._window = make_ok_window(calls)
    for i in range(6):
        b._push("onSplitterProgress", {"stage": "processing", "current": i, "total": 6})
    time.sleep(0.3)
    js = calls["js"][-1]
    idx = [js.index(f'"current": {i}') for i in range(6)]
    check("F9 onSplitterProgress 保持推送顺序", idx == sorted(idx), str(idx))


# ====== F15 / F9 前端 (静态源码断言) ======

def test_f15_no_window_app_capital():
    """F15: novel-splitter.js 的代码里不再有大写 window.App。"""
    src = code_only(WEB_DIR / "views" / "novel-splitter.js")
    check("F15 novel-splitter.js 代码不含 window.App", "window.App" not in src,
          src[:200])
    check("F15 守卫改用 window.app.appendLog",
          "typeof window.app.appendLog === 'function'" in src)
    check("F15 调用点也改成 window.app (只改守卫会 TypeError)",
          "window.app.appendLog('[小说切分] ' + msg)" in src)
    check("F15 toast 守卫与调用点都改成 window.app",
          "typeof window.app.showToast === 'function'" in src
          and "window.app.showToast(msg, type || 'info')" in src)
    check("F15 挂载点改成 window.app.splitter",
          "window.app.splitter = splitter" in src)


def test_f9_delegation_not_case():
    """F9: app.js 不新增 onSplitterProgress 的 case, 只在 default: 委派。"""
    app = code_only(WEB_DIR / "app.js")
    check("F9 app.js 不硬编码 onSplitterProgress", "onSplitterProgress" not in app,
          "app.js 里出现了事件名")
    check("F9 app.js 走 splitter.onEvent 委派",
          "window.app.splitter.onEvent" in app)
    check("F9 未知事件仍落 console.warn (不静默吞)",
          "console.warn('未知事件:'" in app)


def test_f9_splitter_claims_event():
    """F9: splitter 侧认领 onSplitterProgress, 并按 stage 分两种形态渲染。"""
    src = code_only(WEB_DIR / "views" / "novel-splitter.js")
    check("F9 splitter 提供 onEvent 入口", "onEvent(name, data)" in src)
    check("F9 onEvent 认领 onSplitterProgress",
          "name === 'onSplitterProgress'" in src)
    check("F9 done 形态单独分支", "data.stage === 'done'" in src)
    check("F9 processing 形态按 current/total 算宽度",
          "current / total * 100" in src)
    check("F9 done 形态固定 100% (不按 current/total 算宽度)",
          "fill.style.width = '100%'" in src)
    check("F9 done 形态显示 success/fail 统计",
          "成功 / " in src and "data.success" in src and "data.fail" in src)
    check("F9 onEvent 对未认领的事件返回 false (不吞)",
          re.search(r"onEvent\(name, data\) \{.*?return false;", src, re.S) is not None)


if __name__ == "__main__":
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
