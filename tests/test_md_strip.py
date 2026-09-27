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


# === v5.4.2 (全量扫描 G1/G2): CRLF 围栏 + 表格分隔行线性化 ===
def test_v542_crlf_fence_and_perf():
    """CRLF 文本的围栏必须能闭合 (Windows .md 默认 CRLF);
    表格分隔行判定不得有灾难性回溯。"""
    print("\n--- v5.4.2: CRLF 围栏 / 表格分隔性能 ---")
    from app.md_strip import strip_markdown, _is_table_sep_line
    import time

    # 1) CRLF 围栏: 闭围栏匹配 (旧实现在此永不闭合 → 代码内容失去保护)
    s = "前文\r\n```\r\ncode\r\n```\r\n后文"
    once = strip_markdown(s)
    check("CRLF: 围栏标记被剥掉", "```" not in once, repr(once))
    check("CRLF: 代码内容保留", "code" in once, repr(once))
    check("CRLF: 前后文保留", once.startswith("前文") and once.endswith("后文"), repr(once))
    check("CRLF: 换行已归一 (幂等)", strip_markdown(once) == once, repr(once))
    # 仅 CR (老 Mac) 同样归一 → 换行
    check("CR 也归一为换行", strip_markdown("a\rb") == "a\nb", repr(strip_markdown("a\rb")))

    # 2) 表格分隔行判定 (形态对照)
    for line, exp in [("--- | ---", True), ("| --- | :---: |", True),
                      ("| --- | --- | --- |", True), ("---|---", True),
                      ("  | :--- | ---: |  ", True),
                      ("-----", False), ("- - -", False), ("text", False),
                      ("| a | b |", False)]:
        check(f"分隔行判定 {line!r}", _is_table_sep_line(line) is exp)

    # 3) 性能: 旧实现嵌套量词 → 3 万空格单行使整篇跑 9.4s
    line = "-" + " " * 30000
    t = time.perf_counter()
    strip_markdown(line)
    dt = time.perf_counter() - t
    check("长空白行不触发灾难性回溯 (< 500ms)", dt < 0.5, f"{dt * 1000:.1f}ms")
    line2 = "| " + " | ".join(["---"] * 200) + " | " + " " * 20000
    t = time.perf_counter()
    strip_markdown(line2)
    dt2 = time.perf_counter() - t
    check("宽表 + 尾随空格 (< 500ms)", dt2 < 0.5, f"{dt2 * 1000:.1f}ms")


def test_v543_f7_link_regex_guard_and_size_cap():
    """v5.4.3 (F7): 链接/图片/引用三条正则的 O(n^2) 守卫 + md_local 体积上限。

    根因: 三条正则首段字符类 `[^\]]*` 无上界, 行内没有 `]` 时每个 `[` 起点吃
    完整行再逐格回退。实测 (旧实现):
        50000 个 '['   -> _LINK_RE 9.9s + _REF_LINK_RE 8.8s
        50000 个 '!['  -> _IMAGE_RE 4.7s + _LINK_RE 4.3s
    比 v5.4.2 G2 (表格嵌套量词) 更严重: md_local 整文件不切块且**无体积上限**,
    拖进一个巨型日志/JSON, 任务永远不返回。

    守卫必须**包住三条**, 只包两条测不出来 —— v1 就漏了 _IMAGE_RE, 而它之所以
    没被发现是测量盲区: 裸 '[' 行上 _IMAGE_RE 实测 0.000s。
    """
    print("\n--- v5.4.3 (F7): 链接正则守卫 + md_local 上限 ---")
    from app.md_strip import strip_markdown
    import time

    # 1) 性能: 三条都必须在毫秒级
    #    ⚠ '![' 的规模不能只取 8000: 实测 _IMAGE_RE **无守卫**时
    #    8000 个 '![' 要 394.72ms, 对 500ms 预算只剩 1.27 倍余量 ——
    #    慢机器/高负载下会**随机变红** (靠运气过, 不是靠判据过)。
    #    20000 个是 2514ms (5 倍余量), 6000 个以下是 150ms (3.3 倍) 但太贴近。
    #    取 20000: 有守卫时 O(1) 短路, 仍是毫秒级, 不增加测试耗时。
    for label, s, budget in (("50000 个 '['", "[" * 50000, 0.5),
                             ("20000 个 '!['", "![" * 20000, 0.5),
                             ("20000 个 '['", "[" * 20000, 0.5)):
        t = time.perf_counter()
        strip_markdown(s)
        dt = time.perf_counter() - t
        check(f"F7 {label} 不触发二次爆炸 (< 500ms)", dt < budget,
              f"{dt * 1000:.1f}ms")

    # 2) 语义等价: 守卫只在行内无 ']' 时跳过, 有 ']' 时行为必须原样
    cases = [
        ("[abc](x) 和 [ref][1] 和 ![i](y.png)", "abc 和 ref 和 i"),
        ("[abc", "[abc"),                     # 有 [ 无 ]
        ("]", "]"),                           # 只有 ]
        ("[a](b)[c](d)", "ac"),               # 相邻两个链接
        ("![i](y.png) 单独", "i 单独"),         # 图片
        ("[ref][1] 引用", "ref 引用"),         # 引用式
    ]
    for src, want in cases:
        got = strip_markdown(src)
        check(f"F7 语义等价 {src!r}", got == want, f"got={got!r} want={want!r}")

    # 3) 幂等: 守卫不破坏 v5.4.2 的幂等性
    for src in ("[abc](x) 和 [ref][1] 和 ![i](y.png)", "[" * 100, "![" * 50):
        once = strip_markdown(src)
        check(f"F7 幂等 {src[:16]!r}", strip_markdown(once) == once)


def test_v543_f7_md_local_size_cap():
    """v5.4.3 (F7): md_local 超体积上限 -> FAILED 且 error 说清原因。"""
    print("\n--- v5.4.3 (F7): md_local 体积上限 ---")
    import asyncio
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from app.processor import ProcessingEngine, MD_LOCAL_MAX_CHARS
    from app.utils import ProjectConfig, TaskStatus

    check("F7 上限常量是 200 万字", MD_LOCAL_MAX_CHARS == 2_000_000,
          str(MD_LOCAL_MAX_CHARS))

    # 不改常量, 用 monkeypatch 把上限调到很小, 省得造 200 万字字符串
    orig = MD_LOCAL_MAX_CHARS
    with patch("app.processor.MD_LOCAL_MAX_CHARS", 50):
        tmp = Path(tempfile.mktemp(suffix=".txt"))
        tmp.write_text("甲" * 200, encoding="utf-8")
        try:
            cfg = ProjectConfig(api_base="http://x", api_key="k", model="m",
                                prompt_mode="md_local", max_retries=0)
            engine = ProcessingEngine(cfg)
            engine.prepare_tasks([tmp])

            async def _run():
                await engine.run_async()

            asyncio.run(_run())
            task = list(engine.tasks.values())[0]
            check("F7 超上限 -> FAILED", task.status == TaskStatus.FAILED,
                  str(task.status))
            err = (task.result.error or "") if task.result else ""
            # 类型名取自 type(e).__name__, 这里断言的是**具体**类型而不是笼统的
            # ValueError —— 界面上要能看出"是体积超限"而不是"某个 ValueError"。
            check("F7 error 写明类型名 _FileTooLargeError",
                  "_FileTooLargeError" in err, err[:160])
            check("F7 error 写明是体积超限", "过大" in err or "上限" in err, err[:160])
            check("F7 error 给出可操作出路 (改用整篇校对/先拆分)",
                  "整篇校对" in err or "拆分" in err, err[:160])
        finally:
            tmp.unlink(missing_ok=True)

    # 分类验证: 体积超限必须是**不可重试**。
    # 文件太大不是瞬时故障, 重试几次结果都一样, 白烧时间。
    # 可观测量 = 日志里"文件过大"出现的次数 (每次 attempt 记一条):
    #   不可重试 -> 1 次; 可重试 (max_retries=1) -> 2 次。
    # ⚠ 不能拿"有没有构造 AsyncOpenAI"当可观测量 —— md_local 压根不构造客户端,
    #   那个计数恒为 0, 断言会空洞通过 (第一版就栽在这)。
    logs = []
    tmp2 = Path(tempfile.mktemp(suffix=".txt"))
    tmp2.write_text("甲" * 200, encoding="utf-8")
    try:
        with patch("app.processor.MD_LOCAL_MAX_CHARS", 50):
            cfg2 = ProjectConfig(api_base="http://x", api_key="k", model="m",
                                 prompt_mode="md_local", max_retries=1)
            engine2 = ProcessingEngine(cfg2)
            engine2.on_log = logs.append
            engine2.prepare_tasks([tmp2])
            asyncio.run(engine2.run_async())
        t2 = list(engine2.tasks.values())[0]
        check("F7 体积超限仍判 FAILED (max_retries=1)",
              t2.status == TaskStatus.FAILED, str(t2.status))
        # 只数 "[清洗] ... 文件过大" 这一条 (每次 attempt 记一条)。
        # ⚠ 不能只搜 "文件过大": "[不可重试] ... — _FileTooLargeError: 文件过大
        #   ..." 那行把同一条 msg 嵌进去了, 会把计数翻倍 (第一版就栽在这)。
        n_attempts = sum(1 for m in logs
                         if m.startswith("[清洗]") and "文件过大" in m)
        check("F7 体积超限**不烧重试** (不可重试分类生效)",
              n_attempts == 1,
              f"进入体积检查 {n_attempts} 次 (2 = 走了重试路径); "
              f"日志={logs}")
        check("F7 走了不可重试分支",
              any("[不可重试]" in m for m in logs),
              str([m for m in logs if "不可重试" in m or "文件过大" in m])[:200])
    finally:
        tmp2.unlink(missing_ok=True)
        patch.stopall()
    assert MD_LOCAL_MAX_CHARS == orig


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
        test_v542_crlf_fence_and_perf,   # v5.4.2 全量扫描 G1/G2
        test_v543_f7_link_regex_guard_and_size_cap,   # v5.4.3 F7
        test_v543_f7_md_local_size_cap,               # v5.4.3 F7
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
