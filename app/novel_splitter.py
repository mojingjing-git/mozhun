# Apache License 2.0 §4(b)/(c) 强制声明
# 本文件为小说分析器 (Copyright 2026 mojingjing-git, Apache-2.0) 的衍生作品
# 修改时间: 2026-09-13 | 修改方: 墨准项目 | 改动: 编码探测改用 app.utils.read_file_text,
#                                          移除 FastAPI 依赖, 适配 Bridge 接口,
#                                          save_split 改走 ~/.proofreader/novel_splits/{slug}/
# 修改清单: 见 CHANGELOG.md v5.2b
#
# 借鉴自 https://github.com/mojingjing-git/novel-analyzer (Apache-2.0)
# 借鉴内容: 章节/卷/特章识别 + 广告清理 + 相邻去重 + 超大章拆分 + 书名推断 +
#           Gutenberg 头截断 + staging 事务写法
# 借鉴方式: 思路与核心算法借鉴, 见 docs/THIRD_PARTY_NOTICES.md §22-A
# Copyright (c) 2026 mojingjing-git
#
# 思路借鉴自 https://github.com/zzk6780051/novel (MIT)
# 借鉴内容: 多格式章节正则(中文/阿拉伯/罗马/英文/特章) + 前 N 行打分 + MD5 相邻去重
# 借鉴方式: 思路借鉴, 无代码复制
# Copyright (c) zzk6780051
#
# 思路借鉴自 https://github.com/oomol-lab/txt-to-epub-converter (MIT)
# 借鉴内容: 卷/章/节 三层层级结构 + 章节最小/最大字数限制
# 借鉴方式: 思路借鉴, 无代码复制
# Copyright (c) oomol-lab

"""
app/novel_splitter.py — 小说切分核心 (v5.2b+)

第 8 视图「小说切分」业务核心. 纯函数 / dataclass, 0 GUI 依赖, 0 LLM 依赖, 0 异步.
与 app.punct_fix / app.md_strip / app.ai_score_local / app.harness 同层.

对外接口:
  - cn_to_int(s) -> Optional[int]: 中文数字 → int
  - _roman_to_int(s) -> Optional[int]: 罗马数字 → int
  - _word_to_int(s) -> Optional[int]: 英文数词 → int
  - preview_split(file_path, options) -> dict: 单本预览(不落盘)
  - save_split(file_path, book_name, options) -> dict: 切分落盘
  - infer_book_name(file_path) -> str: 从文件名推断书名
  - _book_name_to_slug(book_name) -> str: 书名 → 目录名 slug

模块组织 (按 docs/PLAN-splitter-v5.2b.md §5.1):
  L1-50   借鉴头 8 段
  L51-75  import + 模块常量
  L76-130 数据类 3 个
  L131-220 数字转换 3 个
  L221-240 编码读取 (修 C-1)
  L241-280 章节号抽取
  L281-360 卷层级 3 个
  L361-450 章节正则库 + 候选打分
  L451-520 元数据 3 个
  L521-720 Gutenberg 头截断 3 个
  L721-790 TOC 去重 + 广告常量
  L791-960 切分主函数 split_text
  L961-1050 广告清理 / 短章 / 超大 3 个
  L1051-1180 对外接口 3 个
  L1181-1240 路径 slug + 编码乱码检测
"""

# ==== 标准库 ====
import hashlib
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ==== 墨准内部 ====
# v5.2b (Critical C-1): 复用 app.utils.read_file_text (v4.1.8.2 E4 审计后版本),
# 不另写一份编码探测. 与 AGENTS §29/§32 双引擎零重复红线一致.
from app.utils import read_file_text, CONFIG_DIR
from app.logger import setup_logging

# 墨准约定 (web_backend.py:53 同构): 业务模块 import 时调用 setup_logging().
# 内部 _logger 缓存, 二次调用直接 return, 不重复创建 handler.
logger = setup_logging()


# ==== 模块级常量 ====

# v5.2b: novel_splits 目录与 checkpoints/ 同级, 走 CONFIG_DIR 共享 PROOFREADER_HOME 覆盖
NOVEL_SPLITS_DIR = CONFIG_DIR / "novel_splits"
try:
    NOVEL_SPLITS_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.error(f"novel_splits 目录创建失败: {NOVEL_SPLITS_DIR} — {e}")


# ---- 章节正则库 (13 种, 修 M-4 字段明确) ----
CHAPTER_PATTERNS: List[Tuple[str, str]] = [
    ("第X章(中文)", r"^第[零一二三四五六七八九十百千两万千亿\d]+章"),
    ("第X章(阿拉伯)", r"^第\d+章"),
    ("第X回", r"^第[零一二三四五六七八九十百千两万千亿\d]+回"),
    ("第X节", r"^第[零一二三四五六七八九十百千两万千亿\d]+节"),
    ("卷X第X章", r"^[上下中下零一二三四五六七八九十百千两万千亿\d]+卷.*第[零一二三四五六七八九十百千两万千亿\d]+[章节回]"),
    ("第一卷第一章", r"^第[零一二三四五六七八九十百千两万千亿\d]+卷\s*第[零一二三四五六七八九十百千两万千亿\d]+[章节回]"),
    ("卷一第一章", r"^[卷部篇][零一二三四五六七八九十百千两万千亿\d]+卷?\s*第[零一二三四五六七八九十百千两万千亿\d]+[章节回]"),
    ("英文Chapter", r"^chapter\s+\d+"),
    ("古典罗马章节", r"^[Cc]hapter\s+[IVXLCDM]+[\.\s:]?"),
    ("裸罗马短篇", r"^[IVXLCDM]+\.\s+[A-Z][A-Z\s,'\u2019\-:]{2,80}$"),
    ("裸罗马独行", r"^\s*(?:I{1,3}|IV|VI{0,3}|IX|X|XI{0,2}|XIV|XV|XIX|XX)\s*$"),
    ("数字点编号", r"^\d{1,4}[\.、]\s+[^A-Z\.]{1,40}"),
    ("数字点紧跟", r"^\d{1,4}[\.、][^A-Z\.]{1,40}"),
    ("中文数字顿号", r"^[零一二三四五六七八九十百千]+、"),
    ("括号章", r"^[\【\[]第[零一二三四五六七八九十百千两万千亿\d]+[章节回]"),
    ("特章(序/楔/番外/尾声…)", r"^(序章|序言|引子|引言|前言|楔子|后记|后序|尾声|终章|终幕|番外|外传|附录|彩蛋|特别篇|完本感言)"),
]

# ---- 卷 / 部 / 篇 标记 (5 种) ----
VOLUME_PATTERNS: List[Tuple[str, str]] = [
    ("第X卷", r"^第[零一二三四五六七八九十百千两万千亿\d]+[卷部篇]"),
    ("卷X", r"^[卷部篇][零一二三四五六七八九十百千两万千亿\d]+"),
    ("上下卷", r"^[上下中]+[卷部篇]"),
    ("英文卷", r"^(volume|book|part)\s+[\dIVXLC]+"),
    ("英文卷全", r"^[Bb]ook\s+(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|[IVXLCDM]+)[\.\s]?(?:--|\s|$)?"),
]

# ---- 广告/水印行 (强弱两级) ----
_AD_STRONG = [
    "求月票", "求收藏", "求推荐", "求订阅", "求票", "月票推荐票", "求评价票",
    "求鲜花", "投喂", "催更", "上架感言", "作者感言", "完本感言", "书友群",
    "读者群", "qq群", "q群", "公众号", "作者新书", "笔趣阁", "八一中文",
    "本章说", "防盗章", "防复制", "无弹窗", "最新章节", "章节错误", "请报告",
    "手机阅读", "本书首发", "更新最快", "请收藏", "天才一秒记住", "一秒记住",
    "txt下载", "全文阅读", "顶点小说", "思路客",
]
_AD_WEAK = [
    "月票", "推荐票", "打赏", "赏金", "感言", "微信", "下载", "新书",
    "ps：", "ps:", "p.s", "enjoyment",
]

# 路径 slug (修 M-3)
_SLUG_BAD_CHARS = re.compile(r'[\\/:*?"<>|《》]')
_SLUG_MAX_LEN = 100


# ==== 数字转换 ====

_CN_DIGIT_MAP = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "三": 3, "叁": 3,
    "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7,
    "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_CN_UNIT_MAP = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_BIG_UNIT = {"万": 10000, "亿": 100000000}


def cn_to_int(s: str) -> Optional[int]:
    """中文数字 → int. 失败返回 None.

    支持: 单位十/百/千/万/亿; 阿拉伯数字; 混合(一万零三百)
    失败: 空串 / 非数字 / 复杂单位(兆/京)
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None

    try:
        return int(s)
    except ValueError:
        pass

    total = 0
    current_section = 0
    current_num = 0
    last_is_digit = False

    for ch in s:
        if ch in _CN_DIGIT_MAP:
            current_num = _CN_DIGIT_MAP[ch]
            last_is_digit = True
        elif ch in _CN_UNIT_MAP:
            unit = _CN_UNIT_MAP[ch]
            if current_num == 0:
                current_section += unit
            else:
                current_section += current_num * unit
                current_num = 0
            last_is_digit = False
        elif ch in _CN_BIG_UNIT:
            big = _CN_BIG_UNIT[ch]
            total += (current_section + current_num) * big
            current_section = 0
            current_num = 0
            last_is_digit = False
        else:
            return None

    total += current_section + current_num
    if total == 0 and not last_is_digit:
        return None
    return total


_ROMAN_MAP = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAN_MAX = 3999


def _roman_to_int(s: str) -> Optional[int]:
    """罗马数字 → int. 失败返回 None. 上限 3999."""
    if not s:
        return None
    s = s.strip().upper()
    if not s or len(s) > 12:
        return None
    if not all(c in _ROMAN_MAP for c in s):
        return None
    total = 0
    prev = 0
    for ch in reversed(s):
        val = _ROMAN_MAP[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    if total > _ROMAN_MAX or total <= 0:
        return None
    return total


_WORD_TO_INT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _word_to_int(s: str) -> Optional[int]:
    """英文数词 → int. 失败返回 None."""
    if not s:
        return None
    s = s.strip().lower()
    if not s:
        return None
    s = s.replace("-", " ").replace(" and ", " ")
    parts = s.split()
    if not parts:
        return None

    total = 0
    current = 0
    for p in parts:
        if p in _WORD_TO_INT:
            v = _WORD_TO_INT[p]
            if v >= 20 and v < 100:
                current += v
            else:
                current += v
        else:
            return None
    total += current
    if total <= 0:
        return None
    return total


# ==== 编码读取 (修 C-1) ====


def _read_novel_text(file_path: Path) -> str:
    """读取小说文本.

    v5.2b (Critical C-1 修法):
      复用 app.utils.read_file_text (墨准 v4.1.8.2 审计 E4 修复),
      不另写一份编码探测逻辑. 顺带做行尾归一.
    """
    content = read_file_text(file_path)
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return content


# ==== 数据类 ====


@dataclass
class ChapterBlock:
    """单章数据."""
    index: int
    title: str
    content: str
    word_count: int
    volume: Optional[str] = None
    volume_index: Optional[int] = None
    num: Optional[int] = None
    is_special: bool = False


@dataclass
class SplitOptions:
    """切分选项. v5.2b (Major M-4 修法): 9 字段明确."""
    pattern: str = ""
    mode: str = "auto"  # auto / custom
    use_volume: bool = True
    min_words: int = 0
    merge_tiny: bool = False
    max_words: int = 0
    remove_ads: bool = False
    # 借鉴 v3.0+ 4 段标准借鉴头, strip_whitespace/scan_lines 硬编码不暴露前端
    strip_whitespace: bool = field(default=True, init=False, repr=False)
    scan_lines: int = field(default=800, init=False, repr=False)


@dataclass
class SplitResult:
    """切分结果. v5.2b (X-1 修法): 加 encoding_warning 字段."""
    chapters: List[ChapterBlock]
    total_chapters: int
    total_words: int
    total_volumes: int
    dedup_count: int
    detected_pattern: str
    pattern_name: str
    metadata: Dict[str, Any]
    stats: Dict[str, Any] = field(default_factory=dict)
    encoding_warning: Optional[str] = None


# ==== 章节号抽取 ====


def _extract_chapter_num(title: str) -> Optional[int]:
    """从章节标题中抽取阿拉伯数字章节号. 特章返回 None."""
    if not title:
        return None
    t = title.strip()

    m = re.search(r"第\s*([零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟\d]+)\s*[章回节集卷部篇]", t)
    if m:
        n = cn_to_int(m.group(1))
        if n is not None:
            return n

    m = re.search(r"(?:Chapter|CHAPTER|Ch\.?|Episode|Ep\.?)\s*([A-Za-z0-9]+)", t)
    if m:
        s = m.group(1)
        n = _roman_to_int(s) or _word_to_int(s) or cn_to_int(s)
        if n is not None:
            return n

    m = re.search(r"\b(\d+)\b", t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    return None


# ==== 卷层级 (3 函数) ====


def _compile_volume_patterns() -> List[re.Pattern]:
    return [re.compile(p, re.MULTILINE) for _, p in VOLUME_PATTERNS]


def _normalize_volume_label(line: str) -> Optional[str]:
    """从『第一卷 风起青萍』『第一卷第一章』『卷二』『Part I』『Book the First』等行里提取规范卷标签."""
    m = re.match(r"^(?:第)?\s*([零一二三四五六七八九十百千两万千亿\d]+)\s*([卷部篇])", line, re.IGNORECASE)
    if m:
        return f"第{m.group(1)}{m.group(2)}"
    m = re.match(r"^(卷|部|篇)\s*([零一二三四五六七八九十百千两万千亿\d]+)", line, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m = re.match(r"^([上下中])\s*([卷部篇])", line, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m = re.match(r"^(volume|book|part)\s+([\dIVXLC]+)", line, re.IGNORECASE)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.match(
        r"^[Bb]ook\s+(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)",
        line, re.IGNORECASE,
    )
    if m:
        word_to_roman = {
            "first": "I", "second": "II", "third": "III", "fourth": "IV",
            "fifth": "V", "sixth": "VI", "seventh": "VII", "eighth": "VIII",
            "ninth": "IX", "tenth": "X", "eleventh": "XI", "twelfth": "XII",
        }
        roman = word_to_roman[m.group(1).lower()]
        return f"Book {roman}"
    return None


def _is_volume_start(line: str) -> Optional[str]:
    """判断一行是否是卷起始行. 返回归一化卷标签 / None."""
    if "小说" in line or "连载" in line:
        return None
    for p in VOLUME_PATTERNS:
        rx = re.compile(p[1], re.MULTILINE | re.IGNORECASE)
        if re.match(p[1], line, re.IGNORECASE):
            return _normalize_volume_label(line) or line.strip()
    return None


# ==== 候选正则打分 (1 函数) ====


def _chapter_regex_for_mode(options: SplitOptions, lines: List[str]) -> Tuple[re.Pattern, str]:
    """返回 (compiled_regex, pattern_name).

    - pattern_name: 扫描前 N 行打分选出的「主导格式」(仅用于展示)
    - compiled_regex: 合并【所有】候选章节正则的主正则, 确保任意形态都能被识别

    P2-11 + G6 收口 (2026-08-24): 主导格式足够强时收窄为「主导 + 特章 + 达标次级」,
    次级入选双门槛: 绝对得分 ≥ 2 且得分 ≥ 主导的 15% (排掉高频噪声).
    """
    if options.mode == "custom" and options.pattern and options.pattern.strip():
        try:
            custom_rx = re.compile(options.pattern, re.MULTILINE)
        except re.error as e:
            logger.warning(f"自定义正则编译失败: {e}, 回退自动检测")
        else:
            sample = lines[: options.scan_lines]
            hits = sum(
                1 for ln in sample
                if ln.strip() and len(ln.strip()) <= 60 and custom_rx.match(ln.strip())
            )
            if hits > 0:
                return custom_rx, "自定义正则"
            logger.warning(
                f"自定义正则在前 {options.scan_lines} 行 0 命中 (pattern={options.pattern!r}), "
                f"回退自动检测")

    scores: Dict[str, int] = {}
    for name, pat in CHAPTER_PATTERNS:
        try:
            rx = re.compile(pat, re.MULTILINE | re.IGNORECASE)
        except re.error:
            continue
        score = 0
        for line in lines[: options.scan_lines]:
            s = line.strip()
            if not s or len(s) > 60:
                continue
            if rx.match(s):
                score += 1
        scores[name] = score

    best_name = max(scores, key=lambda k: scores[k]) if scores else ""
    pattern_name = best_name if best_name and scores[best_name] > 0 else "兜底第X章"

    special_patterns = [pat for name, pat in CHAPTER_PATTERNS if name.startswith("特章")]
    special_alt = "|".join(special_patterns)

    if best_name and scores[best_name] >= 5 and not best_name.startswith("特章"):
        _pat_by_name = {name: pat for name, pat in CHAPTER_PATTERNS}
        best_score = scores[best_name]
        combined = f"(?:{_pat_by_name[best_name]})"
        if special_alt:
            combined += f"|(?:{special_alt})"
        included_secondary = 0
        threshold = max(2, int(best_score * 0.15))
        for name, pat in CHAPTER_PATTERNS:
            if name == best_name or name.startswith("特章"):
                continue
            sc = scores.get(name, 0)
            if sc >= threshold:
                combined += f"|(?:{pat})"
                included_secondary += 1
        if included_secondary:
            logger.info(f"次级章节格式并入切分: {included_secondary} 种 (阈值≥{threshold})")
        return re.compile(combined, re.MULTILINE | re.IGNORECASE), pattern_name

    combined = "(" + ")|(".join(p for _, p in CHAPTER_PATTERNS) + ")"
    master = re.compile(combined, re.MULTILINE | re.IGNORECASE)
    return master, pattern_name


# ==== 元数据 (3 函数) ====


def _extract_metadata(
    lines: List[str],
    filename: str,
    external_title: str = "",
) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    if external_title:
        return {"title": external_title.strip(), "author": ""}
    for i, raw in enumerate(lines[:60]):
        line = raw.strip()
        if not line or len(line) > 120:
            continue
        if not meta.get("title"):
            m = re.search(r"[《]([^》]{1,40})[》]", line)
            if m:
                meta["title"] = m.group(1)
            elif i < 8 and not any(k in line for k in ("第", "章", "回", "卷", "Chapter")):
                meta["title"] = line
        if not meta.get("author"):
            m = re.search(r"(?:作者|著)\s*[:：]?\s*(.+)", line)
            if m:
                meta["author"] = m.group(1).strip()
    if not meta.get("title"):
        meta["title"] = filename
    return meta


def _extract_pg_header_meta(content: str) -> Dict[str, str]:
    """从 Gutenberg 头 (pre-START 段) 提取 Title/Author."""
    meta: Dict[str, str] = {}
    start_idx = content.find("*** START OF")
    pre_start = content[:start_idx] if start_idx != -1 else content[:2000]

    m = re.search(r"^Title:\s*(.+)$", pre_start, re.MULTILINE | re.IGNORECASE)
    if m:
        meta["title"] = m.group(1).strip()
    else:
        m = re.search(r"^The Project Gutenberg eBook of (.+?)\s*$",
                      pre_start, re.MULTILINE | re.IGNORECASE)
        if m:
            meta["title"] = m.group(1).strip()

    m = re.search(r"^Author:\s*(.+)$", pre_start, re.MULTILINE | re.IGNORECASE)
    if m:
        meta["author"] = m.group(1).strip()

    return meta


# ==== Gutenberg 头截断 (3 函数) ====


def _is_title_continuation(s: str) -> bool:
    """判断一行是否是章节标题的续行.

    启发式 (v2, 2026-09-02): 标题续行通常 ≤ 5 词、仅末尾 1 个句点、无段落标点.
    """
    if len(s) > 80:
        return False
    word_count = len(s.split())
    if word_count >= 6:
        return False
    if s.count(".") > 1:
        return False
    return True


def _find_first_real_chapter_or_volume(text: str) -> Optional[int]:
    """在 text 中找第一个有 body 紧随的章节/卷行 (区别于 TOC 条目).

    判定逻辑 (v2):
      - 候选章节/卷行之后的 12 行内 (跳过空行):
        - 出现 2 个连续的非空章节/卷标记 → 还在 TOC, 跳过
        - 出现非章节/卷 且非标题续行的"段落"内容 → 真章节/卷, OK
    """
    chapter_pats = [
        re.compile(r"^[Cc]hapter\s+[IVXLCDM\d]", re.IGNORECASE),
        re.compile(r"^[Bb]ook\s+(?:the\s+)?[A-ZIVX\d]", re.IGNORECASE),
        re.compile(r"^第[零一二三四五六七八九十百千两万千亿\d]+[章回节]"),
        re.compile(r"^第\d+章"),
        re.compile(r"^序章|^序言|^引子|^楔子|^正文"),
        re.compile(r"^[IVXLCDM]+\.\s+[A-Z][A-Z\s,'\u2019\-:]{2,80}$"),
        re.compile(r"^\s*(?:I{1,3}|IV|VI{0,3}|IX|X|XI{0,2}|XIV|XV|XIX|XX)\s*$"),
    ]
    lines = text.split("\n")
    max_scan = min(len(lines), 2000)
    for i in range(max_scan):
        s = lines[i].strip()
        if not s:
            continue
        is_candidate = any(rx.match(s) for rx in chapter_pats)
        if not is_candidate:
            continue
        body_found = False
        chapter_after_count = 0
        for j in range(i + 1, min(i + 13, len(lines))):
            ss = lines[j].strip()
            if not ss:
                continue
            is_cand_after = any(rx.match(ss) for rx in chapter_pats)
            if not is_cand_after:
                if not _is_title_continuation(ss):
                    body_found = True
                    break
                continue
            chapter_after_count += 1
            if chapter_after_count >= 2:
                break
        if body_found:
            return sum(len(l) + 1 for l in lines[:i])
    return None


def _strip_gutenberg_header(content: str) -> str:
    """Gutenberg 头截断 + TOC 块跳过.

    T2.5 (2026-09-02): 找到 '*** START OF PROJECT GUTENBERG' 标记后, 截掉到第一个真章节行.
    T2.5b: 在 START 后 100 行内识别 CONTENTS, 整块跳过后再找真章节.
    """
    start_idx = content.find("*** START OF")
    if start_idx == -1:
        return content

    after_start = content[start_idx:]
    nl = after_start.find("\n")
    after_start_no_start = after_start[nl + 1:] if nl != -1 else ""

    contents_m = re.search(
        r"^[\s]*(?:CONTENTS|Table of Contents)\s*$",
        after_start_no_start,
        re.MULTILINE | re.IGNORECASE,
    )
    if contents_m and after_start_no_start[: contents_m.start()].count("\n") <= 100:
        search_text = after_start_no_start[contents_m.end():]
    else:
        search_text = after_start_no_start

    real_offset = _find_first_real_chapter_or_volume(search_text)
    if real_offset is not None:
        return search_text[real_offset:]

    return search_text


# ==== TOC 去重 (1 函数) ====


def _dedup_same_key(blocks: List[ChapterBlock]) -> Tuple[List[ChapterBlock], int]:
    """同号去重: 同 (volume, num) 出现多次时, 仅删除字数 < 阈值的疑似 TOC 条目.

    保守策略:
      - 仅当某条 word_count < 1000 且同 key 存在 word_count >= 5000 的章节时才删
      - 所有同 key 章节字数都 < 1000 → 一律保留
      - 所有同 key 章节字数都 >= 1000 → 一律保留
    """
    if not blocks:
        return blocks, 0
    groups: Dict[Tuple, List[int]] = {}
    for i, blk in enumerate(blocks):
        key = (blk.volume, blk.num)
        groups.setdefault(key, []).append(i)
    to_remove: set = set()
    TOC_THRESHOLD = 1000
    REAL_THRESHOLD = 5000
    for key, indices in groups.items():
        if len(indices) <= 1:
            continue
        real_indices = [i for i in indices if blocks[i].word_count >= REAL_THRESHOLD]
        if not real_indices:
            continue
        for i in indices:
            if blocks[i].word_count < TOC_THRESHOLD:
                to_remove.add(i)
    new_blocks = [b for i, b in enumerate(blocks) if i not in to_remove]
    return new_blocks, len(to_remove)


# ==== 切分主函数 split_text ====


def split_text(
    content: str,
    options: Optional[SplitOptions] = None,
    external_title: str = "",
) -> SplitResult:
    """核心切分. 返回 SplitResult."""
    if options is None:
        options = SplitOptions()

    # T2.7: 先从 pre-START 头提取 Title/Author (必须在截断前)
    pg_meta = _extract_pg_header_meta(content)
    # T2.5 + T2.5b: Gutenberg 头截断 + TOC 跳过
    content = _strip_gutenberg_header(content)
    lines = content.split("\n")

    chapter_rx, pattern_name = _chapter_regex_for_mode(options, lines)
    volume_rxs = _compile_volume_patterns() if options.use_volume else []

    # 第一遍: 定位所有「章/卷」起始行
    raw_blocks: List[Dict[str, Any]] = []
    current_volume: Optional[str] = None
    current_volume_index = 0
    preamble_lines: List[str] = []

    for idx, raw in enumerate(lines):
        s = raw.strip()
        if volume_rxs:
            vol = _is_volume_start(s)
            if vol:
                if not re.search(r"[章回节]$", s):
                    current_volume = vol
                    current_volume_index += 1
                    continue
        if chapter_rx.match(s) and 0 < len(s) <= 80:
            vol_label = _normalize_volume_label(s)
            if vol_label and vol_label != current_volume:
                current_volume = vol_label
                current_volume_index += 1
            title = s
            raw_blocks.append({
                "title": title,
                "start": idx + 1,
                "volume": current_volume,
                "volume_index": current_volume_index,
            })

    if not raw_blocks:
        text = content.strip() if options.strip_whitespace else content
        block = ChapterBlock(1, "全文", text, len(text))
        return SplitResult(
            chapters=[block], total_chapters=1, total_words=len(text),
            total_volumes=0, dedup_count=0,
            metadata=_extract_metadata(lines, "", external_title),
            detected_pattern=chapter_rx.pattern, pattern_name=pattern_name,
        )

    # 第二遍: 切出每块正文
    blocks: List[ChapterBlock] = []
    for i, b in enumerate(raw_blocks):
        end = raw_blocks[i + 1]["start"] - 1 if i + 1 < len(raw_blocks) else len(lines)
        body_lines = lines[b["start"]:end]
        if options.remove_ads:
            body_lines = [ln for ln in body_lines if not _is_ad_line(ln)]
        body = "\n".join(body_lines)
        if options.strip_whitespace:
            body = body.strip()
        title = b["title"]
        num = _extract_chapter_num(title)
        block = ChapterBlock(
            index=0,
            title=title,
            content=(title + "\n" + body) if body else title,
            word_count=len(body),
            volume=b["volume"],
            volume_index=b["volume_index"],
            num=num,
        )
        blocks.append(block)

    # 正文开头 (第一个章节之前的内容) 拼到首章
    if raw_blocks and raw_blocks[0]["start"] > 0:
        pre = "\n".join(lines[: raw_blocks[0]["start"]])
        if options.remove_ads:
            pre_lines = [ln for ln in pre.split("\n") if not _is_ad_line(ln)]
            pre = "\n".join(pre_lines)
        pre = pre.strip() if options.strip_whitespace else pre
        if pre:
            first = blocks[0]
            first.content = pre + "\n\n" + first.content
            first.word_count = len(first.content) - len(first.title)

    # 相邻去重 (MD5)
    deduped: List[ChapterBlock] = []
    prev_hash: Optional[str] = None
    dedup_count = 0
    for blk in blocks:
        h = hashlib.md5(blk.content.encode("utf-8")).hexdigest()
        if h == prev_hash:
            dedup_count += 1
            continue
        prev_hash = h
        deduped.append(blk)
    blocks = deduped

    # T2.5b: 同号去重
    blocks, same_key_dedup = _dedup_same_key(blocks)
    dedup_count += same_key_dedup

    # 最小字数: 跳过 or 合并短章
    if options.min_words > 0:
        pre_filter_count = len(blocks)
        if options.merge_tiny:
            blocks = _merge_tiny(blocks, options.min_words)
        else:
            blocks = [b for b in blocks if b.word_count >= options.min_words or b.num is None]
        if len(blocks) < 5 and pre_filter_count >= 5:
            raise ValueError(
                f"min_words={options.min_words} 过高：切出 {pre_filter_count} 个章节，"
                f"过滤后仅剩 {len(blocks)} 个（阈值过滤了 {pre_filter_count - len(blocks)} 个）。"
                f"网文章节通常 2000-5000 字，建议把 min_words 调到 200-500，"
                f"或设为 0 不过滤。")

    # 超大章自动拆分
    if options.max_words > 0:
        blocks = _split_oversized(blocks, options.max_words)

    # 重新编号
    for i, b in enumerate(blocks, start=1):
        b.index = i

    # 统计
    counts = [b.word_count for b in blocks] or [0]
    counts_sorted = sorted(counts)
    stats = {
        "avg": sum(counts) // len(counts),
        "min": min(counts),
        "max": max(counts),
        "median": counts_sorted[len(counts_sorted) // 2],
    }
    volumes = sorted({b.volume for b in blocks if b.volume})

    # T2.7: pre-START 提取的 Title/Author 优先覆盖
    metadata = _extract_metadata(lines, "", external_title)
    for k, v in pg_meta.items():
        if v:
            metadata[k] = v

    return SplitResult(
        chapters=blocks,
        total_chapters=len(blocks),
        total_words=sum(counts),
        total_volumes=len(volumes),
        dedup_count=dedup_count,
        detected_pattern=chapter_rx.pattern,
        pattern_name=pattern_name,
        metadata=metadata,
        stats=stats,
    )


# ==== 广告清理 / 短章 / 超大 (3 函数) ====


def _is_ad_line(line: str) -> bool:
    """判断一行是否是广告/水印行."""
    s = line.strip().lower()
    if not s:
        return False
    if len(s) > 200:
        return False
    if any(k in s for k in _AD_STRONG):
        return True
    if any(k in s for k in _AD_WEAK):
        return len(s) <= 40 and not any(p in s for p in "，。！？；：,;!?")
    return False


def _merge_tiny(blocks: List[ChapterBlock], min_words: int) -> List[ChapterBlock]:
    """把短于 min_words 的章合并进下一章 (末尾则并入上一章)."""
    merged: List[ChapterBlock] = []
    for blk in blocks:
        if blk.word_count < min_words and blk.num is not None:
            if merged:
                prev = merged[-1]
                prev.content += "\n\n" + blk.content
                prev.word_count = len(prev.content) - len(prev.title)
            else:
                merged.append(blk)
        else:
            merged.append(blk)
    if len(merged) >= 2 and merged[-1].word_count < min_words:
        last = merged.pop()
        merged[-1].content += "\n\n" + last.content
        merged[-1].word_count = len(merged[-1].content) - len(merged[-1].title)
    return merged


def _split_oversized(blocks: List[ChapterBlock], max_words: int) -> List[ChapterBlock]:
    """把超过 max_words 的章按段落拆成多块, 标题加 (n/m) 后缀."""
    out: List[ChapterBlock] = []
    for blk in blocks:
        if blk.word_count <= max_words:
            out.append(blk)
            continue
        parts = blk.content.split("\n", 1)
        title_line = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        paragraphs = body.split("\n") if body else [""]

        norm_paras: List[str] = []
        for p in paragraphs:
            if len(p) > max_words:
                for i in range(0, len(p), max_words):
                    norm_paras.append(p[i:i + max_words])
            else:
                norm_paras.append(p)

        chunks: List[List[str]] = [[]]
        size = 0
        for p in norm_paras:
            if size + len(p) + 1 > max_words and chunks[-1]:
                chunks.append([])
                size = 0
            chunks[-1].append(p)
            size += len(p) + 1

        if len(chunks) > 1:
            last_len = sum(len(p) for p in chunks[-1])
            if last_len < max(200, max_words // 10):
                chunks[-2].extend(chunks[-1])
                chunks.pop()

        total = len(chunks)
        for i, ch in enumerate(chunks, start=1):
            suffix = f" ({i}/{total})" if total > 1 else ""
            text = (title_line + suffix + "\n" + "\n".join(ch)) if ch else (title_line + suffix)
            out.append(ChapterBlock(
                index=0,
                title=blk.title + suffix,
                content=text,
                word_count=len(text),
                volume=blk.volume,
                volume_index=blk.volume_index,
                num=blk.num,
            ))
    return out


# ==== 对外接口 (3 函数) ====


def preview_split(
    file_path: Path,
    options: Optional[SplitOptions] = None,
    preview_count: int = 50,
) -> Dict[str, Any]:
    """单本预览切分 (不落盘)."""
    if options is None:
        options = SplitOptions()
    content = _read_novel_text(file_path)
    encoding_warn = _check_encoding_warning(file_path)
    result = split_text(content, options)
    if encoding_warn:
        result.encoding_warning = encoding_warn
    preview_blocks = result.chapters[:preview_count]
    return {
        "chapters": [
            {
                "index": b.index,
                "title": b.title,
                "word_count": b.word_count,
                "volume": b.volume,
                "num": b.num,
            }
            for b in preview_blocks
        ],
        "total_chapters": result.total_chapters,
        "total_words": result.total_words,
        "total_volumes": result.total_volumes,
        "dedup_count": result.dedup_count,
        "detected_pattern": result.detected_pattern,
        "pattern_name": result.pattern_name,
        "metadata": result.metadata,
        "stats": result.stats,
        "preview_count": len(preview_blocks),
        "encoding_warning": result.encoding_warning,
    }


def save_split(
    file_path: Path,
    output_dir: Path,
    options: Optional[SplitOptions] = None,
    external_title: str = "",
) -> Dict[str, Any]:
    """切分并保存到 output_dir/blocks/.

    X-2 (staging 事务保护, 2026-08-24): 先全部暂存到 _split_staging, 全部成功后才清理旧章并交换.
    避免中途任一写入失败留下"旧章已删、新章残缺、chapters.json 还指向已删除文件"的不一致状态.
    """
    if options is None:
        options = SplitOptions()
    content = _read_novel_text(file_path)
    encoding_warn = _check_encoding_warning(file_path)
    result = split_text(content, options, external_title=external_title)
    if encoding_warn:
        result.encoding_warning = encoding_warn
    output_dir.mkdir(parents=True, exist_ok=True)

    chapters = result.chapters
    if chapters:
        staging_dir = output_dir / "_split_staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True)
        try:
            import os as _os
            max_workers = min(32, (_os.cpu_count() or 4) + 4)

            def _stage(b):
                (staging_dir / f"{b.index:04d}.txt").write_text(b.content, encoding="utf-8")

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                list(ex.map(_stage, chapters))
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        for stale in output_dir.glob("*.txt"):
            stem = stale.name[:-4]
            if stem.isdigit():
                try:
                    stale.unlink()
                except OSError:
                    pass
        for staged in sorted(staging_dir.iterdir()):
            import os as _os
            _os.replace(staged, output_dir / staged.name)
        shutil.rmtree(staging_dir, ignore_errors=True)

    chapters_json = [
        {
            "index": b.index,
            "title": b.title,
            "word_count": b.word_count,
            "volume": b.volume,
            "num": b.num,
        }
        for b in result.chapters
    ]
    (output_dir / "chapters.json").write_text(
        json.dumps(chapters_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "metadata.json").write_text(
        json.dumps(result.metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines_report = [
        f"书名: {result.metadata.get('title', '')}",
        f"作者: {result.metadata.get('author', '')}",
        f"检测正则: {result.pattern_name}  ({result.detected_pattern})",
        f"总章节数: {result.total_chapters}",
        f"总卷数: {result.total_volumes}",
        f"总字数: {result.total_words}",
        f"去重章节数: {result.dedup_count}",
        f"字数统计: 平均 {result.stats.get('avg')} / 最小 {result.stats.get('min')} / 最大 {result.stats.get('max')} / 中位 {result.stats.get('median')}",
        "章节列表:",
    ]
    for b in result.chapters:
        vol = f"[{b.volume}] " if b.volume else ""
        lines_report.append(f"{b.index:04d}. {vol}{b.title} ({b.word_count} 字)")
    (output_dir / "split_report.txt").write_text(
        "\n".join(lines_report), encoding="utf-8"
    )

    logger.info(f"切分完成: {output_dir} ({result.total_chapters} 章)")
    return {
        "saved": True,
        "output_dir": output_dir.as_posix(),
        "total_chapters": result.total_chapters,
        "total_words": result.total_words,
        "total_volumes": result.total_volumes,
        "dedup_count": result.dedup_count,
        "encoding_warning": result.encoding_warning,
    }


def infer_book_name(file_path: Path) -> str:
    """从文件名推断书名.

    P5 + P5b (2026-08-27): 优先截取《...》作为书名; 截不到时回退到通用 regex 剥离版本后缀.

    真实案例: 《从姑获鸟开始》（精校版）.txt → 《从姑获鸟开始》
              《《大王饶命》》（精校版）.txt → 《大王饶命》(最内层)
    """
    name = file_path.stem
    for open_q, close_q in [("《", "》"), ("<", ">")]:
        m = re.search(rf"{re.escape(open_q)}+([^《》<>]{{1,80}}){re.escape(close_q)}+", name)
        if m:
            return f"{open_q}{m.group(1)}{close_q}"

    _VERSION_SUFFIX_RE = re.compile(
        r"[\s\-_.]*"
        r"[\(（]?"
        r"(?:"
        r"校对版全本|校对版|完整版|精校版|精修版|"
        r"典藏版|完结版|最终版|高清版|校对后|全本|完"
        r")"
        r"[\)）]?"
        r"$"
    )
    name = _VERSION_SUFFIX_RE.sub("", name).strip()

    for suffix in ["_分析报告", "_分析", "-分析报告"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()


# ==== 路径 slug (修 M-3) ====


def _book_name_to_slug(book_name: str) -> str:
    """书名 → 目录名. 移除 Windows 特殊字符 + 长度截断.

    v5.2b (Major M-3 修法): 避免《》等 Windows 路径兼容隐患.
    落盘路径用 slug, chapters.json / metadata.json 保留 book_name_display (含《》).
    """
    slug = _SLUG_BAD_CHARS.sub('_', book_name).strip('_').strip()
    if len(slug) > _SLUG_MAX_LEN:
        slug = slug[:_SLUG_MAX_LEN].rstrip('_')
    return slug or "未命名"


# ==== 编码乱码检测 (X-1) ====


def _check_encoding_warning(file_path: Path) -> Optional[str]:
    """检测文件是否可能是乱码. 返回警告字符串 / None.

    启发式: 文本含大量替换字符 (U+FFFD) 视为乱码.
    """
    try:
        text = _read_novel_text(file_path)
        if not text:
            return "文件为空"
        total_chars = len(text)
        if total_chars == 0:
            return "文件为空"
        replace_count = text.count("\ufffd")
        ratio = replace_count / total_chars
        if ratio > 0.01:
            return f"文件可能存在编码问题 (替换字符占 {ratio:.2%})"
        return None
    except Exception as e:
        return f"读取异常: {type(e).__name__}: {e}"


# ==== 调试 / 自测入口 ====


if __name__ == "__main__":
    # 数字转换自测
    print("cn_to_int 测试:")
    cases = [
        ("一", 1), ("十", 10), ("十二", 12), ("二十", 20),
        ("一百", 100), ("一千零一", 1001), ("一万", 10000),
        ("一亿二千万", 120000000), ("一百二十三", 123),
        ("", None), ("abc", None), ("1", 1), ("123", 123),
    ]
    for s, expected in cases:
        got = cn_to_int(s)
        ok = "✓" if got == expected else "✗"
        print(f"  {ok} cn_to_int({s!r}) = {got} (expected {expected})")

    print("\n_roman_to_int 测试:")
    cases = [
        ("I", 1), ("II", 2), ("III", 3), ("IV", 4), ("V", 5),
        ("VIII", 8), ("IX", 9), ("X", 10), ("XXII", 22), ("XLII", 42),
        ("", None), ("i", 1), ("IIII", 4), ("ABC", None),
    ]
    for s, expected in cases:
        got = _roman_to_int(s)
        ok = "✓" if got == expected else "✗"
        print(f"  {ok} _roman_to_int({s!r}) = {got} (expected {expected})")

    print("\n_word_to_int 测试:")
    cases = [
        ("one", 1), ("ten", 10), ("twenty-one", 21), ("twenty one", 21),
        ("ninety-nine", 99), ("", None), ("abc", None), ("fifty", 50),
    ]
    for s, expected in cases:
        got = _word_to_int(s)
        ok = "✓" if got == expected else "✗"
        print(f"  {ok} _word_to_int({s!r}) = {got} (expected {expected})")
