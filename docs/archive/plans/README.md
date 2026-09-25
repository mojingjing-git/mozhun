# 历史升级 Plan 归档 (v3.0 — v5.2c)

本目录归档**已完成**的版本升级 plan,供追溯决策与设计意图用。

> 这些 plan 与当前 v5.2c 架构逐步脱节,仅作历史参考,不要机械按其步骤执行。

| 文件 | 对应版本 | 摘要 |
|---|---|---|
| `PLAN-chunking.md` | v3.0 | chunking 预设 + 跨段上下文 + 断点续传 (PySide6 时代) |
| `PLAN-pywebview.md` | v4.0 | 从 PySide6 迁移到 pywebview 6.x, Bridge API 模式 |
| `PLAN-distill-style.md` | v4.1.7 | 9 轴风格指纹 + 事实骨架 + AI 6 处反制 + 8 轴自评 |
| `PLAN-win11-redesign.md` | v4.1.8 | Win11 Fluent 2 视觉完整重构 (17 token + 6 阴影 + 12 SVG) |
| `PLAN-v4.1.5-ui-redesign.md` | v4.1.5 | 前端 4 视图 → 7 视图分组导航 (Win11 设置应用式) |
| `PLAN-baseline-consolidation-2026-09-26.md` | v5.2c | 合并两条 Git 基线 + 工作区整理，含独立审查修订 |

**当前状态** (v5.2c):

- v3.0+ 业务层在 `app/processor.py` / `app/context_builder.py` 保留 (chunking + 上下文 + 断点)
- v4.0+ GUI 在 `web/` 7 视图 SPA + `app/web_backend.py` Bridge (pywebview)
- v4.1.7+ 风格指纹在 `app/style_profiles/`
- v4.1.8+ 视觉在 `web/style.css` (双皮肤: ink 水墨默认 / fluent 可选)
- v4.3.3+ 本地零 LLM 引擎矩阵: `app/punct_fix.py` / `app/md_strip.py` / `app/ai_score_local.py` / `app/harness.py`
- v5.1.0 校对 harness 化: `app/harness.py` (Edit 工具链)
- v5.2b 小说切分: `app/novel_splitter.py` + `web/views/novel-splitter.js`
- v5.2c harness / 重写双轨配置: chunking 与 timeout 分轨持久化

详细版本日志见 [`/CHANGELOG.md`](../../CHANGELOG.md),项目约定见 [`/AGENTS.md`](../../AGENTS.md)。
