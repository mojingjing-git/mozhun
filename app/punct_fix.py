"""本地标点修复 v2 (纯规则脚本, 不调用 LLM). v4.3.4

背景 (用户场景): AI 写小说时常混入英文半角字符, 尤其是引号 — 中文引号必须成对.
这类错误是确定性的, 用脚本修复比 LLM 更快更稳且零成本.

四条设计红线:
1. 只在"中文上下文"里动手 — 纯英文句子/代码/数字形态 (3.14, 1,000, 12:30, U.S.)
   一律不碰; URL/邮箱整段掩蔽免疫
2. 引号必须成对转换 — 按段落交替配对; 落单保持原样 (宁漏勿误, 不猜开闭);
   跨行未闭合时后续行双引号整体降级跳过 (v4.3.3 评审 FP-1)
3. 只做 半角→全角 方向的标点替换 (全角字母/数字归一化为半角除外 — 指北 B4),
   不做任何"改写"; 分号永不转换 (autocorrect 同款原则: 代码/HTML 实体高危)
4. 幂等 — 对已正确的文本重复执行输出不变

规则表 (v4.3.4, 调研吸收: typeset/autocorrect/macro-correct 思路 + GB/T 15834-2011
与《中文文案排版指北》为规范依据, 思路借鉴均未复制代码):
  "  → “ / ”    按段落交替配对 (仅含 CJK 的段落); 落单不动
  '  → ‘ / ’    同上; 字母夹缝撇号 (don't) 与属格撇号 (James'/players') 不参与
    GB/T 15834: 省略号后不再用句号 — run 末尾的 。 一并归一 (……。 → ……).
  ,  → ，       前邻 CJK/全角标点, 或后邻(跳过一个空格)CJK 且前一位非数字
  :  → ：       前邻 CJK/全角标点 (12:30 安全)
  ?  !  → ？ ！  前邻 CJK/全角标点
  .  → 。       前邻 CJK/全角标点 且 (行尾/后邻 CJK/空白) (3.14/U.S./BABA.N 安全)
  ;  →          永不转换 (分号在代码/HTML 实体高频, autocorrect 同款原则)
  --+/单个—/~+ → ——/～   前后任一邻 CJK 上下文 (GB/T 15834: ——/~ 形态)
  （ ）         半角括号对→全角 (对内含 CJK 或前邻中文); 未配对不动
  ＡＢＣ１２３ → ABC123  全角字母/数字归一化 (不动全角标点/全角空格; 指北 B4)
  "…" 落单/计数不等 → 不修改, 计入不平衡报告 (fix_punctuation_ex)

接口:
  fix_punctuation(text, options=None) -> (str, int)            兼容旧签名
  fix_punctuation_ex(text, options=None) -> (str, dict)        详情 (分规则计数+
                                                                引号不平衡报告)
  options: {"quote_style": "curly"|"rect",      # 直角引号「」 (指北争议项, 默认弯)
            "fullwidth_alnum": bool,            # 全角字母/数字归一化 (默认 True)
            "repeat_compress": bool,            # 重复标点压缩 ！！！→！ (默认 False)
            "dash_tilde": bool}                 # 破折号/波浪补齐 (默认 True)

借鉴来源 (思路借鉴, 代码自写; 完整声明见 THIRD_PARTY_NOTICES.md):
- https://github.com/woct0rdho/typeset (MIT) — 全角折叠/省略号权重法/隔空格回看
- https://github.com/huacnlee/autocorrect (MIT) — CJK 邻接涌现式保护/分号原则/
  URL 整段免疫/规则三态配置
- https://github.com/yongzhuo/macro-correct (Apache-2.0) — 0xFEE0 偏移算法/
  成对标点计数校验思路
- 《中文文案排版指北》https://github.com/sparanoid/chinese-copywriting-guidelines
  (MIT) 与 GB/T 15834-2011《标点符号用法》 — 规则权威依据
"""
import re

# 汉字 (CJK 统一表意文字 + 扩展 A)
_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))
# 全角标点/符号 (CJK 标点 + 全角形式), 视为"中文上下文"的一部分
_CJK_PUNCT = set(
    "，。！？；：、（）【】《》“”‘’…—～·「」『』〖〗"
)

# URL/邮箱掩蔽正则 (v4.3.4, 借鉴 autocorrect PATH_RE 思路):
# 命中整段掩蔽, 其内标点对所有规则免疫
# RFC 3986 字符白名单: 天然排除 CJK/全角标点/弯引号 (评审 P5:
# 旧 \S+ 会把 URL 后紧贴的引号/标点/中文一并吞进免疫段)
_URL_BODY = r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]"
_URL_RE = re.compile(
    r"(?:https?://|www\.)" + _URL_BODY + r"+"
    r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
# 省略号 run: 半角点/全角句号/间隔号/省略号字符的连续序列
_ELLIPSIS_RUN_RE = re.compile(r"[.。·…]+")
# 重复标点 (同字符连续 ≥2): ！！！ / ？？？ / ...
_REPEAT_RE = re.compile(r"([！？!?])\1{1,}")
# 破折号候选: 两个以上连字符 / em dash 连续 / 单个 en dash (单个 - 不动, 区间语义)
_DASH_RE = re.compile(r"-{2,}|—+|–")
# 波浪号连续
_TILDE_RE = re.compile(r"~+")
# 全角字母/数字 (FF10-FF19 数字, FF21-FF3A 大写, FF41-FF5A 小写)
_FULLWIDTH_ALNUM = (
    (0xFF10, 0xFF19),
    (0xFF21, 0xFF3A),
    (0xFF41, 0xFF5A),
)

_DEFAULT_OPTIONS = {
    "quote_style": "curly",     # curly=弯引号“” / rect=直角引号「」
    "fullwidth_alnum": True,    # 全角字母/数字 → 半角
    "repeat_compress": False,   # 重复标点压缩 ！！！→！(默认只保留不压缩)
    "dash_tilde": True,         # 破折号/波浪补齐
}


def _is_han(ch: str) -> bool:
    """汉字 (不含全角标点)."""
    if not ch:
        return False
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _is_cjk_ctx(ch: str) -> bool:
    """中文上下文字符: 汉字或全角标点."""
    return _is_han(ch) or ch in _CJK_PUNCT


def _is_cjk_ctx_skip_space(chars: list[str], i: int, step: int) -> bool:
    """方向性中文上下文判定 (v4.3.4, 借鉴 typeset detect_forward 思路):
    从位置 i 出发按 step (+1/-1) 看, 允许跳过至多一个空格."""
    j = i + step
    if j < 0 or j >= len(chars):
        return False
    if _is_cjk_ctx(chars[j]):
        return True
    if chars[j] == " ":
        k = j + step
        if 0 <= k < len(chars) and _is_cjk_ctx(chars[k]):
            return True
    return False


def _mask_urls(text: str) -> tuple[str, dict]:
    """URL/邮箱整段掩蔽 (autocorrect PATH_RE 思路): 其内标点对所有规则免疫."""
    mapping = {}

    def _sub(m: re.Match) -> str:
        key = f"\x00{len(mapping)}\x00"
        mapping[key] = m.group(0)
        return key

    return _URL_RE.sub(_sub, text), mapping


def _unmask(text: str, mapping: dict) -> str:
    # v4.3.4 (评审 P6): 单遍正则替换 — 逐 key str.replace 是 O(N×K),
    # URL 密集文本实测 22 倍劣化 (80 万字 × 1 万 URL: 0.78s → 17s)
    if not mapping:
        return text
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: mapping.get(m.group(0), m.group(0)), text)


def _merge_options(options: dict | None) -> dict:
    opts = dict(_DEFAULT_OPTIONS)
    if options:
        for k, v in options.items():
            if k in opts and v is not None:
                opts[k] = v
    return opts


def _fold_fullwidth_alnum(chars: list[str], count: list[int]) -> None:
    """全角字母/数字 → 半角 (0xFEE0 偏移, macro-correct q2b 算法思路).

    只转字母/数字 (指北 B4: 数字用半形); 不动全角标点与全角空格
    (全角空格在中文排版有占位语义).
    """
    for i, c in enumerate(chars):
        cp = ord(c)
        if any(lo <= cp <= hi for lo, hi in _FULLWIDTH_ALNUM):
            chars[i] = chr(cp - 0xFEE0)
            count[0] += 1


def _fix_quotes(
    chars: list[str], count: list[int],
    skip_double: bool = False, stats: dict | None = None,
    line_no: int = 0,
) -> set[int]:
    """直引号 → 中文成对引号 (就地修改).

    双引号 ": 段内含 CJK 时按出现顺序交替配对; 奇数个时最后一个保持原样,
    并计入不平衡报告 (只报不改). skip_double=True 时整体跳过 (跨行降级).
    单引号 ': 同上; 排除字母夹缝撇号 (don't) 与属格撇号 (James'/players'),
    两类撇号就地规范为 ’ 字形 (不参与配对), 其位置经返回值上报 —
    _detect_imbalance 据此把撇号字形从"落单闭引号"统计中剔除 (评审 P1).
    """
    has_cjk = any(_is_cjk_ctx(c) for c in chars)
    if not has_cjk:
        return set()  # 纯英文/数字行: 一律不动

    apos_idx: set[int] = set()  # v4.3.4 (评审 P1): 撇号字形位置, 供 imbalance 剔除

    # --- 双引号 ---
    dq = [i for i, c in enumerate(chars) if c == '"']
    if len(dq) % 2 == 1:
        dq = dq[:-1]  # 落单的不猜
        if stats is not None:
            stats["imbalance"].append({
                "kind": "double", "line": line_no, "count": len(dq) + 1,
                "line_text": "".join(chars).strip()[:40],
            })
    if not skip_double:
        for k, i in enumerate(dq):
            chars[i] = "\u201c" if k % 2 == 0 else "\u201d"  # “ / ”
            count[0] += 1

    # --- 单引号 (撇号保护: 缩略 + 属格) ---
    sq = []
    for i, c in enumerate(chars):
        if c != "'":
            continue
        prev_ch = chars[i - 1] if i > 0 else ""
        next_ch = chars[i + 1] if i + 1 < len(chars) else ""
        # 1) 字母夹缝 = 英文缩略撇号 (don't), 不参与配对; 正确字形为 ’ (U+2019)
        if (
            prev_ch.isascii() and prev_ch.isalpha()
            and next_ch.isascii() and next_ch.isalpha()
        ):
            chars[i] = "’"
            count[0] += 1
            apos_idx.add(i)
            continue
        excluded = False
        # 2) v4.3.4 (调研: 属格撇号 James'/players') — 前邻是长度≥2 的字母串
        #    且后邻非字母时, 视为属格/复数所有格, 不参与配对
        if (
            prev_ch.isascii() and prev_ch.isalpha()
            and not (next_ch.isascii() and next_ch.isalpha())
        ):
            j = i - 1
            run_len = 0
            while j >= 0 and chars[j].isascii() and chars[j].isalpha():
                run_len += 1
                j -= 1
            if run_len >= 2:
                excluded = True
        if excluded:
            # 缩略/属格撇号的正确字形是 ’ (U+2019) — 字形规范但不参与配对状态
            chars[i] = "’"
            count[0] += 1
            apos_idx.add(i)
            continue
        sq.append(i)
    if len(sq) % 2 == 1:
        sq = sq[:-1]
        if stats is not None:
            stats["imbalance"].append({
                "kind": "single", "line": line_no, "count": len(sq) + 1,
                "line_text": "".join(chars).strip()[:40],
            })
    if not skip_double:
        for k, i in enumerate(sq):
            chars[i] = "\u2018" if k % 2 == 0 else "\u2019"  # ‘ / ’
            count[0] += 1
    return apos_idx


def _fix_parens(chars: list[str], count: list[int]) -> None:
    """半角括号对 → 全角 (对内含 CJK, 或 ( 前邻中文上下文). 未配对不动."""
    stack = []
    pairs = []
    for i, c in enumerate(chars):
        if c == "(":
            stack.append(i)
        elif c == ")" and stack:
            pairs.append((stack.pop(), i))
    for lo, hi in pairs:
        content = "".join(chars[lo + 1:hi])
        prev_ch = chars[lo - 1] if lo > 0 else ""
        if _is_cjk_ctx(prev_ch) or any(_is_cjk_ctx(c) for c in content):
            chars[lo] = "（"
            chars[hi] = "）"
            count[0] += 2


def _fix_ellipsis_run(line: str, count: list[int], stats: dict | None) -> str:
    """省略号 run 归一化 (v4.3.4 权重法, 借鉴 typeset + GB/T 15834 D1):

    run 字符集 = 半角点/全角句号/间隔号/省略号; 权重 …=3 其余=1, ≥3 归一为 …….
    保留行尾句号: run 末尾的 。 不并入 (……。 的句号是句子终止符, 不能吞).
    """
    def _sub(m: re.Match) -> str:
        run = m.group(0)
        # 权重法 (…=3 其余=1): ≥3 即省略号 run — 含 。。。 (全角句号重复) 与
        # 混合形态; GB/T 15834: 省略号后不再用句号, 故 …。 整体归一为 ……
        weight = sum(3 if c == "…" else 1 for c in run)
        i = m.start()
        prev_ch = line[i - 1] if i > 0 else ""
        end = m.end()
        next_ch = line[end] if end < len(line) else ""
        # run 含全角字符 (。……·) 即自证中文上下文 (评审 P3:
        # 独立成行的 ……。 也要归一)
        if weight >= 3 and (
            any(c in _CJK_PUNCT for c in run)
            or _is_cjk_ctx(prev_ch) or _is_cjk_ctx(next_ch)
        ):
            count[0] += 1
            return "……"
        return run

    return _ELLIPSIS_RUN_RE.sub(_sub, line)


def _apply_rect_quote_style(chars: list[str], count: list[int]) -> None:
    """直角引号风格 (指北争议项 C1, 默认关): “”→「」; 「」区间内的 ‘’→『』."""
    old = "".join(chars)
    # v4.3.4 (评审 P8): “” 的字形变化也要计数
    count[0] += old.count(chr(0x201c)) + old.count(chr(0x201d))
    chars[:] = list(old.replace(chr(0x201c), "「").replace(chr(0x201d), "」"))
    # 单引号: 落在「」区间内 → 『』; 区间外 → 「」
    in_span = False
    depth = 0
    for i, c in enumerate(chars):
        if c == "「":
            depth += 1
            in_span = depth > 0
        elif c == "」":
            depth = max(0, depth - 1)
            in_span = depth > 0
        elif c == "\u2018":
            chars[i] = "『" if in_span else "「"
            count[0] += 1
        elif c == "\u2019":
            # v5.4.3 (F2): 英文拾号 (don't / James') 不参与直角化 ——
            # 字形已由 _fix_quotes 规范为 ’ (:205/:225), 但旧版这里无条件映射成
            # 『/』, 把 v4.3.4 评审 P1 的成果整段推翻 (rect 模式下
            # don't → don」t / James' → James」)。
            #
            # 判据**严格复刻 _fix_quotes 的两条拾号规则** (:201-228), 用 isalpha
            # 而非 isalnum:
            #   规则1 两侧均为 ASCII 字母      → 字母夹缝缩略 (don't)
            #   规则2 前邻 ASCII 字母串长度>=2 且后邻非 ASCII 字母 → 属格 (James')
            # 用 isalnum 会把「中文单引号对里包 ASCII」('a' / 'I') 和「数字成对」
            # (1980'1990') 误判为拾号 —— 实测前者产出落单直角引号, 后者把成对
            # 引号拆成不对等。故此处逐字对齐 _fix_quotes。
            prev_ch = chars[i - 1] if i > 0 else ""
            next_ch = chars[i + 1] if i + 1 < len(chars) else ""
            if (
                prev_ch.isascii() and prev_ch.isalpha()
                and next_ch.isascii() and next_ch.isalpha()
            ):
                continue                      # 规则1: 字母夹缝缩略
            if prev_ch.isascii() and prev_ch.isalpha() and not (
                next_ch.isascii() and next_ch.isalpha()
            ):
                j = i - 1
                run_len = 0
                while j >= 0 and chars[j].isascii() and chars[j].isalpha():
                    run_len += 1
                    j -= 1
                if run_len >= 2:
                    continue                  # 规则2: 属格/复数所有格
            chars[i] = "』" if in_span else "」"
            count[0] += 1


def _detect_imbalance(
    line: str, line_no: int, stats: dict,
    apos_idx: frozenset = frozenset(),
) -> None:
    """成对标点计数校验 (只报不改; 思路借鉴 macro-correct check_double).

    v4.3.4 (评审 P1): 撇号字形 ’ 不计入"落单闭引号" — apos_idx 为 _fix_quotes
    转换的撇号位置; 其余来源的 ’ 用字母邻接启发式排除 (don’t/James’).
    已知取舍: ‘英文词’ 闭引号前邻为 ASCII 字母时会被启发式误排除 (漏报,
    宁漏勿误同样适用于报告).
    v4.3.4 (评审 P2): 条目 schema 统一含 line; _fix_quotes 已报的 (line, kind)
    不再重复出具, 消除同一问题双写.
    """
    reported = {
        (e.get("line"), e["kind"]) for e in stats["imbalance"] if "line" in e
    }
    pairs = [("\u201c", "\u201d", "double"),
             ("\u2018", "\u2019", "single"),
             ("（", "）", "paren")]
    for opener, closer, kind in pairs:
        if (line_no, kind) in reported:
            continue
        o = line.count(opener)
        if kind == "single":
            c = sum(
                1 for i, ch in enumerate(line)
                if ch == closer and i not in apos_idx
                and not (
                    (i > 0 and line[i - 1].isascii() and line[i - 1].isalnum())
                    or (i + 1 < len(line) and line[i + 1].isascii()
                        and line[i + 1].isalnum())
                )
            )
        else:
            c = line.count(closer)
        if o != c:
            stats["imbalance"].append({
                "kind": kind, "line": line_no, "open": o, "close": c,
                "line_text": line.strip()[:40],
            })


def _fix_line(
    line: str, line_no: int, opts: dict, skip_double: bool, stats: dict,
) -> tuple[str, int]:
    """修复单行 (引号/括号基于字符数组就地改; 其余规则基于上下文逐字符替换)."""
    count = [0]
    chars = list(line)

    # 0) 全角字母/数字归一化 (指北 B4; 先行 — 让后续规则的数字守卫看到半角)
    if opts["fullwidth_alnum"]:
        _fold_fullwidth_alnum(chars, count)

    # 1) 引号 (先于其它规则, 后续规则的 _is_cjk_ctx 能把转换后的 “” 识别为中文上下文)
    apos_idx = _fix_quotes(chars, count, skip_double=skip_double, stats=stats,
                           line_no=line_no)
    # 2) 括号对
    _fix_parens(chars, count)

    # 3) 逐字符: , : ? ! . (分号永不转换 — 评审/autocorrect 原则)
    for i, ch in enumerate(chars):
        prev_ch = chars[i - 1] if i > 0 else ""
        next_ch = chars[i + 1] if i + 1 < len(chars) else ""
        prev_ctx = _is_cjk_ctx(prev_ch)
        if ch == ",":
            # 低危档 (autocorrect): 前邻 CJK, 或后邻(跳一个空格)CJK — 数字夹缝除外
            if prev_ctx and not (prev_ch.isdigit() and next_ch.isdigit()):
                chars[i] = "，"
                count[0] += 1
            elif _is_cjk_ctx_skip_space(chars, i, +1):
                # v4.3.4 (评审 FN-1): 后邻 CJK 时前邻即使是数字也不构成千分位
                # (1,000 的后邻是数字) — 1937,战争 / iPhone,好开心 都应转换
                chars[i] = "，"
                count[0] += 1
        elif ch == ":":
            if prev_ctx:
                chars[i] = "："
                count[0] += 1
        elif ch in ("?", "!"):
            if prev_ctx:
                chars[i] = "？" if ch == "?" else "！"
                count[0] += 1
        elif ch == ".":
            # 排除小数/缩写/域名: 要求前邻中文, 且后邻为行尾/中文/空白
            if prev_ctx and (
                next_ch == "" or _is_cjk_ctx(next_ch) or next_ch.isspace()
            ):
                chars[i] = "。"
                count[0] += 1

    line = "".join(chars)

    # 4) 省略号 run 归一化 (。。。/混合 run)
    if _ELLIPSIS_RUN_RE.search(line):
        line = _fix_ellipsis_run(line, count, stats)

    # 5) 破折号/波浪补齐 (GB/T: ——/～ 形态; 单个 - 是连字符不动)
    if opts["dash_tilde"]:

        def _sub_dash(m: re.Match) -> str:
            i = m.start()
            prev_ch = line[i - 1] if i > 0 else ""
            end = m.end()
            next_ch = line[end] if end < len(line) else ""
            if m.group(0) == "——":
                return m.group(0)  # 已是规范形态
            if _is_cjk_ctx(prev_ch) or _is_cjk_ctx(next_ch):
                count[0] += 1
                return "——"
            return m.group(0)

        line = _DASH_RE.sub(_sub_dash, line)

        def _sub_tilde(m: re.Match) -> str:
            i = m.start()
            prev_ch = line[i - 1] if i > 0 else ""
            end = m.end()
            next_ch = line[end] if end < len(line) else ""
            if _is_cjk_ctx(prev_ch) or _is_cjk_ctx(next_ch):
                count[0] += 1
                return "～"
            return m.group(0)

        line = _TILDE_RE.sub(_sub_tilde, line)

    # 6) 重复标点压缩 (默认关 — 小说刻意强调场景; 指北 B1)
    if opts["repeat_compress"]:
        def _sub_repeat(m: re.Match) -> str:
            count[0] += 1  # v4.3.4 (评审 P7): 压缩计入统计
            return m.group(1)
        line = _REPEAT_RE.sub(_sub_repeat, line)

    # 7) 直角引号风格 (默认关; 嵌套层级: 双引号「」, 「」区间内单引号『』)
    # v4.3.4 (评审 P8): “”→「」 的字形变化在 _apply_rect_quote_style 内计数
    if opts["quote_style"] == "rect":
        chars = list(line)
        _apply_rect_quote_style(chars, count)
        line = "".join(chars)

    # 8) 成对标点计数校验 (只报不改) — v4.3.4 (评审 P1): 传入撇号位置剔除
    if any(_is_cjk_ctx(c) for c in line):
        _detect_imbalance(line, line_no, stats, frozenset(apos_idx))

    return line, count[0]


def fix_punctuation_ex(text: str, options: dict | None = None) -> tuple[str, dict]:
    """修复文本中的半角标点 (中文上下文), 返回 (修复后文本, 统计详情).

    统计详情: {"total": 修复总处数, "imbalance": [成对标点不平衡报告...]}
    imbalance 条目: {"kind": double/single/paren, "line": 行号(1 起),
                     "open": 开计数, "close": 闭计数, "line_text": 行摘录}
    只报不改 — 与"宁漏勿误"红线互补.
    """
    opts = _merge_options(options)
    stats = {"total": 0, "imbalance": []}
    if not text:
        return text, stats
    # v4.3.4 (评审 P4): 原文 NUL 与掩蔽占位符同空间 — 剥离防串号破坏原文
    text = text.replace("\x00", "")
    text, url_map = _mask_urls(text)
    total = 0
    out = []
    pending_open = False
    for line_no, line in enumerate(text.split("\n"), start=1):
        fixed, n = _fix_line(line, line_no, opts, pending_open, stats)
        out.append(fixed)
        total += n
        # 跨行引号状态 (FP-1): 仅含 CJK 的行参与翻转; 纯英文行引号与中文引号状态无关
        if any(_is_cjk_ctx(c) for c in line):
            pending_open = pending_open != (line.count('"') % 2 == 1)
    fixed_text = _unmask("\n".join(out), url_map)
    # v4.3.4 (评审 P5): line_text 截取自掩蔽文本, 还原占位符防前端穿帮
    for e in stats["imbalance"]:
        if e.get("line_text"):
            e["line_text"] = _unmask(e["line_text"], url_map)
    stats["total"] = total
    return fixed_text, stats


def fix_punctuation(text: str, options: dict | None = None) -> tuple[str, int]:
    """兼容旧签名: 返回 (修复后文本, 修复总处数). 需要详情用 fix_punctuation_ex."""
    fixed, stats = fix_punctuation_ex(text, options)
    return fixed, stats["total"]
