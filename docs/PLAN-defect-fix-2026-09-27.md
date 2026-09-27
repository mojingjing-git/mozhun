# 缺陷修复计划 v3 — 2026-09-27 全量扫描批次

> **v1 → v2**: 三路 verifier 复审全部 FAIL，修订 5 处改法缺陷、提级 2 项、新增门禁 F0。
> **v2 → v3**: 用户拍板 17 项决策（2026-09-27），F10 增加"重试 1 次后放行"兜底层，
> D2-①（命名空间）从延后提级为 F15。
> **v3 → v4**: 第四路 verifier 复审 v3 增量，判 **FAIL**，报 5 个 BLOCKER + 8 个优化项。
> v4 修掉全部 5 个 BLOCKER（其中 **B-1/B-2 是 v3 兜底层的状态机设计错误**，
> 由 verifier 实测出 flag 轨迹 `[False, False]` 与 audit 恒空）+ 6 个优化项。
>
> **依据**: 2026-09-27 四路代码扫描 + 跨层事件契约对账 + 三条最高危结论独立复现
> + **四路** verifier 复审（技术正确性 / 回归风险 / 范围优先级 / v3 增量复核）+ 用户决策。
> **范围**: 批次 0（门禁 2 项）+ P0（8 项）+ P1（7 项）= **18 个执行单元 / 16 个编号项**。
>
> **状态**: ✅ 已批准（2026-09-27）→ **v4 复审 BLOCKER 已清** → 待实施
> **版本目标**: v5.4.3
> **最后更新**: 2026-09-27

---

## 0. 决策记录（2026-09-27 用户拍板）

| # | 决策点 | 裁决 | 依据 |
|---|---|---|---|
| D-01 | 实施起点 | **先做批次 0** | 后面 14 项的回归有效性全押在门禁上；F3 的回归用例落在门禁盲区 |
| D-02 | F6 告警语义变更 | **做**，接受短文本偏敏感 | 等长全改写静默通过是**数据正确性**问题；告警偏敏感只是**噪音**问题，后者危害小 |
| D-03 | F10 守卫放宽 | **做 + 加"重试 1 次后放行"兜底层** | 把误杀风险压到接近零；兜底层比放宽守卫本身更稳 |
| D-04 | F2 直角引号取舍 | **接受**（`‘good’` 类不再直角化） | 与 `punct_fix` 自身"宁漏勿误"口径一致；替代方案会造出落单引号 |
| D-05 | F12 焦点归还 | **必做** | 不做只是把"误执行破坏性操作"换成"键盘失灵" |
| D-06 | F7 体积上限 | **做，200 万字** | 宁可明确失败，也不让用户看着进度条卡死 |
| D-07 | F6 下限阈值 | **200 字符** | 落在测试用例（4~6 字）与生产 chunk（6000+）之间 |
| D-08 | F14 下限阈值 | **15 字** | 参照 `_AD_WEAK` 的 40 字下移 |
| D-09 | F7 上限阈值 | **200 万字** | 与 `_DEAI_WHOLE_FILE_LIMIT`(20000) 语义独立（后者是"整文件单次调用"）|
| D-10 | F8 重试预算 / buffer 上限 | **2 次 / 2000 条** | 无先例，纯工程取值 |
| D-11 | F10 既有断言 `:453` | **改夹具**（不是改判据） | 用例名叫"长解释文本"但夹具只有 14 字，本就名不副实 |
| D-12 | F6 既有断言 `:196`/`:163` | **不动** | 200 下限让它们不再红；本批次不扩大范围去改测试设计 |
| D-13 | 用户目录清理 | **做**（先给用户看 `app-debug.log` 末尾再删） | 941KB 测试噪音 + 3 个 `%TEMP%` 孤儿断点，日后排查真实问题会被干扰 |
| D-14 | 计划文件入库 | **随批次 0 的 commit 一起入库** | 与 `docs/PLAN-workflow-split-v5.3.md` 等先例一致；§7 执行记录要一路回填 |
| D-15 | D2-① 命名空间 | **提级为 F15，放批次 2 开头** | 与 F9 改同一批文件，成本重合；顺手消掉一个已确认的死代码 bug |
| D-16 | 版本号 | **就标 v5.4.3** | 真值源缺失（D1）留待延后，不塞进本批 |
| D-17 | 延后清单排期 | **本批完成后紧接"测试基建"** | 它是 C2/C3 拆 `app.js`/`style.css` 的硬前置；顺序不能反 |

### 0.1 阈值声明

D-07~D-10 的四个阈值与 `ai_score_local.py` 的六维权重、`harness.py` 的 50 条 cap 同属
**「初始拍定值，未做真实样本校准」**。按 `AGENTS.md` §34 口径标注，
**严禁在代码注释/文档中编造"实测平均 N"之类的校准数据来源**。

---

## 1. 批次 0 — 门禁（**必须最先做**）

> **为什么排最前**: F3 的回归用例落在 `tests/test_novel_splitter.py`，而该文件是门禁盲区。
> 不先修门禁，后面 14 项的回归有效性不可信 —— 会「全绿但没修好」。

### F0-① `run_all_tests.py` 门禁计数失真

**位置**: `run_all_tests.py:37-38`（`out.count("[PASS]")`）、`:49`（`[-3:]` 回显）、`:27`（env 构造）

**根因**（已实测）:
17 个手写套件逐条 `check()` 打印 → 计数 = 断言数；2 个 unittest 套件只打印一行汇总 → 计数 = 1。
```
test_novel_splitter  testsRun = 63  →  门禁算 1
test_harness_split   testsRun = 35  →  门禁算 1
                    合计 98 个真实 test 方法，门禁只看到 2 个
```

**失效方向（比"数字不准"严重）**: `unittest.wasSuccessful()` 对 **0 用例返回 True**，
故零用例套件（类名写错 / 用例被误重命名）会打印 `[PASS] test_x (0/0)`、rc=0 → **静默绿灯**。

**改法**（只改 `run_all_tests.py`，不动 19 个测试文件）:
1. 额外正则解析 `^Ran (\d+) tests? in` 与 `^(OK|FAILED)`，
   对 unittest 套件用 `testsRun - (failures + errors)` 补进 `total_pass`，并回显该行
2. `[:3]` 回显改为「最后 3 行 **加上** 含 `Ran `/`OK`/`FAILED` 的行」
3. 两个 unittest runner 各加 `assert total > 0`，堵掉 `(0/0)` 假绿
4. **同时在 `:27` 构造 env 时预置 `PROOFREADER_HOME=<一次性 mkdtemp>`**（见 F0-② 的防复发）

**验证**: 改完重跑一次，确认两个 unittest 套件的数字从 `1` 变成 `63` / `35`，
总基线从 1581 变成 **1677**。

### F0-② `import test_isolate` 补齐 + env 预置

**位置**: `tests/test_novel_splitter.py:8-19`、`tests/test_harness_split.py`、`run_all_tests.py:27`

**根因**: `test_isolate.py` 靠**进程启动前**设 `PROOFREADER_HOME`，而
`app/logger.py:14` / `app/utils.py:595` / `app/style_profiles/loader.py:41` /
`app/novel_splitter.py:81` **四个模块都在 import 期把该变量冻成模块常量**。
漏一行 → 隔离静默失效 → 跑一次门禁就往用户真实 `~/.proofreader/app.log` 追加
（当前 **941KB**；`checkpoints/` 下有 3 个 `%TEMP%` 孤儿断点）。

**改法**（两层）:
1. **止血**: 两文件各加一行 `import test_isolate  # noqa: F401`
   （放在 `sys.path.insert` 之后、任何 `from app.*` 之前）
2. **防复发**（更重要）: `run_all_tests.py:27` 构造 env 时**预置**
   `PROOFREADER_HOME=<一次性 mkdtemp>`。任何文件将来再漏 `import test_isolate`
   也污染不到用户目录 —— 彻底解除「必须在 import 前」这个单点脆弱约定。
   （注意 `test_isolate.py:35-38` 对预设值会打一条 WARN，属预期行为）

### F0-③ 用户目录清理（D-13）

**范围**: `~/.proofreader/app.log`(941KB) + `app-debug.log`(800KB) 的测试噪音，
`checkpoints/` 下 3 个 `%TEMP%` 孤儿断点。

**前置**: **先向用户展示 `app-debug.log` 末尾若干行**（DEBUG 级含网络异常详情，
可能对用户之前的排查有价值），确认后再删。删除走可恢复删除通道。

---

## 2. 批次 1 — P0 数据正确性（8 项）

### F1. `harness.py:290` CRLF 位置映射多吃一个字符 ✅

**根因**:
```python
orig_end = orig_last + (2 if corrected[orig_last] == "\r" else 1)
```
`_crlf_map`（`:171-178`）对**孤立 CR** 是 1:1 映射，此处假定 `== "\r"` 必是 `\r\n` → 多吃一格。

**实测**: `('甲\r\n乙\r丙丁', '甲\n乙\r', 'ZZ')` → `'ZZ丁'`（「丙」静默删除），
audit 报 `OK` + note"换行归一后匹配"，用户与审阅者都看不出来。

**改法**:
```python
orig_end = orig_last + (2 if (
    corrected[orig_last] == "\r"
    and orig_last + 1 < len(corrected)
    and corrected[orig_last + 1] == "\n"
) else 1)
```

**回归用例**（`tests/test_harness.py`，仿 `:121 test_boundary_8_crlf_normalize`）:
| 输入 | 期望 | 守什么 |
|---|---|---|
| `('甲\r\n乙\r丙丁', '甲\n乙\r', 'ZZ')` | `'ZZ丙丁'` | **被修的那行** |
| `('a\r\nb', 'a\n', 'ZZ')` | `'ZZb'` | 真走 CRLF 映射路径 |
| `('甲\r\n乙\n丙', '甲\n乙', 'ZZ')` | `'ZZ\n丙'` | 常规归一不回归 |
| 上述每条二次 `apply_edits` | 无新编辑 | 幂等 |

> 注：`('a\r\nb', 'a\r', 'ZZ')` 走不到 `:290`（`corrected.count('a\r') == 1`
> 在 `:267-272` 的直接替换路径就返回了），**是空断言，已剔除**。

---

### F2. `punct_fix.py:290-311` 直角引号吞英文撇号 ✅

**根因**（实测）: `_fix_quotes`（`:201-228`）正确区分三类撇号并记入 `apos_idx`，
但 `_apply_rect_quote_style` 无条件把 `’` 映射成 `』`/`」`。
```
curly (total=3): 中文里夹英文 don’t touch it， 还有 James’ 的书。   ✓
rect  (total=5): 中文里夹英文 don」t touch it， 还有 James」 的书。   ✗
```

**已否决的 v1 改法**: `isalnum` 邻接启发式。实测 `他说 'a' 好` → `他说 「a’ 好`（落单）；
`1980'1990'` 数字成对场景同样被拆成不对等。

**改法**（`isalpha`，与 `_fix_quotes:202-214` 语义逐字对齐）:
```python
# 源码用转义串 "\u2019", 不是字面 '’' —— 补丁锚点按转义形式写
elif c == "\u2019":
    # v5.4.3: 英文撇号 (don't / James') 不参与直角化, 字形已由 _fix_quotes 规范为 ’。
    # 判据严格复刻 _fix_quotes 的两条撇号规则 (isalpha, 不是 isalnum):
    #   规则1 两侧均为 ASCII 字母 → 字母夹缝缩略 (don't)
    #   规则2 前邻 ASCII 字母串长度>=2 且后邻非 ASCII 字母 → 属格 (James')
    # 用 isalnum 会把「中文单引号对里包 ASCII」('a'/'I') 和「数字成对」(1980'1990')
    # 误判为撇号, 产出落单直角引号。
    prev_ch = chars[i - 1] if i > 0 else ""
    next_ch = chars[i + 1] if i + 1 < len(chars) else ""
    if (prev_ch.isascii() and prev_ch.isalpha() and next_ch.isascii() and next_ch.isalpha()):
        continue
    if prev_ch.isascii() and prev_ch.isalpha() and not (next_ch.isascii() and next_ch.isalpha()):
        j = i - 1
        run_len = 0
        while j >= 0 and chars[j].isascii() and chars[j].isalpha():
            run_len += 1
            j -= 1
        if run_len >= 2:
            continue
    chars[i] = "』" if in_span else "」"
    count[0] += 1
```

**已知取舍（D-04，CHANGELOG 须明写）**: `isalpha` 口径下 `‘good’`、`‘好’AB` 的闭引号
因拉丁邻接不再直角化 —— 与 `_detect_imbalance:322-323` 已记录的"宁漏勿误"取舍同类。

**注释修正**: 会改行长度的**不止第 6 步**。逐个核过 `_fix_line`:
第 2 步 `_fix_parens`(`:371`)/ 第 3 步(`:374-402`) 长度不变；
**第 4 步 `_fix_ellipsis_run`(`:407-408`)** `。。。`→`……` 3→2；
**第 5 步 `_sub_dash`(`:411-425`)** `–`→`——` 1→2；
**第 6 步 `_sub_repeat`(`:440-444`)** `！！`→`！` 2→1。
（所选改法无下标，不受影响，但注释须改成"第 4/5/6 步"，否则误导后来人。）

**回归用例**（`tests/test_punct_fix.py`，仿 `:117` 表驱动 + `check(f"{src!r} -> {want!r}")`）:
| 输入（`quote_style="rect"`）| 期望 |
|---|---|
| `"他说 'a' 好"` / `"他说 'I' 好"` | `「a」` / `「I」` ← v1 改法的回归 |
| `"生于1980'1990'1991'1992年"` | `「1990年间，卒于1991」1992年` |
| `"中文里夹英文 don't touch it, 还有 James' 的书。"` | `don’t` / `James’` 保留 |
| `"他说：“好。”"` | `「好。」` |
| `"「他说‘好’。」"` | `「他说『好』」` |
| **`"他说：“don't 真的吗？！”"` + `repeat_compress=True`** | 不抛异常且 `don’t` 保留 |

---

### F3. `novel_splitter.py:646-651` 同号去重静默删特章正文 ✅

**根因**（实测）: 去重 key 是 `(blk.volume, blk.num)`，**特章（序章/楔子/番外/引子/尾声）`num` 恒为 `None`**，
同卷内所有短特章共享 `(None, None)`。组内任意一章 ≥5000 字，组内所有 <1000 字的被删。
```
输入 4 章: 序章(6000字)/楔子(500字)/番外(300字)/第一卷·第一章(3000字)
输出: TOTAL=2  dedup_count=2   ← 800 字正文静默消失
```
触发条件"序章在卷首之前"是中文小说常态。
**同源矛盾**: `:773` 的最小字数过滤用 `or b.num is None` **保护**特章，`:646` 却**暴露**特章。

**改法**:
```python
# v5.4.3: num is None = 特章 (序章/楔子/番外/引子/尾声), 不参与同号去重
# — 与下方 min_words 过滤 (or b.num is None) 口径统一
if blk.num is None:
    continue
```

**顺带项（v1 错，必须同时改两处）**: 只补 `_CN_DIGIT_MAP`(`:138-142`) 的 `两` **完全无效** ——
`:332` 的字符类 `[零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟\d]` **本身不含「两」**，
`re.search` 匹配不到。**必须同时改 `:332` 的字符类**（加 `两`）。
（另：v1 说"14 条章节正则"不准，`CHAPTER_PATTERNS` 实为 **16 条**，`:90-105`。）

**回归用例**:
- 扩 `TestDedupSameKey`（`ChapterBlock(0, 标题, 正文, wc, num=None)`，仿 `:350-355`）
  - `[序章(6000字,None), 楔子(500字,None)]` → 全部保留，`dedup_count == 0`
  - `[第一章(num=1,6000字), 第一章(num=1,500字)]` → 仍删 1 条
- 端到端挂 `TestSplitText`（仿 `:517 test_chinese_chapter`）
- **`_extract_chapter_num('第两百章') == 2`**（只测 `cn_to_int('两百')==200` 会给假绿灯）

---

### F4. `processor.py:118` 引擎持有 `Backend._config` 活引用 ✅

**根因**: 持引用非副本；`set_config`（`web_backend.py:195`）与每次 `start_proofread`（`:568-577`）就地改同一对象。
引擎**逐块现场读**：`:771` `_harness_active()`、`:786` `temperature`、`:767` `_base_system_prompt()`。
**触发路径无守卫**: `setProcessingButtons`（`app.js:1584-1606`）只禁 start/add/clear/pause/resume/cancel，
`saveConfig`（`app.js:2437-2449`）照发 `set_config`；侧边栏切入口同理。

**后果**: ① 逐条轨跑一半切整篇轨 → `corrected` 是**两种协议的混合拼接**；
② **断点指纹撒谎**（`compute_prompt_hash` 在 `:281` 算一次固定，实际产出在被篡改的配置下生成）。

**改法**（`from dataclasses import replace` 放模块头 import 区，不塞方法体）:
```python
def __init__(self, config: ProjectConfig):
    # v5.4.3: 配置快照 — 防运行中 set_config / 切入口就改写正在跑的引擎行为
    # (32 字段全标量, dataclasses.replace 浅拷贝即充分)
    self.config = replace(config)
```

**正面副作用（commit message 须写）**: 快照同时修好 `_file_done_payload`(`:629`) 与
`_collect_results`(`:1833`) 的 `effective_workflow(eng.config)` —— 中途切轨不再把
"结果来源"标错轨，与 `AGENTS.md` §41 方向一致。

**回归用例**（**挂 `tests/test_components.py`**，仿 `:241-247`；
不用 `test_chunk_lifecycle.py` —— 那里全是 async + patch 重活，纯同步快照断言不合适）:
- 建 engine 后改 `cfg.prompt_mode` → `engine.config.prompt_mode` 仍为原值
- 建 engine 后改 `cfg.workflow_mode` → `engine._harness_active()` 不变
- `compute_prompt_hash_for_config(cfg)` 与 `engine._current_prompt_hash` 一致

---

### F5. `app.js:1924` + `:1395` 本地模式屏显旧文本 ✅

**根因**:
```javascript
app.js:1924   const partial = this.streamingContent[fileKey] || t.corrected || '';   // 屏显
app.js:2209   const text = t.corrected || this.streamingContent[...] || '';           // 复制
app.js:2244   同上                                                                    // 导出
```
`punct_local`（`processor.py:1127-1139`）/ `md_local`（`:1100-1115`）**一次 `on_stream` 都不发**，
`streamingContent` 只在「清空列表」(`:1105`)、「移除单文件」(`:1120`) 清，**新一轮从不清**。

**v1 改法只修了一半**: `(t.status === 'running' ? streamingContent : '')` 在本地模式
**运行期**仍取到残留（`processor.py:482` 的 `on_file_start` 对本地模式照发
→ `app.js:404` → `markFileRunning`(`:1625-1638`) 设 `'running'`）。

**改法**（两处叠加）:
```javascript
// app.js:1395 附近（既有 renderState 重置循环内）
for (const p of paths) {
    this.renderState[p] = { ... };          // 既有
    delete this.streamingContent[p];        // v5.4.3 新增: 与 renderState 同生命周期
}
```
```javascript
// app.js:1924
// v5.4.3: 本地模式 (punct_local/md_local) 运行期不发 onStream,
// streamingContent 是流式期暂存, 残留值会盖掉本轮 t.corrected
const partial = (t.status === 'running' ? this.streamingContent[fileKey] : '') || t.corrected || '';
```

**回归用例**（`tools/smoke_ui.py`，仿 `_check_think_strip_stream:366`）。
⚠ 冒烟桩的 `start_proofread` 走 Proxy 兜底返回 `{ok:true}`（`_init_script:109`），
"切 punct_local 重跑"根本跑不起来 → **必须手工注入**:
```
App.tasks = [{path, status:'completed', corrected:'', ...}]
App.streamingContent[path] = '旧文本'
App.handleEvent('onTaskComplete', {path:{status:'completed', result:{corrected:'新文本', original:'原文'}}})
→ 断言 #compare-revised.textContent 含「新文本」
```
另补「缓存命中路径」: `markFileDone`(`:1648`) 只设 `status`、**不写 `t.corrected`**（要等 `:1752`）。

---

### F13. `app.js:1841` `_provenanceKey` 单标量 + D3 渲染顺序 ⬆️

**根因**（我已复核）:
```javascript
const key = mismatch ? `${t.workflow}|${cur}` : '';   // ← 不含 fileKey
if (key === this._provenanceKey) return;
...
btn.addEventListener('click', () => this._rerunSingleFile(fileKey, { confirmOverride: false }));
```
key 只由 workflow + 当前轨决定 → A/B 同轨时切到 B 早退 → **提示条仍是 A 的文案，
按钮闭包仍持有 A 的 fileKey**。

**后果**: 用户在 B 上点"用整篇重跑"，**实际重跑并覆盖 A**，且 `{confirmOverride:false}` **跳过二次确认**。

**改法**:
```javascript
// v5.4.3: key 必须含 fileKey — 否则同轨的两个文件 key 相同, 切到第二个时早退,
// 提示条文案与按钮闭包都还锁在上一个 fileKey (在 B 上点重跑会重跑 A)
const key = mismatch ? `${fileKey}|${t.workflow}|${cur}` : '';
```

**D3 必须同批**: `app.js:1862` 的 `_renderProvenance(fileKey)` 在 `:1884` 的
`if (fileKey !== this.selectedFileKey) return;` **守卫之外** —— `scheduleRender`(`:1821-1829`)
用 RAF 排队，回调在用户切换文件之后才执行。两处是不同缺陷（同 40 行内），
但只修一处仍可能因 RAF 排队时序重现。
→ 把 `this._renderProvenance(fileKey)` 移到 `:1884` 守卫之后，与已在那里的
`renderAuditPanel`(`:1888`) 同位置。

**回归用例**（`tools/smoke_ui.py`）:
- A/B 同为 harness 且都有 completed 结果 → 切到 B → 断言提示条文案与按钮闭包都指向 B
- 流式渲染中切文件 → 断言提示条不被上一个文件的 RAF 回调重新打开

---

### F14. `novel_splitter.py:822-833` `_AD_STRONG` 无下限护栏 ⬆️

**根因**: `_AD_WEAK` 有 `len(s) <= 40 and not any(p in s for p in "，。！？；：,;!?")` 双重护栏（`:832`），
**`_AD_STRONG` 只有上限（`:827` 的 200 字）、没有下限** → 任何 ≤200 字含强词的行被整行删除。

**提级理由**: 与 F3 **同属"静默删用户正文"**，触发面更广。F3 进 P0 它延后不自洽。

**改法**:
```python
# v5.4.3: 强词也需护栏 — 原实现只有 200 字上限, 无下限,
# 导致 "他每天去楼下投喂那只流浪猫。"(14字) 这类正常叙述行被整行删除。
# 阈值 15 = 初始拍定值, 未做真实样本校准 (见计划 §0.1)
if _AD_STRONG_HIT and len(s) >= 15 and not any(p in s for p in "，。！？；：,;!?"):
    return True
```

**回归用例**（`tests/test_novel_splitter.py`）:
- `"他每天去楼下投喂那只流浪猫。"` → `_is_ad_line` **False**
- `"最新章节发布啦。"` / `"他翻开书友群里的聊天记录。"` → False
- 真实广告行（长 + 无句末标点 + 含强词）→ **仍 True**

---

## 3. 批次 2 — P1 卡死 / 崩溃（7 项）

> **实施顺序有硬依赖**: `F15 → F9 → F8`。理由见各项。

### F15. `web/views/novel-splitter.js` `window.App` → `window.app` ⬆️（D-15）

**位置**: `web/views/novel-splitter.js:254`、`:262`、`:277`、`:278`

**根因**（我已复核）:
```javascript
// app.js:3459
window.app = App;                          // ← 只写小写
// novel-splitter.js:277
if (!window.App) window.App = {};          // ← 自建空对象（大写）
window.App.splitter = splitter;             // :278
// novel-splitter.js:254
if (window.App && typeof window.App.appendLog === 'function')   // ← 恒 false
```
`window.App` 只是一个**空对象**，没有 `appendLog`/`showToast` →
**两个 `typeof === 'function'` 守卫恒假 → 小说切分的日志行和 toast 永久走 else 分支**。
`build.spec` 是 `console=False`（windowed 打包），用户什么都看不到。
`window.App.splitter` 亦是**只写不读**（`app.js` 对 `splitter` 零引用）。

**改法（⚠ v3 写"4 处"是错的，实际 6 处 —— 漏掉调用点会引入 TypeError）**:

`web/` 全目录 `window.App` 命中且仅命中 `novel-splitter.js` 这 6 处代码引用
（另有注释 `:7`、`:276`）:

| 行 | 内容 | 角色 |
|---|---|---|
| `:254` | `if (window.App && typeof window.App.appendLog === 'function')` | 守卫 |
| **`:255`** | `window.App.appendLog('[小说切分] ' + msg)` | **调用点** |
| `:262` | `if (window.App && typeof window.App.showToast === 'function')` | 守卫 |
| **`:263`** | `window.App.showToast(msg, type \|\| 'info')` | **调用点** |
| `:277` | `if (!window.App) window.App = {};` | 空对象兜底 |
| `:278` | `window.App.splitter = splitter;` | 挂载 |

```javascript
// 6 处全部改 (守卫 + 调用点成对, 只改守卫会因 window.app.appendLog 存在而为真,
// 进入分支后 window.App.appendLog 仍是 undefined -> TypeError, 比现状更糟)
// :254-255
if (window.app && typeof window.app.appendLog === 'function') {
  window.app.appendLog('[小说切分] ' + msg);
// :262-263
if (window.app && typeof window.app.showToast === 'function') {
  window.app.showToast(msg, type || 'info');
// :277-278
if (!window.app) window.app = {};
window.app.splitter = splitter;
```
**连带收益**: 修好后 `window.app.splitter` 成了真正的注册点，F9 可用它。

**赋值顺序无风险**（已核实）: `index.html:659`（app.js）先于 `:661`（novel-splitter.js），
且 `window.app = App` 在 `app.js:3459` 是**顶层语句**（不在 `init()` 里）→ 运行时可解析，不会被覆盖。

**回归用例**（`tools/smoke_ui.py`）:
- 触发一次切分操作 → 断言**日志区出现** `[小说切分]` 开头的内容（当前必然不出现）
- 触发一次失败切分 → 断言 toast 容器里出现对应提示

**顺带（低风险，可随时做）**: `novel-splitter.js:270-274` 的 `escapeHtml` 与
`app.js:3447-3455` 重复且**行为不同**（splitter 版 `String(null)` → 字面量 `"null"`；
app.js 版返回 `''`）。
→ 改为调用 `window.app.escapeHtml`。
**v3 说"`window.app` 在 F15 之前不可用"是错的** —— `app.js:3459` 是顶层语句，
`window.app` 今天就可用，故此合并**无顺序约束**，可独立于 F15 实施。
（当前唯一调用点 `:197` 传 `f.name` 恒为字符串，风险低；但属行为变更，改法里须写明。）

---

### F7. `md_strip.py:64-66, 189-191` 链接正则 O(n²) + `md_local` 无取消 ✅

**根因**（实测）:
```
20000 '[':  _LINK_RE 1.539s + _REF_LINK_RE 1.468s
50000 '[':  _LINK_RE 9.917s + _REF_LINK_RE 8.809s      ← 合计 ~18.7s
50000 '![':  _IMAGE_RE 4.730s + _LINK_RE 4.330s         ← 第三条同样无上界
加守卫后:     0.000s   (7 条语义等价抽查全 OK)
```
首段字符类 `[^\]]*` 无上界；行内无 `]` 时每个 `[` 起点吃完整行再逐格回退。

**为何比 v5.4.2 G2 更严重**: `md_local`（`processor.py:1100-1115`）**整文件不切块 + 无体积上限** →
拖进一个 JSON/日志文件，任务永远不返回。

**改法**:
1. **守卫包住三条正则**（`_IMAGE_RE` 在 `:64`，v1 漏了；v1 之所以没测出来是因为
   裸 `[` 行上 `_IMAGE_RE` 实测 0.000s，属测量盲区）:
   ```python
   # v5.4.3: 无 ']' 的行不可能匹配任何链接/图片类规则 (三条正则都必须吃掉字面 ']')
   # — 旧实现 O(k*n) 二次爆炸, 5 万个 '[' 单行实测 18.7s
   if ']' in line:
       line = _LINK_RE.sub(...)
       line = _REF_LINK_RE.sub(...)
       line = _IMAGE_RE.sub(...)
   ```
2. **体积上限**（v1 写得过简）: `md_local` 分支加阈值，**并写全 `_finalize_failed` 签名** ——
   真实签名是 `(key, task, start, err_type, err_msg)`（`processor.py:674`），
   v1 漏了 `start`。阈值 **200 万字**（D-09）。
   ⚠ **该阈值为初始拍定值，未做真实样本校准**（`AGENTS.md` §34 口径，见 §0.1）——
   实施时须在代码注释里落同样口径，不得编造样本来源。
3. **取消粒度须说清**: `strip_markdown` 是**单次同步调用**，
   "调用前后各查一次 `cancel_event`" 只做到**调用之间**可取消；200 万字在守卫后仍是秒级。
   **取消粒度 = 单次 `strip_markdown` 之间**；"md_local 块内即时取消"列入延后。

**回归用例**:
- **性能（两条）**（`tests/test_md_strip.py` 扩 `:277 test_v542_crlf_fence_and_perf` 同款计时）
  - `'[' * 50000` → `< 0.5s`
  - **`'![' * 8000` → `< 0.5s`** ← 守卫不全时会红
- 语义等价: `'[abc](x) 和 [ref][1] 和 ![i](y.png)'` 剥离结果与改前一致
- 边界: `'[abc'`（有 `[` 无 `]`）、`']'`（只有 `]`）→ 不崩、不变
- 引擎端到端（`test_engine_md_local_mode` 同款）: 超阈值 → FAILED 且 `error` 含类型名

---

### F9. `web_backend.py:1889-1894` `MULTI_ALLOWED` 漏 3 事件 ✅

**根因**: 未命中分类的事件走 `merged[name] = data`（`:1917-1919`），同窗口同名只留最后一条。
`onChunkProgress`(`:646`) / `onDeaiTextDrop`(`:391`) / `onSplitterProgress`(`:2031`+`:2050`) 都不在表里。

**后果**: 块级进度跳格；DeAI 拖入 33ms 内连拖两个文件 → **前一个 `paths` 静默丢失**；
**`onSplitterProgress` 是死事件** —— 后端推 2 处，`app.js:396-424` 的 dispatch
**无对应 case**（落 `default: console.warn` `:423`），切分进度条 0% 直接跳 100%。

**改法**:
1. 后端 `MULTI_ALLOWED` 补三个词（附注释说明各丢了什么）
2. **前端不走 `app.js` 的 dispatch case**（v3 方案已否决，理由见下）——
   改为在 splitter 对象上加通用事件入口，由 `app.js` 的 `default:` 分支委派:
   ```javascript
   // novel-splitter.js: splitter 对象上加
   onEvent(name, data) {
     if (name === 'onSplitterProgress') this.handleProgress(data);
   }
   ```
   ```javascript
   // app.js:423 (现为 default: console.warn(...))
   default:
     // v5.4.3: 通用委派 — 视图级事件由对应视图自处理, 本文件保持零 splitter 知识
     if (window.app && window.app.splitter
         && typeof window.app.splitter.onEvent === 'function') {
       window.app.splitter.onEvent(event, data);
     } else {
       console.warn('未知事件:', event, data);
     }
   ```

   **为什么否决 v3 的 `case` 方案**（v4 修正）:
   - splitter **完全自闭环** —— 自己绑全部监听（`:28/:31/:34/:207/:210`）、自己 init（`:282-285`）、
     进度 DOM `#splitter-progress-fill` / `#splitter-progress-stats` **只被它触碰**
     （`:119/:120/:122/:123/:144/:145`），`app.js` 全文对 `splitter` **零引用**
   - 写 `case` 会在 app.js 里制造**全应用唯一一处**跨模块耦合，并给 splitter 独占的
     两个 DOM 节点加**第二个写者**（后端 `done` 推送在 bridge 调用返回**之前**到达，
     `web_backend.py:2050-2055`，两路写者必然交错）
   - 委派方案保留 `app.js` 的零知识特性，同时 F9 仍需要 F15 提供的 `window.app.splitter` 句柄
     → **F15 → F9 的依赖依然成立**

3. **payload 有两种形态，必须分 `stage` 分支**:
   - `:2031-2035` `{stage:"processing", current, total, book_name}`
   - `:2050-2054` `{stage:"done", current, total, success, fail}`

   若用 `current/total` 算宽度，`done` 时会又跳成 100% 并**盖掉 `success/fail` 统计**。

   ⚠ **`current` 是 0-based**（`web_backend.py:2033` 的 `enumerate(..., start=1)` 之前是
   `for i, (src, name) in enumerate(zip(...), start=1)` —— 但 `current` 传的是 `i`，
   需实施时**实测确认**首推是否为 0）。若是 0-based，进度宽度需 `(current-1+1)/total`
   或改用 `current/total` 但 `processing` 首帧显示 0%。

**回归用例**:
- 后端: 同窗口 2 个 `onChunkProgress` → 都保留；同窗口 2 个 `onDeaiTextDrop` → 都保留；
  `onStream`/`onStatsUpdate` 仍只留最后一条（仿 `test_i3_flush_default_merge:433`）
- 前端（`tools/smoke_ui.py`）: `App.handleEvent('onSplitterProgress', {stage:'processing', current:1, total:3})`
  → 断言 `#splitter-progress-fill` 的 `style.width` 非 0 且非 100%；
  再注 `{stage:'done', current:3, total:3, success:2, fail:1}`
  → 断言 100% 且显示 `success/fail`
  → **夹具需 ≥2 本书**（单本时 `current/total` 恒 1，v3 写的断言会落空）
- 断言 `app.js` 全文**不含** `splitter` 硬编码（守卫委派方案确实保持了这一点）

---

### F8. `web_backend.py:1921-1937` `_flush` 丢事件 ⛔（**必须后于 F9**）

**根因**: 先 `clear()` buffer（`:1921-1922`）再序列化推送；
`json.dumps`（`:1930`）在 `try`（`:1933`）**之外**。
若丢的是 `onFileDone`/`onTaskComplete` → **`isProcessing` 永不复位，按钮永久禁用**。

**⚠ v1 回灌方案的四个洞**:
1. **回灌后没有任何东西重新 arm flush**。`:1922` 已把 `_push_pending = False`，
   `threading.Timer`（`:1869`）只在 `_push` 里创建 → 失败批次要等**下一次 `_push`** 才重试。
   **若失败的就是最后一批（`onTaskComplete`），后面再无 push → 事件永不送达 —— 正是本项要修的 bug。**
2. **幂等性 v1 说"均为幂等赋值"不成立**。已核实的**非幂等** handler:
   - **`_applyDropgedText`（`app.js:2169-2190`）** — 重复的 `onDeaiTextDrop` 会再读一次文件、
     再弹一次三命令框，选「追加到末尾」→ **同一段文本被追加两遍**。
     **F8 回灌 + F9 把 `onDeaiTextDrop` 加进 `MULTI_ALLOWED` = 静默文本损坏。**
     ⚠ **v4 措辞修正**: 这**不是代码层面的先后依赖** —— 终态与"F9 先落 / F8 后落"完全相同,
     重复投递 bug 是在 F9 落地那一刻才诞生的。所以这是
     **「两项必须原子提交、不可单独发布」的流程约束**, 而非必须严格串行。
     并行准备可以, 但 F8 的步间 review 必须显式核对 F9 已生效。
   - **`onTaskComplete`（`:1709-1781`）** — 重复投递再打一条完成日志 + 再弹一次 toast；
     且 `:1718-1722` 的 `task_id` 守卫在首次投递把 `currentTaskId` 置 null 后**失效**
   - **`markFileRunning`（`:1625-1631`）** 会 `t.audit = []; t.warnings = false` ——
     迟到的重复 `onFileStart` 会**擦掉已完成的改动清单**
   - `onLog` 是累积类 → 日志行翻倍
3. **重试风暴 + buffer 无界增长**。持续失败下每 33ms 一次，且每次 `buffer[:0] = events` 多一份，
   **单调增长** → `json.dumps` 成本线性上升，总代价 O(n²) + 内存无界。
4. **毒丸**。`json.dumps` 失败（自引用 list → `ValueError: Circular reference detected`）的批次
   被回灌后**永久留在 buffer** → 此后每次 flush 都在它上面失败 → **整条事件通道对该会话永久死掉**。
   **v1 的回归用例恰好把这个坏行为写成了期望。**

另: v1 的"window 为 None 则不回灌"守卫是**不可达分支** ——
`self._window` 全仓只在 `:114`（构造默认 None）与 `:332`（注入真 window）赋值，**从不置 None**。
真实故障态是"window 还在但 WebView 已死 → `evaluate_js` 抛异常"。

**改法**（四件事一起做）:
1. **回灌后重新 arm 一次 Timer**（或立即同步重试一次）
2. **重试预算**：每批/每事件 **2 次**（D-10），超预算丢弃 + `logger.error`
3. **`json.dumps` 失败 → 丢弃该批**（或逐事件序列化只丢毒事件），**绝不回灌**
4. **buffer 长度上限 2000 条**（D-10），溢出时丢最旧的 `onLog`；
   用「连续失败计数 ≥ N 即停止推送」替代不可达的 `_window is None` 守卫

⚠ **第 2/4 条的两个数（2 次 / 2000 条）与第 1 条的重试上限均为初始拍定值,
未做真实样本校准**（`AGENTS.md` §34 口径, 见 §0.1）—— 实施时须在代码注释里落同样口径。

**回归用例**（`tests/test_web_backend_proofread.py`，仿 `:402 test_i3_flush_multi_events_not_merged`）:
| # | 场景 | 断言 |
|---|---|---|
| 1 | `evaluate_js` 抛异常（window 存在）| 批次回灌 **且 Timer 被重新 arm** |
| 2 | 回灌后无任何新事件 | X ms 内至少有一次重试 flush，**不永久滞留** |
| 3 | `json.dumps` 抛错（循环引用）| 批次被**丢弃**，buffer 不留毒丸，后续 flush 正常 |
| 4 | 同一批连续失败 > 预算 | 丢弃 + `logger.error`，**无 33ms 风暴** |
| 5 | 正常路径三分类 | 行为不变 |

---

### F10. `harness.py:121-137` 守卫误判自然答复 + 兜底层 ⛔（D-03）

**根因**: 白名单只有字面量 `无需修改`（`:115`）且长度 ≤40（`:118`）。
**实测**:
```
'我已仔细检查全文，未发现需要修改之处。'  → True（误判）
'全文检查完毕，没有发现问题。'           → True（误判）
'经过逐句核查，这篇文章没有明显的错别字或标点错误。' → True（误判）
'好的。'                                 → True（误判）
```
后果：本该零改动的文件 → `raise` → 烧重试 → **整文件 FAILED**。
而"全文无错"恰是逐条校对轨最该成功的结局。

**v1 短语白名单的三重问题**:
1. **修不好主场景** —— verifier-1 实测「用 v1 自己的代码跑 v1 自己的实测表，第 5 条仍 = True」，
   因为"没有错"不是"没有**明显的**错别字"的子串
2. **漏 6 种高频措辞**（实测全仍判可疑）: `看起来没问题。` / `整体质量不错，无需调整。` /
   `文章结构完整，标点符号使用正确。` / `未见错别字。` / `检查完毕，一切正常，保持原样。` / `没有错误。`
3. **引入假阳性** —— 实测 80 字推理倾倒（含"没有发现"、不含编辑载体字面量）→ 放行。
   v1 给的理由"用户能从改动清单为空看出"**在代码里不成立** ——
   `app.js:1998-2003`，`audit.length === 0` 时 `renderAuditPanel` **直接 `panel.hidden = true`**，
   用户只看到"完成、零改动" —— 恰是 v5.4.1（`harness.py:109-114`）要消灭的失败态。

**v2 判据（短语白名单作废）**:
```python
def content_suspicious_noop(content: str) -> bool:
    """True = 应重试; False = 合法的"无需修改"答复, 放行。

    v5.4.3 口径变更: 从「白名单精确匹配」改为「编辑载体拦截 + 长度阈值」。
    旧实现只认字面量 '无需修改' 且 <=40 字, 模型用任何别的措辞报告
    "没找到错误" 都会被判可疑 -> raise -> 烧重试 -> 整文件 FAILED,
    而"全文无错"恰是逐条校对轨最该成功的结局。
    新口径: 短答复一律放行(不查短语), 长文本(混大段推理)仍可疑;
    编辑载体字面量(old_text/new_text)无论长短一律可疑 —— 保留 v5.4.1 的核心防线。
    长度阈值保持 40 (原注释出处), 放宽需按 AGENTS §34 标注"待真实样本校准"。
    """
    c = (content or "").strip()
    if not c:
        return False
    if any(m in c for m in _EDIT_CONTENT_MARKERS):   # old_text / new_text 字面量 → 一律可疑
        return True
    return len(c) > _NOOP_CONTENT_MAX_LEN
```

**🆕 兜底层（D-03 新增，用户拍板）** —— `processor.py:950-961` 的抛错点改为:

```python
# v5.4.3: 可疑不直接 FAILED — 记可疑, 走一轮重试; 重试后仍可疑则**放行**。
# 理由: "全文无错"是逐条校对最常见的正常结局, 因措辞不匹配判 FAILED 的代价
# (用户看到红色失败 + 真实结果被丢弃) 远大于放行一个可疑空结果的成本。
#
# ⚠ 三个必须满足的条件 (v3 设计错误的复审结论, 见 §8 BLOCKER B-1/B-2/B-4):
#   ① 计数按 task_key 索引, 不用引擎级布尔 — 否则并发跨文件串预算
#   ② 重置在 _process_file_async 的 for attempt **之前**, 不能放 _call_api_stream
#      (那里每个 attempt 都执行一次, 会把标志抹掉导致本分支永不可达)
#   ③ max_retries==0 时没有第二次机会 → 首轮就放行, 不 raise
suspect_times = self._harness_suspect.get(task_key, 0)
retry_budget = max(1, int(self.config.max_retries or 0))   # 0 也给一次重试
if not edits and content_suspicious_noop(_content):
    preview = _content.strip().replace("\n", " ")[:80]
    if suspect_times < retry_budget:
        self._harness_suspect[task_key] = suspect_times + 1
        self._log(f"[harness] {name}: 模型未产出编辑但 content 非空 "
                  f"(疑似未走工具链), 第 {suspect_times+1} 次可疑, 重试 — 预览: {preview}")
        raise ValueError(
            f"harness 模型未走工具链 (content {len(_content)} 字符, 无 tool_calls)"
        )                                            # 原有路径
    # 预算耗尽 → 放行, 落入下方 corrected = text 的正常无修改路径
    # ⚠ 必须写 audit 条目: 否则 file_audits[key] 为空 → audit_has_warnings 为 False
    #   → 前端 renderAuditPanel (app.js:1998-1999) 直接 panel.hidden=true,
    #   用户只看到绿色"完成、零告警", 恰是 v5.4.1 要消灭的失败态。
    self._log(f"[harness] {name}: 连续 {suspect_times} 次可疑无 tool_calls, 放行 "
              f"(不判定为失败) — 预览: {preview}")
    chunk_audit.append(_make_audit(
        -1, "WARN_NOOP_SUSPICIOUS",
        f"模型连续 {suspect_times} 次未产出 tool_calls 且 content 非空, 已放行不判失败",
        note=preview[:PREVIEW_LIMIT]))
```

配套改动（三处，缺一即失效）:
1. `ProcessingEngine.__init__` 加 `self._harness_suspect: dict[str, int] = {}`
   （与 `file_audits` / `truncated_keys` 同样按 `file_key` 索引）
2. **重置位置**：`processor.py:517` 的 `for attempt in range(max_retries + 1):` **之前**
   加 `self._harness_suspect.pop(key, None)`
   —— ⚠ **不能**放 `_call_api_stream` 入口（`:1092-1094` 那两行所在处）：
   `_call_api_stream` 由 `processor.py:530` 在重试循环内**每个 attempt 调用一次**，
   在那里重置会把标志每次抹成 0，导致"第二次放行"分支**永不可达**（v3 的设计错误）。
3. **前端状态标签**：`app.js:2004-2014` 的 `STATUS_LABEL` 补
   `WARN_NOOP_SUSPICIOUS: '未走工具链（已放行）'`
   —— 否则 `:2019` 的 `STATUS_LABEL[st] || st` 会渲染成裸英文串。
   （`:2018` 判定 `st.indexOf('WARN') === 0` → 自动进 warn 样式，无需另改 CSS）

**⚠ 必然变红的既有断言 1 条（D-11：改夹具，不是改判据）**:
`tests/test_harness.py:453` `check("长解释文本可疑", f("这段文字写得很好，没有错误。") is True)`
—— 夹具只有 **14 字**，新口径下返回 `False`。用例名叫"长解释文本"但夹具是短的，
**本就名不副实**。
**处置**: 夹具换成真正的 >40 字推理文本并重命名为「长推理文本可疑」；
同处新增 `check("短自然措辞放行", f("看起来没问题。") is False)` 锁住新行为。
`tests/test_harness.py:454`（`"无需修改" + "。"*60` = 64 字 > 40）**不红**，无需改。
另 `:421` 的 `long_reasoning` 夹具只有 43 字且不含"无需修改"，
新口径下仍返回 `True` 但**守的不是原性质**（属假绿），需换成真正的 >40 字无编辑载体文本。

**回归用例**:
- 单元（`test_harness.py`，就地改 `:453` + 扩表）:
  - `'无需修改'` / `'无需修改。'` / `'好的。'` / `'看起来没问题。'` / `'未见错别字。'` → **False 放行**
  - `'old_text: xxx'` / `'new_text: yyy'`（长短均测）→ True 可疑
  - 真 >40 字推理文本（无编辑载体）→ True 可疑
- 引擎端到端（仿 `test_engine_suspicious_noop_content_retries:415`，`_FakeHarnessClient` + `max_retries`）:
  - 模型返回自然措辞 + 0 tool_calls → **第一次 raise → 重试 → 第二次放行 → COMPLETED**（不是 FAILED）
  - 且落盘结果的 `audit` **含一条 `WARN_NOOP_SUSPICIOUS`** ← v3 写的这条断言原本是假的
    （放行时 `edits` 为空 → `chunk_audit = list(parse_audit) = []` → `audit_has_warnings([])` 为 False
    → 前端隐藏面板）。补上 `_make_audit` 后才成立
  - **`max_retries=0`** → 首轮即放行（不 raise），不 FAILED ← v3 漏了这个分支
  - **并发隔离**: 2 文件 + `concurrency=2`，两文件各自首次可疑**都应 raise 一次**
    （v3 的引擎级布尔会让文件 B 继承文件 A 的预算，实测只发 3 次而非 4 次）
  - **分块隔离**: 单文件多 chunk，chunk 1 消耗预算后 chunk 2 首次可疑**直接放行**
    （语义为「每文件 N 次预算」，不是「每 chunk N 次」—— 此为有意的语义选择）

---

### F6. `harness.py:322-328` `WARN_RATIO` 等长全改写零告警 ⛔

**根因**（实测）:
```python
diff_ratio = abs(len(corrected) - len(original)) / len(original)   # ← 长度差
```
```
len(orig)=300  len(new)=300  长度比=0.00%   文本实际全改写: True
audit=['OK']   audit_has_warnings=False     ← 零告警
```
> **v4 修正**: v3 用的 136 字夹具**低于 D-07 的 200 下限**（`:652` 处的 `if len(original) >= 200`），
> 会被整块跳过 → 旗舰回归用例必然红，且正是本项存在的唯一理由失效。
> 所有演示与回归夹具一律改用 **≥200 字**（此处取 300）。
> （原 136 字的实测结论本身仍成立 —— 它证明的是"旧算法对等长重写零告警"，
> 不受新下限影响；只是不能直接当新算法的验收用例。）
```
反向假阳性: `apply_edits('短', [{'old':'短','new':'短文'}])` → 100% 告警。

这是 harness 轨**唯一的兜底告警位**，而"模型无视工具纪律把整段改写塞进一条 tool_call"
正是它要拦的事。

**指标选型过程**:
| 候选 | 裁决 |
|---|---|
| 被替换占比 `Σ old_len / len(original)` | **否决** —— 实测重叠 edit 会重复计入放大：真实改动 0 个字符时给出 **87.5%** |
| `difflib` 真比例 | **否决** —— 实测 6000 字 + 8 处小改 **656ms**；50000 字（`extra_large` 档）**60.3 秒** |
| **`max(old_len for OK) / len(original)`** | **✅ 采纳** —— 精确命中"一条 tool_call 吞掉半篇"，O(n)，对"多条小改"零假阳性 |
| 精确位置映射法（O(n×edits)≈0.2s）| 延后到 v5.4.4（侵入性中等，但更准）|

**改法**:
```python
# audit 条目加一个不截断的 old_len (供覆盖率计算; old_preview 仍截断 80 供前端显示)
def _make_audit(index, status, reason, old="", new="", note=""):
    entry = {"index": index, "status": status, "reason": reason or "",
             "old_preview": _preview(old), "new_preview": _preview(new),
             "old_len": len(old) if isinstance(old, str) else 0}
    ...
```
```python
# 边界 10 重写 (v5.4.3)
if applied and original:
    # v5.4.3: 用「单条最大替换占比」而非长度差 — 长度差在等长整体重写下为 0,
    # 而这正是最该告警的场景 (模型无视工具纪律把整段改写塞进一条 tool_call)。
    # 取 max 而非 sum: 重叠 edit 会让 sum 重复计入放大 (实测真实改动 0 字符时给出 87.5%)。
    # 下限 len(original) >= 200: 短文本上任何改动占比都接近 100%, 阈值无意义
    # (阈值 200 = 初始拍定值, 未做真实样本校准, 见计划 §0.1)。
    if len(original) >= 200:
        max_replaced = max((e.get("old_len", 0) for e in audit
                           if e.get("status") == "OK"), default=0)
        if max_replaced / len(original) > RATIO_WARN_THRESHOLD:
            audit.append(_make_audit(
                -1, "WARN_RATIO",
                f"单条编辑替换了原文 {max_replaced/len(original):.0%} "
                f"(>{RATIO_WARN_THRESHOLD:.0%}), 请人工核对"))
```

**`old_len` 不破坏前端消费**（已核实）:
- `app.js:2015-2031` 只读 `status/index/old_preview/new_preview/note/reason` 六个字段，多一个 key 无害
- `tests/test_harness.py:214` 是 `all(k in e ...)` **包含式**断言，加 key 不红
- audit 是会话内存态（`processor.py:140`），**不落断点**，无 schema 变更

**D-12：不动的两条断言** —— `tests/test_harness.py:196`（夹具 `"错误甲。"` = 4 字）与
`:163`（`"他说错误甲。"` = 6 字）都在 200 下限以下，**自动不红**，不改。

**已知取舍（移到"取舍"而非"根因"）**: `apply_edits('短',[{'old':'短','new':'短文'}])`
在新指标下因短文本被下限豁免 → **不再告警**。这是有意的（短文本上该指标无意义）。

**回归用例**（`tests/test_harness.py`，仿 `:146 test_boundary_10_ratio_warn`）:
| 场景 | 期望 |
|---|---|
| **等长整体重写（300→300，全文替换）** | `audit_has_warnings == True` ← **原 bug**；⚠ v3 此行是 136 字、低于 200 下限会必红，v4 已改 |
| ≥200 字段落里单条替换 60% | True |
| ≥200 字段落里多条小改（各 3% 共 30%）| False ← 验证 `max` 而非 `sum`（实测 max=6% vs sum=65%）|
| ≥200 字段落里重叠 edit（净改动 0 字符）| False ← 验证放大问题已解（实测 max=40% vs sum=62%）|
| 短文本（<200 字）任何改动 | False（下限豁免，D-12 语义）|

> **v4 增补的验证要求**（源自 §4 review 检查项第 3 条）:
> 上表每一行都必须**确认用例真的进入了新代码路径**（`len(original) >= 200` 为真），
> 不能靠"下限把整块跳过"空洞通过。verifier 复审时应自行构造反例验证这一点。

---

### F11. `start.py:112` `"py -3"` 被当文件路径 ✅

**位置（v1 路径错）**: **仓库根 `start.py`**，不是 `app/start.py`。
`find_python:81`（签名）/ `:92,:102`（前两分支）/ `:112`（`return "py -3"`）/ `:130,:133`（`ensure_venv` 消费）/
`:143`（`deps_ok` 消费）/ `:146-149`（except 列表）/ `:223`（`cmd_check` 调用）

**根因**: 返回值类型不统一 —— 前两分支返回**解释器名**，第三分支返回**带参数的命令行**。
`subprocess.check_output([py, "-c", ...])` 会找名为 `py -3` 的可执行文件。
**且** `deps_ok:146-149` 的 except 只捕 `TimeoutExpired`/`CalledProcessError`，
**不含 `FileNotFoundError`** → 逃逸 → `python start.py check` traceback。

**⚠ v1 改法会引入新 bug**: 统一返回 list 后，`deps_ok`/`ensure_venv` 会同时收到**两种类型**:
- **list**: `:223` `deps_ok(py)`、`:262` `ensure_venv(py)`
- **str**: `:268` `deps_ok(vpy)`、`:272` `[vpy, "-m", "pip", ...]`、`:294` `[vpy, "main.py"]`

按 v1 的 `[py[0], *py[1:], ...]` → `py[0]` 取到**首字符 `'C'`** → **把 venv 启动路径改坏**。

**改法**:
```python
def _as_cmd(py: str | list[str]) -> list[str]:
    """v5.4.3: deps_ok / ensure_venv 的入参有两种来源 ——
    find_python() 返回 list[str]; VENV_PY 恒为 str。
    统一在此归一化, 避免下游 [py[0]] 取到 str 的首字符。"""
    return py if isinstance(py, list) else [py]

def _ver_ok(out: str) -> bool:
    """v5.4.3: 版本闸门 —— 抽 helper 给 :101 / :111 两处共用。
    只看主版本 3 会放行 3.0~3.9, 但代码用 3.10+ 语法 (str | None 在 3.9 导入期就 TypeError)。"""
    m = re.match(r"\((\d+),\s*(\d+)\)", out.strip())
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (3, 10)
```
- 三个分支统一返回 list: `[name]` / `[name]` / `["py", "-3"]`；同步更新 `:81` 返回类型注解
- `deps_ok` / `ensure_venv` 入口各调一次 `_as_cmd(py)`
- except 补 `FileNotFoundError` / `OSError`
- 显示处 `:204`/`:259` 用 `' '.join(cmd)`
- 版本闸门两处（`:101` 和 `:111`）都改用 `_ver_ok(out)`

**回归用例**（**新建 `tests/test_start.py`；`run_all_tests.py:14-18` 是 glob 自动发现，新建即入门禁**）:
- `find_python` 三分支各返回 `list`（mock `subprocess.check_output` 返回 `b"(3, 11)"`）
- **`deps_ok` / `ensure_venv` 必须同时传 `str` 和 `list` 两种入参** ← 关键，否则上述洞漏网
- `_ver_ok`: `(3, 9)` 拒绝 / `(3, 10)` 接受 / `(2, 7)` 拒绝
- `deps_ok` 遇 `FileNotFoundError` → 返回 `(False, msg)` 而非抛

---

### F12. `app.js:247-250` ContentDialog Enter 无条件走主按钮 ✅

**根因**:
```javascript
else if (e.key === 'Enter') { e.stopPropagation(); close(true); }   // ← 无视焦点, 无 preventDefault
document.addEventListener('keydown', onKey, true);                  // ← 捕获阶段
```
捕获阶段先于按钮原生激活 → 焦点在哪个按钮都 `close(true)`。

| 对话框 | 主按钮 | 后果 |
|---|---|---|
| `clearFiles`(`:1091-1098`) | 「清空」`danger:true` | Tab 到「取消」按 Enter → **清空全部文件** |
| `_applyDroppedText`(`:2173-2180`) | 「追加到末尾」 | 焦点在「替换现有内容」按 Enter → **执行追加**；第三按钮键盘下永远选不中 |
| 跨轨覆盖确认(`:1371-1378`) / `_deleteStyleProfile`(`:3212-3219`) | 「继续」/「删除」 | 同上 |

**改法**（复审通过 ✓）:
```javascript
const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(false); }
    // v5.4.3: 删掉 Enter -> close(true) 分支。
    // 原实现在捕获阶段无条件解析为主按钮, 导致 Tab 到"取消"按 Enter 仍执行破坏性操作,
    // 且三命令对话框的第三按钮键盘不可达。改由 <button> 原生激活处理焦点所在按钮。
    // 配套: close() 里归还焦点 (见下), 否则点对话框空白处使焦点落到 body 时 Enter 无响应。
};
```
已确认 `web/` 全仓**无第二个 Enter 监听器**，删掉 `stopPropagation()` 不会泄漏快捷键。

**焦点归还（D-05 必做）**:
```javascript
const prevFocus = document.activeElement;   // 打开时记
const close = (result) => {
    root.hidden = true;
    document.removeEventListener('keydown', onKey, true);
    if (prevFocus && prevFocus.focus) prevFocus.focus();   // 归还
    resolve(result);
};
```

**⚠ v1 的回归用例是错的**: DOM 顺序是 **secondary(`:646`) → close(`:647`) → primary(`:648`)**，
`btnP.focus()`(`:240`) 把焦点放在**最后**一个 → `keyboard.press('Tab')` 会**把焦点移出对话框**。
**v2 用 `page.focus(selector)` 而非 `Tab`**:
- `page.focus('#dialog-btn-secondary')` + `Enter` → 断言 `window.__cfResult === false`
- `page.focus('#dialog-btn-close')` + `Enter` → 同上（第三按钮键盘可达）
- 焦点在 `#dialog-btn-primary` + `Enter` → 断言 `=== true`
- 点对话框正文（焦点落 body）后按 Enter → 断言仍生效（验证焦点维持）
- `Escape` 行为不变

---

## 4. 实施顺序（含步间 review 要求）

| 步 | 项 | 依赖 | 预估 | **步间 review** |
|---|---|---|---|---|
| **0** | F0-① 门禁计数 + F0-② `import test_isolate`/env 预置 | — | 2h | ✓ review：基线是否变 1677、盲区是否消除 |
| **0.5** | F0-③ 用户目录清理 | 0 | 0.2h | 向用户展示 `app-debug.log` 末尾后再删 |
| **1** | F1, F2, F3, F4, F5, F13, F14 | 0 | ≈ 8.5h | ✓ review：红线核对 + 4 条既有断言状态 + 冒烟 |
| **2a** | **F15** → **F9** → **F8** | F15→F9 是代码依赖；F9↔F8 是**原子提交约束**（终态相同，非串行要求，见 F8 §）| ≈ 9h | ✓ review：**单独 review 这条链**（耦合风险最高）；F8 的 review 须显式核对 F9 已生效 |
| **2b** | F7, F6, F10, F11, F12 | — | ≈ 11h | ✓ review：F6/F10 的测试语义变更 + F7 性能 |

**步间 review 的检查项**（每步结束派独立 verifier）:
1. `python run_all_tests.py` 实际通过数（应单调不减，且 ≥1677）
2. 该步涉及的**红线**是否仍成立（§29 punct_fix / §30 md_strip）
3. 该步的回归用例是否**真的**能挡住反向回归（verifier 需自行构造反例验证），
   **并确认该用例真的进入了新代码路径**（未被阈值 / 下限 / 短路分支豁免）——
   否则测试可以空洞通过。⚠ **F6 的 136 字用例就是这么空洞失败的**（见 F6 § 的 v4 修正）
4. `tools/smoke_ui.py`（凡改前端）通过数 **≥ 本步开始前的实测值**。
   ⚠ **不要写死 96** —— 该计数是动态的（`smoke_ui.py:46-48` 累加、`:509` 打印），
   文件里没有任何硬编码 96（只有 51 个 `check(` 调用点，靠三视口循环放大），会随新增断言漂移。
   每步开工前先实测并回填 §7
5. `git status` 是否只有预期改动

**commit 约定**: 每项一个 commit，格式 `fix(v5.4.3): <一句话> — <根因>`。
批次 0 的第一个 commit 额外包含计划文件入库（D-14）。

---

## 5. 明确不做（延后清单）

| # | 项 | 理由 |
|---|---|---|
| D1 | 版本号单一真值源 | `app/__init__.py` 0 字节，4 处不一致。独立工程（D-16 决定不塞进本批）|
| D2-③ | `cfg-timeout` 重复 id | 藏在 `index.html:396` `<details>` **折叠区默认不可见**，不是"一眼能看见"的等级 |
| D2-④ | 快捷键无视图守卫 | 均带 Ctrl 修饰，不会在打字时误触，属 UX 打磨 |
| D7 | `_deriveTrack`/`_effectiveChunkPreset` 前后端漂移 | 根治需新增只读 Bridge，属**接口设计变更**，需先定 API |
| D8 | CSS 缺陷（`--shadow16` 拼写、`.seg-icon` 无规则、响应式断点缺 3 视图、43 处 `<label>` 无 `for`、4 处对比度不达 AA）| 属 UI 债务，单列"前端 UI 批次"并配套 `smoke_ui.py` 断言 |
| D9-② | Gutenberg 中文 TOC 跳过失效 | 可与 F3 同 commit（**若时间允许本批带上，否则延后**）|
| D9-③ | `_book_name_to_slug` 不过滤 `..` | 需恶意/异常书名才触发 |
| D10 | ai_score blacklist 短文本吃满 / ★✔ 当 emoji | v1 的"权重待校准"理由对这两项不成立（加最小长度门槛/收窄字符域即可），但仍需真实样本定阈值 |
| D11 | 窗口关闭无收尾钩子（4 条 daemon 线程被强杀）| 健壮性工程，需改 `main.py` 注册 `window.events.closing` + 非原子写改原子写 |
| D12 | AGENTS 文档漂移 | 纯文档修正，随各项修复顺带更新 |
| — | `md_local` **块内即时取消** | v3 明确 F7 的取消粒度只到"单次 `strip_markdown` 之间"；块内即时需改 `md_strip` 内部循环，改动量大一档 |
| — | F6 的**精确比例**（位置映射法）| 精确方案 O(n×edits)≈0.2s 更准，但侵入性中等 → 紧随 v5.4.3 的 v5.4.4 |
| — | **测试基建**（D5 剩余 + D6 源码式断言）| D-17 决定**本批完成后紧接**。它是 C2/C3 拆 `app.js`/`style.css` 的**硬前置** —— 改 `app.js` 会触发 7 个测试文件里的源码式静态断言，现在看似能跑，C2 一拆就大面积假红。**顺序不能反** |

---

## 6. 验收门禁（基线已修正）

```powershell
python run_all_tests.py        # 真实基线 1677 通过 / 0 失败（v1 写的 1581 少报 96）
python tools/smoke_ui.py       # 改前端项必跑（AGENTS §46）
python start.py check
```

**硬性要求**:
1. **批次 0 必须先完成**（门禁修好后基线才可信）
2. 每项**必须**新增对应回归用例
3. F2 / F7 改完后**额外核对 §29 / §30 四条红线**。复审结论: F2 只动
   `_apply_rect_quote_style` 的 `’` 分支 → §29 四条**字面均不破**，但"保守"这层的
   实践效果会打折（D-04 已接受），需在 CHANGELOG 明写这是有意的口径变更;
   F7 的 `if ']' in line` 对三条正则**严格等价** → §30 四条**全不破**
4. 改前端项必须重跑 `smoke_ui.py` 三视口
5. 推送到 GitHub 前**须经用户确认**

---

## 7. 执行记录

> **状态**: 批次 0 / 1 / 2a / 2b 全部完成。批次 0.5（用户目录清理）等用户确认后再动。
> 门禁 **1677 → 1900 通过 / 0 失败**（21 套件）；`tools/smoke_ui.py` **96 → 117**。

| 步 | 项 | 状态 | commit | 回归用例 | review 结论 | 备注 |
|---|---|---|---|---|---|---|
| 0 | F0-① 门禁计数 | ✅ | `15fc0a9` | — | ✅ 0 BLOCKER | 1581→**1677**（差 96 = 两个 unittest 套件各折算成 1）|
| 0 | F0-② `import test_isolate` + env 预置 | ✅ | `15fc0a9` | — | ✅ | 门禁对用户目录零污染 |
| 0.5 | F0-③ 用户目录清理 | ⏳ | | | | **待用户确认**（先展示 `app-debug.log` 末尾再删）|
| 1 | F1 CRLF 位置映射 | ✅ | `3dd3f94` | 4 | ✅ | 孤立 CR 被当 CRLF → 静默删字 |
| 1 | F2 直角引号撇号 | ✅ | `3dd3f94` | 7 | ✅ | 含 1 条组合用例 |
| 1 | F3 特章同号去重 | ✅ | `3dd3f94` | 5 | ✅ | review 后改法：key 加 `title` |
| 1 | F4 config 快照 | ✅ | `3dd3f94` | 3 | ✅ | |
| 1 | F5 屏显旧文本 | ✅ | `f0203a3` | 3 | ✅ | 手工注入式（review 补覆盖）|
| 1 | F13 `_provenanceKey` + D3 | ✅ | `f0203a3` | 2 | ✅ | |
| 1 | F14 `_AD_STRONG` 护栏 | ✅ | `3dd3f94` | 4 | ✅ | 拆 `_AD_PURE`/`_AD_COLLO`/`_AD_WEAK` |
| 2a | F15 命名空间 | ✅ | `b434787` | 5 | ✅ PASS | **F9/F8 的前置**，实为 6 处非 4 处 |
| 2a | F9 `MULTI_ALLOWED` | ✅ | `b434787` | 8 | ✅ PASS | 委派方案（保持 app.js 零 splitter 知识）|
| 2a | F8 `_flush` 丢事件 | ✅ | `b434787` `16b016d` `7732085` `0c9301f` | 97 | ✅ PASS（三轮）| 与 F9 原子提交 |
| 2b | F7 md_strip 正则 + md_local | ✅ | `e5312ca` `62e80e6` | 20 | ✅ PASS | 性能 3 条 + 体积上限 + 不可重试分类 |
| 2b | F6 `WARN_RATIO` | ✅ | `5e384e8` | 19 | ✅ PASS | 等长重写 + `max` 而非 `sum` + 200 下限 |
| 2b | F10 守卫 + 兜底层 | ✅ | `a82e59d` | 16 | ✅ PASS | 判据作废短语白名单 + 放行兜底 |
| 2b | F11 `find_python` | ✅ | `5e997ca` | 30 | ✅ PASS | 新建 `tests/test_start.py` |
| 2b | F12 ContentDialog Enter | ✅ | `ad98a26` | 6 | ✅ PASS | 用 `page.focus()` 不用 `Tab` |

### 实施期复审记录（5 轮步间 review，全部有产出）

| 轮 | 对象 | verdict | 抓到什么 |
|---|---|---|---|
| 计划期 4 路 | v1→v4 | FAIL ×4 | 5 个 BLOCKER；F2 `isalnum`→`isalpha`；F15 实为 6 处；F6 夹具违反自身 200 下限；F10 兜底层状态机两处设计错误 |
| 2a 第 1 轮 | `b434787` | **FAIL** | **B1 BLOCKER**：取走重投槽不为残留 buffer 补 arm → 最后一批事件永久滞留（相对修复前是**回归**）；M1 硬熔断无复位点；M2 `onDeaiTextDrop` 重投=静默文本损坏；L1/L2/L3 |
| 2a 第 2 轮 | `16b016d` | **FAIL** | **B2 BLOCKER**：`2 ** over` 在 streak≥1028 抛 `OverflowError`，而 arm 先置 `_push_pending=True` → 通道永久焊死且零日志（**这条是 16b016d 自己新引入的**）；L4 口径数字错；L5 死参数；L6 源码断言会自我满足；L7 守护断言不定向 |
| 2a 第 3 轮 | `7732085` | **PASS** | 0 BLOCKER 0 中危；两条低危（§34 数字、arm 顺序覆盖理由不成立）→ `0c9301f` 做掉 |
| 2b 第 1 轮 | 5 个提交 | 中途夭折 | 撞 Token Plan 上限，未出报告；已自查其留下的 `web/app.js` 并行撞车（工作树自愈，SHA 已核对）|
| 2b 第 2 轮 | 6 个提交 | **PASS** | 0 BLOCKER 0 中危。发现 F7 性能用例**靠运气过**（`'![' * 8000` 无守卫 394ms / 预算 500ms，余量仅 1.27 倍）→ `62e80e6` 提到 20000 |

### 实施期偏离计划之处（均已在对应 commit 信息里写明理由）

| # | 计划写的 | 实际做的 | 为什么 |
|---|---|---|---|
| 1 | F10 `retry_budget = max(1, max_retries)` | `max(0, ...)` | 计划代码自身有矛盾：`max_retries=0` 时首轮仍 raise，而**根本没有第二次机会** → 必然 FAILED，正是 F10 要消除的危害。计划的条件 ③（"首轮就放行，不 raise"）才是对的 |
| 2 | F7 原地调 `_finalize_failed` 再 return | 抛 `_FileTooLargeError`（进不可重试通道）| `_call_api_stream` 返回契约是**三元组**，return None 会让调用方解包炸 `TypeError`；且计划漏了 `start` 参数、函数里也没有名为 `task` 的局部变量 |
| 3 | F8 硬熔断 `_push_disabled` | 指数退避（`_flush_interval`）| 硬熔断无任何复位点，pywebview 窗口最小化的瞬时异常就会永久静默通道 |
| 4 | F8 回灌用 `buffer[:0] = events` | 独立 `_push_retry_slot` | 混回 buffer 会让新事件排在旧事件前，且 buffer 随每次重试单调增长（O(n²)）|
| 5 | F9「F8/F9 必须原子提交」 | 承认是**流程约定**而非代码约束 | reviewer 实测确认代码层不成立（分界是 F8 有无重投，不是 F9）。真正的代码保证由 `_NO_RETRY_EVENTS` 给出 |

### 变异实验自检（提交者侧，建议纳入常规流程）

每个修复都做「撤掉修复 → 确认用例变红」，跑完校验文件按 SHA256 字节还原。**这是抓出"恒绿断言"最有效的手段**——本计划实施期共发现 9 处自己写的用例没有区分度，全部是这样照出来的：

- B1 用例因失败路径末尾的 arm 而失去区分度
- 并发槽 mock 只装槽不抛异常 → 恒绿
- arm 幂等用例把**被测方法整个替换掉** → 守卫生在被删的方法里
- B2 用例对低 streak 也断言封顶
- F6「重叠 edit」夹具：顺序 replace 下第二条必然 SKIPPED，`sum` 与 `max` 算出来一样
- F7 分类断言拿「有没有构造 AsyncOpenAI」当可观测量——`md_local` 压根不构造，恒为 0
- F7 分类断言只搜日志里的「文件过大」——`[不可重试]` 那行嵌了同一条 msg，计数翻倍
- F12 `prevFocus` 捕获时机写错（`btnP.focus()` 之后 → 捕获到主按钮本身）
- F7 性能用例余量不足 1.27 倍，靠运气过

### 未做（记录）
- 批次 0.5 用户目录清理（等用户确认）
- `md_local` 块内即时取消（当前取消粒度 = 单次 `strip_markdown` 之间）
- F6 的「精确位置映射法」覆盖率指标（O(n×edits)≈0.2s，比 `max` 更准，延后到 v5.4.4）
- **§34 拍定值的真实样本校准**（`AGENTS.md` §34 口径）——这是当前最大的已知风险敞口，单元测试回答不了"阈值合不合适"

### 复审记录（四份 verdict）

| verifier | 角度 | verdict | 关键贡献 |
|---|---|---|---|
| 1 | 技术正确性 | **FAIL** | B1/B2/B3 三项裁决；F2 的 `isalnum`→`isalpha`；F3 顺带项无效；F5 只修一半；F7 漏 `_IMAGE_RE`；F8 四洞；F10「v1 跑 v1 的表仍失败」|
| 2 | 回归风险 | **FAIL** | 4 条必红断言（`:163` `:196` `:453` `:454`）；F2 落单引号实测；F7 `_IMAGE_RE`；F8 无 Timer 重臂；F9 `this` 绑定；F11 双类型入参；10 个遗漏测试点 |
| 3 | 范围优先级 | **FAIL** | 门禁基线 1581→1677；F9 被 D2 阻塞；D2-②/D9-① 提级；D5 拆两半；4 处 v1 事实错误；工期低估 2 倍 |
| **4** | **v3 增量复核** | **FAIL** | **5 个 BLOCKER（B-1/B-2 是 v3 兜底层的状态机设计错误）**；F6 回归表自我违反 200 下限；F15 实为 6 处非 4 处；F9 集成形态该用委派而非 `case`；F10 `max_retries=0` 漏分支；并发跨文件串预算 |

**v3 → v4 的 5 个 BLOCKER 处置**（verifier-4 报，我逐条回代码原文复核确认）:

| # | 项 | 问题 | v4 处置 |
|---|---|---|---|
| **B-1** | F10 | 标志在 `_call_api_stream` 入口重置 = 每 attempt 一次，恰好抹掉兜底所需计数 → 「第二次放行」**永不可达**（实测 flag 轨迹 `[False, False]`，`max_retries=1/3` 全 FAILED）| 改为**按 `task_key` 索引的 `dict[str,int]`** + 重置移到 `_process_file_async` 的 `for attempt` **之前**。复核依据：`processor.py:1092-1094` 确在 `_call_api_stream` 内，其 docstring 止于 `:1090`；而 `:530` 的调用在 `:517` 的重试循环内 |
| **B-2** | F10 | 放行后 audit 恒为空（0 tool_calls → `parse_tool_calls` 返回 `([],[])` → `chunk_audit=[]`）→ `audit_has_warnings([])`=False → 前端 `renderAuditPanel`(`app.js:1998-1999`) 隐藏面板 → **用户零信号**。v3 写的回归用例"audit 含一条可疑标注"**是假的** | 放行分支补 `_make_audit(-1,"WARN_NOOP_SUSPICIOUS",...)` + `app.js:2004-2014` 的 `STATUS_LABEL` 增项。复核依据：`harness.py:356-358` 确认空 tool_calls 返回双空列表 |
| **B-3** | F6 | 旗舰回归用例 136 字**低于 D-07 的 200 下限** → 整块跳过必红，而本项存在的唯一理由失效 | 夹具改 300/300，根因数字同步；并加"用例必须真的进入新代码路径"的验证要求 |
| **B-4** | F10 | `max_retries=0`（合法用户配置）只有一次 attempt → 即便修正重置位置仍 FAILED，兜底完全失效 | `retry_budget = max(1, max_retries)`，首轮即可放行；补该分支回归用例 |
| **B-5** | F15 | 说"4 处"实际 **6 处**（`:254 :255 :262 :263 :277 :278`），且 `:255`/`:263` 是**真调用点** —— 只改守卫会因 `window.app.appendLog` 存在而为真，进入分支后 `window.App.appendLog` 仍 undefined → **TypeError，比现状更糟** | 改为 6 处并列表逐条标注角色 |

**v4 采纳的优化项**: F9 集成形态改「`default:` 分支通用委派 + splitter 加 `onEvent`」
（splitter 完全自闭环、`app.js` 零引用，写 `case` 会制造全应用唯一跨模块耦合 + 进度 DOM 双写者）；
F15 的「`window.app` 之前不可用」论证有误（`app.js:3459` 是顶层语句，escapeHtml 合并无顺序约束）；
F7/F8 补 AGENTS §34 的行内"初始拍定值"标注；§4 冒烟基线改「≥ 本步实测值」不写死 96；
§4 review 第 3 条补「确认用例真的进入新代码路径」。

**交叉验证发现的复审自身错误**: verifier-3 称 `docs/ROADMAP.md` 不存在 —— **错，文件在**。
记录以免误导后来人。
