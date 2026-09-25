# -*- coding: utf-8 -*-
"""harness — Edit 工具校对结果应用引擎 (v5.1.0)。

harness 化核心思想: LLM 不再整篇重输出, 而是返回"编辑建议"列表
(old_text/new_text/reason), 由客户端按精确字符串匹配逐条应用。
收益: 输出 token 大幅下降 (只输出改动点), 且每条改动可审计
(改了什么/为什么/是否被采纳)。

职责边界 (与 app/punct_fix.py / app/md_strip.py 同类同纪律):
  - 纯函数, 无 IO, 无 GUI 依赖, 不 import openai/webview。
  - apply 阶段绝不抛异常 (除调用方契约错误): 单条编辑失败只记录
    audit, 让 UI 呈现"哪些 LLM 提议没被采纳、为什么"。
  - 整轮全失败 (corrected == original 且 edits 非空) 由调用方判定。

# 借鉴自 Claude Code Edit 工具 (https://code.claude.com/docs/, Anthropic 文档)
# 借鉴内容: old_text/new_text 精确字符串匹配 + 全局唯一性要求 + 逐条状态回执的
#           Edit 工具设计范式 (12 条边界表见 .workbuddy/research/agent1-tech-feasibility.md §3.3)
# 借鉴方式: 思路借鉴,无代码复制
# Copyright (c) 2026 Anthropic PBC
# 致谢说明 (同 THIRD_PARTY_NOTICES §10 Microsoft 先例): 借鉴设计思路而非代码,
# 文档不适用开源许可证, 不附 LICENSE 全文。
"""

import json


# 每轮 (每块) 编辑条数上限。
# 50 条 × 平均 100 字符 old_text ≈ 5K tokens 输出, 是主流模型 tool_calls
# 输出长度的舒适区; 超过说明模型在"逐处改写"而不是聚合改写, 属异常信号
# (audit 告警, 超限条目不应用 — 见 apply_edits 的 WARN_EDIT_CAP)。
MAX_EDITS_PER_ROUND = 50

# audit 预览字段截断长度 (old_preview/new_preview ≤ 80 字符)。
PREVIEW_LIMIT = 80

# 单条 status 枚举 (12 边界表 §3.3 对应):
#   OK                    精确匹配, 已替换
#   SKIPPED_NOT_FOUND     边界 1: old_text 在当前文本中找不到
#   SKIPPED_NOT_UNIQUE    边界 2: old_text 出现 >=2 次, 不自动选第 1 个
#   SKIPPED_CASCADED      边界 3: 原文里有, 但被前面成功的 edit 改掉了
#   SKIPPED_NOOP          边界 4: old_text 为空或与 new_text 相同 (无意义调用)
# 扩展 status (12 表之外的现实边界, 均 SKIPPED_/WARN_ 前缀):
#   SKIPPED_CAP           超出单轮 50 条上限, 未应用
#   SKIPPED_BAD_ARGS      tool_call 参数不是合法 JSON / 缺 old_text
#   WARN_EDIT_CAP         整轮级: 存在超限未应用条目 (index=-1 汇总条目)
#   WARN_RATIO            整轮级: 改动后文本与原文差异 >50% (不熔断, 只告警)
RATIO_WARN_THRESHOLD = 0.5

# Edit 工具 OpenAI 兼容 schema (agent1 §3.2; 烟测证实 MiniMax-M3 接受)。
# 单工具: LLM 的全部产出 = edit_text 调用数组; 每处错误一次调用。
EDIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "edit_text",
            "description": (
                "在原文中精确定位 old_text 并替换为 new_text。"
                "old_text 必须在原文中恰好出现 1 次（唯一匹配）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "old_text": {
                        "type": "string",
                        "description": (
                            "原文中的精确子串，1-2000 字符，必须唯一匹配。"
                            "不允许空白差异、不允许部分匹配。"
                        ),
                    },
                    "new_text": {
                        "type": "string",
                        "description": "替换后的新内容。空字符串表示删除。",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "1 句话说明改动原因（如'删除填充词'、'修正错别字'），"
                            "用于审计显示，不影响执行。"
                        ),
                    },
                },
                "required": ["old_text", "new_text"],
            },
        },
    }
]

# tool_choice: auto — 模型可自行决定"无错误时返回 0 个调用"。
TOOL_CHOICE = "auto"

# 工具使用纪律 (注入到校对 system prompt 尾部; agent1 §3.2 7 条 + 错误回执协议)。
# 注意: harness 路径下 LLM 不输出修改后全文, 全部产出 = tool_calls。
TOOL_DISCIPLINE = """# 工具使用纪律

你是一个中文校对编辑。检查用户给出的文本，把发现的每一处错误用 edit_text 工具提交修复。一次响应里提交全部编辑（每处错误一次独立的 edit_text 调用），不要只改一处。

## 调用规则
1. old_text 必须唯一：在原文中只出现 1 次。如果出现多次（含同形不同义），改用更长上下文（前后各加 1-2 句）让匹配唯一。
2. 单次只改一处：不要把多处改动塞进同一次 edit_text。每处错误一次调用，便于审计。
3. 不要改未发现错误的段落：没问题的部分不调用 edit_text。
4. old_text 保留原文的换行/缩进/全半角：精确匹配，连标点都按原文。
5. new_text 不引入新信息：事实纪律与校对模式要求一致。
6. reason 用 1 句话写中文：示例："修正'在再'误用" / "删除填充词"。
7. 不要在参数里放解释文本：old_text / new_text 只放要替换的纯文本。

## 输出要求
不要输出修改后的全文。你的全部产出就是 edit_text 调用；除工具调用外不要输出任何正文。全文没有错误时，回复"无需修改"四个字。"""

# v5.4.1 (用户烟测 Q1): "0 tool_calls" 防误报守卫。
# 背景: MiniMax 等推理模型走 tools 调用时仍会消耗上万思维链 token, 偶发不产出
# tool_calls 而是在 content 里自答 "无需修改" —— 但真实原因是它把整轮推理都
# 放进了 content, 工具链根本没被触发。若一律判成功, 用户看到 "完成但零改动"。
# 守卫: content 若包含编辑载体特征或明显不是 "无需修改", 判可疑 → raise 让
# 通用重试链再试一次 (默认重试 1 次, 耗尽才 FAILED — 宁可失败也不静默放过)。
_NOOP_CONTENT = "无需修改"
_EDIT_CONTENT_MARKERS = ("old_text", "new_text")


def content_suspicious_noop(content: str) -> bool:
    """content 非 tool_call 回复的"可疑无需修改"判定。

    True = content 含编辑载体 (old_text/new_text) 或非平凡长文本 → 大概率是
    模型没走工具链, 应重试; False = 合法 "无需修改" / 空回复 / 极短白名单。
    """
    c = (content or "").strip()
    if not c or c == _NOOP_CONTENT:
        return False
    if any(m in c for m in _EDIT_CONTENT_MARKERS):
        return True
    # "无需修改" 的常见变体 (含句号/括号解释) 放行; 其余长文本视为可疑
    return len(c) > 8 or _NOOP_CONTENT not in c


# 分块场景附加说明 (_stream_chunked 注入): 上下文只是参照物, 不可编辑。
CHUNK_SCOPE_NOTE = (
    "注意：系统提示中的跨段上下文只是理解本文的参照，不要对它提出编辑；"
    "你只能对用户消息中的正文提出编辑。"
)


def _preview(s: str) -> str:
    """audit 预览: 超长截断加省略号 (≤PREVIEW_LIMIT 字符)。"""
    s = s or ""
    if len(s) <= PREVIEW_LIMIT:
        return s
    return s[: PREVIEW_LIMIT - 1] + "…"


def _norm_crlf(s: str) -> str:
    """\\r\\n → \\n 归一化 (边界 8 的匹配辅助)。"""
    return s.replace("\r\n", "\n")


def _crlf_map(s: str) -> tuple[str, list[int]]:
    """返回 (归一化文本, 映射表), 映射表[norm_idx] = 原文该字符起始下标。

    "\\r\\n" 序列在归一化文本中占 1 个位置, 映射到 "\\r" 的下标;
    由 orig_end 计算时若命中 "\\r" 会把 "\\n" 一并划入替换区。
    """
    out: list[str] = []
    mapping: list[int] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\r" and i + 1 < n and s[i + 1] == "\n":
            out.append("\n")
            mapping.append(i)
            i += 2
        else:
            out.append(s[i])
            mapping.append(i)
            i += 1
    return "".join(out), mapping


def _make_audit(index: int, status: str, reason: str,
                old: str = "", new: str = "", note: str = "") -> dict:
    """构造一条 audit 条目 (供前端「改动清单」渲染)。"""
    entry = {
        "index": index,
        "status": status,
        "reason": reason or "",
        "old_preview": _preview(old),
        "new_preview": _preview(new),
    }
    if note:
        entry["note"] = note
    return entry


def apply_edits(original: str, edits: list[dict]) -> tuple[str, list[dict]]:
    """把 LLM 的编辑建议逐条应用到 original, 返回 (corrected, audit)。

    严格按返回顺序串行应用 (不重排 — 顺序是 LLM 意图的一部分, §3.4);
    每条用 ``str.replace(old, new, 1)`` 语义只替换第一处唯一匹配。

    12 条边界 (agent1 §3.3) 处理策略:
      1 NOT_FOUND    跳过, 继续后续 (audit 记录)
      2 NOT_UNIQUE   跳过, 不自动选第 1 个 (避免歧义)
      3 CASCADED     原文存在但已被前面的成功 edit 消耗 → 跳过
      4 NOOP         old 为空或 old == new → 跳过
      5 跨行 old     接受 (str.replace 按字面处理, 不特殊对待)
      6 重叠 edit    按顺序应用, 后面的可能 NOT_FOUND/CASCADED
      7 含代码围栏   接受, 按字面字符处理
      8 \\r\\n 差异    归一化匹配 + 位置映射替换, audit 标注 (note=换行归一)
      9 代码块内     接受 (不做上下文感知保护, LLM 自觉)
      10 改动 >50%   不熔断, 整轮级 WARN_RATIO audit 告警
      11 全失败      不在此判定 — 调用方判 (corrected==original 且 edits 非空)
      12 部分成功    接受结果不重试, 调用方据 audit 判 warnings

    audit 条目: {index, status, reason, old_preview, new_preview[, note]};
    整轮级告警条目 index=-1 (WARN_EDIT_CAP / WARN_RATIO)。
    """
    corrected = original
    audit: list[dict] = []

    # 边界 (cap): 超出 MAX_EDITS_PER_ROUND 的条目不应用, 汇总告警。
    over_cap = edits[MAX_EDITS_PER_ROUND:]
    if over_cap:
        audit.append(_make_audit(
            -1, "WARN_EDIT_CAP",
            f"模型提交 {len(edits)} 条编辑, 超过单轮 {MAX_EDITS_PER_ROUND} 条上限, "
            f"后 {len(over_cap)} 条未应用 (应聚合改写而非逐处提交)",
        ))
    for j, e in enumerate(over_cap):
        old = e.get("old_text", "") if isinstance(e, dict) else ""
        new = e.get("new_text", "") if isinstance(e, dict) else ""
        audit.append(_make_audit(
            MAX_EDITS_PER_ROUND + j, "SKIPPED_CAP",
            "超出单轮编辑上限, 未应用", old, new,
        ))
    applied = edits[:MAX_EDITS_PER_ROUND]

    for i, e in enumerate(applied):
        if not isinstance(e, dict):
            audit.append(_make_audit(i, "SKIPPED_BAD_ARGS", "编辑条目不是对象"))
            continue
        old = e.get("old_text", "")
        new = e.get("new_text", "")
        reason = e.get("reason", "")

        # 边界 4: 空 old / old == new — 无意义调用。
        if not old:
            audit.append(_make_audit(i, "SKIPPED_NOOP", "old_text 为空 (无意义调用)", old, new, reason))
            continue
        if old == new:
            audit.append(_make_audit(i, "SKIPPED_NOOP", "old_text 与 new_text 相同", old, new, reason))
            continue

        n = corrected.count(old)
        if n == 1:
            # 常规路径: 精确唯一匹配, 直接替换。
            corrected = corrected.replace(old, new, 1)
            audit.append(_make_audit(i, "OK", reason, old, new))
            continue
        if n > 1:
            # 边界 2: 歧义, 不自动选第 1 个。
            audit.append(_make_audit(
                i, "SKIPPED_NOT_UNIQUE",
                f"old_text 在当前文本中出现 {n} 次, 需加上下文使其唯一",
                old, new, reason,
            ))
            continue

        # n == 0: 精确匹配失败 — 先试 \r\n 归一化 (边界 8), 再判级联 (边界 3)。
        norm_cur, cur_map = _crlf_map(corrected)
        norm_old = _norm_crlf(old)
        n_norm = norm_cur.count(norm_old) if norm_old else 0
        if n_norm == 1:
            norm_start = cur_map[norm_cur.index(norm_old)]
            last = norm_cur.index(norm_old) + len(norm_old) - 1
            orig_last = cur_map[last]
            orig_end = orig_last + (2 if corrected[orig_last] == "\r" else 1)
            replaced_region = corrected[norm_start:orig_end]
            # 新文本换行风格跟随被替换区域: 区域含 \r\n 则新文本 \n → \r\n。
            norm_new = _norm_crlf(new)
            if "\r\n" in replaced_region:
                norm_new = norm_new.replace("\n", "\r\n")
            corrected = corrected[:norm_start] + norm_new + corrected[orig_end:]
            audit.append(_make_audit(i, "OK", reason, old, new, "换行归一后匹配 (\\r\\n 差异)"))
            continue
        if n_norm > 1:
            audit.append(_make_audit(
                i, "SKIPPED_NOT_UNIQUE",
                f"old_text 换行归一后在文本中出现 {n_norm} 次",
                old, new, reason,
            ))
            continue
        # 边界 3: 原文里存在、当前文本里没有 → 被前面成功的 edit 消耗。
        if _norm_crlf(original).count(norm_old) >= 1:
            audit.append(_make_audit(
                i, "SKIPPED_CASCADED",
                "old_text 在原文中存在, 已被前面成功的编辑修改 (级联失效)",
                old, new, reason,
            ))
            continue
        # 边界 1: 原文里也找不到 — 模型幻觉/看错原文。
        audit.append(_make_audit(
            i, "SKIPPED_NOT_FOUND",
            "old_text 在原文中不存在 (可能没看清原文或前面编辑已把它改掉)",
            old, new, reason,
        ))

    # 边界 10: 改动比例异常告警 (不熔断 — LLM 删大段是合法操作)。
    if applied and len(original) > 0:
        diff_ratio = abs(len(corrected) - len(original)) / len(original)
        if diff_ratio > RATIO_WARN_THRESHOLD:
            audit.append(_make_audit(
                -1, "WARN_RATIO",
                f"应用后文本长度与原文差异 {diff_ratio:.0%} (>{RATIO_WARN_THRESHOLD:.0%}), 请人工核对",
            ))

    return corrected, audit


def audit_has_warnings(audit: list[dict]) -> bool:
    """文件级部分成功判定 (边界 12 → FileResult.warnings)。

    存在任何未生效的编辑 (SKIPPED_* 中除 NOOP 外) 或整轮级告警 (WARN_*)
    即视为 warnings; 纯 NOOP (old==new 的无意义调用) 不算 — 它没有
    丢失任何改动。全失败 (无任何 OK) 不走这里 — 调用方已判 FAILED。
    """
    for e in audit or []:
        status = e.get("status", "")
        if status == "OK" or status == "SKIPPED_NOOP":
            continue
        if status.startswith("SKIPPED_") or status.startswith("WARN_"):
            return True
    return False


def parse_tool_calls(message) -> tuple[list[dict], list[dict]]:
    """从 OpenAI 兼容响应的 message 中解析 edit_text 调用。

    返回 (edits, parse_audit): edits 是可直接喂给 apply_edits 的 dict 列表;
    parse_audit 是参数解析失败的条目 (SKIPPED_BAD_ARGS), 由调用方并入
    整轮 audit。忽略非 edit_text 的工具调用 (当前只暴露这一个工具)。
    """
    edits: list[dict] = []
    parse_audit: list[dict] = []
    tool_calls = getattr(message, "tool_calls", None) or []
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        if fn is None or getattr(fn, "name", "") != "edit_text":
            continue
        raw = getattr(fn, "arguments", "") or ""
        try:
            args = json.loads(raw)
        except Exception:
            parse_audit.append(_make_audit(
                len(edits) + len(parse_audit), "SKIPPED_BAD_ARGS",
                "tool_call 参数不是合法 JSON",
                raw[:PREVIEW_LIMIT], "",
            ))
            continue
        if not isinstance(args, dict):
            parse_audit.append(_make_audit(
                len(edits) + len(parse_audit), "SKIPPED_BAD_ARGS",
                "tool_call 参数不是对象",
                str(args)[:PREVIEW_LIMIT], "",
            ))
            continue
        edits.append(args)
    return edits, parse_audit
