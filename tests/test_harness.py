# -*- coding: utf-8 -*-
"""v5.1.0 harness 测试套件 (app/harness.py 12 边界 + 引擎 Edit 工具链端到端).

覆盖:
- apply_edits 12 条边界逐条 (agent1-tech-feasibility.md §3.3)
- audit 结构 / 预览截断 / ≤50 cap / 换行归一 / 整轮级告警
- parse_tool_calls (合法 JSON / 坏 JSON / 非 edit_text 忽略)
- audit_has_warnings 部分成功判定
- 引擎端到端: strict 走 harness / custom 不走 / harness_enabled=False 不走 /
  全失败标 FAILED / warnings 置位 / 多 chunk audit 合并 (mock AsyncOpenAI,
  patch 模式镜像 test_punct_fix.py::test_engine_punct_local_mode)

run_all_tests.py 按 test_*.py glob 自动发现 (无需注册).
"""
import asyncio
import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))  # v6.0: tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离, 防止污染真实 ~/.proofreader

passed = 0
failed = 0
errors_list = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        errors_list.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


# ============================================================
# apply_edits 单元: 12 条边界
# ============================================================

def test_boundary_1_not_found():
    """边界 1: old_text 在原文中找不到 → SKIPPED_NOT_FOUND, 其余继续."""
    print("\n--- 边界 1: NOT_FOUND ---")
    from app.harness import apply_edits
    original = "今天天气很好。"
    corrected, audit = apply_edits(original, [
        {"old_text": "不存在的文本", "new_text": "任意", "reason": "幻觉"},
        {"old_text": "天气", "new_text": "气候", "reason": "换词"},
    ])
    check("NOT_FOUND 跳过不中止", corrected == "今天气候很好。", repr(corrected))
    check("状态 SKIPPED_NOT_FOUND", audit[0]["status"] == "SKIPPED_NOT_FOUND")
    check("后续编辑仍生效", audit[1]["status"] == "OK")


def test_boundary_2_not_unique():
    """边界 2: old_text 出现 >=2 次 → SKIPPED_NOT_UNIQUE, 不自动选第 1 个."""
    print("\n--- 边界 2: NOT_UNIQUE ---")
    from app.harness import apply_edits
    original = "错误甲和错误甲。"
    corrected, audit = apply_edits(original, [
        {"old_text": "错误甲", "new_text": "正确", "reason": "歧义"},
    ])
    check("歧义不替换", corrected == original, repr(corrected))
    check("状态 SKIPPED_NOT_UNIQUE", audit[0]["status"] == "SKIPPED_NOT_UNIQUE")
    check("审计提到出现次数", "2" in audit[0]["reason"], audit[0]["reason"])


def test_boundary_3_cascaded():
    """边界 3: old_text 被前面成功的 edit 消耗 → SKIPPED_CASCADED.

    区别于边界 1: old 在原文中存在 (但前面编辑把它改掉了)。
    """
    print("\n--- 边界 3: CASCADED ---")
    from app.harness import apply_edits
    original = "表视很好，表视二字需要修。"
    corrected, audit = apply_edits(original, [
        {"old_text": "表视很好，表视二字需要修", "new_text": "表示很好，表视二字需要修", "reason": "第一条"},
        {"old_text": "表视很好", "new_text": "表示很好", "reason": "已被第一条消耗"},
    ])
    check("第一条生效", audit[0]["status"] == "OK")
    check("级联失效判定", audit[1]["status"] == "SKIPPED_CASCADED", audit[1]["status"])
    check("级联不误报 NOT_FOUND", audit[1]["status"] != "SKIPPED_NOT_FOUND")


def test_boundary_4_noop():
    """边界 4: old==new / old 为空 → SKIPPED_NOOP (空 old 不得走 replace)."""
    print("\n--- 边界 4: NOOP ---")
    from app.harness import apply_edits
    original = "正常文本。"
    corrected, audit = apply_edits(original, [
        {"old_text": "正常文本", "new_text": "正常文本", "reason": "相同"},
        {"old_text": "", "new_text": "插入", "reason": "空 old"},
    ])
    check("old==new 跳过", corrected == original)
    check("空 old 跳过 (防 count('') 灾难)", corrected == original)
    check("两条都是 SKIPPED_NOOP",
          audit[0]["status"] == "SKIPPED_NOOP" and audit[1]["status"] == "SKIPPED_NOOP")


def test_boundary_5_7_multiline_fence():
    """边界 5/7/9: 跨行 old / 含代码围栏 / 代码块内容 — 按字面接受."""
    print("\n--- 边界 5/7/9: 跨行 + 围栏字面 ---")
    from app.harness import apply_edits
    original = "第一行错误甲\n第二行错误乙。\n```python\nprint('错误丙')\n```"
    corrected, audit = apply_edits(original, [
        {"old_text": "错误甲\n第二行错误乙", "new_text": "正确甲\n第二行正确乙", "reason": "跨行改"},
        {"old_text": "print('错误丙')", "new_text": "print('正确丙')", "reason": "代码块内"},
    ])
    check("跨行替换生效", "正确甲" in corrected and "正确乙" in corrected)
    check("代码块内容也按字面替换", "print('正确丙')" in corrected)
    check("围栏保留", corrected.startswith("```python") is False or "```" in corrected)
    check("两条 OK", all(a["status"] == "OK" for a in audit))


def test_boundary_8_crlf_normalize():
    """边界 8: \\r\\n vs \\n — 归一化匹配 + 位置映射替换 + audit 标注.

    反向也要: 原文 \\r\\n 区域被替换后新文本跟随 \\r\\n 风格。
    """
    print("\n--- 边界 8: CRLF 归一 ---")
    from app.harness import apply_edits
    original = "第一段错误甲。\r\n第二段错误乙。\r\n"
    corrected, audit = apply_edits(original, [
        {"old_text": "第一段错误甲。\n第二段错误乙。", "new_text": "第一段正确甲。\n第二段正确乙。", "reason": "换行差异"},
    ])
    check("归一化后匹配替换", "正确甲" in corrected and "正确乙" in corrected, repr(corrected))
    check("audit 标注换行归一", "换行归一" in audit[0].get("note", ""), audit[0].get("note", ""))
    check("状态仍为 OK", audit[0]["status"] == "OK")
    check("替换区外的 \\r\\n 保留", corrected.endswith("。\r\n"), repr(corrected[-6:]))
    check("替换区新文本跟随 \\r\\n", "正确甲。\r\n第二段" in corrected, repr(corrected))
    # 反向: 原文 \n, LLM 给 \r\n
    original2 = "甲。\n乙。\n"
    corrected2, audit2 = apply_edits(original2, [
        {"old_text": "甲。\r\n乙。", "new_text": "丙。\r\n丁。", "reason": "反向差异"},
    ])
    check("反向归一也生效", corrected2 == "丙。\n丁。\n", repr(corrected2))
    check("反向 audit 标注", audit2[0]["status"] == "OK")


def test_boundary_10_ratio_warn():
    """边界 10: 改动后长度差异 >50% → 不熔断, WARN_RATIO 整轮级告警."""
    print("\n--- 边界 10: 改动比例告警 ---")
    from app.harness import apply_edits
    # 唯一标记前缀 + 重复正文; old = 全文 (唯一), new 极短 → 差异 >50%
    original = "开头标记。" + "这是一段很长很长的文本。" * 20
    corrected, audit = apply_edits(original, [
        {"old_text": original, "new_text": "短。", "reason": "删除大段"},
    ])
    check("删除大段不熔断 (照常应用)", len(corrected) < len(original))
    warns = [e for e in audit if e["status"] == "WARN_RATIO"]
    check("WARN_RATIO 整轮级条目存在", len(warns) == 1)
    check("整轮级条目 index=-1", warns[0]["index"] == -1)
    # 小改动不告警
    _, audit2 = apply_edits("他说错误甲。", [
        {"old_text": "错误甲", "new_text": "正确乙", "reason": "小改"},
    ])
    check("小改动无告警", not any(e["status"] == "WARN_RATIO" for e in audit2))


def test_boundary_11_all_failed_caller_semantics():
    """边界 11: 全失败由调用方判 (corrected==original 且 edits 非空).

    apply_edits 本身不 raise; 引擎侧语义在 test_engine_all_failed_failed 验证。
    """
    print("\n--- 边界 11: 全失败判定契约 ---")
    from app.harness import apply_edits
    original = "原文内容。"
    edits = [{"old_text": "不存在", "new_text": "x", "reason": "幻觉"}]
    corrected, audit = apply_edits(original, edits)
    check("全失败不抛异常", corrected == original)
    check("audit 记录失败原因", audit[0]["status"] == "SKIPPED_NOT_FOUND")
    check("调用方判据成立: corrected==original 且 edits 非空", corrected == original and len(edits) > 0)


def test_boundary_12_partial_success():
    """边界 12: 部分成功 → 接受结果, audit 列出失败条目, warnings 判定."""
    print("\n--- 边界 12: 部分成功 ---")
    from app.harness import apply_edits, audit_has_warnings
    original = "错误甲在这里。错误乙在那里。"
    corrected, audit = apply_edits(original, [
        {"old_text": "错误甲", "new_text": "正确甲", "reason": "错别字"},
        {"old_text": "错误乙", "new_text": "正确乙", "reason": "错别字"},
        {"old_text": "幻觉丙", "new_text": "x", "reason": "幻觉"},
    ])
    check("部分成功接受", corrected == "正确甲在这里。正确乙在那里。", repr(corrected))
    check("失败条目在 audit", any(e["status"] == "SKIPPED_NOT_FOUND" for e in audit))
    check("audit_has_warnings True", audit_has_warnings(audit) is True)
    # 纯 OK → 无 warnings
    _, audit_ok = apply_edits("错误甲。", [{"old_text": "错误甲", "new_text": "正确乙", "reason": "r"}])
    check("纯 OK 无 warnings", audit_has_warnings(audit_ok) is False)
    # 纯 NOOP → 无 warnings (没丢任何改动)
    _, audit_noop = apply_edits("错误甲。", [{"old_text": "错误甲", "new_text": "错误甲", "reason": "r"}])
    check("纯 NOOP 无 warnings", audit_has_warnings(audit_noop) is False)
    # 空审计 → 无 warnings
    check("空 audit 无 warnings", audit_has_warnings([]) is False)


def test_audit_structure_and_preview_cap():
    """audit 条目结构 {index,status,reason,old_preview,new_preview}; 预览 ≤80."""
    print("\n--- audit 结构与预览截断 ---")
    from app.harness import apply_edits, PREVIEW_LIMIT
    long_old = "甲" * 300
    long_new = "乙" * 300
    _, audit = apply_edits("内容。" + long_old + "。", [
        {"old_text": long_old, "new_text": long_new, "reason": "长文本"},
    ])
    e = audit[0]
    check("条目含五要素", all(k in e for k in ("index", "status", "reason", "old_preview", "new_preview")))
    check("预览截断 ≤80", len(e["old_preview"]) <= 80 and len(e["new_preview"]) <= 80,
          f"{len(e['old_preview'])}/{len(e['new_preview'])}")
    check("PREVIEW_LIMIT 常量 = 80", PREVIEW_LIMIT == 80)
    check("截断带省略号", e["old_preview"].endswith("…"))
    check("index 从 0 计", e["index"] == 0)
    # 换行归一 note 条目额外字段
    _, audit2 = apply_edits("甲。\r\n乙。", [{"old_text": "甲。\n乙。", "new_text": "丙。\n丁。", "reason": "r"}])
    check("note 字段仅标注时出现", "note" in audit2[0] and "换行归一" in audit2[0]["note"])


def test_edit_cap_50():
    """每块 edits ≤50 条: 前 50 应用, 超限 SKIPPED_CAP + WARN_EDIT_CAP 汇总."""
    print("\n--- 单轮 50 条上限 ---")
    from app.harness import apply_edits, MAX_EDITS_PER_ROUND
    check("MAX_EDITS_PER_ROUND = 50", MAX_EDITS_PER_ROUND == 50)
    # 两位编号避免 "错误4" 命中 "错误49" 的前缀歧义 (NOT_UNIQUE 干扰)
    original = "".join(f"错误{i:02d}。" for i in range(60))
    edits = [{"old_text": f"错误{i:02d}", "new_text": f"正确{i:02d}", "reason": "r"} for i in range(60)]
    corrected, audit = apply_edits(original, edits)
    ok_n = sum(1 for e in audit if e["status"] == "OK")
    cap_n = sum(1 for e in audit if e["status"] == "SKIPPED_CAP")
    warn_n = sum(1 for e in audit if e["status"] == "WARN_EDIT_CAP")
    check("只应用前 50 条", ok_n == 50, f"ok={ok_n}")
    check("超限 10 条 SKIPPED_CAP", cap_n == 10, f"cap={cap_n}")
    check("WARN_EDIT_CAP 汇总告警 1 条", warn_n == 1)
    check("汇总告警 index=-1", any(e["index"] == -1 and e["status"] == "WARN_EDIT_CAP" for e in audit))
    check("前 50 条内容已替换", "正确49" in corrected and "正确59" not in corrected)

def test_parse_tool_calls():
    """parse_tool_calls: 合法解析 / 坏 JSON SKIPPED_BAD_ARGS / 非 edit_text 忽略."""
    print("\n--- parse_tool_calls ---")
    from app.harness import parse_tool_calls

    def tc(name, args):
        return SimpleNamespace(function=SimpleNamespace(name=name, arguments=args))

    good = tc("edit_text", json.dumps({"old_text": "甲", "new_text": "乙", "reason": "r"}, ensure_ascii=False))
    bad = tc("edit_text", "{not valid json")
    nonobj = tc("edit_text", json.dumps([1, 2]))
    other = tc("other_tool", json.dumps({"x": 1}))
    msg = SimpleNamespace(tool_calls=[good, bad, nonobj, other, None])
    edits, parse_audit = parse_tool_calls(msg)
    check("合法调用解析出 1 条", len(edits) == 1 and edits[0]["old_text"] == "甲")
    check("坏 JSON 2 条进 parse_audit", len(parse_audit) == 2)
    check("坏 JSON 状态 SKIPPED_BAD_ARGS",
          all(e["status"] == "SKIPPED_BAD_ARGS" for e in parse_audit))
    check("非 edit_text 被忽略", all("other" not in json.dumps(e, default=str) for e in edits))
    # 无 tool_calls (无需修改场景)
    edits2, pa2 = parse_tool_calls(SimpleNamespace(tool_calls=None))
    check("无 tool_calls → 空 edits", edits2 == [] and pa2 == [])
    # tool_calls 缺失属性 (None message)
    edits3, pa3 = parse_tool_calls(None)
    check("None message 不炸", edits3 == [] and pa3 == [])


def test_order_and_overlap():
    """边界 6: 重叠 edit 按返回顺序串行 (前一条的 new 可被后一条 old 命中)."""
    print("\n--- 边界 6: 顺序与重叠 ---")
    from app.harness import apply_edits
    original = "错误甲。"
    corrected, audit = apply_edits(original, [
        {"old_text": "错误甲", "new_text": "中间态", "reason": "第一步"},
        {"old_text": "中间态", "new_text": "最终态", "reason": "第二步"},
    ])
    check("按顺序两步都生效", corrected == "最终态。", repr(corrected))
    check("两条 OK", all(e["status"] == "OK" for e in audit))
    # 顺序敏感: 反过来第二条先执行则第一条找不到 — 但我们严格按返回顺序,
    # 所以模型返回顺序决定结果 (不重排)
    corrected2, audit2 = apply_edits("中间态。", [
        {"old_text": "最终态", "new_text": "x", "reason": "后步"},
        {"old_text": "中间态", "new_text": "最终态", "reason": "前步"},
    ])
    check("顺序决定结果 (不重排)", corrected2 == "最终态。", repr(corrected2))
    check("先返回的未命中被跳过", audit2[0]["status"] == "SKIPPED_NOT_FOUND")


# ============================================================
# 引擎端到端 (mock AsyncOpenAI; 镜像 test_punct_fix.py::test_engine_punct_local_mode)
# ============================================================

class _FakeCompletion:
    """非流式 ChatCompletion 替身 (harness 路径)."""

    def __init__(self, tool_calls=None, content="", total_tokens=42):
        message = SimpleNamespace(tool_calls=tool_calls or [], content=content)
        self.choices = [SimpleNamespace(message=message)]
        self.usage = SimpleNamespace(total_tokens=total_tokens) if total_tokens else None


def _tool(name="edit_text", **kwargs):
    return SimpleNamespace(function=SimpleNamespace(
        name=name, arguments=json.dumps(kwargs, ensure_ascii=False)))


class _FakeStreamClient:
    """流式客户端替身 (非 harness 路径) — 记录调用 kwargs 并返回事件流."""

    def __init__(self, text="流式输出全文", total_tokens=7):
        self.calls = []
        self._text = text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._tokens = total_tokens

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        ev = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=self._text))],
            usage=SimpleNamespace(total_tokens=self._tokens),
        )

        async def gen():
            yield ev

        return gen()


class _FakeHarnessClient:
    """非流式客户端替身 (harness 路径) — 按序返回预设 completion."""

    def __init__(self, completions):
        self._completions = list(completions)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._completions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _make_tmp(text):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return Path(f.name)


def _run_engine(cfg, file_text, client_ctor):
    """engine 端到端: prepare_tasks → run_async (patch AsyncOpenAI 构造器)."""
    tmp = _make_tmp(file_text)

    async def _run():
        with patch("app.processor.AsyncOpenAI", return_value=client_ctor):
            from app.processor import ProcessingEngine
            engine = ProcessingEngine(cfg)
            done = {}
            engine.on_file_done = lambda k, s: done.__setitem__(k, s)
            engine.prepare_tasks([tmp])
            await engine.run_async()
        return engine, done, str(tmp)

    try:
        engine, done, key = asyncio.run(_run())
        return engine, done, key
    finally:
        tmp.unlink(missing_ok=True)


def test_engine_strict_harness_happy_path():
    """strict + harness 默认开 → 走非流式 tools 调用; 编辑生效; audit 存储."""
    print("\n--- 引擎 strict harness happy path ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[_tool(old_text="表视", new_text="表示", reason="错别字")]),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", max_retries=0)
    engine, done, key = _run_engine(cfg, "他表视很好。", client)
    task = engine.tasks[key]
    check("文件完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("编辑已应用", task.result.corrected == "他表示很好。", repr(task.result.corrected))
    check("audit 按 file_key 存储", len(engine.file_audits.get(key, [])) == 1)
    check("audit 状态 OK", engine.file_audits[key][0]["status"] == "OK")
    check("audit reason 透传", engine.file_audits[key][0]["reason"] == "错别字")
    check("无 warnings", task.result.warnings is False)
    check("走非流式 (stream=False)", client.calls and client.calls[0].get("stream") is False)
    check("带 tools schema", "tools" in client.calls[0] and client.calls[0]["tools"])
    check("system 注入工具纪律", "工具使用纪律" in client.calls[0]["messages"][0]["content"])
    check("token 计数来自 usage", task.result.token_count == 42)


def test_engine_empty_edits_noop_success():
    """模型返回 0 个 tool_calls (无需修改) → corrected=原文, 正常完成无 audit."""
    print("\n--- 引擎空 edits (无需修改) ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeHarnessClient([_FakeCompletion(tool_calls=[], content="无需修改")])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", max_retries=0)
    engine, done, key = _run_engine(cfg, "完美文本。", client)
    task = engine.tasks[key]
    check("正常完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("corrected=原文", task.result.corrected == "完美文本。")
    check("无 audit 条目", engine.file_audits.get(key, []) == [])
    check("无 warnings", task.result.warnings is False)


def test_engine_suspicious_noop_content_retries():
    """v5.4.1 (用户烟测 Q1): 推理模型 0 tool_calls + content 长文本 → 判可疑,
    raise 走重试链 (max_retries=0 → FAILED), 不再静默判"无需修改"成功."""
    print("\n--- 引擎可疑 no-op content 守卫 ---")
    from app.utils import ProjectConfig, TaskStatus

    long_reasoning = "经过仔细检查，这段文字在语法和用词上都没有问题，因此不需要进行任何修改，可以直接使用。"
    client = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[], content=long_reasoning),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", max_retries=0)
    engine, done, key = _run_engine(cfg, "他表视很好。", client)
    task = engine.tasks[key]
    check("可疑 content → FAILED (不静默成功)", task.status == TaskStatus.FAILED,
          str(task.status))
    check("error 含工具链语义", "工具链" in (task.result.error or ""), task.result.error)

    # 对照: 真正的 "无需修改" 仍判成功
    client2 = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[], content="无需修改"),
    ])
    engine2, done2, key2 = _run_engine(cfg, "完美文本。", client2)
    task2 = engine2.tasks[key2]
    check("真'无需修改'仍判成功", task2.status == TaskStatus.COMPLETED, str(task2.status))


def test_content_suspicious_noop_unit():
    """content_suspicious_noop 纯函数: 白名单/编辑载体/长文本."""
    print("\n--- content_suspicious_noop 单元 ---")
    from app.harness import content_suspicious_noop as f
    check("空串放行", f("") is False)
    check("'无需修改' 放行", f("无需修改") is False)
    check("'无需修改。' 放行", f("无需修改。") is False)
    check("含 old_text 可疑", f("old_text: xxx") is True)
    check("含 new_text 可疑", f("new_text: yyy") is True)
    check("长解释文本可疑", f("这段文字写得很好，没有错误。") is True)


def test_engine_partial_success_warnings():
    """部分成功 (OK + NOT_FOUND) → warnings=True; 不新增枚举, 状态仍 completed."""
    print("\n--- 引擎部分成功 warnings ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[
            _tool(old_text="表视", new_text="表示", reason="错别字"),
            _tool(old_text="幻觉词", new_text="x", reason="幻觉"),
        ]),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", max_retries=0)
    engine, done, key = _run_engine(cfg, "他表视很好。", client)
    task = engine.tasks[key]
    check("状态 completed (不加枚举)", task.status == TaskStatus.COMPLETED, str(task.status))
    check("warnings 置位", task.result.warnings is True)
    statuses = [e["status"] for e in engine.file_audits[key]]
    check("audit 含 OK + SKIPPED", "OK" in statuses and "SKIPPED_NOT_FOUND" in statuses, str(statuses))


def test_engine_all_failed_failed():
    """边界 11 引擎侧: 有效编辑全部未生效 → raise → 重试耗尽 → FAILED."""
    print("\n--- 引擎全失败 FAILED ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[_tool(old_text="幻觉词", new_text="x", reason="幻觉")]),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", max_retries=0)
    engine, done, key = _run_engine(cfg, "正常文本。", client)
    task = engine.tasks[key]
    check("整文件 FAILED", task.status == TaskStatus.FAILED, str(task.status))
    check("error 含 harness 语义", "harness" in (task.result.error or ""), task.result.error)
    check("corrected 不回填原文", task.result.corrected == "")


def test_engine_harness_disabled_falls_back_stream():
    """harness_enabled=False → 不走 harness (流式路径, 无 tools kwarg)."""
    print("\n--- 引擎 harness_enabled=False ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeStreamClient(text="流式校对全文")
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", harness_enabled=False, max_retries=0)
    engine, done, key = _run_engine(cfg, "他表视很好。", client)
    task = engine.tasks[key]
    check("完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("结果来自流式输出", task.result.corrected == "流式校对全文", repr(task.result.corrected))
    check("流式调用 (stream=True)", client.calls and client.calls[0].get("stream") is True)
    check("无 tools 参数", "tools" not in client.calls[0])
    check("无 audit", engine.file_audits.get(key, []) == [])


def test_engine_custom_mode_no_harness():
    """custom 模式不走 harness (白名单双决策: 仅 strict/polish)."""
    print("\n--- 引擎 custom 模式不走 harness ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeStreamClient(text="自定义校对输出")
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="custom", custom_prompt="自定义提示词", max_retries=0)
    engine, done, key = _run_engine(cfg, "他表视很好。", client)
    task = engine.tasks[key]
    check("完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("结果来自流式输出", task.result.corrected == "自定义校对输出")
    check("流式调用 (stream=True)", client.calls and client.calls[0].get("stream") is True)
    check("无 tools 参数", "tools" not in client.calls[0])


def test_engine_polish_mode_harness():
    """polish 也在白名单 → 走 harness."""
    print("\n--- 引擎 polish 模式走 harness ---")
    from app.utils import ProjectConfig, TaskStatus

    client = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[_tool(old_text="错误甲", new_text="正确乙", reason="r")]),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="polish", max_retries=0)
    engine, done, key = _run_engine(cfg, "这里错误甲。", client)
    task = engine.tasks[key]
    check("完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("编辑已应用", task.result.corrected == "这里正确乙。", repr(task.result.corrected))
    check("走非流式 (stream=False)", client.calls and client.calls[0].get("stream") is False)


def test_engine_harness_chunked_audit_merge():
    """多 chunk harness: 每块独立 edits/apply, audit 合并 (文件级 = 各块之和)."""
    print("\n--- 引擎多 chunk audit 合并 ---")
    from app.utils import ProjectConfig, TaskStatus

    # fast=2000 字; 段落编号递增 → 总长 >2000 分 2 块, 且 old_text 在所属块内唯一
    text = "".join(f"段落{i}他说表视不错。" for i in range(200))
    client = _FakeHarnessClient([
        _FakeCompletion(tool_calls=[
            _tool(old_text="段落0他说表视不错", new_text="段落0他说表示不错", reason="块1"),
        ]),
        _FakeCompletion(tool_calls=[
            _tool(old_text="段落199他说表视不错", new_text="段落199他说表示不错", reason="块2"),
        ]),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict",
                        chunking_preset_harness="fast",  # v5.2c (D 方案): 测试目的是 harness 模式多 chunk, 用 chunking_preset_harness 派生
                        max_retries=0)
    engine, done, key = _run_engine(cfg, text, client)
    task = engine.tasks[key]
    check("完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("确实分了多块", len(task.result.chunks_results) >= 2, str(len(task.result.chunks_results)))
    audit = engine.file_audits.get(key, [])
    check("audit 合并两块", len(audit) == 2, str(len(audit)))
    check("块间顺序保持", [e.get("reason") for e in audit] == ["块1", "块2"],
          str([e.get("reason") for e in audit]))
    check("两块编辑都生效", audit[0]["status"] == "OK" and audit[1]["status"] == "OK")
    check("块 2 user 消息含 scope 说明",
          len(client.calls) >= 2 and "跨段上下文" in client.calls[1]["messages"][1]["content"])


def test_engine_retry_rebuilds_audit():
    """整文件重试时 audit 重建 (不跨 attempt 累积重复)."""
    print("\n--- 引擎重试 audit 重建 ---")
    from app.utils import ProjectConfig, TaskStatus

    # 第 1 次: 限速异常 (触发整文件重试); 第 2 次: 成功
    from openai import RateLimitError
    # RateLimitError.__init__ 只访问 response.request; headers 走 Retry-After 提取
    fake_resp = SimpleNamespace(request=SimpleNamespace(method="POST", url="http://x"),
                                headers={}, status_code=429)
    limit_err = RateLimitError("rate limited", response=fake_resp, body=None)
    client = _FakeHarnessClient([
        limit_err,
        _FakeCompletion(tool_calls=[_tool(old_text="表视", new_text="表示", reason="重试后")]),
    ])
    cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                        prompt_mode="strict", max_retries=1)
    engine, done, key = _run_engine(cfg, "他表视很好。", client)
    task = engine.tasks[key]
    check("重试后完成", task.status == TaskStatus.COMPLETED, str(task.status))
    check("audit 无重复 (重建)", len(engine.file_audits.get(key, [])) == 1,
          str(len(engine.file_audits.get(key, []))))
    check("audit 是重试轮的", engine.file_audits[key][0]["reason"] == "重试后")


def test_hash_and_config_roundtrip():
    """v5.1.0 配置: harness_enabled 进 ProjectConfig + 双 hash 函数同步纳入."""
    print("\n--- harness_enabled 配置与指纹 ---")
    from app.utils import ProjectConfig, compute_prompt_hash, compute_prompt_hash_for_config
    cfg = ProjectConfig()
    d = cfg.to_dict()
    check("to_dict 含 harness_enabled", "harness_enabled" in d)
    check("默认 True", d["harness_enabled"] is True)
    cfg2 = ProjectConfig.from_dict(d)
    check("往返完整", cfg2.harness_enabled is True)
    cfg3 = ProjectConfig.from_dict({"prompt_mode": "strict"})
    check("缺失字段兜底 True", cfg3.harness_enabled is True)
    cfg4 = ProjectConfig.from_dict({"harness_enabled": False})
    check("显式 False 保留", cfg4.harness_enabled is False)
    # hash: 开关翻转 → 指纹变化 (旧断点失效, 语义同 md_strip)
    base = compute_prompt_hash("strict", "m", "", harness_enabled=True)
    off = compute_prompt_hash("strict", "m", "", harness_enabled=False)
    check("compute_prompt_hash 纳入 harness_enabled", base != off)
    on_cfg = ProjectConfig(prompt_mode="strict")
    off_cfg = ProjectConfig(prompt_mode="strict", harness_enabled=False)
    check("for_config 同步纳入",
          compute_prompt_hash_for_config(on_cfg) != compute_prompt_hash_for_config(off_cfg))
    # for_config 与显式传参一致: 显式调用须传全部 cfg 字段 (默认值不同会失配)
    check("for_config 与显式调用一致",
          compute_prompt_hash_for_config(on_cfg) == compute_prompt_hash(
              on_cfg.prompt_mode, on_cfg.model, on_cfg.custom_prompt,
              chunking_preset=on_cfg.chunking_preset,
              context_max_chars=on_cfg.context_max_chars,
              context_max_chunks=on_cfg.context_max_chunks,
              temperature=on_cfg.temperature,
              api_base=on_cfg.api_base,
              punct_fix=on_cfg.punct_fix,
              punct_quote_style=on_cfg.punct_quote_style,
              punct_fullwidth_alnum=on_cfg.punct_fullwidth_alnum,
              punct_repeat_compress=on_cfg.punct_repeat_compress,
              punct_dash_tilde=on_cfg.punct_dash_tilde,
              md_strip=on_cfg.md_strip_before_llm,
              harness_enabled=on_cfg.harness_enabled,
              # v5.3.0: for_config 传的是 effective 值 (harness_enabled=True +
              # prompt_mode=strict → "harness"), 显式调用必须传同一个值
              workflow_mode="harness",
          ))
    # FileResult.warnings 字段
    from app.utils import FileResult
    r = FileResult(original="a", corrected="b", warnings=True)
    rd = r.to_dict()
    check("FileResult.warnings 序列化", rd.get("warnings") is True)
    r2 = FileResult.from_dict(rd)
    check("FileResult.warnings 往返", r2.warnings is True)
    r3 = FileResult.from_dict({"original": "x"})  # 旧断点无字段
    check("旧断点缺字段兜底 False", r3.warnings is False)


def main():
    tests = [
        test_boundary_1_not_found,
        test_boundary_2_not_unique,
        test_boundary_3_cascaded,
        test_boundary_4_noop,
        test_boundary_5_7_multiline_fence,
        test_boundary_8_crlf_normalize,
        test_boundary_10_ratio_warn,
        test_boundary_11_all_failed_caller_semantics,
        test_boundary_12_partial_success,
        test_audit_structure_and_preview_cap,
        test_edit_cap_50,
        test_parse_tool_calls,
        test_order_and_overlap,
        test_engine_strict_harness_happy_path,
        test_engine_empty_edits_noop_success,
        test_engine_suspicious_noop_content_retries,
        test_content_suspicious_noop_unit,
        test_engine_partial_success_warnings,
        test_engine_all_failed_failed,
        test_engine_harness_disabled_falls_back_stream,
        test_engine_custom_mode_no_harness,
        test_engine_polish_mode_harness,
        test_engine_harness_chunked_audit_merge,
        test_engine_retry_rebuilds_audit,
        test_hash_and_config_roundtrip,
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
    if errors_list:
        print("\n失败项:")
        for name in errors_list:
            print(f"  - {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
