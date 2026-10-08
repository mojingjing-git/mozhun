"""输入身份指纹回归 (v5.5 I-1 — PLAN-integrity-batch-2026-10-08 §2.1)。

锁定外部复核 M06 的两个形态:
  ① 文件内容改了 → 旧实现仍命中旧断点, diff 基线停留在旧文本
  ② 文件被删除 → 旧实现仍报"缓存命中 / 已完成"
根因: prepare_tasks 先查缓存后读文件, 输入内容与存在性完全不参与判定。
v5.5 改为"先读文件 → 算输入指纹 → 再查缓存", 本套件逐条锁定该顺序。

另含 FileResult.source_hash 的序列化/旧断点兼容断言 (字段追加不破坏旧 JSON)。
"""
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))  # tests/ 的父目录 = 项目根
import test_isolate  # noqa: F401  测试隔离: 重定向 ~/.proofreader 到临时目录

from app.processor import ProcessingEngine
from app.utils import (
    FileResult,
    FileTask,
    ProjectConfig,
    TaskStatus,
    compute_prompt_hash_for_config,
    compute_source_hash,
    save_checkpoint,
)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         -> {detail}")


def _cfg(**kw):
    """测试配置: 关掉两个本地预处理开关, 让 original_text 与文件内容逐字一致。"""
    base = dict(api_base="http://audit.invalid/v1", api_key="k", model="m",
                punct_fix=False, md_strip_before_llm=False)
    base.update(kw)
    return ProjectConfig(**base)


def _make_done_checkpoint(fp: Path, text: str, cfg, *, source_hash=None,
                          corrected="改好了"):
    """落一个 COMPLETED 断点; source_hash 默认按当前文本算 (模拟 v5.5 之后的断点)。"""
    task = FileTask(
        file_path=fp, status=TaskStatus.COMPLETED, original_text=text,
        result=FileResult(
            original=text, corrected=corrected,
            prompt_hash=compute_prompt_hash_for_config(cfg),
            source_hash=(compute_source_hash(text) if source_hash is None else source_hash),
        ),
    )
    save_checkpoint(fp, task)
    return task


def test_source_hash_is_deterministic():
    print("\n--- 指纹本身: 确定性 / 空文本 / 区分度 ---", flush=True)
    check("同文本同指纹", compute_source_hash("甲") == compute_source_hash("甲"))
    check("空文本也有非空指纹", bool(compute_source_hash("")),
          f"got={compute_source_hash('')!r}")
    check("不同文本不同指纹", compute_source_hash("甲") != compute_source_hash("乙"))
    check("指纹长度 16", len(compute_source_hash("任意文本")) == 16)


def test_same_content_hits_cache():
    print("\n--- 未改动 + 配置未变 → 命中 (行为与旧版一致) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "same.txt"
        fp.write_text("原文内容。", encoding="utf-8")
        cfg = _cfg()
        _make_done_checkpoint(fp, "原文内容。", cfg)
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([fp])
        key = str(fp)
        check("命中缓存", key in eng.cached_files)
        check("采用断点里的结果", eng.tasks[key].result.corrected == "改好了")
        check("状态 COMPLETED", eng.tasks[key].status == TaskStatus.COMPLETED)


def test_changed_content_misses_cache():
    print("\n--- 文件内容改了 → 必须重跑, diff 基线是新原文 (M06 形态①) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "changed.txt"
        fp.write_text("旧原文。", encoding="utf-8")
        cfg = _cfg()
        _make_done_checkpoint(fp, "旧原文。", cfg)
        fp.write_text("新原文。", encoding="utf-8")
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([fp])
        key = str(fp)
        check("不命中缓存", key not in eng.cached_files,
              f"cached_files={eng.cached_files}")
        check("original_text 是新原文", eng.tasks[key].original_text == "新原文。",
              f"got={eng.tasks[key].original_text!r}")
        check("输入指纹随新原文更新",
              eng._source_hashes.get(key) == compute_source_hash("新原文。"))


def test_deleted_source_does_not_hit_cache():
    print("\n--- 文件被删除 → 不命中 + FAILED 占位 (M06 形态②) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "gone.txt"
        fp.write_text("会被删掉的原文。", encoding="utf-8")
        cfg = _cfg()
        _make_done_checkpoint(fp, "会被删掉的原文。", cfg)
        fp.unlink()
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([fp])
        key = str(fp)
        check("不命中缓存", key not in eng.cached_files)
        t = eng.tasks[key]
        check("标 FAILED", t.status == TaskStatus.FAILED, f"status={t.status}")
        check("skip 占位 (不再进 pending)", t.skip is True)
        check("错误信息含读取失败",
              bool(t.result and "读取失败" in (t.result.error or "")),
              f"error={getattr(t.result, 'error', None)!r}")


def test_legacy_checkpoint_without_source_hash_misses():
    print("\n--- 旧断点 (无 source_hash 字段) → 一次性重跑, 不得放行 ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "legacy.txt"
        fp.write_text("旧版本落下的原文。", encoding="utf-8")
        cfg = _cfg()
        # source_hash="" 即 v5.5 之前的断点形态 (from_dict 默认值)
        _make_done_checkpoint(fp, "旧版本落下的原文。", cfg, source_hash="")
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([fp])
        check("旧断点不命中", str(fp) not in eng.cached_files)
        check("旧断点不被采用", eng.tasks[str(fp)].result is None)


def test_empty_expected_hash_never_reuses():
    print("\n--- 防御: expected_source_hash 为空串一律不复用 (空==空 不得放行) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "empty.txt"
        fp.write_text("正文。", encoding="utf-8")
        cfg = _cfg()
        _make_done_checkpoint(fp, "正文。", cfg, source_hash="")
        from app.utils import load_checkpoint
        got = load_checkpoint(
            fp,
            expected_hash=compute_prompt_hash_for_config(cfg),
            expected_source_hash="",
        )
        check("空 expected 不复用", got is None)


def test_force_rerun_skips_cache():
    print("\n--- force_rerun=True → 仍跳过缓存且不报错 (v4.3.1 UX#7 回归) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "force.txt"
        fp.write_text("强制重跑原文。", encoding="utf-8")
        cfg = _cfg()
        _make_done_checkpoint(fp, "强制重跑原文。", cfg)
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([fp], force_rerun=True)
        key = str(fp)
        check("不命中缓存", key not in eng.cached_files)
        check("原文被重新读取", eng.tasks[key].original_text == "强制重跑原文。")


def test_config_change_still_blocks():
    print("\n--- 仅配置变化 → 仍由 prompt_hash 拦下 (既有语义回归) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "cfg.txt"
        fp.write_text("配置变化原文。", encoding="utf-8")
        _make_done_checkpoint(fp, "配置变化原文。", _cfg())
        eng = ProcessingEngine(_cfg(temperature=0.9))
        eng.prepare_tasks([fp])
        check("配置指纹不匹配 → 不命中", str(fp) not in eng.cached_files)


def test_source_hashes_reset_each_prepare():
    print("\n--- _source_hashes 每次 prepare 重置 (不残留上一批文件) ---", flush=True)
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.txt"
        b = Path(d) / "b.txt"
        a.write_text("甲文件。", encoding="utf-8")
        b.write_text("乙文件。", encoding="utf-8")
        cfg = _cfg()
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([a, b])
        check("两文件都在表内", set(eng._source_hashes) == {str(a), str(b)})
        eng.prepare_tasks([b])
        check("重置后只剩本次文件", set(eng._source_hashes) == {str(b)},
              f"got={sorted(eng._source_hashes)}")
        check("指纹正确", eng._source_hashes[str(b)] == compute_source_hash("乙文件。"))


def test_source_hash_serialization():
    print("\n--- FileResult.source_hash 落盘/回读/旧 JSON 兼容 ---", flush=True)
    r = FileResult(original="a", corrected="b", source_hash="deadbeefdeadbeef")
    d = r.to_dict()
    check("to_dict 带 source_hash", d.get("source_hash") == "deadbeefdeadbeef")
    back = FileResult.from_dict(d)
    check("from_dict 回读一致", back.source_hash == "deadbeefdeadbeef")
    legacy = FileResult.from_dict({"original": "a", "corrected": "b"})
    check("旧 JSON 缺键 → 空串默认", legacy.source_hash == "")
    check("字段顺序兼容: 位置传参 2 参仍可用",
          FileResult("a", "b").corrected == "b")


def test_engine_writes_source_hash_end_to_end():
    print("\n--- 写入侧: 引擎产出的结果必须带指纹, 且能再次命中 (B1 复核 BLOCKER-1) ---", flush=True)
    import asyncio
    from unittest.mock import AsyncMock, patch

    with tempfile.TemporaryDirectory() as d:
        fp = Path(d) / "e2e.txt"
        raw = "端到端原文。"
        fp.write_text(raw, encoding="utf-8")
        cfg = _cfg()
        eng = ProcessingEngine(cfg)
        eng.prepare_tasks([fp])
        key = str(fp)

        async def fake_stream(task_key, text):
            return text.replace("端到端", "E2E"), 7, [
                FileResult(original=text, corrected=text.replace("端到端", "E2E"))
            ]

        with patch.object(ProcessingEngine, "_call_api_stream",
                          new=AsyncMock(side_effect=fake_stream)):
            asyncio.run(eng.run_async())

        check("引擎跑完标 COMPLETED", eng.tasks[key].status == TaskStatus.COMPLETED)
        got = getattr(eng.tasks[key].result, "source_hash", None)
        check("结果带输入指纹 (写入侧存在)",
              got == compute_source_hash(raw), f"got={got!r}")

        from app.utils import load_checkpoint
        cp = load_checkpoint(
            fp, expected_hash=compute_prompt_hash_for_config(cfg),
            expected_source_hash=compute_source_hash(raw),
        )
        check("落盘断点可复用 (指纹随结果写出)", cp is not None and cp.is_done)

        eng2 = ProcessingEngine(cfg)
        eng2.prepare_tasks([fp])
        check("新引擎二次 prepare 命中缓存", key in eng2.cached_files,
              f"cached_files={eng2.cached_files}")


def main():
    print("=" * 60)
    print("  输入身份指纹回归 (v5.5 I-1)")
    print("=" * 60)
    tests = [
        test_source_hash_is_deterministic,
        test_same_content_hits_cache,
        test_changed_content_misses_cache,
        test_deleted_source_does_not_hit_cache,
        test_legacy_checkpoint_without_source_hash_misses,
        test_empty_expected_hash_never_reuses,
        test_force_rerun_skips_cache,
        test_config_change_still_blocks,
        test_source_hashes_reset_each_prepare,
        test_source_hash_serialization,
        test_engine_writes_source_hash_end_to_end,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            check(t.__name__, False, f"{type(e).__name__}: {e}")
    print()
    print("=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
