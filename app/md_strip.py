# 借鉴自 https://github.com/commonmark/commonmark-spec (CC-BY-SA 4.0, spec 文本)
# 借鉴内容: Markdown 结构语义的保守子集 (围栏/强调边界/表格形态/ATX 标题)
# 借鉴方式: 规范语义引用,无代码复制
# Copyright (c) John MacFarlane, CommonMark contributors

"""md_strip — 本地 Markdown 清洗引擎 (v4.4.2, 与 punct_fix 同类的零 LLM 纯规则变换).

需求: AI 产出的 .md / md 格式 txt 丢进来, 产出一篇无 md 标记、适宜人类阅读的文章.

红线 (与 punct_fix 同款纪律):
1. 内容不丢 — 只剥标记不删文字. 两类例外:
   a) 链接/图片的 URL 丢弃: [text](url)→text (text 空则留 url); 图片 alt 空则整段丢弃;
   b) 纯标记行整行删除: 水平线/围栏行/表格分隔行/引用定义行/frontmatter 边界.
2. 代码内容保留 — 围栏剥壳留内容 (含缩进/空行, 单遍内被掩蔽完整保护);
   行内代码: 内容含 md 字符 → 整体保留 (含反引号, 防暴露后二次伤害);
   内容干净 → 剥反引号留纯文本 (两分支各自幂等).
3. 幂等 — 对非代码区成立 (全部正例连跑两遍相等). 围栏内容单遍内逐字保护,
   但剥壳后暴露于二次剥离的行级规则 — 管线单遍使用不受影响 (重跑走原文);
   本模块不承诺对"已剥离输出"再次剥离的围栏区幂等 (评审 P1-3/幂等分析).
4. 保守 — 歧义/不成对标记不动. 两个典型决策:
   - 下划线强调 __x__ 整类不剥 (AI 文章罕见, __init__/snake_case 常见, 剥必误伤;
     CommonMark 自己会渲染成斜体, 我们偏保守);
   - 星号强调加 ASCII 词边界: 开/闭标记紧邻 ASCII 字母/数字/下划线不剥
     (2*3*4 / word**x**word 跳过), 紧邻 CJK/标点/空白/行首尾才剥 (词**加粗**词 主用例).

明确不做 (v1 边界):
- HTML 标签 (<b>/<br> 等原样保留)
- 4 空格缩进代码块 (按普通行处理, 内容与缩进保留)
- 转义还原 (\\* 保留原样 — 转义剥离有确证的幂等漏洞: \\*强调\\* 第一遍转义后暴露
  成对星号, 第二遍被强调规则吃掉; 剥在强调前则吞掉用户字面星号, 更差. 评审 P1-3)
- 数学 $...$、脚注语义、任务列表复选框语义、嵌套列表缩进重排

规则表 (行级 → 行内):
  ---\\ntitle:...\\n---          → YAML frontmatter 整块剥离 (仅文件开头, 评审 P1-7)
  #\\s 标题 ##                 → 去井号留文字 (# 后须空格/行尾, `#1 序言` 不是标题)
  > 引用                       → 剥标记留内容 (含多层 >>, 迭代剥)
  -/+/* 空格 列表              → 剥标记留内容 (迭代剥, - - x → x; 有序列表 1. 保留)
  | --- | :---: |              → 删除 (分隔行; 容忍空格与对齐冒号)
  | a | b |                    → a  b (剥首尾竖线, 单元格两空格连接)
  --- / *** / ___ 独立行        → 删除 (水平线)
  [ref]: https://...           → 删除 (引用定义行, 评审 P1-5)
  ![alt](src)                  → alt (alt 空则丢弃)
  [text](url) / [text][ref]    → text (text 空则留 url)
  **x** / ~~x~~ / *x*          → x (带 ASCII 词边界, 见红线 4)
  行尾空白 / 3+ 空行            → 规整 (掩蔽区不受影响)

接口: strip_markdown(text) -> str. 无选项 — 清洗语义不做配置 (保守集合).
调用方 (processor) 负责空结果兜底: 纯标记文件产出空文本时回退保留原文
(空 corrected 会击穿 diff 与断点 is_done 语义, 评审 P2-16).
"""
import re

# 掩蔽占位符 (punct_fix 同款): NUL 在入口剥离, 不会与用户文本串号
# v5.0.1 (审计 L-1/L-2): 围栏开/闭分离校验 (同字符同长度); 行内代码等长 run 配对
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")        # 开: 可带语言标记
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")  # 闭: 仅尾随空白
_CODE_SPAN_RE = re.compile(r"(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)")
_MD_CHARS = set("*_~`#[]()!|>-+")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]*)\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
_REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_REF_DEF_RE = re.compile(r"^ {0,3}>{0,2}\s*\[[^\]]+\]:\s*\S+.*$")
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(\s+(.*?))?\s*#*\s*$")
_QUOTE_RE = re.compile(r"^ {0,3}> ?")
_UL_RE = re.compile(r"^ {0,3}[-+*] (.*)$")
_HR_RE = re.compile(r"^ {0,3}([-_*]\s*){3,}$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n?", re.DOTALL)
_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC_RE = re.compile(r"\*([^*\n]+?)\*")
_STRIKE_RE = re.compile(r"~~([^~\n]+?)~~")


def _boundary_ok(s: str, i: int, j: int, star: bool = False) -> bool:
    """星号强调的 ASCII 词边界: 开标记前邻 / 闭标记后邻 (即 s[i-1] 与 s[j])
    若为 ASCII 字母/数字/下划线则不剥 (2*3*4 / word**x**word 保守跳过);
    为 CJK/全角标点/空白/行首尾才剥 (词**加粗**词 是主用例).
    追加两条硬屏蔽:
    - 前邻 '\\' (md 转义星号) 一律不剥 — 转义还原已列入不做 (评审 P1-3);
    - star=True (单星斜体) 时前/后邻 '*' 也不剥 — 防止在被 bold 边界否决的
      2**3**4 残余星号上误配对 (评审复现的幂等反例); bold 不启用此条,
      否则 ***粗斜*** 的外层星号会挡住自身匹配."""
    for pos in (i - 1, j):
        if 0 <= pos < len(s):
            c = s[pos]
            if c == "\\":
                return False
            if star and c == "*":
                return False
            if c.isascii() and (c.isalnum() or c == "_"):
                return False
    return True


def _strip_paired(line: str, pattern: re.Pattern[str], star: bool = False) -> str:
    def repl(m: re.Match) -> str:
        if _boundary_ok(line, m.start(), m.end(), star):
            return m.group(1)
        return m.group(0)
    return pattern.sub(repl, line)


def _store(store: dict, content: str) -> str:
    token = f"\x00M{len(store)}\x00"
    store[token] = content
    return token


def _mask_fences(text: str, store: dict) -> str:
    """Phase 1a: 围栏代码块掩蔽 (行级状态机, CommonMark §4.5).

    v5.0.1 (审计 L-1): 闭合围栏必须与开启围栏**同字符且长度 >= 开启长度**
    (``` 开的块不再被 ~~~ 行闭合, 异字符行按代码内容保留) — 旧实现任何围栏
    行都当闭合, 异字符行被吞导致内容丢失 (触红线 1). 未闭合到 EOF 保守
    掩蔽到尾. 开启行 (含语言标记) 与闭合行剥壳, 内容逐行保留."""
    lines = text.split("\n")
    out: list[str] = []
    fence: tuple[str, int, list[str]] | None = None  # (围栏字符, 开启长度, 内容行)
    for ln in lines:
        if fence is not None:
            m = _FENCE_CLOSE_RE.match(ln)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                out.append(_store(store, "\n".join(fence[2])))  # 剥壳留内容
                fence = None
            else:
                fence[2].append(ln)  # 异字符围栏行 / 普通行 → 代码内容
            continue
        m = _FENCE_OPEN_RE.match(ln)
        if m:
            fence = (m.group(1)[0], len(m.group(1)), [])  # 开围栏行剥壳丢弃
            continue
        out.append(ln)
    if fence is not None:  # 未闭合到 EOF: 开围栏行丢弃, 内容整块保护
        out.append(_store(store, "\n".join(fence[2])))
    return "\n".join(out)


def _mask_inline_code(line: str, store: dict) -> str:
    """Phase 1b: 行内代码 (CommonMark §6.1 反引号 run 等长配对).

    v5.0.1 (审计 L-2): 开/闭反引号 run **等长**配对 (``code`` 双反引号整段
    剥壳) — 旧实现只配单反引号对, 双反引号残留半对. 内容含 md 字符 (含 `)
    → 整体保留含反引号 (掩蔽保护, 防暴露后二次伤害); 干净内容 → 剥反引号.
    两分支各自幂等."""
    def repl(m: re.Match) -> str:
        content = m.group(2)
        if any(c in _MD_CHARS for c in content):
            return _store(store, m.group(0))  # 含反引号整体保留
        return _store(store, content)  # 干净内容剥反引号
    return _CODE_SPAN_RE.sub(repl, line)


def _strip_line(line: str) -> str:
    """Phase 2+3: 单行的行级规则与行内规则. 顺序: 引用/列表迭代剥 →
    纯标记行删除 → ATX/表格变换 → 行内 (图片/链接/强调). 有序列表 1./1)
    保留原样 — 数字即人类可读顺序."""
    for _ in range(32):  # 迭代剥引用/列表 (>> 与 - - x), 上限防病态输入
        if _QUOTE_RE.match(line):
            line = _QUOTE_RE.sub("", line, count=1)
            continue
        m = _UL_RE.match(line)
        if m:
            line = m.group(1)
            continue
        break
    if _TABLE_SEP_RE.match(line):
        return ""
    if _REF_DEF_RE.match(line):
        return ""
    if _HR_RE.match(line):
        return ""
    m = _ATX_RE.match(line)
    if m:
        line = m.group(3) or ""  # 标题文字可能含强调, 落到行内规则继续处理
    m = _TABLE_ROW_RE.match(line)
    if m:
        cells = [c.strip() for c in m.group(1).split("|")]
        line = "  ".join(c for c in cells if c)  # 单元格内容同样落入行内规则
    # 行内: 图片先于链接 (![..](..) 含链接形态), 引用式链接随后, 再强调
    line = _IMAGE_RE.sub(lambda m: m.group(1), line)
    line = _LINK_RE.sub(lambda m: m.group(1) or m.group(2), line)
    line = _REF_LINK_RE.sub(r"\1", line)
    line = _strip_paired(line, _BOLD_RE)
    line = _strip_paired(line, _STRIKE_RE)
    line = _strip_paired(line, _ITALIC_RE, star=True)
    return line.rstrip()


def _is_pure_marker_line(ln: str) -> bool:
    """纯标记行 (红线 1b): 整行删除而非替换成空行 — 替换为空行会凭空多出
    段间空行 (水平线/分隔行/引用定义行三种)."""
    return bool(
        _HR_RE.match(ln) or _TABLE_SEP_RE.match(ln) or _REF_DEF_RE.match(ln)
    )


def strip_markdown(text: str) -> str:
    """剥离 Markdown 标记, 返回适宜人类阅读的纯文本. 见模块 docstring 红线."""
    if not text:
        return text
    # 入口剥 NUL (punct_fix P4 同款): 掩蔽占位符含 \x00, 不能与用户文本串号
    text = text.replace("\x00", "")
    # YAML frontmatter (AI 生成 md 常见, 评审 P1-7): 仅文件开头, 整块剥离
    text = _FRONTMATTER_RE.sub("", text)

    store: dict[str, str] = {}
    # Phase 1a: 围栏掩蔽 (行级状态机, 未闭合保守到尾)
    text = _mask_fences(text, store)
    # Phase 1b: 行内代码掩蔽 (干净内容剥反引号, 脏内容整体保留)
    text = "\n".join(_mask_inline_code(ln, store) for ln in text.split("\n"))

    # Phase 2+3: 逐行规则 (掩蔽 token 行不含 md 标记, 天然免疫)
    # 纯标记行整行过滤 (红线 1b), 不留空行残迹
    kept = (ln for ln in text.split("\n") if not _is_pure_marker_line(ln))
    text = "\n".join(_strip_line(ln) for ln in kept)

    # Phase 4: 空行规整 (掩蔽区已外置, 代码内部空行不受影响)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # 还原掩蔽区 (token 唯一, 顺序无关); 围栏内容自此暴露 — 单遍管线语义见红线 3
    for token, content in store.items():
        text = text.replace(token, content)
    return text
