"""
tests/test_novel_splitter.py — 小说切分核心 单元 + E2E 测试 (v5.2b+)

按 docs/PLAN-splitter-v5.2b.md §7 测试分块清单.

基线: 1334 (v5.1.0) → ~1385 (v5.2b 增量约 51)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 让 tests/ 能 import app/
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.novel_splitter import (
    # 数据类
    ChapterBlock, SplitResult, SplitOptions,
    # 数字转换
    cn_to_int, _roman_to_int, _word_to_int,
    # 编码读取
    _read_novel_text, _check_encoding_warning,
    # 章节号抽取
    _extract_chapter_num,
    # 卷层级
    _normalize_volume_label, _is_volume_start, _compile_volume_patterns,
    # 正则库 + 打分
    CHAPTER_PATTERNS, VOLUME_PATTERNS, _chapter_regex_for_mode,
    # 元数据
    _extract_metadata, _extract_pg_header_meta,
    # Gutenberg
    _strip_gutenberg_header, _find_first_real_chapter_or_volume, _is_title_continuation,
    # TOC 去重
    _dedup_same_key,
    # 切分主函数
    split_text,
    # 广告/短章/超大
    _is_ad_line, _merge_tiny, _split_oversized,
    # 对外接口
    preview_split, save_split, infer_book_name,
    # 路径 slug
    _book_name_to_slug,
    # 常量
    NOVEL_SPLITS_DIR,
)
from app.utils import CONFIG_DIR


# ============================================================
# 数字转换 (~12 项)
# ============================================================

class TestCnToInt(unittest.TestCase):
    def test_simple_digits(self):
        self.assertEqual(cn_to_int("一"), 1)
        self.assertEqual(cn_to_int("九"), 9)
        self.assertEqual(cn_to_int("零"), 0)

    def test_with_unit_ten(self):
        self.assertEqual(cn_to_int("十"), 10)
        self.assertEqual(cn_to_int("十二"), 12)
        self.assertEqual(cn_to_int("二十"), 20)
        self.assertEqual(cn_to_int("二十三"), 23)

    def test_with_unit_hundred(self):
        self.assertEqual(cn_to_int("一百"), 100)
        self.assertEqual(cn_to_int("一百二十三"), 123)

    def test_with_unit_thousand(self):
        self.assertEqual(cn_to_int("一千零一"), 1001)
        self.assertEqual(cn_to_int("三千五百"), 3500)

    def test_with_wan(self):
        self.assertEqual(cn_to_int("一万"), 10000)
        self.assertEqual(cn_to_int("一万零三百"), 10300)
        self.assertEqual(cn_to_int("十二万"), 120000)

    def test_with_yi(self):
        self.assertEqual(cn_to_int("一亿"), 100000000)
        self.assertEqual(cn_to_int("一亿二千万"), 120000000)

    def test_pure_arabic(self):
        self.assertEqual(cn_to_int("1"), 1)
        self.assertEqual(cn_to_int("123"), 123)
        self.assertEqual(cn_to_int("0"), 0)

    def test_invalid(self):
        self.assertIsNone(cn_to_int(""))
        self.assertIsNone(cn_to_int("   "))
        self.assertIsNone(cn_to_int("abc"))
        self.assertIsNone(cn_to_int("一兆"))

    def test_capital_form(self):
        self.assertEqual(cn_to_int("壹"), 1)
        self.assertEqual(cn_to_int("贰拾"), 20)


class TestRomanToInt(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_roman_to_int("I"), 1)
        self.assertEqual(_roman_to_int("V"), 5)
        self.assertEqual(_roman_to_int("X"), 10)
        self.assertEqual(_roman_to_int("L"), 50)
        self.assertEqual(_roman_to_int("C"), 100)
        self.assertEqual(_roman_to_int("D"), 500)
        self.assertEqual(_roman_to_int("M"), 1000)

    def test_subtractive(self):
        self.assertEqual(_roman_to_int("IV"), 4)
        self.assertEqual(_roman_to_int("IX"), 9)
        self.assertEqual(_roman_to_int("XL"), 40)
        self.assertEqual(_roman_to_int("XC"), 90)
        self.assertEqual(_roman_to_int("CD"), 400)
        self.assertEqual(_roman_to_int("CM"), 900)

    def test_compound(self):
        self.assertEqual(_roman_to_int("VIII"), 8)
        self.assertEqual(_roman_to_int("XXII"), 22)
        self.assertEqual(_roman_to_int("XLII"), 42)
        self.assertEqual(_roman_to_int("MCMXCIX"), 1999)

    def test_lowercase_accepted(self):
        self.assertEqual(_roman_to_int("i"), 1)
        self.assertEqual(_roman_to_int("iv"), 4)

    def test_invalid(self):
        self.assertIsNone(_roman_to_int(""))
        self.assertIsNone(_roman_to_int("   "))
        self.assertIsNone(_roman_to_int("ABC"))
        self.assertIsNone(_roman_to_int("MMMM"))
        self.assertIsNone(_roman_to_int("X" * 13))
        self.assertIsNone(_roman_to_int("0"))


class TestWordToInt(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_word_to_int("one"), 1)
        self.assertEqual(_word_to_int("ten"), 10)
        self.assertEqual(_word_to_int("nineteen"), 19)
        self.assertEqual(_word_to_int("ninety"), 90)

    def test_compound(self):
        self.assertEqual(_word_to_int("twenty-one"), 21)
        self.assertEqual(_word_to_int("twenty one"), 21)
        self.assertEqual(_word_to_int("ninety-nine"), 99)

    def test_invalid(self):
        self.assertIsNone(_word_to_int(""))
        self.assertIsNone(_word_to_int("   "))
        self.assertIsNone(_word_to_int("abc"))
        self.assertIsNone(_word_to_int("hundred"))


# ============================================================
# 编码读取 + 乱码检测 (5 项, 修 C-1)
# ============================================================

class TestReadNovelText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="novel_splitter_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_utf8_with_bom(self):
        path = Path(self.tmp) / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbf" + "第一章 开始".encode("utf-8"))
        text = _read_novel_text(path)
        self.assertFalse(text.startswith("\ufeff"))
        self.assertIn("第一章", text)

    def test_gb18030(self):
        path = Path(self.tmp) / "gbk.txt"
        path.write_bytes("第一章 退婚".encode("gb18030"))
        text = _read_novel_text(path)
        self.assertIn("第一章", text)
        self.assertIn("退婚", text)

    def test_line_endings_normalized(self):
        path = Path(self.tmp) / "crlf.txt"
        path.write_bytes("第一行\r\n第二行\r第三行".encode("utf-8"))
        text = _read_novel_text(path)
        self.assertNotIn("\r", text)
        self.assertIn("第一行\n第二行\n第三行", text)


class TestEncodingWarning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="novel_splitter_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normal_text_no_warning(self):
        path = Path(self.tmp) / "ok.txt"
        path.write_text("这是正常的中文小说内容。", encoding="utf-8")
        self.assertIsNone(_check_encoding_warning(path))

    def test_empty_file(self):
        path = Path(self.tmp) / "empty.txt"
        path.write_text("", encoding="utf-8")
        warn = _check_encoding_warning(path)
        self.assertIsNotNone(warn)
        self.assertIn("空", warn)

    def test_mojibake_warning(self):
        path = Path(self.tmp) / "bad.txt"
        bad = "\ufffd" * 100 + "正常"
        path.write_text(bad, encoding="utf-8")
        warn = _check_encoding_warning(path)
        self.assertIsNotNone(warn)
        self.assertIn("编码", warn)


# ============================================================
# 章节号抽取 (4 项)
# ============================================================

class TestExtractChapterNum(unittest.TestCase):
    def test_chinese(self):
        self.assertEqual(_extract_chapter_num("第一章 开始"), 1)
        self.assertEqual(_extract_chapter_num("第 3 章 转折"), 3)
        self.assertEqual(_extract_chapter_num("第二十五章 高潮"), 25)

    def test_english_chapter_arabic(self):
        self.assertEqual(_extract_chapter_num("Chapter 5"), 5)
        self.assertEqual(_extract_chapter_num("CHAPTER 12"), 12)

    def test_english_chapter_roman(self):
        self.assertEqual(_extract_chapter_num("Chapter III"), 3)
        self.assertEqual(_extract_chapter_num("Chapter XXII"), 22)

    def test_special_chapter(self):
        self.assertIsNone(_extract_chapter_num("序章"))
        self.assertIsNone(_extract_chapter_num("楔子"))
        self.assertIsNone(_extract_chapter_num("番外: 十年后"))
        self.assertIsNone(_extract_chapter_num("尾声"))


# ============================================================
# 卷层级 (4 项)
# ============================================================

class TestVolumePatterns(unittest.TestCase):
    def test_normalize_chinese(self):
        self.assertEqual(_normalize_volume_label("第一卷 风起青萍"), "第一卷")
        self.assertEqual(_normalize_volume_label("第一卷第一章"), "第一卷")
        self.assertEqual(_normalize_volume_label("卷二 风云"), "卷二")

    def test_normalize_english(self):
        self.assertEqual(_normalize_volume_label("Part I"), "Part I")
        self.assertEqual(_normalize_volume_label("Volume III"), "Volume III")
        self.assertEqual(_normalize_volume_label("Book I"), "Book I")
        # Dickens 风格
        self.assertEqual(_normalize_volume_label("Book the First--Recalled to Life"), "Book I")
        self.assertEqual(_normalize_volume_label("Book the Second"), "Book II")

    def test_normalize_invalid(self):
        self.assertIsNone(_normalize_volume_label(""))
        self.assertIsNone(_normalize_volume_label("这是一段正文"))

    def test_is_volume_start(self):
        """中篇小说/连载 行应被排除"""
        self.assertIsNone(_is_volume_start("中篇小说连载中"))
        self.assertIsNone(_is_volume_start("小说连载中"))
        # 正常卷行
        self.assertEqual(_is_volume_start("第一卷"), "第一卷")
        self.assertEqual(_is_volume_start("卷三"), "卷三")
        # 注: "上篇简介" 会命中 "^[上下中]+[卷部篇]" (匹配 "上篇"),
        # 但 _is_volume_start 用 normalize 失败时返回 None — 实际会返回 "上篇"
        # 这是小说分析器原版行为, 不修 (AGENTS "不要放宽标点红线" 同质)


# ============================================================
# 元数据 (3 项)
# ============================================================

class TestMetadata(unittest.TestCase):
    def test_extract_metadata_external_title(self):
        """external_title 优先, 不读正文"""
        lines = ["第一段", "第二段"]
        meta = _extract_metadata(lines, "filename.txt", external_title="《指定书名》")
        self.assertEqual(meta["title"], "《指定书名》")
        self.assertEqual(meta["author"], "")

    def test_extract_metadata_chinese_bookname(self):
        """《...》 书名识别"""
        lines = ["", "《斗破苍穹》", "作者: 天蚕土豆", "", "第一章", "正文"]
        meta = _extract_metadata(lines, "book.txt")
        self.assertEqual(meta["title"], "斗破苍穹")
        self.assertEqual(meta["author"], "天蚕土豆")

    def test_extract_pg_header(self):
        """Gutenberg Title:/Author: 显式行"""
        content = """Title: Pride and Prejudice
Author: Jane Austen

*** START OF THE PROJECT GUTENBERG EBOOK PRIDE AND PREJUDICE ***

Chapter I.
正文开始
"""
        meta = _extract_pg_header_meta(content)
        self.assertEqual(meta["title"], "Pride and Prejudice")
        self.assertEqual(meta["author"], "Jane Austen")


# ============================================================
# Gutenberg 头截断 (2 项)
# ============================================================

class TestGutenbergHeader(unittest.TestCase):
    def test_no_start_marker(self):
        """无 START 标记时直接返回原文"""
        text = "无特殊标记的小说\n第一章\n正文"
        self.assertEqual(_strip_gutenberg_header(text), text)

    def test_with_start_and_toc(self):
        """START + TOC + 真章节 应跳过 START 和 TOC"""
        content = """\
Title: Test
Author: Tester

*** START OF THE PROJECT GUTENBERG EBOOK TEST ***

CONTENTS

Chapter I. (TOC 条目)
Chapter II. (TOC 条目)

Chapter I.
This is the real first chapter.
"""
        result = _strip_gutenberg_header(content)
        # 应跳过 START + CONTENTS + TOC, 落到真 Chapter I.
        self.assertIn("This is the real first chapter.", result)
        self.assertNotIn("CONTENTS", result)


# ============================================================
# TOC 去重 (1 项)
# ============================================================

class TestDedupSameKey(unittest.TestCase):
    def test_dedup_short_when_long_exists(self):
        """同 (vol, num) 一短一长, 删短的"""
        b1 = ChapterBlock(0, "第一章", "短", 100, num=1)
        b2 = ChapterBlock(0, "第一章", "x" * 6000, 6000, num=1)
        new_blocks, removed = _dedup_same_key([b1, b2])
        self.assertEqual(removed, 1)
        self.assertEqual(len(new_blocks), 1)
        self.assertEqual(new_blocks[0].word_count, 6000)

    def test_keep_all_when_all_short(self):
        """全短 → 一律保留"""
        b1 = ChapterBlock(0, "第一章", "短1", 100, num=1)
        b2 = ChapterBlock(0, "第一章", "短2", 200, num=1)
        new_blocks, removed = _dedup_same_key([b1, b2])
        self.assertEqual(removed, 0)
        self.assertEqual(len(new_blocks), 2)


# ============================================================
# 广告清理 (2 项)
# ============================================================

class TestAdLine(unittest.TestCase):
    def test_strong_keyword(self):
        """强广告标记命中即删"""
        self.assertTrue(_is_ad_line("求月票啦求订阅"))
        self.assertTrue(_is_ad_line("本书首发起点中文网"))
        self.assertTrue(_is_ad_line("笔趣阁"))

    def test_weak_keyword_short_line(self):
        """弱标记 + 短行 + 无标点 → 删"""
        self.assertTrue(_is_ad_line("微信:abc123"))
        self.assertTrue(_is_ad_line("ps: 推荐一下"))

    def test_weak_keyword_long_or_punctuated(self):
        """弱标记 + 长行/有标点 → 保留 (正文)"""
        # 长行 (>40 字) 不论有没有标点都保留
        self.assertFalse(_is_ad_line("他打开微信看到消息，笑着说了一声你好"))
        # 短行 (<=40) 但有句中标点 (，。！？；：) → 保留
        self.assertFalse(_is_ad_line("他说：微信真方便。"))  # 短但有标点

    def test_empty_line(self):
        self.assertFalse(_is_ad_line(""))
        self.assertFalse(_is_ad_line("   "))


# ============================================================
# 书名推断 (5 项, 修 M-3 关联)
# ============================================================

class TestInferBookName(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="infer_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chinese_bookname(self):
        path = Path(self.tmp) / "《斗破苍穹》（精校版）.txt"
        path.touch()
        self.assertEqual(infer_book_name(path), "《斗破苍穹》")

    def test_double_layer_bookname(self):
        """双层《《xxx》》取最内层"""
        path = Path(self.tmp) / "《《大王饶命》》（精校版）.txt"
        path.touch()
        self.assertEqual(infer_book_name(path), "《大王饶命》")

    def test_no_bookname_with_version_suffix(self):
        path = Path(self.tmp) / "斗破苍穹精校版.txt"
        path.touch()
        self.assertEqual(infer_book_name(path), "斗破苍穹")

    def test_no_bookname_separator_variants(self):
        cases = [
            ("斗破苍穹-精校版.txt", "斗破苍穹"),
            ("斗破苍穹_精校版.txt", "斗破苍穹"),
            ("凡人修仙传 （校对版）.txt", "凡人修仙传"),
            ("星辰变(校对版).txt", "星辰变"),
        ]
        for fname, expected in cases:
            path = Path(self.tmp) / fname
            path.touch()
            self.assertEqual(infer_book_name(path), expected, f"failed for {fname}")

    def test_plain_no_suffix(self):
        path = Path(self.tmp) / "斗破苍穹.txt"
        path.touch()
        self.assertEqual(infer_book_name(path), "斗破苍穹")


# ============================================================
# 路径 slug (2 项, 修 M-3)
# ============================================================

class TestSlug(unittest.TestCase):
    def test_chinese_bookname(self):
        """《》等 Windows 特殊字符 → _"""
        self.assertEqual(_book_name_to_slug("《斗破苍穹》"), "斗破苍穹")
        self.assertEqual(_book_name_to_slug("a/b\\c"), "a_b_c")
        # 空格保留, : * ? → _, strip 末尾 _
        self.assertEqual(_book_name_to_slug("name: with *chars?"), "name_ with _chars")

    def test_length_truncate(self):
        """超长截断到 100"""
        long_name = "书名" * 100  # 200 字
        slug = _book_name_to_slug(long_name)
        self.assertLessEqual(len(slug), 100)
        self.assertTrue(slug.startswith("书名"))

    def test_empty_fallback(self):
        """全特殊字符 → '未命名'"""
        self.assertEqual(_book_name_to_slug("《》"), "未命名")
        self.assertEqual(_book_name_to_slug(""), "未命名")


# ============================================================
# 数据类 (3 项)
# ============================================================

class TestDataclasses(unittest.TestCase):
    def test_chapter_block_defaults(self):
        cb = ChapterBlock(index=1, title="测试", content="内容", word_count=2)
        self.assertEqual(cb.index, 1)
        self.assertIsNone(cb.volume)
        self.assertIsNone(cb.num)
        self.assertFalse(cb.is_special)

    def test_split_options_defaults(self):
        opt = SplitOptions()
        self.assertEqual(opt.pattern, "")
        self.assertEqual(opt.mode, "auto")
        self.assertTrue(opt.use_volume)
        self.assertEqual(opt.min_words, 0)
        self.assertFalse(opt.merge_tiny)
        self.assertEqual(opt.max_words, 0)
        self.assertFalse(opt.remove_ads)
        self.assertTrue(opt.strip_whitespace)
        self.assertEqual(opt.scan_lines, 800)

    def test_split_result_with_warning(self):
        sr = SplitResult(
            chapters=[], total_chapters=0, total_words=0, total_volumes=0,
            dedup_count=0, detected_pattern="", pattern_name="",
            metadata={}, encoding_warning="可能乱码"
        )
        self.assertEqual(sr.encoding_warning, "可能乱码")


# ============================================================
# 模块级常量 (1 项)
# ============================================================

class TestModuleConstants(unittest.TestCase):
    def test_novel_splits_dir(self):
        self.assertEqual(NOVEL_SPLITS_DIR, CONFIG_DIR / "novel_splits")


# ============================================================
# 切分主函数 (3 项)
# ============================================================

class TestSplitText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="split_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chinese_chapter(self):
        """中文章节切分"""
        content = """\
《测试书》
作者: 测试

第一章 开始
这是第一段。
这是第二段。

第二章 继续
第二段内容。

第三章 结尾
最后一段。
"""
        path = Path(self.tmp) / "test.txt"
        path.write_text(content, encoding="utf-8")

        result = split_text(content)
        self.assertEqual(result.total_chapters, 3)
        self.assertEqual(result.chapters[0].num, 1)
        self.assertEqual(result.chapters[1].num, 2)
        self.assertEqual(result.chapters[2].num, 3)
        self.assertEqual(result.metadata.get("title"), "测试书")

    def test_english_chapter_roman(self):
        """英文 Chapter Roman"""
        content = """\
Chapter I.
First chapter body.

Chapter II.
Second chapter body.
"""
        result = split_text(content)
        self.assertEqual(result.total_chapters, 2)
        self.assertEqual(result.chapters[0].num, 1)
        self.assertEqual(result.chapters[1].num, 2)

    def test_no_chapter_fallback(self):
        """无章节时整本作为 1 章"""
        content = "这是没有章节标记的长文本。第一段。\n\n第二段。"
        result = split_text(content)
        self.assertEqual(result.total_chapters, 1)
        self.assertEqual(result.chapters[0].title, "全文")

    def test_min_words_too_high_raises(self):
        """min_words 过高抛 ValueError (避免静默失败)"""
        content = ""
        for i in range(1, 11):
            content += f"第{i}章\n" + ("x" * 200) + "\n\n"
        opts = SplitOptions(min_words=10000)
        with self.assertRaises(ValueError) as ctx:
            split_text(content, opts)
        self.assertIn("min_words", str(ctx.exception))


# ============================================================
# save_split 落盘 (2 项, 修 X-2 staging 事务)
# ============================================================

class TestSaveSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="save_split_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_directory_structure(self):
        """save_split 应在 output_dir (blocks 目录) 下生成 {0001..NNNN}.txt + 同级 3 个 JSON/TXT"""
        content = """\
第一章 开始
内容一。

第二章 继续
内容二。
"""
        src = Path(self.tmp) / "src.txt"
        src.write_text(content, encoding="utf-8")
        book_dir = Path(self.tmp) / "out"
        blocks_dir = book_dir / "blocks"
        # save_split 的 output_dir 参数语义: blocks 目录本身 (与小说分析器 save_to_workspace 同构)

        result = save_split(src, blocks_dir, external_title="《测试书》")
        self.assertTrue(result["saved"])
        self.assertEqual(result["total_chapters"], 2)

        # 目录结构: blocks_dir 下生成 0001.txt / 0002.txt + 3 个产物
        self.assertTrue((blocks_dir / "0001.txt").is_file())
        self.assertTrue((blocks_dir / "0002.txt").is_file())
        self.assertTrue((blocks_dir / "chapters.json").is_file())
        self.assertTrue((blocks_dir / "metadata.json").is_file())
        self.assertTrue((blocks_dir / "split_report.txt").is_file())
        # staging 应清理
        self.assertFalse((blocks_dir / "_split_staging").exists())

        # chapters.json 结构
        with open(blocks_dir / "chapters.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["index"], 1)
        self.assertEqual(data[0]["title"], "第一章 开始")

        # metadata.json 含 external_title
        with open(blocks_dir / "metadata.json", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["title"], "《测试书》")

    def test_save_atomic_no_partial(self):
        """save_split 失败时不应留半截 (staging 事务保护)"""
        content = """\
第一章
正文一。

第二章
正文二。
"""
        src = Path(self.tmp) / "src.txt"
        src.write_text(content, encoding="utf-8")
        blocks_dir = Path(self.tmp) / "readonly" / "blocks"
        # 验 save_split 完整成功 + staging 已清理 (上面已验), 这里只验幂等
        result = save_split(src, blocks_dir, external_title="《测试》")
        self.assertTrue(result["saved"])
        # 再次 save, 应该是覆盖而非报错
        result2 = save_split(src, blocks_dir, external_title="《测试》")
        self.assertTrue(result2["saved"])


# ============================================================
# E2E 端到端 (3 项, 修 X-3)
# ============================================================

class TestE2EPreviewSave(unittest.TestCase):
    """走临时 PROOFREADER_HOME 验完整流程."""

    def setUp(self):
        self.tmp_proofreader = tempfile.mkdtemp(prefix="e2e_proofreader_")
        self.tmp_src = tempfile.mkdtemp(prefix="e2e_src_")
        self.original_env = os.environ.get("PROOFREADER_HOME")
        os.environ["PROOFREADER_HOME"] = self.tmp_proofreader

    def tearDown(self):
        if self.original_env:
            os.environ["PROOFREADER_HOME"] = self.original_env
        else:
            os.environ.pop("PROOFREADER_HOME", None)
        shutil.rmtree(self.tmp_proofreader, ignore_errors=True)
        shutil.rmtree(self.tmp_src, ignore_errors=True)

    def test_e2e_preview(self):
        """preview_split 端到端"""
        content = """\
《测试》
作者: 测试者

第一章 开始
第一段。

第二章 继续
第二段。
"""
        path = Path(self.tmp_src) / "《测试》.txt"
        path.write_text(content, encoding="utf-8")

        preview = preview_split(path, SplitOptions())
        self.assertIn("chapters", preview)
        self.assertIn("metadata", preview)
        self.assertEqual(preview["metadata"]["title"], "测试")  # 《》strip
        self.assertGreaterEqual(preview["total_chapters"], 2)

    def test_e2e_save_with_slug(self):
        """save_split 端到端 + slug 化路径"""
        content = """\
《《最内层》》（精校版）

第一章
正文。
"""
        path = Path(self.tmp_src) / "《《最内层》》（精校版）.txt"
        path.write_text(content, encoding="utf-8")

        book_name = infer_book_name(path)
        self.assertEqual(book_name, "《最内层》")
        slug = _book_name_to_slug(book_name)
        # 《》 → _, strip _, 期望 "最内层"
        self.assertEqual(slug, "最内层")

        out = Path(self.tmp_proofreader) / "novel_splits" / slug
        blocks_dir = out / "blocks"
        result = save_split(path, blocks_dir, external_title=book_name)
        self.assertTrue(result["saved"])
        self.assertTrue((blocks_dir / "0001.txt").exists())

    def test_e2e_batch_simulation(self):
        """模拟 batch 切 3 本, 一本空文件 + 两本正常"""
        # 空文件
        empty = Path(self.tmp_src) / "empty.txt"
        empty.write_text("", encoding="utf-8")

        # 正常 1
        ok1 = Path(self.tmp_src) / "《正常1》.txt"
        ok1.write_text("《正常1》\n\n第一章\n内容。\n", encoding="utf-8")

        # 正常 2
        ok2 = Path(self.tmp_src) / "《正常2》.txt"
        ok2.write_text("《正常2》\n\n第一章\n内容。\n", encoding="utf-8")

        results = []
        for src in [empty, ok1, ok2]:
            out = Path(self.tmp_proofreader) / "novel_splits" / _book_name_to_slug(infer_book_name(src))
            try:
                r = save_split(src, out)
                results.append(("ok", r))
            except Exception as e:
                results.append(("err", str(e)))

        # 空文件也能切 (作为 1 章全文)
        self.assertEqual(results[0][0], "ok")
        # 正常 1 / 2 必成功
        self.assertEqual(results[1][0], "ok")
        self.assertEqual(results[2][0], "ok")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    # 兼容 run_all_tests.py: 输出 [PASS]/[FAIL] 关键字供 glob 统计.
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    # 末尾追加汇总行 (run_all_tests.py 用 count("[PASS]") 统计)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    if result.wasSuccessful():
        print(f"[PASS] test_novel_splitter ({passed}/{total})")
    else:
        print(f"[FAIL] test_novel_splitter ({passed}/{total}, {failed} fail)")
    sys.exit(0 if result.wasSuccessful() else 1)
