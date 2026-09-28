"""
v5.4.3 (F8 / F9 / F15) 事件推送通道 + 视图事件委派 + 命名空间回归。

背景 (docs/archive/README.md 第二节 (已封存) §F8 / §F9 / §F15):

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


def make_ok_window(calls):
    """建一个记录调用的 mock window (投递一律成功)。"""
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
    check("F8 未误触发退避 (3 次失败 < 阈值 5)",
          b._flush_interval() == 0.033, str(b._flush_interval()))
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


def test_f8_retry_slot_does_not_strand_buffer():
    """B1: 取走重投槽时, 残留 buffer 必须被补一次 arm。

    这是 F8 自己的 bug 换了个形态回来 (复审 B1)。触发时序:
      1. 批次 A 的 evaluate_js 阻塞, 期间又 _push 了事件 B (B 自己 arm 了一个 Timer)
      2. A 抛异常 -> 重投槽 = [A]; B 的 Timer 已在飞, 不再补 arm
      3. B 的 Timer 触发 -> 本轮取走的是 [A] 这个重投槽, **B 留在 buffer 里**
      4. [A] 再失败 -> 预算耗尽 -> 丢弃, 不 arm
      => B 永久滞留, _push_pending 已归零, 再无 Timer。
    丢的若是 onTaskComplete, 就是"开始按钮永久禁用" —— 与 F8 修复目标逐字相同,
    且相对修复前 (buffer[:0] = events) 是**回归**: 旧版会把 A 和 B 一起送出。

    为排除时序运气, 本用例**关掉自动 arm 并手工驱动 _flush**, 让"有没有 Timer
    在飞"成为确定的事实。
    """
    from app.web_backend import Backend

    b = Backend(window=None)
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("dead"))
    # 拦掉真 Timer (否则 sleep 里会乱序), 但保留 arm 的**可观测效果**:
    # arm 成功即 pending=True, 于是"有没有为残留 buffer 补 arm"成为确定事实。
    b._arm_push_timer_locked = lambda: setattr(b, "_push_pending", True)

    b._push("onLog", "A")
    b._flush()                                    # 首发 A 失败 -> 重投槽 = [A]
    check("B1 首刷后重投槽装的是 A",
          b._push_retry_slot == [("onLog", "A")], repr(b._push_retry_slot))

    # 关键: 第二轮让投递**成功**。若投递失败, 失败路径末尾的重投 arm 也会把
    # pending 置回 True, 断言就没有区分度了 (这正是本用例第一版的毛病 ——
    # 撤掉 B1 修复后它依然 69/0 全绿, 等于零覆盖)。
    # 投递成功时 pending 唯一可能被置位的地方就是 B1 修复那一行。
    ok = {}
    b._window = make_ok_window(ok)
    b._push("onTaskComplete", {"task_id": "FINAL"})   # 新事件到达 (与 A 同窗口)
    b._flush()                                    # 取走重投槽 [A] 并投递成功
    check("B1 修复后取走重投槽时为残留 buffer 补 arm",
          b._push_pending is True,
          f"FINAL 滞留 buffer={b._push_buffer} pending={b._push_pending}")

    b._flush()                                    # 补上那次 arm 兑现: 投 FINAL
    check("B1 修复后 FINAL 真的送达",
          ok["count"] == 2 and '"FINAL"' in ok["js"][-1],
          f"count={ok['count']} last={ok['js'][-1] if ok['js'] else ''}")
    check("B1 修复后 buffer 排空", b._push_buffer == [], str(b._push_buffer))


def test_f8_exhausted_budget_does_not_wipe_concurrent_slot():
    """预算耗尽时不得清空重投槽 —— 槽里若是并发的另一轮放进去的, 清掉即丢一整批。

    本批审查追查 B1 时发现的第二个丢事件路径。交错点在 evaluate_js 期间:
    本轮已把自己的批次取走, 正等在 evaluate_js 里, 另一轮 _flush 趁机把它的
    批次放进了重投槽; 本轮随后失败并耗尽预算 —— 此时**只能丢自己那一批**,
    一旦顺手写 `self._push_retry_slot = None`, 就把别人的批次一并抹掉。

    单线程调不动这个交错 (本轮失败路径执行时槽已被自己取空), 所以让
    evaluate_js 自己去装那一份来模拟"并发的另一轮", 从而让断言可判定。
    """
    from app.web_backend import Backend

    b = Backend(window=None)
    b._arm_push_timer_locked = lambda: None
    b._push("onLog", "OWN")           # 本轮自己的那一批

    class ConcurrentInjector:
        """模拟: evaluate_js 期间另一轮 _flush 把自己的批次放进了重投槽, 随后本轮失败。

        两个必须:
        - 装完槽**再抛** —— 只装不抛则投递算成功, 失败分支根本走不到 (恒绿)
        - 只在第 3 次注入 —— 预算耗尽分支要求已试满 1+预算 次
        """

        def __init__(self):
            self.n = 0

        def evaluate_js(self, js):
            self.n += 1
            if self.n >= 3:            # 这一次本轮将耗尽预算
                b._push_retry_slot = [("onLog", "CONCURRENT")]
            raise RuntimeError("dead")

    w = ConcurrentInjector()
    b._window = w
    b._flush()                        # 首发 OWN 失败 -> 重投
    b._flush()                        # 重投 OWN 失败 -> 重试计数到上限
    b._flush()                        # OWN 预算耗尽 -> 走 else 分支
    check("确实走到了预算耗尽分支", w.n == 3, f"attempts={w.n}")
    check("预算耗尽不误清并发放进去的重投槽",
          b._push_retry_slot == [("onLog", "CONCURRENT")],
          f"slot={b._push_retry_slot} (None = 被误清, 并发那批被凭空丢掉)")


def test_f8_new_batch_gets_fresh_budget():
    """某批耗尽预算后, **下一个新批次**必须拿到完整预算, 而不是只剩 1 次。

    这是实现过程中被回归用例测出来的真缺陷: 取新批次时若漏了
    `self._push_retry_count = 0`, 计数会停在上限 2 不动, 于是此��本会话
    每个新批次都只投递 1 次 —— WebView 偶发瞬时异常再也得不到重试机会,
    通道事实上退化成"只试一次就丢"。
    """
    from app.web_backend import Backend, _PUSH_RETRY_BUDGET

    b = Backend(window=None)
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("dead"))
    b._arm_push_timer_locked = lambda: None       # 手工驱动, 排除时序

    b._push("onLog", "A")
    for _ in range(6):
        b._flush()                                 # 远超预算, 早已丢弃
    check("第一批只试 1+预算 次就收手", att["n"] == 1 + _PUSH_RETRY_BUDGET,
          f"attempts={att['n']}")
    check("第一批耗尽后计数停在预算上限", b._push_retry_count == _PUSH_RETRY_BUDGET,
          f"retry_count={b._push_retry_count}")

    n0 = att["n"]
    b._push("onTaskComplete", {"task_id": "B"})     # 全新批次
    for _ in range(6):
        b._flush()
    check("新批次拿到完整重试预算 (不是只剩 1 次)",
          att["n"] - n0 == 1 + _PUSH_RETRY_BUDGET,
          f"新批次只试了 {att['n'] - n0} 次 (期望 {1 + _PUSH_RETRY_BUDGET})")


def test_f8_no_retry_for_corrupting_events():
    """M2: 不可重投事件投递失败时必须**丢弃**, 绝不放回重投槽。

    evaluate_js 抛异常时无法区分"JS 没跑"和"JS 跑完但返回值回传失败",
    重投就有真实概率把同一事件投两遍。onDeaiTextDrop 的 handler
    _applyDroppedText 会再读一次文件、再追加一遍 -> 同一段文本凭空出现两遍,
    静默且用户极难察觉。宁可丢 (重新拖一次) 也不能投第二遍。
    """
    from app.web_backend import Backend, _NO_RETRY_EVENTS

    check("onDeaiTextDrop 属不可重投集合", "onDeaiTextDrop" in _NO_RETRY_EVENTS,
          str(sorted(_NO_RETRY_EVENTS)))
    check("onTaskComplete 仍可重投 (丢了会按钮永久禁用)",
          "onTaskComplete" not in _NO_RETRY_EVENTS, str(sorted(_NO_RETRY_EVENTS)))

    # 纯 onDeaiTextDrop 批次 -> 整批丢弃, 不进重投槽
    b = Backend(window=None)
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("dead"))
    b._arm_push_timer_locked = lambda: None
    b._push("onDeaiTextDrop", {"target": "deai", "paths": ["p1"]})
    b._flush()
    check("纯不可重投批次失败后不进重投槽", b._push_retry_slot is None,
          repr(b._push_retry_slot))
    check("纯不可重投批次不再重试", att["n"] == 1, f"attempts={att['n']}")

    # 混合批次 -> 只保留可重投的那部分, 不可重投的被剔除
    b2 = Backend(window=None)
    att2 = {}
    b2._window = make_failing_window(att2, lambda: RuntimeError("dead"))
    b2._arm_push_timer_locked = lambda: None
    b2._push("onTaskComplete", {"task_id": "t1"})        # 默认覆盖类, 同名只留一条
    b2._push("onFileDone", {"file_key": "f1"})
    b2._push("onDeaiTextDrop", {"target": "deai", "paths": ["p1"]})
    b2._flush()
    names = [n for n, _ in (b2._push_retry_slot or [])]
    check("混合批次重投时剔除不可重投事件",
          "onDeaiTextDrop" not in names and "onFileDone" in names, str(names))


def test_f8_backoff_never_overflows():
    """B2: 退避指数必须钳位 —— streak 无上界, 不钳会抛 OverflowError。

    _push_fail_streak 只在**成功**时归零, 失败期单调增长。若直接算
    `0.033 * (2 ** over)`, 到 over≈1024 就超出 float 范围抛 OverflowError;
    而 16b016d 的 _arm_push_timer_locked 是"先置 _push_pending=True 再求值
    Timer 参数", 于是异常发生在 Timer 建好之前 -> 通道永久焊死: 之后每个
    _push 都在 _push_pending 短路, 事件只进 buffer 永不投递, 且**零日志**,
    比原来的硬熔断还糟。
    可达性: 每批 3 次失败, 2s 封顶, 约 34 分钟持续失败即触发。
    """
    from app.web_backend import (Backend, _PUSH_BACKOFF_MAX, _PUSH_BACKOFF_EXP_MAX)

    b = Backend(window=None)
    for s in (0, 5, 25, 1000, 1027, 1028, 2000, 10 ** 6):
        b._push_fail_streak = s
        try:
            iv = b._flush_interval()
        except Exception as e:
            check(f"B2 streak={s} 不抛", False, f"{type(e).__name__}: {e}")
            continue
        # 低 streak 本来就不在退避态, 只要求"有界"; 深退避才要求已封顶
        # 退避曲线: streak<5 -> 33ms; streak>=5 起按 2 的幂涨, streak>=10 撞上
        # _PUSH_BACKOFF_MAX=2.0 封顶 (0.033 * 2**6 = 2.112 >= 2.0)
        capped = s >= 10
        want = _PUSH_BACKOFF_MAX if capped else (0.033 if s < 5 else 0.033 * 2 ** (s - 4))
        check(f"B2 streak={s} 不抛且间隔有界", iv == want, f"iv={iv} 期望={want}")
    check("B2 指数钳位常量是 32", _PUSH_BACKOFF_EXP_MAX == 32, str(_PUSH_BACKOFF_EXP_MAX))


def test_f8_arm_is_idempotent():
    """L7: arm 幂等守卫要有**定向**断言, 不能只靠 buffer 上限用例顺带撞到。

    守卫生效: 已 pending 时不再起第二个 Timer。反例: 去掉守卫后同一批
    会被两个 Timer 各投一次 -> 前端收到重复的离散事件。
    """
    from app.web_backend import Backend
    import app.web_backend as wbmod

    b = Backend(window=None)
    b._window = make_failing_window({}, lambda: RuntimeError("dead"))
    # 必须用**真** _arm_push_timer_locked —— 幂等守卫生存在它内部, 替换掉
    # 就等于把被测对象一起删了。改为拦截 Timer 的**构造**来数 arm 次数,
    # 且不真的 start (免得真去 flush)。
    built = []
    orig = wbmod.threading.Timer

    class CountingTimer(orig):
        def __init__(self, *a, **kw):
            built.append(a)
            super().__init__(*a, **kw)

        def start(self):
            pass                  # 故意不启动: 本用例只关心"有没有建 Timer"

    wbmod.threading.Timer = CountingTimer
    try:
        b._push("onLog", "A")
        first = len(built)
        b._push("onLog", "B")     # 已 pending -> 守卫应短路
    finally:
        wbmod.threading.Timer = orig

    check("L7 首次 push 建了 1 个 Timer", first == 1, f"建了 {first} 个")
    check("L7 已 pending 时不重复 arm",
          len(built) == 1,
          f"累计建了 {len(built)} 个 Timer (2 = 幂等守卫失效, 同一批会被两个 Timer 各投一次)")
    check("L7 B 仍留在 buffer 等这一轮一起送",
          b._push_buffer == [("onLog", "A"), ("onLog", "B")], str(b._push_buffer))


def test_f8_arm_is_exception_safe():
    """B2 兜底层: arm 路径上**任何**异常都不得把通道留在半更新状态。

    不变量: _push_pending 为 True <=> 确实有一个 Timer 在飞。
    16b016d 的 BLOCKER 就是破坏它 —— "先置 pending 再求值 Timer 参数"且无守卫,
    参数求值抛异常 (streak 极大时 2**over 溢出) 时通道被永久焊死, 零日志。

    两处注入点各测一遍: ① _flush_interval 求值抛 (B2 原始触发方式)
    ② Timer.start() 抛 (线程起不来的极端情况)。第三轮复审纠正了我上一轮
    "顺序不可观测所以不覆盖"的说法: 用实例属性桩即可让这条路径可观测。
    """
    from app.web_backend import Backend

    for where in ("interval", "start"):
        b = Backend(window=None)
        calls = {}
        b._window = make_ok_window(calls)

        import app.web_backend as wbmod
        orig_timer = wbmod.threading.Timer
        if where == "interval":
            def boom():
                raise OverflowError("模拟退避计算抛异常")
            b._flush_interval = boom
        else:
            class BoomTimer(orig_timer):
                def start(self):
                    raise RuntimeError("模拟线程起不来")
            wbmod.threading.Timer = BoomTimer
        try:
            b._push("onLog", "arm-炸")
            check(f"B2({where}) arm 抛异常后 _push_pending 已回滚",
                  b._push_pending is False,
                  f"pending={b._push_pending} (True = 通道焊死)")
            check(f"B2({where}) arm 抛异常后事件仍在 buffer (没被吞)",
                  b._push_buffer == [("onLog", "arm-炸")], str(b._push_buffer))
            if where == "interval":
                del b._flush_interval
            wbmod.threading.Timer = orig_timer
            b._push("onTaskComplete", {"task_id": f"RECOVER-{where}"})
        finally:
            wbmod.threading.Timer = orig_timer
        time.sleep(0.3)
        check(f"B2({where}) 恢复后事件真的送达",
              calls["count"] >= 1 and f"RECOVER-{where}" in calls["js"][-1],
              f"count={calls['count']}")


def test_f8_backoff_not_hard_disable():
    """连续失败进**退避**, 不是硬熔断 —— 通道必须能自愈。

    旧设计 (_push_disabled) 一旦触发就无任何复位点, pywebview 在窗口最小化/
    后台切换时可能抛一次瞬时异常, 连续几次抖动就让本会话推送永久静默,
    用户侧是"按钮永久禁用且无解释"。退避既挡风暴又保证恢复后自动补投。
    """
    from app.web_backend import (Backend, _PUSH_FLUSH_INTERVAL, _PUSH_BACKOFF_MAX,
                                 _PUSH_FAIL_STREAK_MAX)

    check("退避阈值常量是 5", _PUSH_FAIL_STREAK_MAX == 5, str(_PUSH_FAIL_STREAK_MAX))
    check("退避上限常量是 2.0 秒", _PUSH_BACKOFF_MAX == 2.0, str(_PUSH_BACKOFF_MAX))

    b = Backend(window=None)
    b._arm_push_timer_locked = lambda: None      # 手工驱动

    check("F8 失败 0 次间隔 = 33ms", b._flush_interval() == _PUSH_FLUSH_INTERVAL,
          str(b._flush_interval()))
    for n in range(1, 5):
        b._push_fail_streak = n
        check(f"F8 失败 {n} 次仍在 33ms (阈值前)", b._flush_interval() == _PUSH_FLUSH_INTERVAL,
              str(b._flush_interval()))
    b._push_fail_streak = _PUSH_FAIL_STREAK_MAX
    iv = b._flush_interval()
    check("F8 到阈值后开始退避", iv > _PUSH_FLUSH_INTERVAL, str(iv))
    b._push_fail_streak = _PUSH_FAIL_STREAK_MAX + 20
    check("F8 退避封顶不超上限", b._flush_interval() == _PUSH_BACKOFF_MAX,
          str(b._flush_interval()))
    check("F8 退避有上限, 不是无限增长", b._flush_interval() < 60,
          str(b._flush_interval()))

    # 关键: 反复失败**不会**永久禁用通道, WebView 恢复后照常投递
    att = {}
    b._window = make_failing_window(att, lambda: RuntimeError("dead"))
    for _ in range(4):                 # 远超阈值, 共 12 次失败
        b._push("onLog", "boom")
        b._flush()
        b._flush()
        b._flush()
    check("F8 反复失败后没有硬熔断开关",
          not hasattr(b, "_push_disabled"), "代码里仍有 _push_disabled 硬熔断")
    check("F8 反复失败后已退避到上限",
          b._flush_interval() == _PUSH_BACKOFF_MAX, str(b._flush_interval()))

    calls = {}
    b._window = make_ok_window(calls)   # WebView 恢复
    del b._arm_push_timer_locked         # 交还真 arm, 让真 Timer 跑起来
    b._push("onTaskComplete", {"task_id": "AFTER-RECOVERY"})
    # 此刻通道处于退避态 (间隔已是 _PUSH_BACKOFF_MAX=2s), 所以必须等超过 2s
    # 才能证明"退避只拖慢、不阻断" —— 这正是旧版硬熔断做不到的地方。
    time.sleep(_PUSH_BACKOFF_MAX + 0.6)
    check("F8 WebView 恢复后事件自动补投 (自愈)",
          calls["count"] >= 1 and '"AFTER-RECOVERY"' in calls["js"][0],
          f"count={calls['count']}")
    check("F8 恢复后失败计数归零", b._push_fail_streak == 0, str(b._push_fail_streak))
    check("F8 恢复后退避解除", b._flush_interval() == _PUSH_FLUSH_INTERVAL,
          str(b._flush_interval()))


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
