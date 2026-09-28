# 封存索引 — docs/archive/

> 归档日期：2026-09-29　｜　基线：commit `5a46b34`（tag `backup/pre-cleanup-20260928`）
> 计划：[`docs/PLAN-deadcode-cleanup-2026-09-28.md`](../PLAN-deadcode-cleanup-2026-09-28.md) §Phase 4

本目录收纳**历史升级 plan**与**已完成的实施计划**。它们的执行结论已回填进
`AGENTS.md`（设计决策）与 `CHANGELOG.md`（版本日志），原文仅供追溯，**不再随工作区加载**。

## 当前状态

截至归档时，墨准为 **v5.4.3**，7 视图 SPA、pywebview Bridge、`harness`/`rewrite` 双轨工作流、
思维链剥离已落地。已完成批次：

| 批次 | 主题 | 决策落点 |
|---|---|---|
| v3.0 | 分块 / 跨段上下文 / 断点 | `AGENTS.md` §1-§9 |
| v4.0 | pywebview 重写 + Fluent 2 前端 | `AGENTS.md` §11-§24 |
| v4.3.x | 本地标点修复规则引擎 | `AGENTS.md` §29-§30 |
| v4.4.0 | 水墨宣纸皮肤（`data-skin` token 镜像不变量） | `AGENTS.md` §31 |
| v4.4.2 | Markdown 清洗本地引擎 | `AGENTS.md` §32 |
| v5.0.2 | DeAI 后置三件套（strip / ai_score / revise） | `AGENTS.md` §33-§35 |
| v5.1.0 | 校对 harness 化（Edit 工具链） | `AGENTS.md` §36 |
| v5.2c | 双轨配置（D 方案） | `AGENTS.md` §37 |
| v5.3.0 | 工作流一等身份 + 50K 档 + 断点保护 | `AGENTS.md` §39-§46 |
| v5.4.0 | 思维链剥离（产出侧单点） | `AGENTS.md` §47-§52 |

## 一、历史升级 plan（v3.0 — v4.1.7 完成态）

| 原路径 | 大小 | 行数 | 主题 |
|---|---|---|---|
| `docs/archive/plans/PLAN-chunking.md` | 43.7 KB | 1242 | 分块 / 上下文 / 断点三件套的原始设计 |
| `docs/archive/plans/PLAN-pywebview.md` | 40.3 KB | 1099 | v4.0 前端重写（引用了已移除的 marked.js） |
| `docs/archive/plans/CLEANUP_PLAN-v6.0.md` | 27.8 KB | 552 | v6.0 整理 + 改名（分支 `cleanup/v6` 已废弃） |
| `docs/archive/plans/PLAN-v4.1.5-ui-redesign.md` | 20.5 KB | 587 | v4.1.5 UI 改版 |
| `docs/archive/plans/PLAN-win11-redesign.md` | 18.8 KB | 346 | Win11 Fluent 2 重构 |
| `docs/archive/plans/PLAN-distill-style.md` | 14.4 KB | 274 | 风格蒸馏（9 轴指纹） |
| `docs/archive/plans/PLAN-baseline-consolidation-2026-09-26.md` | 11.4 KB | 376 | 基线合并（`PLAN-pywebview` 的前身） |

## 二、已完成的实施计划（v5.2b — v5.4 批次）

| 原路径 | 大小 | 行数 | 主题 |
|---|---|---|---|
| `docs/PLAN-defect-fix-2026-09-27.md` | 65.1 KB | 1053 | 缺陷修复批次（含 D1-D7 待决项，见下） |
| `docs/PLAN-workflow-split-v5.3.md` | 42.1 KB | 401 | 工作流双入口（§2 D4/D7、§3.4 决策出处） |
| `docs/PLAN-think-strip-v5.4.md` | 40.9 KB | 577 | 思维链剥离（AGENTS §47-§52 出处） |
| `docs/PLAN-splitter-v5.2b.md` | 17.6 KB | 397 | 小说切分 |

## 三、未入库的 agent 评审产物

`.workbuddy/` 被 `.gitignore` 忽略，**从未进入 git 历史**，仅存于归档压缩包：

- `reviews/` — 13 份 plan 评审报告（think-strip 两轮、workflow-split、v5.5 可行性等）
- `plans/` — 2 份早期 plan 草稿
- `verifier/2026-09-20/` — 一次 verifier 运行的报告与 scratch 痕迹

> ⚠️ 压缩包 `docs-archive-20260928.zip` 落 `.local/`（gitignored）。
> **`.workbuddy/` 的内容只存在于该 zip 内**，git 历史无法兜底。仓库外另行保存副本。

## 仍然保留在 `docs/` 的文件

| 文件 | 保留理由 |
|---|---|
| `THIRD_PARTY_NOTICES.md` | 借鉴来源 + LICENSE 全文，唯一的合规权威副本 |
| `ROADMAP.md` | **活文档** — 路线图与跨会话待办（含 42 行 backlog + 跨版本"明确不做"共识） |
| `PLAN-change-report-v5.5.md` | 待评审的 v5.5 功能计划（校对反馈闭环三件套） |
| `PLAN-deadcode-cleanup-2026-09-28.md` | 本次清理计划与执行记录 |
| `Windows11-设计原则.md` | `THIRD_PARTY_NOTICES.md` §6 的出处凭据 |

## 已知断裂的引用（有意保留）

- `AGENTS.md` §36 与 `app/harness.py` 引用的 `.workbuddy/research/agent1-tech-feasibility.md`
  **在归档前已不存在**（早期 session 删除），压缩包也无法兜底。相关 12 条边界表
  已完整实施进 `app/harness.py`，原文仅存于 git 历史之外的评审报告中。
- `docs/PLAN-defect-fix-2026-09-27.md` 的 **D1-D7 待决项**（E 组前后端派生收敛、读属性
  边界、样式与配色等）随包封存；D7「前端派生收敛需先定 Bridge 只读 API」仍是**未决**议题。
