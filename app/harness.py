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
#           Edit 工具设计范式 (12 条边界表见 (已遗失 — 见 docs/archive/README.md「已知断裂的引用」) §3.3)
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
#   WARN_RATIO            整轮级: 单条编辑替换了原文 >50% (不熔断, 只告警)
RATIO_WARN_THRESHOLD = 0.5
# v5.4.3 (F6): 覆盖率告警的**原文长度下限**。短文本上任何改动占比都接近 100%,
# 阈值无意义 (改 1 个字就是 100%), 会把每次校对都刷成告警。
# 200 = 初始拍定值, 未做真实样本校准 (AGENTS.md §34 口径)。
RATIO_WARN_MIN_CHARS = 200

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
#
# v5.4.3 (F10) 口径变更: 从「白名单精确匹配」改为「编辑载体拦截 + 长度阈值」。
# 旧实现只认字面量 _NOOP_CONTENT 且要求它出现在 content 里、且总长 <= 40。
# 实测模型用任何**别的措辞**报告"没找到错误"都会被判可疑:
#   '我已仔细检查全文，未发现需要修改之处。'      -> 旧判据 True (误判)
#   '全文检查完毕，没有发现问题。'               -> 旧判据 True (误判)
#   '经过逐句核查，这篇文章没有明显的错别字或标点错误。' -> 旧判据 True (误判)
#   '好的。'                                -> 旧判据 True (误判)
# 后果: 本该零改动的文件 -> raise -> 烧重试 -> **整文件 FAILED**。
# 而"全文无错"恰是逐条校对轨最该成功的结局。
# 短语白名单作废的另一个理由: "没有错"不是"没有**明显的**错别字"的子串, 补
# 词表补不完 —— 模型的措辞空间远大于任何能穷举的短语表。
_EDIT_CONTENT_MARKERS = ("old_text", "new_text")
# 短答复长度上限: 超过说明混了大段推理/解释, 不是干净的"无需修改"答复。
_NOOP_CONTENT_MAX_LEN = 40
# ⚠ 40 = 初始拍定值, 未做真实样本校准 (AGENTS.md §34 口径)。放宽需重新标注。


def content_suspicious_noop(content: str) -> bool:
    """content 非 tool_call 回复的"可疑无需修改"判定。 (v5.4.3 F10 改判据)

    True = 应重试; False = 合法的"无需修改"答复, 放行。

    判定顺序 (F10 新口径):
    1. 空 / 仅空白 → 放行 (模型确实没说话, 走既有 no-op 路径)
    2. 含编辑载体字面量 (old_text / new_text) → **一律可疑**, 无论多长
       (v5.4.1 的核心防线, 保留)
    3. 其余: 长度 > _NOOP_CONTENT_MAX_LEN → 可疑 (混了大段推理);
       短于等于 → **放行**, 不再查任何短语

    短答复一律放行是有意的取舍: 一旦靠短语表判断, 漏一种措辞就误判 FAILED,
    而误判的代价 (用户看到红色失败 + 真实结果被丢弃) 远大于放行一个可疑空结果。
    长文本 (混大段推理) 仍会被拦, 所以 v5.4.1 要消灭的"推理倾倒"没有漏网。
    """
    c = (content or "").strip()
    if not c:
        return False
    if any(m in c for m in _EDIT_CONTENT_MARKERS):
        return True
    return len(c) > _NOOP_CONTENT_MAX_LEN


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
        # v5.4.3 (F6): 不截断的 old_len —— 边界 10 的覆盖率计算要用它。
        # old_preview 仍截断 (前端只显示那么多), 拿预览长度算占比会失真。
        # 多一个 key 对前端无害: app.js 的渲染只读 status/index/old_preview/
        # new_preview/note/reason 六个字段; test_harness 的断言是包含式
        # (`all(k in e ...)`), 加 key 不红; audit 是会话内存态不落断点, 无 schema 变更。
        "old_len": len(old) if isinstance(old, str) else 0,
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

        # v5.4.2 (全量扫描 E5): 非字符串参数必须在类型边界上拦住。旧实现直通到
        # str.count/replace → TypeError 冒出 apply_edits, 违反本模块"apply 不抛
        # 异常"的契约, 且会在上层被当成通用失败烧掉整文件重试额度。
        if not isinstance(old, str) or not isinstance(new, str):
            audit.append(_make_audit(
                i, "SKIPPED_BAD_ARGS",
                "old_text / new_text 必须是字符串",
                str(old)[:PREVIEW_LIMIT], str(new)[:PREVIEW_LIMIT],
            ))
            continue

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
            # v5.4.3 (F1): 必须确认下一个字符确实是 \n 才能 +2。
            # 旧实现只判 corrected[orig_last] == "\r" 就 +2, 但 _crlf_map 对
            # **孤立 CR** 是 1:1 映射 (harness.py:171-178 的 else 分支), 多推进一格
            # 会把匹配区外的下一个字符一起吃进替换区 (实测 '甲\r\n乙\r丙丁' + '甲\n乙\r'
            # → 'ZZ丁', 「丙」静默删除, 而 audit 仍报 OK)。
            _is_crlf = (
                corrected[orig_last] == "\r"
                and orig_last + 1 < len(corrected)
                and corrected[orig_last + 1] == "\n"
            )
            orig_end = orig_last + (2 if _is_crlf else 1)
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
    if applied and original:
        # v5.4.3 (F6): 指标从「长度差」换成「单条最大替换占比」。
        #
        # 旧指标 abs(len(corrected) - len(original)) / len(original) 在**等长整体
        # 重写**下恒为 0 —— 而那正是本项唯一要拦的场景 (模型无视工具纪律, 把半篇
        # 塞进一条 tool_call)。实测 300 字原文被等长整体改写, 旧指标 audit 全 OK、
        # 零告警。这是 harness 轨**唯一的兜底告警位**, 漏在这里等于没有兜底。
        #
        # 为什么取 max 而不是 sum: 重叠 edit 会被 sum 重复计入放大 (实测真实改动
        # 0 个字符时 sum 给出 87.5%)。max 只看"最大的一条吞了多少", 对多条小改
        # 零假阳性, 精确命中"一条 tool_call 吞掉半篇"。
        # 为什么不用 difflib 真比例: 实测 6000 字 + 8 处小改 656ms, 50000 字
        # (extra_large 档) 60.3 秒 —— 不可接受。
        #
        # 下限 len(original) >= 200: 短文本上任何改动占比都接近 100%, 阈值无意义。
        # (200 = 初始拍定值, 未做真实样本校准, 见计划 §0.1)
        if len(original) >= RATIO_WARN_MIN_CHARS:
            max_replaced = max(
                (e.get("old_len", 0) for e in audit if e.get("status") == "OK"),
                default=0,
            )
            ratio = max_replaced / len(original)
            if ratio > RATIO_WARN_THRESHOLD:
                audit.append(_make_audit(
                    -1, "WARN_RATIO",
                    f"单条编辑替换了原文 {ratio:.0%} "
                    f"(>{RATIO_WARN_THRESHOLD:.0%}), 请人工核对",
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
