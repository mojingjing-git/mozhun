# -*- coding: utf-8 -*-
"""v4.4.2 Markdown 清洗测试套件 (app/md_strip.py + 引擎 md_local 分支).

run_all_tests.py 按 test_*.py glob 自动发现 (无需注册).
"""
import asyncio
import sys
from pathlib import Path
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


def _idem(name, sample):
    """幂等断言: strip 连跑两遍 == 一遍 (评审 P2-13 的测试形态)."""
    from app.md_strip import strip_markdown
    once = strip_markdown(sample)
    twice = strip_markdown(once)
    check(f"幂等: {name}", twice == once, repr((once[:50], twice[:50])))


def test_headings():
    """ATX 标题: 去井号留文字; # 后须空格/行尾 (评审 P2-12)."""
    print("\n--- 标题 ---")
    from app.md_strip import strip_markdown
    check("一级标题", strip_markdown("# 标题一") == "标题一")
    check("三级标题+尾随井号", strip_markdown("### 深层标题 ##") == "深层标题")
    check("#1 不是标题 (无空格)", strip_markdown("#1 序言保留") == "#1 序言保留")
    check("#hashtag 不是标题", strip_markdown("#hashtag") == "#hashtag")
    check("空标题行", strip_markdown("#") == "")
    check("标题文字含强调", strip_markdown("# **章节**名") == "章节名")


def test_quote_and_list():
    """引用/列表: 迭代剥标记; 有序列表保留数字."""
    print("\n--- 引用与列表 ---")
    from app.md_strip import strip_markdown
    check("单层引用", strip_markdown("> 引用文字") == "引用文字")
    check("多层引用", strip_markdown(">> 两层引用") == "两层引用")
    check("引用内列表", strip_markdown("> - 条目") == "条目")
    check("无序列表 -", strip_markdown("- 项目一") == "项目一")
    check("无序列表 *", strip_markdown("* 星号项") == "星号项")
    check("无序列表 +", strip_markdown("+ 加号项") == "加号项")
    check("嵌套列表迭代剥", strip_markdown("- - 嵌套") == "嵌套")
    check("有序列表保留数字", strip_markdown("1. 第一步") == "1. 第一步")
    check("有序括号保留", strip_markdown("1) 另一种") == "1) 另一种")
    check("强调行不是列表", strip_markdown("*斜体行*") == "斜体行")


def test_hr_and_table():
    """水平线/表格: 纯标记行删除, 数据行转两空格连接."""
    print("\n--- 水平线与表格 ---")
    from app.md_strip import strip_markdown
    check("水平线 ---", strip_markdown("上文\n---\n下文") == "上文\n下文")
    check("水平线 ***", strip_markdown("***") == "")
    check("水平线 - - -", strip_markdown("- - -") == "")
    check("下划线线 ___", strip_markdown("___") == "")
    check("表格分隔行", strip_markdown("| --- | :---: |") == "")
    check("分隔行容忍空格", strip_markdown("| :--- | ---: |") == "")
    check("表格数据行", strip_markdown("| 名称 | 数量 |") == "名称  数量")
    check("无首尾竖线不动", strip_markdown("a | b") == "a | b")


def test_links_and_images():
    """链接/图片: URL 丢弃 (红线 1a 例外), text 空回退 url."""
    print("\n--- 链接与图片 ---")
    from app.md_strip import strip_markdown
    check("链接取文字", strip_markdown("[文字](https://a.com)") == "文字")
    check("空文字链接留 url", strip_markdown("[](https://a.com)") == "https://a.com")
    check("图片取 alt", strip_markdown("![截图](x.png)") == "截图")
    check("空 alt 图片丢弃", strip_markdown("前 ![](x.png) 后") == "前  后")
    check("引用式链接", strip_markdown("[文字][ref]") == "文字")
    check("引用定义行删除", strip_markdown("[ref]: https://a.com") == "")


def test_emphasis():
    """强调: 星号系剥除带 ASCII 词边界; 下划线系整类不剥 (红线 4)."""
    print("\n--- 强调 ---")
    from app.md_strip import strip_markdown
    check("CJK 加粗 (主用例)", strip_markdown("词**加粗**词") == "词加粗词")
    check("空格加粗", strip_markdown("词 **加粗** 词") == "词 加粗 词")
    check("星号斜体", strip_markdown("这是*斜体*字") == "这是斜体字")
    check("粗斜体", strip_markdown("***粗斜***") == "粗斜")
    check("删除线", strip_markdown("~~作废~~") == "作废")
    check("数学乘法不动", strip_markdown("2*3*4=24") == "2*3*4=24")
    check("双星数学不动", strip_markdown("2**3**4=8") == "2**3**4=8")
    check("英文词紧邻不动", strip_markdown("word**x**word") == "word**x**word")
    check("__init__ 不剥 (红线 4)", strip_markdown("__init__ 方法") == "__init__ 方法")
    check("snake_case 不剥", strip_markdown("snake_case_name") == "snake_case_name")
    check("转义保留原样 (P1-3)", strip_markdown("\\*字面星号\\*") == "\\*字面星号\\*")


def test_code_protection():
    """代码保护 (红线 2): 围栏剥壳留内容含缩进; 行内代码分脏/净两分支."""
    print("\n--- 代码保护 ---")
    from app.md_strip import strip_markdown
    src = "前文\n```python\n# 这是注释\nx = [1, 2]\n```\n后文"
    r = strip_markdown(src)
    check("围栏剥壳留内容 (含 # 行)", r == "前文\n# 这是注释\nx = [1, 2]\n后文", repr(r))
    check("行内代码净内容剥反引号", strip_markdown("运行 `pip install` 即可") == "运行 pip install 即可")
    check("行内代码脏内容整体保留", strip_markdown("写 `**不是加粗**` 字面") == "写 `**不是加粗**` 字面")
    check("未闭合围栏内容保护", strip_markdown("```py\n代码甲\n代码乙") == "代码甲\n代码乙")
    check("4 空格缩进按普通行 (明确不做)", strip_markdown("    x = 1") == "x = 1")
    check("围栏内空行保留", strip_markdown("```\n甲\n\n乙\n```") == "甲\n\n乙")


def test_frontmatter_and_normalization():
    """frontmatter 整块剥离 (P1-7); 空行/行尾空白规整; NUL 剥离."""
    print("\n--- frontmatter 与规整 ---")
    from app.md_strip import strip_markdown
    check("frontmatter 剥离", strip_markdown("---\ntitle: X\n---\n正文") == "正文")
    check("frontmatter 多行", strip_markdown("---\na: 1\nb: 2\n---\n开始") == "开始")
    check("非开头 --- 不当 frontmatter", strip_markdown("正文\n---\n尾") == "正文\n尾")
    check("空行规整 3+→1", strip_markdown("甲\n\n\n\n乙") == "甲\n\n乙")
    check("行尾空白", strip_markdown("甲   \n乙") == "甲\n乙")
    check("NUL 剥离不串号", strip_markdown("甲\x00乙") == "甲乙")
    check("纯标记文件产出空文本", strip_markdown("---\n***\n---") == "")


def test_idempotency():
    """幂等 (红线 3, 非代码区): 全部正例连跑两遍相等 (评审 P2-13)."""
    print("\n--- 幂等 ---")
    samples = {
        "标题强调": "# **章节**名\n正文*, 保留",
        "列表引用": "> - 条目一\n> - 条目二",
        "表格": "| 名称 | 数量 |\n| --- | --- |\n| 甲 | 1 |",
        "链接": "见 [文档](https://a.com) 与 ![图](x.png)",
        "混合强调": "词**加粗**词, *斜体* 与 ~~删除~~",
        "frontmatter": "---\ntitle: X\n---\n正文",
        "干净代码": "运行 `pip install` 后 `import os`",
    }
    from app.md_strip import strip_markdown
    for name, sample in samples.items():
        once = strip_markdown(sample)
        twice = strip_markdown(once)
        check(f"幂等: {name}", twice == once, repr((once[:60], twice[:60])))


def test_content_preserved_e2e():
    """中文端到端: 一篇完整 md 结构的 AI 风格文章 — 标记全剥, 文字不丢."""
    print("\n--- 端到端 ---")
    from app.md_strip import strip_markdown
    article = (
        "---\ntitle: 示例\n---\n"
        "# 项目说明\n\n"
        "本项目**注重实效**, 详见 [官方文档](https://example.com)。\n\n"
        "## 使用步骤\n\n"
        "- 安装依赖\n- 运行 `start.py`\n\n"
        "| 环境 | 状态 |\n| --- | --- |\n| 生产 | 稳定 |\n\n"
        "> 提示: 2*3*4 不是强调。\n"
        "---\n"
    )
    r = strip_markdown(article)
    for keep in ("项目说明", "本项目注重实效", "官方文档", "使用步骤",
                 "安装依赖", "start.py", "环境  状态", "生产  稳定",
                 "提示: 2*3*4 不是强调。"):
        check(f"端到端保留: {keep}", keep in r, repr(r))
    for gone in ("#", "**", "](", "> ", "- 安装", "```", "title:"):
        check(f"端到端无残留: {gone!r}", gone not in r, repr(r))


def test_engine_md_local_mode():
    """引擎 md_local 分支: 不调 LLM、整文件清洗、标点链式生效 (镜像 punct_local 引擎测试)."""
    print("\n--- 引擎 Markdown 清洗模式 ---")
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig

    async def run():
        cfg = ProjectConfig(
            api_base="", api_key="", model="",
            prompt_mode="md_local", chunking_preset="whole_file",
        )
        engine = ProcessingEngine(cfg)
        if hasattr(engine, "_pause_event"):
            engine._pause_event.set()
        engine.stats.start_time = __import__("time").time()
        with patch("app.processor.AsyncOpenAI") as fake_ctor:
            corrected, tokens, chunks = await engine._call_api_stream(
                "k", "# 标题\n**加粗**的正文, 见 [链接](https://a.com)。"
            )
            # 端到端验证本地模式不建 AsyncOpenAI (空 api_key 下回归会抛 ValidationError)
            engine.tasks = {}
            await engine._run_all()
            ctor_called = fake_ctor.called
            client_after = engine._client
        return corrected, tokens, chunks, ctor_called, client_after

    corrected, tokens, chunks, ctor_called, client_after = asyncio.run(run())
    check("md_local 不创建 LLM 客户端", ctor_called is False and client_after is None)
    check("不消耗 token", tokens == 0)
    # 标点链式修复: ", 见" 的半角逗号转全角, 逗号后的空格保留 (punct_fix 不删空格)
    check("md 已清洗 + 标点链式修复",
          corrected == "标题\n加粗的正文， 见 链接。", repr(corrected))
    check("chunks 单块整文件", len(chunks) == 1 and chunks[0].original.startswith("# 标题"))


def test_engine_empty_fallback():
    """空结果兜底 (评审 P2-16): 纯标记文件回退保留原文."""
    print("\n--- 空结果兜底 ---")
    from app.md_strip import strip_markdown  # noqa: F401  引擎内已引用
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig

    async def run():
        cfg = ProjectConfig(api_base="", api_key="", model="", prompt_mode="md_local")
        engine = ProcessingEngine(cfg)
        if hasattr(engine, "_pause_event"):
            engine._pause_event.set()
        engine.stats.start_time = __import__("time").time()
        corrected, tokens, chunks = await engine._call_api_stream("k", "---\n***\n---")
        return corrected, tokens, chunks

    corrected, tokens, chunks = asyncio.run(run())
    check("纯标记文件回退原文", corrected == "---\n***\n---", repr(corrected))
    check("原文作为 diff 基线", chunks[0].original == "---\n***\n---")


def test_config_and_hash():
    """md_strip_before_llm 字段往返 + 缓存指纹纳入 (评审 P2-9)."""
    print("\n--- 配置字段与指纹 ---")
    from app.utils import ProjectConfig, compute_prompt_hash
    cfg = ProjectConfig()
    check("md_strip_before_llm 默认 False", cfg.md_strip_before_llm is False)
    cfg.md_strip_before_llm = True
    d = cfg.to_dict()
    check("to_dict 含 md_strip_before_llm", d.get("md_strip_before_llm") is True)
    cfg2 = ProjectConfig.from_dict(d)
    check("from_dict 还原 True", cfg2.md_strip_before_llm is True)
    cfg3 = ProjectConfig.from_dict({k: v for k, v in d.items() if k != "md_strip_before_llm"})
    check("旧配置兼容 (缺字段 -> False)", cfg3.md_strip_before_llm is False)
    h_off = compute_prompt_hash("strict", "m", "", md_strip=False)
    h_on = compute_prompt_hash("strict", "m", "", md_strip=True)
    check("开关改变指纹", h_on != h_off)
    modes_keys = ""
    from app.templates import PROMPT_MODES
    modes_keys = PROMPT_MODES.get("md_local", {}).get("label", "")
    check("PROMPT_MODES 含 md_local", "Markdown" in modes_keys, modes_keys)


def test_engine_md_local_reports():
    """v5.0.1 (审计 I-2): total=0 但 imbalance 非空 (只有落单引号) 也要收集 — 旧 total 门控吞掉."""
    print()
    print("--- 引擎 md_local 不平衡报告 (total=0) ---")
    from app.processor import ProcessingEngine
    from app.utils import ProjectConfig

    async def run():
        cfg = ProjectConfig(api_base="", api_key="", model="", prompt_mode="md_local")
        engine = ProcessingEngine(cfg)
        if hasattr(engine, "_pause_event"):
            engine._pause_event.set()
        engine.stats.start_time = __import__("time").time()
        corrected, tokens, chunks = await engine._call_api_stream("k", '只有"落单引号的一行')
        return corrected, engine.punct_reports

    corrected, reports = asyncio.run(run())
    check("md_local total=0 也收集不平衡报告", len(reports) >= 1, str(reports))


def main():
    global passed, failed
    tests = [
        test_headings,
        test_quote_and_list,
        test_hr_and_table,
        test_links_and_images,
        test_emphasis,
        test_code_protection,
        test_frontmatter_and_normalization,
        test_idempotency,
        test_content_preserved_e2e,
        test_engine_md_local_mode,
        test_engine_md_local_reports,
        test_engine_empty_fallback,
        test_config_and_hash,
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
