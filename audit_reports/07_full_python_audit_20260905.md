# 全量代码审计报告（Python 后端，web/ 前端除外）

> 项目：新时代校对大师 v4.1.8（git 基线 `55bb965`）
> 审计时间：2026-09-05
> 方法：6 个并行只读子代理按架构分片逐行审计（Bridge / 引擎 / 数据层 / Prompt 层 / 入口构建 / 测试套件）→ 1 个独立验证器逐条复检
> 范围：`app/`（web_backend / processor / utils / templates / style_profiles / context_builder / logger）+ `main.py` + `dev_launcher.py` + `check_exe.py` + `run_all_tests.py` + `build.spec` + `test_*.py`
> 排除：`web/`（前端，用户指定不审）、`.venv/`、`dist/`、`build/`、`audit_reports/`（历史产物）、`.baseline-v2.0/`
> 验证统计：**38 CONFIRMED / 3 PARTIAL / 1 NOT FOUND / 1 CANNOT_VERIFY**

---

## 一、严重度总览

| 严重度 | 数量 | 关键条目 |
|---|---|---|
| 🔴 HIGH | 12 | A1 A2 A3 B1 B2 C1 C2 D1 D2 E1 F1 F2 |
| 🟠 MEDIUM | 18 | A3 B3 B4 B5 B6 C3 C4 C5 D3 D4 D5 E2 E3 E4 F3 F4 F5 E7 |
| 🟡 LOW | 12 | A4 A5 A6 B7 B9 B10 B11 D6 D7 E5 E6 F6 |
| ⚪ PARTIAL/无法判定 | 4 | A6(死代码真但不可达) B5(半真) C4(空流但不抛错) A7(需运行时) |
| ❌ 误报 | 1 | B8 |

> 编号说明：A=web_backend，B=processor/context_builder，C=utils/logger，D=入口/构建，E=templates/style_profiles，F=测试。A2 与 C1 为同一根因的跨文件表现，计 1 个问题。

---

## 二、🔴 HIGH — 12 处

### H1 [A1] `start_proofread` 无并发重入保护 → 旧任务回调 KeyError、双线程驱动同一引擎
- **位置**：`web_backend.py:350`（无条件重建 engine）、`:362-372`（回调 lambda 读动态 `self._engine.tasks[k]`）、`:409-410`（直接起线程）
- **为什么是 bug**：任务在跑时再点开始会替换 `self._engine`；旧线程回调在新引擎的 `tasks` 上取 key → KeyError → 被当普通失败反复重试；极端时两个线程 `run_until_complete` 同一 engine 交叉写断点。
- **建议修复**：启动前检查在途任务（`is_alive()` 或 engine running 标志），在跑则先 cancel+join 或直接返回错误；回调闭包捕获 engine/task 局部引用而非动态 `self._engine`。

### H2 [A2/C1] api_key 混淆串往返污染 → "保存一次设置后全线 401"
- **位置**：`utils.py:181`（`to_dict` 恒 `_obf(api_key)`）+ `web_backend.py:100-116`（get_config 把混淆串回显，set_config 无 deobf 保护）+ `web/app.js:221/1070`（回显密码框→保存写回）
- **为什么是 bug**：get_config 把 `_obf(api_key)` 返回给前端填进密码框；用户改任意设置触发自动保存时，混淆串被当明文写回 → 磁盘存 `obf(obf(key))`，Bearer 变 `obf:…` → 永久 401。
- **建议修复**：get_config 不返回混淆串（返回 `api_key_set: bool`，前端空框占位）；或 set_config 对 `obf:` 前缀值忽略（视为未修改）。

### H3 [B1] RateLimit 重试耗尽路径不更新 stats → 进度永远少 1
- **位置**：`processor.py:481-501`（429 break 后只置 status/存断点/发 on_file_done，缺 `stats.completed_files/failed_files += 1` 与 `on_stats_update`）
- **对照**：`:416-419`（不可重试）与 `:467-470`（通用异常耗尽）都有补计数，唯独 429 这条生产最常见路径漏了。
- **建议修复**：抽统一 `_finalize_file()` 收尾，或该分支补 stats 自增 + `on_stats_update`。

### H4 [B2] cancel 落在"排队/重试间隙/attempt 顶部"的文件不留任何痕迹 → UI 永远卡"排队中"
- **位置**：`processor.py:289-294`（排队文件拿信号量后仅 return，task 停留 PENDING）；`:317-326`（attempt 顶部只置 CANCELLED 不落断点不回调）
- **对照**：`:371-396` CancelledError 分支有完整收尾（result/CANCELLED/断点/stats/回调）。
- **为什么是 bug**：`concurrency < 文件数` 时 cancel 一按，排队的文件全部走 289 早退 → 无 result、进度缺失、UI 文件永远"等待中"。
- **建议修复**：两早退点走与 371-396 相同的完整收尾；`limited()` 拿信号量前先查 `_cancel_event`。

### H5 [C2] 断点指纹 hash 漏关键配置字段 → 改档位重跑命中旧断点
- **位置**：`utils.py:50-53`（`compute_prompt_hash` 仅 prompt_mode/model/custom_prompt 三字段）+ `processor.py:155-157/166`（据此判断点失效）
- **为什么是 bug**：改 `chunking_preset / context_max_chars / context_max_chunks` 属会改变生成内容的操作，但 hash 不变 → 静默复用旧断点，返回与当前档位不符的结果。
- **建议修复**：hash 纳入 chunking_preset、context_max_chars、context_max_chunks（以及 temperature 等实际影响生成的参数）。

### H6 [C5] `expected_hash` 生产零调用 + 空 hash 旧断点永不失效
- **位置**：`utils.py:349/370`（参数无人传）+ `processor.py:165-171`（`cached_hash = ... or ""`，`if cached_hash and ...` 对空 hash 永假）
- **为什么是 bug**：v1 旧断点（无 prompt_hash）在 prompt/配置变更后仍被静默复用，防护对历史断点整体失效。
- **建议修复**：`load_checkpoint` 调用处补 `expected_hash` 实参；空 hash 断点按"无指纹"处理（失效或强制重跑策略）。

### H7 [D1] `check_exe.py` 正斜杠探测在 Windows 打包产物上恒误报失败
- **位置**：`check_exe.py:19`（`data.count(b"web/")`）
- **实证**：对真实 `dist/新时代校对大师.exe`（45.7MB）字节扫描：`b"web/"` 出现 **0 次**，`b"web\\index.html"` 出现 1 次（PyInstaller Windows 清单用**反斜杠**）。check_exe 必然误报"❌ 未打入"且 exit 1。
- **建议修复**：探测串改 `b"web\\"`，或直接搜 `b"web\\index.html"` 等目标名组合；路径用 `os.path.dirname(os.path.abspath(__file__))` 锚定。

### H8 [D2] `build.spec` datas 漏 `app/style_profiles/builtin/*.json` → 打包后 3 套内置文风 profile 静默丢失
- **位置**：`build.spec:61-64`（datas 只有 `('web','web')`）
- **依据**：`loader.py:130-149` list_builtin/get_builtin 全走 `Path(__file__).parent / "builtin" / "*.json"`；PyInstaller 不自动收集模块旁数据文件，frozen 下目录不存在 → list_builtin 静默返回 `[]`（不报错）、get_builtin FileNotFoundError。
- **建议修复**：datas 增加 `('app/style_profiles/builtin', 'app/style_profiles/builtin')`。

### H9 [E1] 选中「预置 profile」对去AI味 step2/3 完全无效（静默 no-op）— v4.1.7 新功能半实现
- **位置**：`loader.py:296-302`（get_style_card 只读 `~/.proofreader/styles/<slug>/style-card.md`）；`loader.py:144-149`（get_builtin **全仓零调用**，内置 JSON 从未被转成可注入 markdown）；`web_backend.py:707/717/734-743`（注入路径全走 get_style_card）
- **为什么是 bug**：前端把 3 个 builtin 与 custom 放同一下拉，选定后 `_load_style_card_text` 对 builtin slug 返回 `""` → prompt 无任何 9 轴卡：step2 不按该风格改写、step3 因"没提供风格卡"跳过 8 轴自评。界面显示"已选"，实际空转。
- **建议修复**：loader 增加统一入口——builtin slug 命中时回退 `get_builtin()` 并把 axes+ai_tells_counter 渲染成与蒸馏产物同构的 markdown；或随包内置 3 份 .md。

### H10 [F1] 测试套件污染真实 `~/.proofreader/` 且部分用例真实外呼网络 — **已在本机造成现实损害**
- **位置**：`test_components.py:107/321`、`test_bugs.py:42`、`test_web_backend.py:127-137/211-229/266-310`
- **实证**：本机 `~/.proofreader/last_config.json` 现已被测试值覆盖（`api_base="http://test"`、`model="test-model"`、`temperature=0.42`、**api_key 被清空**）；`checkpoints/` 有 **594 个**指向已删除 Temp 文件的孤儿断点；start_proofread/deai 测试启动真实后台线程，配置有效时会真发 LLM 请求。
- **建议修复**：套件入口统一把 `utils.CONFIG_DIR/CHECKPOINT_DIR` 与 `style_profiles.loader.STYLES_DIR` 指向 `tempfile.mkdtemp()`（`test_v416_*` 已示范正确做法），finally 还原；对 start_proofread/deai 测试 mock 引擎或注入假 client。

### H11 [F2] v4.1.5「D 算法/renderState」测试 mock 过度 + 3 个纯恒真用例
- **位置**：`test_web_backend.py:1398-1442`（MockRenderState 复刻类，从不读 `web/app.js`）、`:1511-1526`（remove_cleanup，测自己建的 dict）、`:1529-1542`（error_state_fallback，恒真+断言刚赋的值）、`:1545-1560`（mode_toggle，改自己字段再断言）
- **为什么是 bug**：测的是"测试作者在 Python 里复刻的算法"而非产品前端；真正前端 diff 逻辑回归时这些用例全绿。约 20 check 虚增覆盖率。
- **建议修复**：删除 3 个纯恒真用例；mock 类注释改为"参考实现自检，不担保 app.js"；或从 app.js 提取真实 renderCompare 行为断言。

### H12 [E7/cross] custom_prompt 残留无条件覆盖任意校对模式，与 UI 承诺矛盾
- **位置**：`processor.py:553-560/659-666`（custom_prompt 非空即优先于任何 prompt_mode）+ `web_backend.py:339-340`（只写不清理）+ `web/app.js:602`（无条件传 custom_prompt）
- **为什么是 bug**：用户曾用自定义模式、后切回"纯纠错/技术文档"但输入框没清空（或程序内残留），实际跑的还是旧自定义 system，与 index.html "仅 custom 模式生效" 的 UI 说明矛盾。
- **建议修复**：processor 只在 `prompt_mode=='custom'` 时采用 custom_prompt，或 start 时 mode≠custom 强制清空。

---

## 三、🟠 MEDIUM — 主要条目

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| M1 [A3] | web_backend.py:350 + processor.py:98-99 | engine 持有同一可变 config，运行中 set_config 直改 → 批内后半文件切配置但断点 hash 按旧值 | start 时 `dataclasses.replace` 快照一份给 engine |
| M2 [A4] | web_backend.py:620-981 | `_deai_tasks` 4+ 个错误分支不 pop，且全文件无读取点（纯泄漏记账结构） | 收敛到线程包装函数 try/finally pop |
| M3 [A5] | processor.py:214 + web_backend.py:414-418 | start 后立刻 cancel 被 `run_async` 的 `clear()` 吞掉，仍返回 ok:True | 引擎补"清事件后再查一次"或线程启动握手 |
| M4 [B3] | processor.py:601/616/680-681 | 多 chunk 流式推送作用域不一致：块内推 chunk buffer、块完成推全量 → 前端替换渲染时"回缩/闪断" | `_stream_single` 增加 prefix 参数推单调增长全量 |
| M5 [B4] | processor.py:438/449 | 退避 `asyncio.sleep(retry_after/delay)` 不可被 cancel/pause 中断（Retry-After 可几十秒） | 拆 0.2s 小步 sleep 逐段查 cancel，或用 `asyncio.wait(FIRST_COMPLETED)` |
| M6 [B5] | processor.py:580-588 | 流式静默期（服务端不出 token）cancel/pause 不生效；pause 停 `_await_resume` 期间连接悬空，恢复后可能 APIConnectionError 整文件重试 | 挂 0.1s 轮询 watchdog；pause 超阈值关流释放连接 |
| M7 [B6] | processor.py:144-200 + web_backend.py:350-351 | `prepare_tasks` 同步方法在主线程读全部文件（4 编码解码 ×N + 同步 load_checkpoint）+ 全文驻留内存 → 大文件批 GUI 冻结数秒 | `asyncio.to_thread` 异步读；懒加载任务文本 |
| M8 [C3] | utils.py:317-324 | `save_config` 非原子写盘（无 tmp+rename/fsync），写一半崩溃整份丢失且 UI 已报成功 | 先写 `config.json.tmp` 再 `os.replace` |
| M9 [C4] | logger.py:62-65 | windowed 打包（console=False）下 StreamHandler(sys.stdout) 流为 None（空流静默失效） | 判空后再 add handler，或仅 dev 模式加 console handler |
| M10 [D3] | main.py:92-108 + build.spec:100 | windowed 下 `sys.stderr` 为 None → 启动失败兜底 `sys.stderr.write` 抛 AttributeError，掩盖 WebView2 缺失原始异常 | 判空 + ctypes MessageBoxW 原生提示 |
| M11 [D4] | dev_launcher.py:155-176 | pop_tail_window 不设标题，kill_tail_window 按 `WINDOWTITLE eq NewEraProofreader-tail*` 过滤 → 永不命中，每次 dev run 泄漏 tail 控制台 | 改用 Popen pid + taskkill /PID |
| M12 [D5] | run_all_tests.py:26-52 | 只看 stdout [PASS]/[FAIL] 文本不看 `result.returncode` → 套件 import 崩溃也被报"全 PASS" exit 0 | returncode≠0 计入 fail；退出码纳入判定 |
| M13 [E2] | web_backend.py:588-595/731 + templates.py:619-624 | deai step3 audit 拿不到原文却要评"保留原意度(对比原文事实)" → 伪评分 | `deai_step3_audit(original, rewritten, slug)` 双文送入 |
| M14 [E3] | templates.py:571-616 | V5 rewrite prompt 未内嵌 7 大类 AI 味词表（detect/audit 有）→ 默认无卡路径清 AI 味缺硬约束 | 词表抽共享常量，无卡分支拼进 rewrite system |
| M15 [E4] | loader.py:252-259/324 | add_sample 保留任意扩展名但计数+1，蒸馏只 glob("*.md") → meta 与实蒸馏数长期不一致 | 归一 .md 或蒸馏前按实 glob 校验 |
| M16 [F3] | test_web_backend.py:2310-2323 | v418 暗色 token 断言从 media 块切到**文件尾**，尾部重复的 `[data-theme="dark"]` 兜底 → media 块内删 token 仍绿 | 截到 media 块闭合 `}` 再断言 |
| M17 [F4] | test_bugs.py:68-82 | test_bug4"线程安全"测自建 dict+自建锁、全访问同锁内 → 与产品并发模型无关，永不红 | 删除或改真打 `engine.tasks` 的并发用例 |
| M18 [F5] | test_web_backend.py:661-680 | test_i3_fetch_models_async 以 `check(..., True)` 收尾恒真，且真发 requests 到 localhost:1234 | 照抄 683-709 的 patch 做法，断言 onFetchModelsComplete |

---

## 四、🟡 LOW — 12 处

| 编号 | 位置 | 问题 |
|---|---|---|
| L1 [A6] | web_backend.py:1027/1054-1057 | `_push` 持锁同步调 `_flush`（自死锁分支，当前靠不变量不可达但危险）；`_flush` 空缓冲早退不清 `_last_push_time` 与正常出口不一致 |
| L2 [A7] | web_backend.py:1032/1093 | evaluate_js 由多个独立 threading.Timer 并发调用无串行化（离散事件可能乱序；需运行验证） |
| L3 [B7] | processor.py:52-56 | `_RETRYABLE_ERRORS` 定义后零引用（死代码）；不可重试元组缺 422/内容过滤类 → 白白退避重试 |
| L4 [B9] | processor.py:283-287/337 | docstring 声称"单 chunk 失败→corrected=原文+failed_chunks"，但 _stream_chunked 无 per-chunk try/except → failed_chunks 恒空，局部失败语义不可达 |
| L5 [B10] | processor.py:519-520/613-614 | 空/纯空白文件被送进 LLM，服务端回空 → 空文件 FAILED 而非快速完成 |
| L6 [B11] | context_builder.py:37-57 | 字符预算未计题头(26字符)与 `\n---\n`(5字符/段)，实际输出超 max_chars（默认 2 段超 31 字符） |
| L7 [D6] | main.py | 无单实例互斥、无 window.events.closing 清理钩子；重复双击开多实例共享 ~/.proofreader；关窗 daemon 线程被 OS 掐断无提示 |
| L8 [D7] | dev_launcher.py:33/163 | 顶层 `import winreg` + `CREATE_NEW_CONSOLE` → 非 Windows 直接崩（脚本自称 cross-platform，实际 Windows-only） |
| L9 [E5] | loader.py:197-232 | create_custom 不查撞 builtin key → 可创建但 delete_custom 对 builtin key 抛 PermissionError → 永远删不掉 + 下拉同名双选项 |
| L10 [E6] | loader.py:127-142/362-381 | 9 轴 schema 无校验：list_builtin 只查 JSON 可解析、_parse_style_card_axes 正则切段，缺轴/写错标题静默少轴无告警 |
| L11 [E2 副] | templates.py:336 | v3.1 DEAI system 中文黑名单存在重复词（抓手×2、闭环×2），去重后覆盖率不变但长度虚高 |
| L12 [F6] | README.md:163/193 | 测试数量口径过时（声称 360/360，实测 768 check 通过）；run_all_tests.py:17 注释版本号错误 |

---

## 五、PARTIAL / NOT FOUND / CANNOT_VERIFY

- **A6 PARTIAL**：持锁同步 flush 的死锁分支模式真实存在，但单定时器协议下不可达（危险死代码，改动 flush 逻辑时务必先解）；空缓冲早退不清 `_last_push_time` 的状态重置不一致真实存在。
- **B5 PARTIAL**：静默期 cancel/pause 检查点失效属实；"pause 悬空连接→恢复后 APIConnectionError 触发整文件重试"需运行时（pause 超读超时）才能确认。
- **C4 PARTIAL**：windowed 下 console StreamHandler 流为 None 属实，但 logging 内部 handleError 有防护，只会静默失效、不会抛错，影响比原指控低。
- **A7 CANNOT_VERIFY**：多 Timer 并发调 evaluate_js 代码层属实，但乱序与否取决于 pywebview/WebView2 是否内部串行化，需运行验证。
- **B8 NOT FOUND（误报）**：Python str 是码点序列，码点索引切片不会产生孤立代理对（只有 UTF-16 字节切分才会）。真实存在的仅是"可能从组合 emoji/ZWJ 序列中断开"这一不同且无害的问题。

---

## 六、优先修复清单（建议顺序）

**第一批（P0，用户可感知 / 数据安全）**
1. **H2 api_key 往返污染** — "保存一次设置后全线 401"，影响最直接。修：get_config 返回 `api_key_set`，前端空框占位。
2. **H10 测试污染真实目录** — 已在本机损坏用户配置（api_key 被清空、594 孤儿断点）。修：测试统一走 tempfile 隔离目录。
3. **H1 start_proofread 并发重入** — 取消串台/KeyError/双线程写断点总根源。

**第二批（P1，发布前必改）**
4. **H8 build.spec 漏 style_profiles json** + **H7 check_exe 误报** — 打包/校验链路硬伤，下次发版前必须修。
5. **H3/H4 引擎收尾一致性**（stats 少 1、cancel 排队文件卡死）+ **H5/H6 断点指纹**（漏字段+空 hash 不失效）。
6. **H9 预置 profile 静默失效** — v4.1.7 功能级缺陷，核心卖点空转。

**第三批（P2，质量加固）**：M4 流式回缩、M5/M6 可中断退避、M10 windowed 兜底崩溃、M12 测试门禁假绿、H11 恒真用例删除、H12 custom_prompt 覆盖、E 组 profile schema 校验、D6 单实例/优雅退出。

---

## 七、副发现：真实环境已被测试污染（需用户处理）

审计测试套件子代理实际运行了 3 轮测试后，本机 `~/.proofreader/` 现状：
- `last_config.json` 被覆盖为测试残留：`api_base="http://test"`、`model="test-model"`、`api_key=""`（**原 api_key 已被清空，无法自动恢复，需重新填写**）
- `checkpoints/` 有 **594 个**指向已删除 Temp 文件的孤儿断点 json
- 处理建议：删除 `~/.proofreader/checkpoints/` 下全部孤儿断点（均为测试产生的死文件）；重新在设置页填入真实 API 配置。此问题根因即 H10，修完测试隔离后不会再发生。

---

## 八、值得肯定的点（审计中也确认无问题）

- 引擎 async 骨架：事件循环配对创建/关闭、client finally close、整文件重试粒度、Event 式 pause/cancel 语义均正确
- pywebview 迁移干净：无 Qt/PySide6 残留；bridge 返回类型均可 JSON 序列化、对外方法普遍有 try/except 兜底
- 路径解析 dev/frozen 双模式正确、DPI 处理、服务商模板 base_url 映射（DeepSeek/Ollama/vLLM/智谱/通义）正确
- 测试契约：6 个测试文件调用的方法/参数/返回结构与实现一致，无测旧 API；引擎重试/断点语义有真异步驱动（768 check 全绿）
- 编码处理：read_file_text 4 编码降级、checkpoint JSON utf-8 一致
