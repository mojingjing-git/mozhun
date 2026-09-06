"""本地标点修复 (纯规则脚本, 不调用 LLM). v4.3.3

背景 (用户场景): AI 写小说时常混入英文半角字符, 尤其是引号 — 中文引号必须成对
(“” ‘’). 这类错误是确定性的, 用脚本修复比 LLM 更快更稳且零成本.

三条设计红线:
1. 只在"中文上下文"里动手 — 纯英文句子/代码/数字形态 (3.14, 1,000, 12:30, U.S.)
   一律不碰
2. 引号必须成对转换 — 按段落内出现顺序交替配对; 落单的引号保持原样
   (宁可漏改不误改, 不猜测开/闭)
3. 只做 半角→全角 方向的标点替换, 不做任何"改写"

规则表:
  "  → “ / ”   按段落内出现顺序交替配对 (仅含 CJK 的段落)
  '  → ‘ / ’   同上; 字母间的撇号 (don't) 不参与配对
  ...+ → ……    前邻或后邻为 CJK/全角标点时
  ,  → ，      前邻 CJK/全角标点, 或后邻 CJK 且前一位非数字 (排除 1,000)
  :  → ：      前邻 CJK/全角标点 (排除 12:30)
  ;  → ；      前邻 CJK/全角标点
  ?  !  → ？ ！ 前邻 CJK/全角标点
  .  → 。      前邻 CJK/全角标点 且 (行尾 或 后邻 CJK/全角标点/空白)
               (排除 3.14 / U.S. / example.com)
  ( ) → （ ）   括号对内含 CJK, 或 "(" 前邻 CJK/全角标点; 未配对不动

实现说明: 逐行处理 (引号配对不跨行 — 中文小说对话极少跨行, 跨行配对极易错配).
"""
import re

# 汉字 (CJK 统一表意文字 + 扩展 A)
_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))
# 全角标点/符号 (CJK 标点 + 全角形式), 视为"中文上下文"的一部分
_CJK_PUNCT = set(
    "，。！？；：、（）【】《》“”‘’…—～·「」『』〖〗"
)

_ELLIPSIS_RE = re.compile(r"\.{3,}")


def _is_han(ch: str) -> bool:
    """汉字 (不含全角标点)."""
    if not ch:
        return False
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _is_cjk_ctx(ch: str) -> bool:
    """中文上下文字符: 汉字或全角标点."""
    return _is_han(ch) or ch in _CJK_PUNCT


def _fix_quotes(chars: list[str], count: list[int], skip_double: bool = False) -> None:
    """直引号 → 中文成对引号 (就地修改).

    双引号 ": 段内含 CJK 时按出现顺序交替配对; 奇数个时最后一个保持原样.
    单引号 ': 同上, 且排除字母间的英文撇号 (don't / it's).

    v4.3.3 (评审 FP-1): skip_double=True 时跳过双引号转换 — 上一行存在未闭合
    引号时, 本行第一个引号实为 closer, 交替配对会整体反向 (把对的改错).
    保守降级: 该行双引号全部保持原样 (宁漏勿误).
    """
    has_cjk = any(_is_cjk_ctx(c) for c in chars)
    if not has_cjk:
        return  # 纯英文/数字行: 一律不动

    # --- 双引号 ---
    if not skip_double:
        dq = [i for i, c in enumerate(chars) if c == '"']
        if len(dq) % 2 == 1:
            dq = dq[:-1]  # 落单的不猜
        for k, i in enumerate(dq):
            chars[i] = "\u201c" if k % 2 == 0 else "\u201d"  # “ / ”
            count[0] += 1

    # --- 单引号 (撇号保护) ---
    sq = []
    for i, c in enumerate(chars):
        if c != "'":
            continue
        prev_ch = chars[i - 1] if i > 0 else ""
        next_ch = chars[i + 1] if i + 1 < len(chars) else ""
        # 字母夹缝 = 英文撇号 (don't), 不参与配对
        if (
            prev_ch.isascii() and prev_ch.isalpha()
            and next_ch.isascii() and next_ch.isalpha()
        ):
            continue
        sq.append(i)
    if len(sq) % 2 == 1:
        sq = sq[:-1]
    for k, i in enumerate(sq):
        chars[i] = "\u2018" if k % 2 == 0 else "\u2019"  # ‘ / ’
        count[0] += 1


def _fix_parens(chars: list[str], count: list[int]) -> None:
    """半角括号对 → 全角 (对内含 CJK, 或 ( 前邻中文上下文). 未配对不动."""
    stack = []
    pairs = []
    for i, c in enumerate(chars):
        if c == "(":
            stack.append(i)
        elif c == ")" and stack:
            pairs.append((stack.pop(), i))
    # 交叉/未配对的 ( 与 ) 不处理 (pairs 只含成功配对项; 未配对索引不在其中)
    for lo, hi in pairs:
        content = "".join(chars[lo + 1:hi])
        prev_ch = chars[lo - 1] if lo > 0 else ""
        if _is_cjk_ctx(prev_ch) or any(_is_cjk_ctx(c) for c in content):
            chars[lo] = "（"
            chars[hi] = "）"
            count[0] += 2


def _fix_line(line: str, skip_double: bool = False) -> tuple[str, int]:
    """修复单行 (引号/括号基于字符数组就地改; 其余规则基于上下文逐字符替换)."""
    count = [0]
    chars = list(line)

    # 1) 引号 (先于其它规则, 后续规则的 _is_cjk_ctx 能把转换后的 “” 识别为中文上下文)
    _fix_quotes(chars, count, skip_double=skip_double)
    # 2) 括号对
    _fix_parens(chars, count)

    # 3) 逐字符: , : ; ? ! . (省略号先单独处理)
    def _sub_ellipsis(m: re.Match) -> str:
        i = m.start()
        prev_ch = chars[i - 1] if i > 0 else ""
        next_i = m.end()
        next_ch = chars[next_i] if next_i < len(chars) else ""
        if _is_cjk_ctx(prev_ch) or _is_cjk_ctx(next_ch):
            count[0] += 1
            return "……"
        return m.group(0)

    line2 = "".join(chars)
    if _ELLIPSIS_RE.search(line2):
        new_line2 = _ELLIPSIS_RE.sub(_sub_ellipsis, line2)
        if new_line2 != line2:
            chars = list(new_line2)
            line2 = new_line2

    for i, ch in enumerate(chars):
        prev_ch = chars[i - 1] if i > 0 else ""
        next_ch = chars[i + 1] if i + 1 < len(chars) else ""
        prev_ctx = _is_cjk_ctx(prev_ch)
        if ch == ",":
            # 排除数字夹缝 (1,000); 后邻 CJK 且前一位非数字时也转 (John,他说)
            if prev_ctx and not (prev_ch.isdigit() and next_ch.isdigit()):
                chars[i] = "，"
                count[0] += 1
            elif _is_cjk_ctx(next_ch):
                # v4.3.3 (评审 FN-1): 后邻是 CJK 时前邻即使是数字也不构成千分位
                # 形态 (1,000 的后邻是数字) — 1937,战争 / 1000,成交 应当转换
                chars[i] = "，"
                count[0] += 1
        elif ch == ":":
            if prev_ctx:
                chars[i] = "："
                count[0] += 1
        elif ch == ";":
            if prev_ctx:
                chars[i] = "；"
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

    return "".join(chars), count[0]


def fix_punctuation(text: str) -> tuple[str, int]:
    """修复文本中的半角标点 (中文上下文), 返回 (修复后文本, 修复处数).

    逐行处理: 引号配对不跨行 — 跨行配对在小说场景极易错配, 宁可漏改.
    """
    if not text:
        return text, 0
    total = 0
    out = []
    # v4.3.3 (评审 FP-1): 跨行引号状态 — 上一行有未闭合的中文引号时,
    # 本行双引号整体跳过转换 (保守降级). 每个引号切换一次开/闭状态.
    pending_open = False
    for line in text.split("\n"):
        fixed, n = _fix_line(line, skip_double=pending_open)
        out.append(fixed)
        total += n
        # 仅含 CJK 的行参与状态翻转 (纯英文行的引号与中文引号状态无关)
        if any(_is_cjk_ctx(c) for c in line):
            pending_open = pending_open != (line.count('"') % 2 == 1)
    return "\n".join(out), total
