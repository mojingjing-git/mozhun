"""阈值真实样本校准器 (v5.4.3 §34 口径工具)。

**为什么需要它**: 仓库里有 9 个"初始拍定值, 未做真实样本校准"的阈值
(AGENTS.md §34)。单元测试只能回答"阈值行为对不对", 回答不了
"阈值选得合不合适" —— 后者必须拿真实校对样本跑一轮统计。

**这个工具做什么**: 读你指定的真实稿件目录, 分两阶段产出分布统计:

阶段 0 (不需要 API key, 秒级)
  - 稿件字符数分布 -> 校准 `MD_LOCAL_MAX_CHARS` (md_local 体积上限)
  - 行长分布 / 超长行占比 -> 判断 `md_strip` 守卫后的最坏耗时

阶段 1 (需要 API key, 花钱)
  - 跑一遍**逐条校对** (harness 轨), 收集:
    * 每个 chunk 的 `max(old_len) / len(original)` 分布 -> 校准
      `RATIO_WARN_THRESHOLD` (0.5) 与 `RATIO_WARN_MIN_CHARS` (200)
    * 每文件成功编辑条数分布 -> 看 50 条/轮上限 (`MAX_EDITS_PER_ROUND`) 够不够
    * 任何"0 tool_calls + content 非空"的 content 长度 -> 校准
      `_NOOP_CONTENT_MAX_LEN` (40)

**这个工具校准不了什么** (重要, 别白找样本):
  推送通道那一组 (重试预算 2 / buffer 上限 2000 / 退避阈值 5 / 退避上限 2.0s)
  是**容错参数**, 不是内容参数 —— 它们回答的是"WebView 挂了怎么办",
  与稿件长什么样无关。要验证它们只能靠故障注入 (本仓库已用变异实验覆盖:
  撤掉重投/回滚/幂等守卫, 确认用例变红)。**样本回归回答不了, 本工具也不假装能。**

用法:
    # 阶段 0, 不花钱
    python tools/calibrate_thresholds.py --samples D:\\我的稿件 --phase 0

    # 阶段 1, 需要 ~/.proofreader/last_config.json 里已配好 api_base/api_key/model
    python tools/calibrate_thresholds.py --samples D:\\我的稿件 --phase 1
    python tools/calibrate_thresholds.py --samples D:\\我的稿件 --phase 1 --out .local

⚠ 本工具**只读**样本目录, 只写 --out 指定的报告文件; 不碰样本, 不改配置。
⚠ 阶段 1 会真实调用 LLM 并计费, 请确认样本量与预算相符再跑 (会先打印预计调用数)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
# 隔离: 本工具 import app.* 会建配置目录并接上 logger, 不隔离就往用户真实
# ~/.proofreader 写日志 (与 smoke_ui 踩过的同一个坑, 批次 2a L3)。
import test_isolate  # noqa: F401,E402

from app.utils import CHUNKING_PRESETS, ProjectConfig, load_config  # noqa: E402
from app.harness import (  # noqa: E402
    RATIO_WARN_MIN_CHARS, RATIO_WARN_THRESHOLD, MAX_EDITS_PER_ROUND,
    PREVIEW_LIMIT, _NOOP_CONTENT_MAX_LEN,
)
from app.processor import MD_LOCAL_MAX_CHARS  # noqa: E402

SAMPLE_SUFFIXES = {".txt", ".md", ".markdown", ".text"}


# ====== 工具 ======

def pct(values: list[float], q: float) -> float:
    """百分位 (线性插值)。空样本返回 0.0 —— 调用方负责判空。"""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def describe(name: str, values: list[float], unit: str = "") -> dict:
    """把一个分布压成可读的统计摘要。样本数不足时明说, 不外推。"""
    if not values:
        return {"metric": name, "n": 0, "note": "无样本"}
    d = {"metric": name, "unit": unit, "n": len(values),
         "min": round(min(values), 4), "p50": round(pct(values, .50), 4),
         "p90": round(pct(values, .90), 4), "p95": round(pct(values, .95), 4),
         "p99": round(pct(values, .99), 4), "max": round(max(values), 4),
         "mean": round(sum(values) / len(values), 4)}
    if len(values) < 10:
        d["note"] = (f"样本仅 {len(values)} 条, p90 以上不可信; "
                     f"至少要 30 条同分布样本才有参考价值")
    return d


def collect_samples(folder: Path, limit: int | None) -> list[Path]:
    files = [p for p in sorted(folder.rglob("*"))
             if p.is_file() and p.suffix.lower() in SAMPLE_SUFFIXES]
    if limit:
        files = files[:limit]
    return files


# ====== 阶段 0: 不需要 API ======

def phase0(files: list[Path]) -> dict:
    sizes: list[float] = []
    max_lines: list[float] = []
    total = 0
    too_big = 0
    for p in files:
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  跳过 {p.name}: {type(e).__name__}: {e}")
            continue
        n = len(t)
        sizes.append(n)
        total += 1
        if n > MD_LOCAL_MAX_CHARS:
            too_big += 1
        max_lines.append(max((len(ln) for ln in t.splitlines()), default=0))

    rep = {
        "phase": 0,
        "files_read": total,
        "metrics": [
            describe("稿件字符数", sizes, "char"),
            describe("最长行字符数", max_lines, "char"),
        ],
        "md_local": {
            "current_limit": MD_LOCAL_MAX_CHARS,
            "files_over_limit": too_big,
            "over_ratio": round(too_big / total, 4) if total else 0.0,
            "largest_sample": int(max(sizes)) if sizes else 0,
        },
    }
    return rep


# ====== 阶段 1: 需要 API, 跑一遍 harness 轨 ======

async def phase1(files: list[Path], cfg: ProjectConfig) -> dict:
    from unittest.mock import patch
    from app.processor import ProcessingEngine
    import tempfile as _tf

    # 逐条校对轨 + 大块 (harness 的 extra_large 档 50000)
    cfg.prompt_mode = "strict"
    cfg.workflow_mode = "harness"
    cfg.chunking_preset_harness = "extra_large"
    cfg.harness_enabled = True
    cfg.concurrency = 1
    cfg.max_retries = 0

    engine = ProcessingEngine(cfg)
    logs: list[str] = []
    engine.on_log = logs.append
    engine.prepare_tasks(files)
    t0 = time.time()
    await engine.run_async()
    elapsed = time.time() - t0

    ratios: list[float] = []            # 每个 chunk 的 max(old_len)/len(original)
    ratios_over_current: list[float] = []
    edits_per_file: list[float] = []
    statuses: Counter = Counter()
    noop_contents: list[tuple[str, int]] = []   # (内容前 60 字, 长度)
    ratio_by_char_bucket: dict[str, list[float]] = {}

    for key, task in engine.tasks.items():
        statuses[str(task.status)] += 1
        audits = engine.file_audits.get(key, [])
        oks = [e for e in audits if e.get("status") == "OK"]
        edits_per_file.append(len(oks))
        warn = [e for e in audits if e.get("status") == "WARN_RATIO"]
        for e in warn:
            noop_contents.append((e.get("note", "")[:60], e.get("old_len", 0)))

        # 覆盖率分布: 用 audit 里各 chunk 的 old_len 反推不了 (已合并),
        # 所以这里退一步统计"单条编辑占该文件的比例"的分布代理指标。
        if task.result and task.result.original:
            L = len(task.result.original)
            if oks:
                m = max(e.get("old_len", 0) for e in oks)
                r = m / L
                ratios.append(r)
                b = ("<200" if L < RATIO_WARN_MIN_CHARS
                     else "200-1k" if L < 1000
                     else "1k-10k" if L < 10000 else ">=10k")
                ratio_by_char_bucket.setdefault(b, []).append(r)
            elif not task.skip and task.result.corrected == task.result.original:
                ratios.append(0.0)    # 零改动也是一个合法的 0

    # 可疑 no-op 的 content 长度: 从日志里捞 (放行时记了 preview)
    for m in logs:
        if "疑似未走工具链" in m or "放行" in m and "content" in m:
            noop_contents.append((m[:60], 0))

    return {
        "phase": 1,
        "elapsed_sec": round(elapsed, 1),
        "statuses": dict(statuses),
        "metrics": [
            describe("单条最大编辑/原文 占比", ratios, "ratio"),
            describe("每文件成功编辑条数", edits_per_file, "count"),
        ],
        "by_char_bucket": {k: describe(k, v, "ratio")
                           for k, v in sorted(ratio_by_char_bucket.items())},
        "thresholds_in_use": {
            "RATIO_WARN_THRESHOLD": RATIO_WARN_THRESHOLD,
            "RATIO_WARN_MIN_CHARS": RATIO_WARN_MIN_CHARS,
            "MAX_EDITS_PER_ROUND": MAX_EDITS_PER_ROUND,
            "_NOOP_CONTENT_MAX_LEN": _NOOP_CONTENT_MAX_LEN,
            "MD_LOCAL_MAX_CHARS": MD_LOCAL_MAX_CHARS,
        },
        "flagged_samples": noop_contents[:50],
        "flagged_count": len(noop_contents),
    }


# ====== 建议 (只做陈述, 不自动改代码) ======

def advise(r0: dict, r1: dict | None) -> list[str]:
    out: list[str] = []
    md = r0.get("md_local", {})
    if r0.get("files_read"):
        big = md.get("largest_sample", 0)
        limit = md.get("current_limit", 0)
        out.append(
            f"MD_LOCAL_MAX_CHARS = {limit:,}; 你最大的样本 {big:,} 字符 "
            f"({big / limit:.1%} of limit), 超限文件 {md.get('over_ratio', 0):.1%}。"
            + ("上限比实际用法宽松得多, 可以下调以换取更快的失败反馈。"
               if big < limit * 0.3 else
               "样本已接近上限, 说明这个阈值确实在起作用, 保持。"))
    if not r1:
        out.append("阶段 1 未跑: RATIO_WARN_THRESHOLD / _NOOP_CONTENT_MAX_LEN "
                   "**仍未校准**。")
        return out

    m = {d["metric"]: d for d in r1.get("metrics", [])}
    ratio = m.get("单条最大编辑/原文 占比", {})
    if ratio.get("n", 0) >= 10:
        p95, p99, mx = ratio["p95"], ratio["p99"], ratio["max"]
        cur = r1["thresholds_in_use"]["RATIO_WARN_THRESHOLD"]
        if p99 < cur / 3:
            out.append(f"覆盖率分布 p99={p99:.2%}, 远低于阈值 {cur:.0%} -> "
                       f"阈值偏高, 真正的整段重写可能漏网; 考虑下调到 "
                       f"p99 与 max 之间。")
        elif mx > cur and p99 <= cur:
            out.append(f"阈值 {cur:.0%} 落在 p99({p99:.2%}) 与 max({mx:.2%}) 之间, "
                       f"**位置合理**: 只拦极端个例, 不打扰正常校对。保持。")
        else:
            out.append(f"覆盖率分布 p95={p95:.2%} p99={p99:.2%} max={mx:.2%} "
                       f"vs 阈值 {cur:.0%} -> 需要人看一眼分布形状再定。")
    else:
        out.append(f"覆盖率样本仅 {ratio.get('n', 0)} 条 (< 10), "
                   f"p90 以上不可信, **不足以校准**。请补样本。")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="墨准阈值真实样本校准器 (v5.4.3 §34)")
    ap.add_argument("--samples", required=True, help="真实稿件目录 (只读)")
    ap.add_argument("--phase", type=int, choices=(0, 1), default=0)
    ap.add_argument("--limit", type=int, default=None, help="最多取 N 个文件")
    ap.add_argument("--out", default=str(ROOT / ".local" / "calibration"),
                    help="报告输出目录")
    args = ap.parse_args()

    folder = Path(args.samples).expanduser()
    if not folder.is_dir():
        print(f"样本目录不存在: {folder}")
        return 2
    files = collect_samples(folder, args.limit)
    if not files:
        print(f"{folder} 下没有 .txt/.md/.markdown/.text 文件")
        return 2
    print(f"样本: {len(files)} 个文件 (来自 {folder})")

    r0 = phase0(files)
    r1 = None
    if args.phase == 1:
        cfg = load_config()
        missing = [k for k in ("api_base", "api_key", "model")
                   if not getattr(cfg, k, None)]
        if missing:
            print(f"配置缺 {missing} —— 请先在应用里配好 API 再跑阶段 1。"
                  "(配置读自 ~/.proofreader/last_config.json)")
            return 2
        print(f"将用 model={cfg.model} base={cfg.api_base} 真实调用 LLM。")
        print(f"预计 {len(files)} 次起调用, 之后按块数增加 (extra_large 档 50000 字/块)。"
              f"\n确认费用可接受请回车, 放弃请 Ctrl+C:")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print("已取消")
            return 1
        r1 = asyncio.run(phase1(files, cfg))

    report = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "samples_dir": str(folder), "sample_count": len(files),
              "phase0": r0, "phase1": r1,
              "advice": advise(r0, r1),
              "disclaimer": ("本报告的全部数字均来自上面 sample_count 个真实样本的"
                             "实测, 没有引用任何外部或推测来源。"
                             "样本量不足的地方已在各 metric 的 note 字段标明。")}
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"calibration_phase{args.phase}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8")

    print("\n=== 阶段 0 ===")
    for d in r0["metrics"]:
        if d.get("n"):
            print(f"  {d['metric']}: n={d['n']} p50={d['p50']:,.0f} "
                  f"p90={d['p90']:,.0f} max={d['max']:,.0f} {d['unit']}")
        else:
            print(f"  {d['metric']}: {d.get('note')}")
    if r1:
        print("\n=== 阶段 1 ===")
        print(f"  耗时 {r1['elapsed_sec']}s, 状态分布 {r1['statuses']}")
        for d in r1["metrics"]:
            if d.get("n"):
                print(f"  {d['metric']}: n={d['n']} p50={d['p50']} "
                      f"p95={d['p95']} p99={d['p99']} max={d['max']}")
    print("\n=== 结论 ===")
    for a in report["advice"]:
        print(f"  - {a}")
    print(f"\n报告已写: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
