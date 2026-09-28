# 借鉴自 https://github.com/Aboudjem/humanizer-skill (MIT License)
# 借鉴内容: 客户端 0-100 AI-tell 本地评分范式 ("a number is a stand-in, not a verdict",
#           纯函数 + 0 依赖 + 0 网络 + 0 IO, 分数是信号不是判定)
# 借鉴自 https://github.com/blader/humanizer (MIT License) 的痕迹分类语义
# 借鉴内容: AI 写作痕迹分类 (其现行 v3.0 为 "five sections + 25 patterns" 表述;
#           本项目"7 大类"是自己的归纳, 未沿用其任何编号)
# 借鉴自 https://github.com/harshaneel/humanize (MIT License) 的 audit-revise 思路
# 借鉴内容: 出戏句 (offenders) 反馈再改写的循环语义
# 借鉴方式: 思路借鉴, 无代码复制 (词表/正则/权重全部项目语言自写)
# Copyright (c) 2026 Adam Boudjemaa; Copyright (c) 2025 Siqi Chen; Copyright (c) 2026 Harshaneel Gokhale

"""ai_score_local — 客户端 0-100 AI 味评分引擎 (v5.0.2, 与 md_strip 同类的零 LLM 纯函数).

需求: DeAI rewrite 完成后, 在不调 LLM 的前提下给改写文本一个 0-100 的"AI 味分"
(分数越高 AI 味越重), 并摘出最"出戏"的句子供 revise 内层循环做反馈.

定位 (与 Step 3 LLM audit 评分的关系, verifier P1-5 澄清):
- ai_score_local = 客户端 0 成本初筛信号 (触发 revise / 前端预警)
- deai_step3 audit = LLM 精确评分 (最终用户展示)
- 两者并存互补, 本模块不替代 audit

纪律 (与 md_strip/punct_fix 同款):
1. 纯函数 — 无 IO / 无网络 / 无 GUI / 无随机, 同输入恒同输出 (幂等)
2. 0 依赖 — 仅用标准库 re / math / unicodedata
3. 信号非判定 — 分数只用于预警与 revise 触发, 不落盘不进任何缓存/断点
4. 保守 — 全部正则有界 (无嵌套量词), 病态输入不回溯爆炸; 短文本不判 burstiness

权重表 (总和恒等于 100, test_ai_score.py 兜底校验):
  blacklist   硬黑名单词频        28  — 最确定信号 (人工整理词表, 误报率最低),
                                        密度计分 (每 100 字符命中数封顶 1.5 处)
  patterns    7 大类 AI 痕迹      24  — DETECT_V5 第 2-7 类 (否定对照/三连词/破折号
                                        泛滥/意义膨胀/宣传腔/模糊归因), 每类 4 分;
                                        第 1 类 (硬黑名单) 已由 blacklist 维度覆盖,
                                        不双计
  counter     AI 6 处反制         18  — 本地可测 5 项: 缺真实专名 4 / 结尾太圆 4 /
                                        推进太顺 4 / 鸡汤化 4 / 批次指纹 2 (与破折号
                                        泛滥部分重叠, 降权); 第 6 项"文章原型不匹配"
                                        需语义理解, 本地不可测 → 0 分, 其份额分摊给
                                        其余 5 项 (诚实缺位优于硬凑假检测)
  burstiness  句长方差            12  — 人写文本长短句方差大 (GPTZero 类指标);
                                        CV >= 0.6 记 0 分, CV <= 0.2 记满分; 句数 < 3
                                        不判 (记 0, 不冤枉短文本)
  markdown    Markdown 装饰密度   10  — 井号/星号/列表符/表格线/围栏等装饰行占比;
                                        rewrite prompt 已禁装饰, 残留即扣分
  punct       标点签名             8  — CJK 邻接半角标点混排 + emoji 密度; 最弱信号
                                        (人写差异大), 最低权重

  合计 28 + 24 + 18 + 12 + 10 + 8 = 100

**权重为初始拍定值, 未做真实样本校准** — 上线后按真实样本 (建议 100 个 case)
重新拟合前严禁在文档/注释中编造"实测平均 N"之类的校准数据来源。

REVISE_THRESHOLD = 50 亦为初始拍定值, 同样待真实样本校准。

接口: ai_score(text) -> {"score": int(0-100), "dims": {名: {"score", "weight", "detail"}},
                          "offenders": [{"text", "reasons"}, ...] (出戏句, 最多 5 条)}
"""
import math
import re

# ---------- 权重 (唯一事实源, docstring 权重表与此处同步) ----------
DIM_WEIGHTS = {
    "blacklist": 28,
    "patterns": 24,
    "counter": 18,
    "burstiness": 12,
    "markdown": 10,
    "punct": 8,
}
assert sum(DIM_WEIGHTS.values()) == 100, "ai_score 权重总和必须恒等于 100"

# revise 内层循环触发阈值 (初始拍定值, 待真实样本校准)
REVISE_THRESHOLD = 50

# offenders 截断上限 (revise 反馈过长会稀释 prompt 信号)
_MAX_OFFENDERS = 5

# ---------- 词表 (语义来源 app/templates.py DETECT_V5, 结构化为可计算词表) ----------
# 硬黑名单 (DETECT_V5 第 1 类): 英文按 \b 词边界, 中文按子串
_BLACKLIST_EN = [
    "delve", "tapestry", "leverage", "harness", "pivotal", "testament",
    "beacon", "realm", "intricate", "vibrant", "groundbreaking", "seamless",
    "robust", "unlock", "journey", "navigate", "landscape", "nuanced",
    "holistic",
]
_BLACKLIST_ZH = [
    "赋能", "闭环", "底层逻辑", "长期主义", "抓手", "认知升级", "价值沉淀",
    "深耕", "赛道", "发力", "痛点", "复盘", "对齐", "颗粒度", "护城河",
    "底层架构", "生态位",
]
_BLACKLIST_EN_RE = re.compile(
    r"\b(" + "|".join(_BLACKLIST_EN) + r")\b", re.IGNORECASE
)

# 7 大类的第 2-7 类正则 (第 1 类 = 硬黑名单, 已由 blacklist 维度覆盖)
# 全部有界: 字符类内限量词, 无嵌套量词, 防灾难性回溯
_PATTERNS = {
    "否定式对照": re.compile(
        r"不是[^\n。,，;；]{1,15}[，,]\s*而是|不仅是[^\n。]{1,15}[，,]?\s*更是"
        r"|不只是[^\n。]{1,15}[，,]?\s*更是"
        r"|not\s+(?:just|only|merely)[^\n.!?]{1,40}(?:but\s|it'?s\b)",
        re.IGNORECASE,
    ),
    "三连词": re.compile(
        r"首先[^\n。]{1,50}其次[^\n。]{1,50}(?:最后|再次|然后)"
        r"|第[一二三][，、是][^\n。]{1,40}第[二三][，、是][^\n。]{1,40}第三[，、是]"
        r"|[一二三]是[^\n。]{1,40}[二三]是[^\n。]{1,40}三是"
        r"|first[^\n.]{1,60}second[^\n.]{1,60}third",
        re.IGNORECASE,
    ),
    "破折号泛滥": None,  # 特判: 逐段落数 "——" (单段 >= 3 计满), 不用正则
    "意义膨胀": re.compile(
        r"标志着|新篇章|奠定(?:了)?基础|更广泛的趋势|转折点"
        r"|stands\s+as\s+a\s+testament|pivotal\s+moment|new\s+(?:era|chapter)",
        re.IGNORECASE,
    ),
    "宣传腔": re.compile(
        r"充满活力|开创性|叹为观止|前所未有|举世瞩目"
        r"|revolutioniz|game[- ]?chang|cutting[- ]edge|state[- ]of[- ]the[- ]art"
        r"|groundbreaking|vibrant|innovative",
        re.IGNORECASE,
    ),
    "模糊归因": re.compile(
        r"专家(?:认为|表示|指出)|业内人士|研究表明|研究显示|据统计|数据显示"
        r"|有人认为|studies\s+show|experts\s+(?:say|believe)|research\s+shows?",
        re.IGNORECASE,
    ),
}
_PATTERN_KEYS = list(_PATTERNS.keys())

# AI 6 处反制中本地可测的措辞类信号 (缺专名/推进太顺为统计型, 单独实现)
_COUNTER_PHRASES = {
    "结尾太圆": re.compile(
        r"希望(?:对您|大家|这篇文章)[^\n。]{0,8}帮助|总而言之|综上所述|总之"
        r"|祝您|愿我们|值得关注|让我们",
    ),
    "鸡汤教科书化": re.compile(
        r"站在更高的视角|底层逻辑|归根结底|从更深层次|本质上说|不难发现",
    ),
}

# 全角字母数字折叠前的 CJK 范围 (标点签名用)
_CJK = r"\u4e00-\u9fff"
# CJK 邻接半角标点: 中文字符后直接跟半角 , . ; : ? ! (或反过来)
_MIXED_PUNCT_RE = re.compile(
    rf"[{_CJK}]\s?[,.;:?!]|[,.;:?!]\s?[{_CJK}]"
)
# emoji 常用区 (含符号区, AI 惯用装饰性表情)
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]"
)
_SENT_SPLIT_RE = re.compile(r"[。！？!?\n]+")
# Markdown 装饰行特征 (逐行匹配)
_MD_LINE_RES = [
    re.compile(r"^ {0,3}#{1,6}\s"),                 # ATX 标题
    re.compile(r"^ {0,3}[-*+]\s"),                  # 无序列表符
    re.compile(r"^ {0,3}>\s"),                      # 引用
    re.compile(r"^ {0,3}([-_*]\s*){3,}$"),          # 水平线
    re.compile(r"^ {0,3}(`{3,}|~{3,})"),            # 围栏
    re.compile(r"\*\*[^*\n]+?\*\*"),                # 加粗
    re.compile(r"~~[^~\n]+?~~"),                    # 删除线
    re.compile(r"\[[^\]\n]*\]\([^)\n]*\)"),         # 链接/图片
    re.compile(r"^\s*\|.+\|\s*$"),                  # 表格行
]


def _count_matches(text: str, regex: re.Pattern) -> int:
    return len(regex.findall(text or ""))


def _dim_blacklist(text: str) -> tuple[float, str, list[str]]:
    """硬黑名单维度: 密度计分 (每 100 字符命中 1.5 处记满). 返回 (ratio, detail, 命中词)."""
    hits_en = _BLACKLIST_EN_RE.findall(text)
    hits_zh = [w for w in _BLACKLIST_ZH for _ in re.finditer(re.escape(w), text)]
    n = len(hits_en) + len(hits_zh)
    if n == 0:
        return 0.0, "未命中黑名单", []
    density = n * 100.0 / max(len(text), 1)
    ratio = min(1.0, density / 1.5)
    words = sorted(set(w.lower() for w in hits_en) | set(hits_zh))
    detail = f"命中 {n} 处 ({'/'.join(words[:6])}{'…' if len(words) > 6 else ''})"
    return ratio, detail, words


def _dim_patterns(text: str) -> tuple[float, str, dict]:
    """7 大类第 2-7 类: 每类 24/6=4 分, 类内 2 次命中记满. 返回 (ratio, detail, 各类命中数)."""
    per = DIM_WEIGHTS["patterns"] / len(_PATTERN_KEYS)
    counts: dict[str, int] = {}
    total = 0.0
    for key in _PATTERN_KEYS:
        if key == "破折号泛滥":
            # 单段 >= 3 个 "——" 计满该类, 退化按全文总数封顶
            paras = [p for p in text.split("\n") if p.strip()]
            c = max((p.count("——") for p in paras), default=0)
            c = max(c, min(text.count("——"), 4))
            counts[key] = c
        else:
            c = _count_matches(text, _PATTERNS[key])
            counts[key] = c
        total += per * min(1.0, c / 2.0)
    hit_names = [k for k, v in counts.items() if v > 0]
    detail = (f"命中: {'/'.join(hit_names)}" if hit_names else "未命中")
    return total / DIM_WEIGHTS["patterns"], detail, counts


def _dim_counter(text: str) -> tuple[float, str, list[str]]:
    """AI 6 处反制 (本地可测 5 项). 返回 (ratio, detail, 命中项名)."""
    w = DIM_WEIGHTS["counter"]  # 18 = 4+4+4+4+2
    total = 0.0
    hit: list[str] = []
    # 1) 缺真实专名 (4): 长文 (>=500 字) 且无 >=2 位连续字母/数字, 且泛称 >= 3 处
    has_proper = bool(re.search(r"[A-Za-z0-9][A-Za-z0-9._\-]+", text))
    generic = len(re.findall(r"人们|大家|我们|众人|行业|社会|世界", text))
    if len(text) >= 500 and not has_proper and generic >= 3:
        total += 4.0
        hit.append("缺真实专名")
    # 2) 结尾太圆 (4): 文本末尾 80 字符内命中空泛收尾措辞
    tail = text[-80:]
    if _COUNTER_PHRASES["结尾太圆"].search(tail):
        total += 4.0
        hit.append("结尾太圆")
    # 3) 推进太顺 (4): >= 4 段且全文无转折标记
    paras = [p for p in text.split("\n") if p.strip()]
    has_twist = bool(re.search(r"但|不过|然而|可是|虽然|尽管|坑[:：]|例外", text))
    if len(paras) >= 4 and not has_twist:
        total += 4.0
        hit.append("推进太顺")
    # 4) 鸡汤教科书化 (4)
    if _COUNTER_PHRASES["鸡汤教科书化"].search(text):
        total += 4.0
        hit.append("鸡汤教科书化")
    # 5) 批次指纹 (2): 单段 >= 3 个反问/感叹 (与破折号泛滥部分重叠故降权)
    marks = max(
        (len(re.findall(r"[?？!！]", p)) for p in paras), default=0
    )
    if marks >= 3:
        total += 2.0
        hit.append("批次指纹")
    detail = (f"命中: {'/'.join(hit)}" if hit else "未命中 (原型不匹配为 LLM 审计专属, 本地不计)")
    return total / w, detail, hit


def _dim_burstiness(text: str) -> tuple[float, str]:
    """句长方差: CV (标准差/均值) 越小越像 AI. CV>=0.6 记 0, CV<=0.2 记满."""
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(text) if len(s.strip()) >= 2]
    if len(sents) < 3:
        return 0.0, f"句数 {len(sents)} < 3, 不判"
    lens = [len(s) for s in sents]
    mean = sum(lens) / len(lens)
    if mean <= 0:
        return 0.0, "平均句长为 0"
    var = sum((x - mean) ** 2 for x in lens) / len(lens)
    cv = math.sqrt(var) / mean
    ratio = max(0.0, min(1.0, (0.6 - cv) / 0.4))
    return ratio, f"{len(sents)} 句, CV={cv:.2f}"


def _dim_markdown(text: str) -> tuple[float, str]:
    """Markdown 装饰密度: 装饰行占比 >= 25% 记满."""
    lines = [ln for ln in text.split("\n")]
    if not lines:
        return 0.0, "空文本"
    total = len(lines)
    decorated = sum(
        1 for ln in lines
        if any(r.search(ln) for r in _MD_LINE_RES)
    )
    ratio = min(1.0, (decorated / total) * 4.0)
    return ratio, f"{decorated}/{total} 行含装饰标记"


def _dim_punct(text: str) -> tuple[float, str]:
    """标点签名: CJK 邻接半角标点混排 (每 100 字符 1 处记满) + emoji (2 个记满)."""
    mixed = _count_matches(text, _MIXED_PUNCT_RE)
    emoji = _count_matches(text, _EMOJI_RE)
    s1 = min(1.0, (mixed * 100.0 / max(len(text), 1)) / 1.0)
    s2 = min(1.0, emoji / 2.0)
    ratio = min(1.0, s1 + s2)
    return ratio, f"混排 {mixed} 处, emoji {emoji} 个"


def _collect_offenders(text: str) -> list[dict]:
    """摘出戏句: 逐句检查黑名单词 + 7 类正则 + 结尾反制, 最多 _MAX_OFFENDERS 条.

    全局型反制 (缺专名/推进太顺) 无法归属到具体句子, 不进 offenders —
    revise 反馈只吃"可指着鼻子改"的句子级问题."""
    offenders: list[dict] = []
    sents: list[str] = []
    for para in text.split("\n"):
        sents.extend(s for s in _SENT_SPLIT_RE.split(para) if len(s.strip()) >= 2)
    for sent in sents:
        reasons: list[str] = []
        for w in _BLACKLIST_EN_RE.findall(sent):
            reasons.append(f"黑名单:{w.lower()}")
        for w in _BLACKLIST_ZH:
            if w in sent:
                reasons.append(f"黑名单:{w}")
        for key in _PATTERN_KEYS:
            if key == "破折号泛滥":
                if sent.count("——") >= 2:
                    reasons.append("7类:破折号泛滥")
            elif _PATTERNS[key].search(sent):
                reasons.append(f"7类:{key}")
        if _COUNTER_PHRASES["结尾太圆"].search(sent):
            reasons.append("反制:结尾太圆")
        if _COUNTER_PHRASES["鸡汤教科书化"].search(sent):
            reasons.append("反制:鸡汤化")
        if reasons:
            offenders.append({"text": sent.strip()[:120], "reasons": reasons})
            if len(offenders) >= _MAX_OFFENDERS:
                break
    return offenders


def ai_score(text: str) -> dict:
    """客户端 0-100 AI 味评分 (纯函数, 幂等, 0 依赖). 见模块 docstring 权重表.

    返回:
        {"score": int (0-100, 越高 AI 味越重),
         "dims": {维度名: {"score": int 得分, "weight": int 权重, "detail": str}},
         "offenders": [{"text": 出戏句(截 120 字), "reasons": [命中原因]}, ...] 最多 5 条}
    """
    if not text or not text.strip():
        return {"score": 0, "dims": {}, "offenders": []}

    dims = {}
    total = 0.0

    r, detail, _words = _dim_blacklist(text)
    dims["blacklist"] = {"score": round(r * DIM_WEIGHTS["blacklist"]),
                         "weight": DIM_WEIGHTS["blacklist"], "detail": detail}
    total += r * DIM_WEIGHTS["blacklist"]

    r, detail, _counts = _dim_patterns(text)
    dims["patterns"] = {"score": round(r * DIM_WEIGHTS["patterns"]),
                        "weight": DIM_WEIGHTS["patterns"], "detail": detail}
    total += r * DIM_WEIGHTS["patterns"]

    r, detail, _hit = _dim_counter(text)
    dims["counter"] = {"score": round(r * DIM_WEIGHTS["counter"]),
                       "weight": DIM_WEIGHTS["counter"], "detail": detail}
    total += r * DIM_WEIGHTS["counter"]

    r, detail = _dim_burstiness(text)
    dims["burstiness"] = {"score": round(r * DIM_WEIGHTS["burstiness"]),
                          "weight": DIM_WEIGHTS["burstiness"], "detail": detail}
    total += r * DIM_WEIGHTS["burstiness"]

    r, detail = _dim_markdown(text)
    dims["markdown"] = {"score": round(r * DIM_WEIGHTS["markdown"]),
                        "weight": DIM_WEIGHTS["markdown"], "detail": detail}
    total += r * DIM_WEIGHTS["markdown"]

    r, detail = _dim_punct(text)
    dims["punct"] = {"score": round(r * DIM_WEIGHTS["punct"]),
                     "weight": DIM_WEIGHTS["punct"], "detail": detail}
    total += r * DIM_WEIGHTS["punct"]

    score = max(0, min(100, round(total)))
    return {"score": score, "dims": dims, "offenders": _collect_offenders(text)}
