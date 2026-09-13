# 墨准 v5.2b 小说切分 — 实施计划

**版本**: v5.2b (独立发布, 与 v5.2 Word 友好分离)
**分支**: cleanup/v6
**状态**: ⏳ 执行中
**总工时**: 12-16h (2-2.5 人天)
**最后更新**: 2026-09-13

---

## 0. 版本与决策(默认推荐组合, 由父会话拍板)

| 决策 | 选择 | 理由 |
|---|---|---|
| M-1 cleanup/v6 Phase C2 抢先做 | ✅ 走 | splitter.js 一步到位, 避免 C2 时重拆 |
| v5.2b 独立 vs 合并 v5.2 | ✅ 独立 | 借鉴源 / 用户场景 / 测试可独立 |
| X-6 借鉴头 4 段标准纪律 | ✅ 合入 | 与 v3.0+ punct_fix / md_strip / ai_score_local / harness 同构 |

---

## 1. 目标

墨准新增**第 8 视图「小说切分」**, 集成小说分析器 `SplitterService` 核心能力, 沿用墨准水墨/Fluent 视觉与 pywebview Bridge 模式, 0 字段侵入 ProjectConfig(27→27), 借鉴 Apache 2.0 小说分析器 + 思路借鉴 2 个 MIT 项目。

---

## 2. 改动清单 (v2 整合 Critical + Major)

| # | 类型 | 文件 | 估计行 | 风险 |
|---|---|---|---:|---|
| 1 | 新增 | `app/novel_splitter.py` (借鉴头 8 段 + 530 行核心) | +530 | 🟡 |
| 2 | 改 | `app/web_backend.py` (3 Bridge + 1 cancel) | +75 | 🟢 |
| 3 | 改 | `web/index.html` (侧边栏 + 视图骨架) | +55 | 🟢 |
| 4 | 改 | `web/app.js` (路由表 + 视图装载) | +35 | 🟡 |
| 5 | 新增 | `web/views/novel-splitter.js` | +300 | 🟢 |
| 6 | 新增 | `tests/test_novel_splitter.py` (~48 项 + 3 e2e) | +520 | 🟢 |
| 7 | 改 | `docs/THIRD_PARTY_NOTICES.md` (加 §22-A/B/C) | +260 | 🟢 |
| 8 | 改 | `AGENTS.md` (加 §37 决策) | +35 | 🟢 |
| 9 | 改 | `CHANGELOG.md` (v5.2b 条目) | +55 | 🟢 |
| 10 | 改 | `README.md` (特性段 + 借鉴清单 20→23) | +18 | 🟢 |
| 11 | 改 | `CLEANUP_PLAN.md` (Phase C2 状态回填) | +5 | 🟢 |

**总改动**: 6 新增 + 7 改, 净增约 1888 行.

---

## 3. 借鉴合规 (升级版, 修 C-2)

### 3.1 `app/novel_splitter.py` 借鉴头 (8 段)

**位置**: 文件顶部第 1-50 行, **显著位置**, 不可藏在文件尾.

**结构** (Apache §4(b)/(c) 4 段 + 墨准 v3.0+ 4 段标准):
```
# Apache License 2.0 §4(b)/(c) 强制声明
# 本文件为小说分析器 (Copyright 2026 mojingjing-git, Apache-2.0) 的衍生作品
# 修改时间: 2026-09-XX | 修改方: 墨准项目 | 改动: 编码探测改用 app.utils.read_file_text, 移除 FastAPI 依赖, 适配 Bridge 接口
# 修改清单: 见 CHANGELOG.md v5.2b

# 借鉴自 https://github.com/mojingjing-git/novel-analyzer (Apache-2.0)
# 借鉴内容: 章节/卷/特章识别 + 广告清理 + 相邻去重 + 超大章拆分 + 书名推断 + Gutenberg 头截断 + staging 事务
# 借鉴方式: 思路与核心算法借鉴, 见 docs/THIRD_PARTY_NOTICES.md §22-A
# Copyright (c) 2026 mojingjing-git

# 思路借鉴 zzk6780051/novel (MIT): 多格式章节正则 + 前 N 行打分
# 思路借鉴 oomol-lab/txt-to-epub-converter (MIT): 卷/章/节层级 + 字数限制
```

### 3.2 `docs/THIRD_PARTY_NOTICES.md` §22 (3 子节)

- **§22-A**: Apache 2.0 LICENSE 完整副本 (200 行, 从 `F:/AI/01_项目/小说分析器/LICENSE` 复制)
- **§22-B**: zzk6780051/novel MIT 完整 LICENSE (~20 行, MIT 模板, 加版权行)
- **§22-C**: oomol-lab/txt-to-epub-converter MIT 完整 LICENSE (~20 行)
- 顶部索引加 §22 子表, 末尾核验状态表加 3 行

### 3.3 `AGENTS.md` §37 决策

```
### v5.2b 新增 (小说切分: 第 8 视图 + Apache 2.0 衍生集成)
37. **小说切分集成设计** (v5.2b+): `app/novel_splitter.py` 从姊妹项目「小说分析器」
    `splitter_service.py` 整合核心纯函数, Apache 2.0 衍生, 完整 LICENSE 副本
    在 THIRD_PARTY_NOTICES §22-A. 思路借鉴 zzk6780051/novel (MIT, §22-B) +
    oomol-lab/txt-to-epub-converter (MIT, §22-C), 仅思路, 无代码复制.
    0 字段侵入 ProjectConfig (27→27), 选项走方法参数直传.
    编码探测复用 `app.utils.read_file_text` (v4.1.8.2 E4 审计后版本), 不另写一份.
    输出 `~/.proofreader/novel_splits/{slug}/`, slug 化路径 (避免 `《》` Windows 隐患),
    章节文件 `blocks/{0001}.txt`, 与 `checkpoints/` 同级.
    进度推送 + 取消借鉴校对/DeAI `_push()` 50ms 节流 + `threading.Event` 模式.
```

### 3.4 `CHANGELOG.md` v5.2b 条目 (沿用 v5.0.2 6 节结构)

新模块 / Bridge / 配置(0 字段) / UI / 借鉴合规 / 测试

---

## 4. Bridge 接口 (3 + 1, 修 M-5 + M-2)

**位置**: `app/web_backend.py` 「校对任务 API」之后新增 section

```python
# ==================== 小说切分 API (v5.2b+) ====================

def infer_book_name(self, path: str) -> dict:  # 改名自 infer_splitter_book_name (M-5)
    """从文件名推断书名(走 novel_splitter.infer_book_name)"""
    # 复用 read_file 模式: try/except + {ok, book_name/error}

def preview_splitter(self, file_path: str, options: dict) -> dict:
    """单本预览切分(不落盘)"""
    # 路径校验 → SplitOptions(**options) → preview_split → 序列化
    # 返回 {ok, chapters: [...], total, volumes, ...}

def batch_splitter(self, file_paths: list[str], book_names: list[str],
                   options: dict) -> dict:
    """批量切分落盘(走 novel_splitter.save_split)"""
    # 单本 >50MB 走 threading.Thread (与 start_proofread 同构, 修 M-2)
    # 进度推送 self._push("onSplitterProgress", {stage, current, total, book_name})
    # 取消检查 self._splitter_cancel_event.is_set()
    # 部分失败隔离 + 顶层 _batch_report.txt
    # 返回 {ok, total, success, fail, results: [...], batch_report}

def cancel_splitter(self) -> dict:
    """取消当前批量切分(设 threading.Event)"""
    if self._splitter_cancel_event:
        self._splitter_cancel_event.set()
        return {"ok": True, "action": "cancelled"}
    return {"ok": False, "action": "no_active"}
```

**删除** `choose_splitter_files`(M-5): 复用现有 `choose_files` (web_backend.py:216).

**0 字段侵入 ProjectConfig** (27→27). 选项走 `options: dict` 直传.

---

## 5. 核心模块 `app/novel_splitter.py`

### 5.1 模块布局 (530 行)

```
# 借鉴头 8 段 (L1-50)
# 标准库 import (L51-60)
# 墨准内部 import (L61-65)
# 模块常量 (L66-75)
#   - NOVEL_SPLITS_DIR = CONFIG_DIR / "novel_splits"
#   - CHAPTER_PATTERNS (13 种)
#   - VOLUME_PATTERNS (3-4 种)
#   - _AD_STRONG / _AD_WEAK
#   - _WORD_TO_INT 字典
# 数据类 (L76-130)
#   - ChapterBlock
#   - SplitResult
#   - SplitOptions
# 数字转换 (L131-220, ~90 行)
#   - cn_to_int
#   - _roman_to_int
#   - _word_to_int
# 编码读取 (L221-240, ~20 行, 修 C-1)
#   - _read_novel_text
# 章节号抽取 (L241-280, ~40 行)
#   - _extract_chapter_num
# 卷层级 (L281-340, ~60 行)
#   - _normalize_volume_label
#   - _is_volume_start
#   - _compile_volume_patterns
# 候选正则打分 (L341-400, ~60 行)
#   - _chapter_regex_for_mode
# 元数据 (L401-470, ~70 行)
#   - _extract_metadata
#   - _extract_pg_header_meta
#   - _strip_gutenberg_header
# TOC 去重 (L471-510, ~40 行)
#   - _dedup_same_key
# 切分主函数 (L511-580, ~70 行)
#   - split_text(content, options, external_title) -> SplitResult
# 广告清理 + 短章 + 超大 (L581-650, ~70 行)
#   - _is_ad_line
#   - _skip_tiny / _merge_tiny
#   - _split_oversized
# 对外接口 (L651-750, ~100 行)
#   - preview_split(file_path, options) -> dict
#   - save_split(file_path, book_name, options) -> dict
#   - infer_book_name(file_path) -> str
# 路径 slug (L751-790, ~40 行, 修 M-3)
#   - _book_name_to_slug
```

### 5.2 编码探测 (Critical C-1 修法)

```python
def _read_novel_text(file_path: Path) -> str:
    """读取小说文本.

    v5.2b (Critical C-1): 复用 app.utils.read_file_text (墨准 v4.1.8.2 审计 E4 修复),
    不另写一份编码探测逻辑. 顺带做行尾归一.

    修法要点 (C-1):
    - 小说分析器 splitter_service.py:89-90 用 backend.utils.text_utils.detect_and_decode,
      这是小说分析器私有模块, 墨准项目没有
    - 墨准 app/utils.py:430-449 已有 read_file_text: BOM/utf-8/gb18030/replace 兜底
    - 与 AGENTS §29/§32 双引擎零重复红线一致
    """
    content = read_file_text(file_path)
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return content
```

### 5.3 路径 slug (Major M-3 修法)

```python
_SLUG_BAD_CHARS = re.compile(r'[\\/:*?"<>|《》]')
_SLUG_MAX_LEN = 100

def _book_name_to_slug(book_name: str) -> str:
    """书名 → 目录名. 移除 Windows 特殊字符 + 长度截断."""
    slug = _SLUG_BAD_CHARS.sub('_', book_name).strip('_').strip()
    if len(slug) > _SLUG_MAX_LEN:
        slug = slug[:_SLUG_MAX_LEN].rstrip('_')
    return slug or "未命名"
```

落盘路径:
- `book_dir = NOVEL_SPLITS_DIR / slug(book_name) /`
- `book_dir / "blocks" / f"{idx:04d}.txt"`
- `book_dir / "chapters.json"` 保留 `book_name_display` + `book_dir` 两字段
- `book_dir / "metadata.json"`
- `book_dir / "split_report.txt"`

---

## 6. 落盘路径

```
~/.proofreader/                          (CONFIG_DIR, 已有)
├── last_config.json                     (config)
├── checkpoints/                         (已有, 校对)
├── deai_results/                        (已有, DeAI)
├── styles/                              (已有, 风格库)
└── novel_splits/                        (新增, v5.2b)
    ├── _batch_report.txt                (批量聚合, 失败记录)
    ├── {slug}/
    │   ├── blocks/
    │   │   ├── 0001.txt
    │   │   ├── 0002.txt
    │   │   └── ...
    │   ├── chapters.json                (含 book_name_display + book_dir 字段)
    │   ├── metadata.json
    │   └── split_report.txt             (人类可读)
```

`mkdir(parents=True, exist_ok=True)` 在 import 时执行(与 CHECKPOINT_DIR 同构).

---

## 7. 测试 (~48 项 + 3 e2e)

| 类别 | 项 | 覆盖 |
|---|---:|---|
| 编码 (X-1) | 3 | utf-8 / gb18030 / BOM |
| 数字转换 | 12 | cn_to_int 7 / _roman_to_int 3 / _word_to_int 2 |
| 书名推断 | 5 | `《》` / 双层 / 无书名号 / 后缀 / 多分隔符 |
| 章节正则 | 9 | CHAPTER_PATTERNS 13 种各覆盖 1 项 (中文章/回/节/序/楔/番外/尾声/英文 Chapter/数字) |
| 卷正则 | 3 | VOLUME_PATTERNS 3-4 种 |
| min_words | 3 | 0 / 正常 / 过高(触发 ValueError) |
| max_words | 2 | 0 / 单段超 max_words |
| Gutenberg | 2 | 普通 / 含 TOC |
| 广告清理 | 2 | 强标记 / 弱+短行 / 正文中"微信"不误删 |
| 相邻去重 | 2 | 同内容相邻 / 不同内容相邻 |
| 同号去重 | 2 | TOC vs 正文 / 全部短章 |
| 整合 | 5 | preview / save / save 端到端 / 路径 slug / 编码乱码告警 |
| 异常 (X-2) | 1 | 文件不存在 |
| 路径 (M-3) | 3 | 含 `《》` / 含空格 / 超长书名 |
| 取消 (M-2) | 1 | batch 切 5 本到第 3 本 cancel, 验 1/2 已落盘 + 3/4/5 不存在 |
| 性能 (X-5) | 1 | max_concurrent_books=3 限流 |
| **单元合计** | **~48** | |
| E2E (X-3) | 3 | preview e2e / save e2e / batch e2e 走临时 PROOFREADER_HOME |
| **总计** | **~51** | 基线 1334 → 1385 |

---

## 8. 风险表 (13 项, 修 X-4)

| # | 风险 | 等级 | 应对 |
|---|---|---|---|
| R1 | Apache 2.0 LICENSE 副本粘贴遗漏 | 🟢 | 从 `F:/AI/01_项目/小说分析器/LICENSE` 完整 200 行逐字粘贴 |
| R2 | 编码探测自写(已修) | 🟢 | 复用 `app.utils.read_file_text` (修 C-1) |
| R3 | app.js 路由表接入 | 🟢 | dry read `web/app.js:113-120` 找 `setView` 注入点 |
| R4 | cleanup/v6 Phase C2 抢先做 (修 M-1) | 🟡 | Session 2 专做 C2, splitter.js 一步到位 |
| R5 | 大文件 IO 阻塞 (修 M-2) | 🟢 | 进度推送 + 50ms 节流 + threading.Event 取消 |
| R6 | app.js 3080 行已超可读阈值 (已修) | 🟢 | Session 2 C2 解决 |
| R7 | 编码乱码静默 (X-1) | 🟡 | SplitResult 加 `encoding_warning: Optional[str]` |
| R8 | staging 事务保护 (X-2) | 🟡 | 移植 splitter_service.py:1107-1136 完整事务写法 |
| R9 | E2E 测试缺 (X-3) | 🟢 | 加 3 项 e2e 走临时 PROOFREADER_HOME |
| R10 | `《》` 路径 Windows 兼容 (修 M-3) | 🟢 | `_book_name_to_slug` + `book_name_display` 保留 |
| R11 | SplitOptions 字段对齐 (修 M-4) | 🟢 | 9 字段明确 + strip_whitespace/scan_lines 硬编码 |
| R12 | batch 聚合报告 (X-5 关联) | 🟢 | 顶层 `_batch_report.txt` |
| R13 | 性能限流 (X-5) | 🟢 | `max_concurrent_books=3` |

---

## 9. Session 划分 (4 个 session, 12-16h)

### Session 1: 后端核心 + 测试 + 借鉴合规 (4-5h)
- 写 `app/novel_splitter.py` 完整 530 行 (借鉴头 8 段 + 数字转换 + 编码读取 + 章节号抽取 + 卷层级 + 候选正则打分 + 元数据 + TOC 去重 + 切分主函数 + 广告/短章/超大 + 对外接口 + 路径 slug)
- 写 `tests/test_novel_splitter.py` 48 单元 + 3 e2e = 51 项
- 跑测试基线: `python tests/test_novel_splitter.py` 全绿
- 加 Bridge 3 + 1 方法: `app/web_backend.py`
- 写 `docs/THIRD_PARTY_NOTICES.md` §22-A/B/C
- 写 `AGENTS.md` §37
- 写 `CHANGELOG.md` v5.2b 条目
- `run_all_tests.py` 全绿 (基线 1334 → 1385)
- **git commit 1**: `feat(splitter): 小说切分核心 + Bridge + 测试 + 借鉴合规 (v5.2b)`

### Session 2: cleanup/v6 Phase C2 拆 app.js (4-6h)
- 跑 CLEANUP_PLAN.md:215-264 Phase C2 全 8 步
  - C2.1: 依赖图 (读 app.js 函数调用关系)
  - C2.2: 启动时序 (main.py → app.js init)
  - C2.3: 创建 `web/views/{home,results,deai,styles,api,params,appearance}.js` 7 个
  - C2.4: 改 `web/index.html` 加 `<script type="module" src="app.js">`
  - C2.5: 改 `web/app.js` 改 import 路径
  - C2.6: 备份 `web/.baseline-v510/app.js`
  - C2.7: 浏览器控制台验证 7 视图全部可切换
  - C2.8: 跑全量测试 (无破坏性)
- **git commit 2**: `refactor(v6.0): Phase C2 拆 app.js → 7 个 web/views/*.js`

### Session 3: 前端视图 (3-4h)
- dry read `web/app.js` 找 `VIEWS` / `switchView` 注入点
- 写 `web/views/novel-splitter.js` 完整 300 行 (借 SplitterPage.vue 形态, 套墨准水墨 token)
- 改 `web/index.html` 加侧边栏第 8 项 + 视图骨架
- 改 `web/app.js` 加 `splitter` case + `renderSplitter` 调用
- `python start.py check` 跑通
- 启动 dev 模式 dry check 加载 splitter 视图无报错
- **git commit 3**: `feat(ui): 小说切分第 8 视图 (v5.2b)`

### Session 4: 收尾 + 全量回归 (1-2h)
- 改 `README.md` 特性段 + 借鉴清单 20→23
- 改 `CLEANUP_PLAN.md` Phase C2 状态回填 (✅)
- `run_all_tests.py` 最终验证 (1385 全绿)
- `python start.py check` 全绿
- 干跑 1 次 `python main.py` 验证启动 (30s)
- **git commit 4**: `docs(v5.2b): README 更新 + 收尾 + 回归验证`

---

## 10. Git commits (4 个, 独立可回滚)

```
1. feat(splitter): 小说切分核心 + Bridge + 测试 + 借鉴合规 (v5.2b)
2. refactor(v6.0): Phase C2 拆 app.js → 7 个 web/views/*.js
3. feat(ui): 小说切分第 8 视图 (v5.2b)
4. docs(v5.2b): README 更新 + 收尾 + 回归验证
```

---

## 11. 复审 Checklist (本次已修)

| 项 | 等级 | 状态 | 修法 |
|---|---|---|---|
| C-1 编码探测 | 🔴 | ✅ 已修 | 复用 `app.utils.read_file_text` |
| C-2 Apache §4(b)/(c) | 🔴 | ✅ 已修 | 借鉴头 8 段 + THIRD_PARTY_NOTICES §22-A/B/C 三个子节 |
| M-1 C2 拆 app.js | 🟡 | ✅ 已修 | 走方案 1, Session 2 专做 C2 |
| M-2 进度+取消 | 🟡 | ✅ 已修 | Bridge 4 方法 + `onSplitterProgress` 推送 + `cancel_splitter` |
| M-3 路径 `《》` | 🟡 | ✅ 已修 | `_book_name_to_slug` + `book_name_display` |
| M-4 SplitOptions 字段 | 🟡 | ✅ 已修 | 9 字段明确 + strip_whitespace/scan_lines 硬编码 |
| M-5 Bridge 4→3 | 🟡 | ✅ 已修 | 删 choose_splitter_files, infer_book_name 改名 |
| X-1 编码乱码告警 | 🟡 | ✅ 已修 | SplitResult.encoding_warning |
| X-2 staging 事务 | 🟡 | ✅ 已修 | 移植 splitter_service.py:1107-1136 |
| X-3 E2E 测试 | 🟢 | ✅ 已修 | 3 项 e2e 走临时 PROOFREADER_HOME |
| X-4 风险表 6→13 | 🟡 | ✅ 已修 | R1-R13 全部登记 |
| X-5 性能限流 | 🟢 | ✅ 已修 | max_concurrent_books=3 |
| X-6 4 段标准 | 🟡 | ✅ 已修 | 借鉴头 8 段 (Apache 4 + 墨准 4) |

**复审结论**: 13/13 已修, 可开干.

---

## 引用

- Verifier 审核报告 (子 agent): 14 个 file:line 引用
- CLEANUP_PLAN.md:215-264 — Phase C2 拆 app.js 计划
- AGENTS.md §10/§29/§32/§36 — 借鉴纪律 + 双引擎零重复
- 小说分析器 `splitter_service.py:1-49` — 借鉴头格式
- 小说分析器 `LICENSE` — Apache 2.0 完整 200 行

---

**最后更新**: 2026-09-13
**生成依据**: 父会话 Mavis + verifier 子 agent 审核 (2026-09-13)
