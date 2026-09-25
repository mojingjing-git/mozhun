# 墨准双基线合并与工作区整理计划

> 状态: 调研完成，独立审查完成，待按修订版执行
> 创建: 2026-09-26
> 目标分支: `master`
> 实施分支: `codex/merge-baselines`

## 0. 独立审查结论

独立审查结论: **APPROVE WITH CHANGES**

确认可行的部分:

- 以 `cleanup/v6` 为第一父、`master` 为第二父生成 merge commit 的拓扑正确
- 随后把本地 `master` 快进到合并提交，不需要 force push
- CI 使用的 `app/`、`web/`、`main.py`、`start.py`、`run_all_tests.py` 在目标树中均存在

必须先收紧的部分:

1. 备份全部未跟踪内容，tag 不能保护工作区文件。
2. 合并、文档/CI、工作区清理必须拆成独立提交。
3. 全程禁止 `git add -A`、`git commit -a`、`git clean -fd`、`git clean -fdx`。
4. README 冲突必须手工解决，不能整文件取 ours/theirs。
5. 验收必须检查第一父/第二父、冲突标记、`.github` 完整性和 `origin/master` 祖先关系。

## 1. 目标

把当前两条历史线合并成唯一主线，并清理根目录中的临时文件和研究产物。

完成后应满足:

1. `master` 同时包含 `v5.2c` 完整代码历史与 GitHub 仓库门面。
2. `master` 是唯一默认开发入口，不再需要手动判断 `master` / `cleanup/v6`。
3. 测试全绿。
4. 根目录只保留稳定入口、文档和源码。
5. 临时文件有明确的归档、忽略或删除规则。

## 2. 调研结论

### 2.1 两条基线的真实关系

公共祖先:

```text
55bb965 chore: 初始化仓库（v4.1.8 基线，含 .gitignore）
```

当前分支差异:

- `master` 相对公共祖先多 1 个提交:
  - `d6358b3 chore: GitHub 仓库门面 (CI + Issue/PR 模板 + dependabot + README badges)`
  - 仅新增 `.github/` 5 个文件，并给 `README.md` 增加徽章
- `cleanup/v6` 相对公共祖先多 32 个提交:
  - v4.1.9 到 v5.2c 的完整演进
  - 最新提交 `6921090 feat(ui): 校对参数页 harness / 重写 段控件 (v5.2c)`
- `origin/master` 停在 `9e0c0a4`，是 `cleanup/v6` 的祖先
- 因此以 `cleanup/v6` 为第一父提交合并 `master` 后，`master` 可以快进到合并结果，不需要强推

### 2.2 合并冲突面

只读合并预演结果:

- 仅 `README.md` 冲突
- `.github/` 全部可自动合并
- `.gitignore`、测试目录、应用代码和前端代码均可自动合并

冲突原因:

- `master` 在旧 README 标题下新增 4 个徽章
- `cleanup/v6` 已把 README 整体更新到 v5.1.0 架构

解决原则:

- 以 `cleanup/v6` 的 README 内容为主体
- 补回 GitHub 徽章
- 把版本标题和测试说明同步到当前 `v5.2c`
- 增加小说切分与 harness / 重写双轨配置说明

### 2.3 CI 兼容性

`master` 的 CI 使用:

```text
python -m compileall -q app/ web/ main.py start.py
python run_all_tests.py
```

两项在 `cleanup/v6` 中都存在，因此目录重组后 CI 仍兼容。

建议顺手补两项:

- Python matrix 增加 `3.13`，与当前开发环境一致
- 保留 Windows runner，不新增 Linux/macOS 门禁

### 2.4 测试基线

当前检出的 `master`:

```text
6 套件: 768 通过 / 0 失败
```

隔离 worktree 中的 `cleanup/v6` @ `6921090`:

```text
run_all_tests.py: 1336 通过 / 0 失败
```

说明:

- `cleanup/v6` 已有 18 个自动发现测试文件
- 部分套件用单行汇总 `[PASS]`，runner 汇总数低于测试函数内部声明的逻辑 check 数
- 合并验收以 `run_all_tests.py` 退出码为门禁

## 3. 工作区现状

当前未跟踪内容分为四类。

### 3.1 可删除的提交消息草稿

```text
.commit-msg-1.txt
.commit-msg-2.txt
.commit-msg-3.txt
```

内容分别对应已存在的 `v5.2b`、`v5.2c` 两个提交，已无保留价值。

### 3.2 需保留但不应留在根目录的 ASR 烟测

```text
_asr_smoke_test.py
_asr_smoke_test_result.json
_asr_view.txt
_dump_asr_result.py
_dump_asr_result.txt
_render_asr_view.py
_seg_inspect.txt
_seg_inspect_bom.txt
```

这些文件调用 MiniMax `speech_to_text`，与墨准主业务无关。

默认处理:

```text
.local/asr-smoke-2026-09-13/
```

新增 `.local/` 到 `.gitignore`，保证文件保留但 Git 状态干净。

### 3.3 需归档的规划文档

```text
ROADMAP.md
CLEANUP_PLAN.md
.workbuddy/plan-v5.2.md
.workbuddy/plan-v5.2c-harness-split.md
.workbuddy/review-v5.2-plan.md
.workbuddy/review-v5.2-plan-v2.md
.workbuddy/verifier-2026-09-20/REPORT.md
```

处理规则:

- `ROADMAP.md`: 更新到 v5.2c 状态后移到 `docs/ROADMAP.md`
- `CLEANUP_PLAN.md`: 归档到 `docs/archive/plans/CLEANUP_PLAN-v6.0.md`
- `.workbuddy/`: 保持本地工作数据，不重新纳入版本控制
- `.workbuddy` 内部按 `plans/`、`reviews/`、`verifier/` 分类
- verifier 临时 `test*.txt` 和 `_marker.txt` 删除

### 3.4 已忽略或生成内容

- `.venv/`: 保留
- `__pycache__/`: 可清理，但不是合并前置条件
- `.workbuddy/`: 合并后会由目标分支 `.gitignore` 忽略

## 4. 合并策略

采用真实 merge commit，不用复制目录或 cherry-pick 重做。

分支布局:

```text
cleanup/v6 (第一父) --\
                      +-- codex/merge-baselines -> master
master      (第二父) --/
```

原因:

- 保留两条历史的可追溯性
- `cleanup/v6` 的第一父身份让未来日志更容易看出主线演进
- `master` 作为第二父保留 GitHub 门面的来源
- `origin/master` 是 `cleanup/v6` 祖先，最终普通 push 即可快进

## 5. 执行阶段

### Phase 0: 冻结基线与备份工作区

- 确认工作区只有预期未跟踪文件
- 创建备份 tag:
  - `backup/pre-consolidation-master-20260926`
  - `backup/pre-consolidation-cleanup-v6-20260926`
- 记录当前 commit hash
- 在仓库外创建未跟踪内容备份:
  - `git status --porcelain=v1 -uall`
  - ASR 文件、提交草稿、`.workbuddy/`、规划文档和 verifier 报告
  - 备份清单和 SHA256

验收:

- 两个 tag 指向预期提交
- 未跟踪文件已有仓库外可恢复副本
- 不修改 `master` 和 `cleanup/v6`

### Phase 1: 建立实施分支并合并

- 从 `cleanup/v6` 创建 `codex/merge-baselines`
- 执行 `git merge --no-commit --no-ff master`
- 解决 `README.md`
- 保留 `cleanup/v6` 的正文内容
- 补回徽章
- 此时只形成纯合并提交，不在同一提交里改文档或 CI

验收:

- `git diff --cached --check` 通过
- staged 文件不包含 `_asr`、`.commit-msg`、`.workbuddy`、`.local`
- 第一父为 `6921090`
- 第二父为 `d6358b3`

### Phase 2: 独立文档与 CI 提交

- README 更新独立提交，内容对齐 v5.2c:
  - 版本标题
  - 小说切分
  - harness / 重写双轨配置
  - `tests/` 路径
  - 当前 runner 测试口径
- CI 调整放到单独提交:
  - 现有 matrix 保持 `3.10` 到 `3.12`
  - Python 3.13 延后为独立 CI 变更，避免扩大本次合并风险
- `.gitignore` 增加:
  - `.local/`
  - `.commit-msg-*.txt`
- 将本计划移到:
  - `docs/archive/plans/PLAN-baseline-consolidation-2026-09-26.md`

约束:

- 每次只用 `git add -- <显式路径>`
- 提交前检查 `git diff --cached --name-only`
- 文档更新不引用 `.workbuddy` 本地路径

### Phase 3: 工作区清理

- 创建 `.local/asr-smoke-2026-09-13/`
- 移动全部 `_asr_*`、`_dump_asr_result*`、`_render_asr_view.py`、`_seg_inspect*`
- 移动 `.commit-msg-*.txt` 到 `.local/commit-drafts/`，不在本阶段直接删除
- 整理 `.workbuddy/`:
  - `plans/`
  - `reviews/`
  - `verifier/2026-09-20/`
- `ROADMAP.md`: 合并成功后再处理，更新为 `docs/ROADMAP.md`，并移除失效的 `.workbuddy` 链接
- `CLEANUP_PLAN.md`: 合并成功后再归档到 `docs/archive/plans/CLEANUP_PLAN-v6.0.md`
- verifier 的临时 `test*.txt` 和 `_marker.txt`: 先留在仓库外备份，主线稳定后再清理
- 清理 `__pycache__/`

安全规则:

- 所有移动使用显式路径
- 所有递归删除前先确认绝对路径位于项目根目录
- ASR 原始结果不纳入版本控制
- 不用 `git clean`
- 清理不进入合并提交或文档提交

### Phase 4: 验收

执行:

```powershell
python run_all_tests.py
git status --short
git log --graph --oneline --decorate -12
git show -s --format='%H %P' HEAD
git diff --check HEAD^1 HEAD
git grep -n '<<<<<<<'
git ls-tree -r --name-only HEAD -- .github
git merge-base --is-ancestor cleanup/v6 master
git merge-base --is-ancestor backup/pre-consolidation-master-20260926 master
git merge-base --is-ancestor backup/pre-consolidation-cleanup-v6-20260926 master
git merge-base --is-ancestor origin/master master
git check-ignore -v .local .workbuddy
```

通过条件:

- 测试退出码为 0
- 合并提交父节点顺序为 `cleanup/v6`、旧 `master`
- 无冲突标记
- `.github/` 5 个文件完整
- README 徽章和 v5.2c 正文同时存在
- `cleanup/v6` 和旧 `master` 都是合并后 `master` 的祖先
- 工作区没有未分类文件
- 根目录无 ASR 烟测和提交消息草稿

### Phase 5: 主线切换

- 切回 `master`
- 使用 `git merge --ff-only codex/merge-baselines`
- 再次运行测试

验收:

- `master` 指向合并提交
- `cleanup/v6` 暂时保留，作为远端历史分支
- 不自动 push；推送需单独确认

## 6. 回滚方案

执行前已有两个备份 tag。

若 Phase 1 出错:

- 删除或重置 `codex/merge-baselines`
- `master` 和 `cleanup/v6` 不受影响

若 Phase 2 或 Phase 3 出错:

- 先停止提交，不在脏工作区继续操作
- 未跟踪文件从仓库外备份恢复
- 已移动但未提交的文件按备份清单反向恢复
- 已提交的文档变更使用单独 `git revert`，不重写合并提交

若已切到 `master` 后发现问题:

- 使用 `backup/pre-consolidation-master-20260926` 恢复旧视角
- 不执行 force push

## 7. 风险

| 风险 | 等级 | 应对 |
|---|---:|---|
| README 冲突解决时丢失徽章 | 低 | 对照 `d6358b3` 逐项检查 |
| 合并后 CI 路径失效 | 低 | 已确认 CI 走 `run_all_tests.py`，合并后本地复跑 |
| ASR 文件被误提交或误删 | 中 | 先移入 `.local/`，不直接删除 |
| 旧规划文档覆盖新路线图 | 中 | 归档旧文档，更新 `docs/ROADMAP.md` |
| 工作区清理误删用户文件 | 中 | 移动优先、删除其次、路径白名单 |
| `git add -A` 把临时文件带进提交 | 高 | 只允许显式路径 add，提交前断言 staged 清单 |
| 未跟踪内容无备份 | 高 | 仓库外完整备份 + SHA256 |
| 文档整理与合并失败难以区分 | 中 | 合并、文档/CI、清理拆成独立提交 |
| 远端分支状态混乱 | 低 | 本次不自动 push，合并完成后再决定 |

## 8. 不在本次范围

- 不拆 `web/app.js`
- 不拆 `web/style.css`
- 不修 verifier 报告中的业务缺陷
- 不删除远端 `cleanup/v6`
- 不更新 Python 3.13 CI matrix
- 不改 verifier High 级业务问题
- 不发布、不打包、不推送

这些事项在合并完成、主线稳定后单独排期。
